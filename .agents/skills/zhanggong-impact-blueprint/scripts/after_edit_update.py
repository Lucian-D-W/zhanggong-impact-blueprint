#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import build_graph
import generate_report
from adapters import adapter_coverage_adapter, detect_language_adapter, detect_project_profile_name
from db_support import connect_db
from parser_backends import v8_relative_path
from runtime_support import append_jsonl, read_json, read_jsonl, runtime_paths, write_json
from test_command_resolver import baseline_regression_status, command_to_string, failure_signature_from_output, normalize_command, preflight_test_command, record_test_command_history, resolve_test_command


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_post_change_note(report_path: pathlib.Path, lines: list[str]) -> None:
    with report_path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        for line in lines:
            fh.write(f"{line}\n")


def normalize_test_command(command: list[str]) -> list[str]:
    if not command:
        return []
    if command[0].lower() == "python":
        return [sys.executable, *command[1:]]
    if command[0].lower() == "npm":
        npm_binary = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        return [npm_binary, *command[1:]]
    return command


def coveragepy_available() -> bool:
    return importlib.util.find_spec("coverage") is not None


def parse_test_count(output: str, adapter_name: str) -> tuple[int | None, str]:
    if not output:
        return None, "unknown"

    unittest_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+[0-9.]+s", output)
    if unittest_match:
        return int(unittest_match.group(1)), "parsed"

    node_match = re.search(r"(?m)^#\s*tests\s+(\d+)\s*$", output)
    if node_match:
        return int(node_match.group(1)), "parsed"

    vitest_match = re.search(r"(?m)^\s*Tests\s+(\d+)\s+passed\b", output)
    if vitest_match:
        return int(vitest_match.group(1)), "parsed"

    filtered_output = output
    if adapter_name in {"generic", "tsjs"}:
        filtered_output = "\n".join(
            line
            for line in output.splitlines()
            if not re.match(r"^\s*(Test Files|Test Suites)\b", line)
        )

    if any(token in filtered_output for token in (" passed", " failed", " skipped", " error", " errors")):
        total = 0
        seen_summaries: set[tuple[int, str]] = set()
        for count, label in re.findall(r"\b(\d+)\s+(passed|failed|skipped|errors?|xfailed|xpassed)\b", filtered_output):
            normalized_label = "error" if label in {"error", "errors"} else label
            key = (int(count), normalized_label)
            if key in seen_summaries:
                continue
            seen_summaries.add(key)
            total += int(count)
        if total:
            return total, "parsed"

    return None, "unknown"


def report_json_path_for_task(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str) -> pathlib.Path:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    return paths["report_dir"] / f"impact-{task_id}.json"


def load_task_report_json(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str) -> dict:
    report_json_path = report_json_path_for_task(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
    )
    if not report_json_path.exists():
        return {}
    return json.loads(report_json_path.read_text(encoding="utf-8"))


def python_unittest_target_from_seed(seed: str) -> str | None:
    parts = seed.split(":", 2)
    if len(parts) != 3:
        return None
    _, relative_path, test_name = parts
    if not relative_path.endswith(".py"):
        return None
    module_name = pathlib.PurePosixPath(relative_path).with_suffix("").as_posix().replace("/", ".")
    if module_name.endswith(".__init__"):
        module_name = module_name[: -len(".__init__")]
    if not module_name or not test_name:
        return None
    return f"{module_name}.{test_name}"


def python_unittest_command_from_target(target: str) -> list[str]:
    return ["python", "-m", "unittest", target]


def map_test_seed_to_command(seed: str) -> tuple[list[str] | None, str, str]:
    parts = seed.split(":", 2)
    if len(parts) != 3 or parts[0] != "test":
        return None, "low", "unsupported seed format"
    _, relative_path, _ = parts
    python_target = python_unittest_target_from_seed(seed)
    if python_target:
        return ["python", "-m", "unittest", python_target], "high", "direct COVERS edge"
    if relative_path.endswith((".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx")):
        return ["node", "--test", relative_path], "medium", "direct COVERS edge"
    return None, "low", "no direct test command mapping available"


def map_history_test_target_to_command(target: str, adapter_name: str) -> list[str] | None:
    if not target:
        return None
    if adapter_name == "python" and "." in target:
        return python_unittest_command_from_target(target)
    if adapter_name == "tsjs" and target.endswith((".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx")):
        return ["node", "--test", target.replace("\\", "/")]
    return None


def parse_failed_tests(output: str, adapter_name: str) -> list[str]:
    failed: list[str] = []
    if adapter_name == "python":
        for pattern in (
            r"(?m)^(?:FAIL|ERROR):\s+\S+\s+\(([^)]+)\)\s*$",
            r"(?m)^\s*unittest\.loader\._FailedTest\.([^\s]+)\s*$",
        ):
            failed.extend(match.group(1) for match in re.finditer(pattern, output))
    elif adapter_name == "tsjs":
        failed.extend(match.group(1).strip() for match in re.finditer(r"(?m)^\s*not ok\b.*?-\s*(.+?)\s*$", output))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in failed:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def load_history_rows(workspace_root: pathlib.Path) -> list[dict]:
    return read_jsonl(runtime_paths(workspace_root)["test_history"])


def load_baseline_status(workspace_root: pathlib.Path) -> dict:
    return read_json(runtime_paths(workspace_root)["baseline_status"]) or {}


def output_excerpt_lines(output_text: str) -> list[str]:
    return [line.strip() for line in output_text.splitlines() if line.strip()][:20]


def enrich_test_summary_with_regression(workspace_root: pathlib.Path, summary: dict, output_text: str) -> dict:
    summary["output_excerpt_lines"] = output_excerpt_lines(output_text)
    summary["failure_signature"] = failure_signature_from_output(
        summary.get("command") or [],
        summary.get("exit_code"),
        output_text,
        summary.get("failed_tests", []),
    )
    summary.update(
        baseline_regression_status(
            baseline=load_baseline_status(workspace_root),
            current={
                "status": summary.get("status", "unknown"),
                "failure_signature": summary.get("failure_signature"),
                "full_suite": summary.get("full_suite", False),
            },
        )
    )
    return summary


def relevant_history_rows(history_rows: list[dict], changed_files: list[str], changed_symbols: list[str]) -> list[dict]:
    changed_file_set = set(changed_files)
    changed_symbol_set = set(changed_symbols)
    relevant: list[dict] = []
    for row in history_rows:
        if changed_file_set & set(row.get("changed_files", [])):
            relevant.append(row)
            continue
        if changed_symbol_set & set(row.get("changed_symbols", [])):
            relevant.append(row)
    return relevant


def combine_recommended_commands(recommended_tests: list[dict]) -> list[list[str]]:
    commands = [list(item.get("command") or []) for item in recommended_tests if item.get("command")]
    if not commands:
        return []
    if all(command[:3] == ["python", "-m", "unittest"] for command in commands):
        ordered_targets: list[str] = []
        for command in commands:
            for target in command[3:]:
                if target not in ordered_targets:
                    ordered_targets.append(target)
        return [["python", "-m", "unittest", *ordered_targets]]
    if all(command[:2] == ["node", "--test"] for command in commands):
        ordered_files: list[str] = []
        for command in commands:
            for target in command[2:]:
                if target not in ordered_files:
                    ordered_files.append(target)
        return [["node", "--test", *ordered_files]]

    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


def recommend_tests_for_task(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str) -> dict:
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    adapter_name = detect_language_adapter(project_root, config)
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    fallback_command = list(
        resolve_test_command(
            workspace_root=workspace_root,
            project_root=project_root,
            config=config,
            adapter_name=adapter_name,
            profile_name=profile_name,
        ).get("selected_test_command_argv")
        or []
    )
    report_payload = load_task_report_json(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
    )
    direct_test_seeds = list(((report_payload.get("direct") or {}).get("tests")) or [])
    changed_files = list(report_payload.get("changed_files") or [])
    changed_symbols = []
    definition = report_payload.get("definition") or {}
    if definition.get("symbol"):
        changed_symbols.append(definition["symbol"])
    recommended_by_command: dict[tuple[str, ...], dict] = {}
    mapped_count = 0
    for seed in direct_test_seeds:
        command, confidence, reason = map_test_seed_to_command(seed)
        if command:
            mapped_count += 1
            key = tuple(command)
            recommended_by_command[key] = {
                "seed": seed,
                "command": command,
                "confidence": confidence,
                "reason": reason,
                "graph_score": 100,
                "history_score": 0,
                "risk_score": 0,
                "final_score": 100,
                "ranking_explanation": ["graph direct cover"],
            }
    history_rows = relevant_history_rows(load_history_rows(workspace_root), changed_files, changed_symbols)
    for row in history_rows:
        dependency_boost = 20 if row.get("dependency_fingerprint_status") in {"unknown", "changed"} else 0
        for failed_target in row.get("failed_tests", []):
            command = map_history_test_target_to_command(failed_target, adapter_name)
            if not command:
                continue
            key = tuple(command)
            current = recommended_by_command.get(key)
            if current is None:
                current = {
                    "seed": f"history:{failed_target}",
                    "command": command,
                    "confidence": "medium",
                    "reason": "history co-failure",
                    "graph_score": 0,
                    "history_score": 0,
                    "risk_score": 0,
                    "final_score": 0,
                    "ranking_explanation": [],
                }
                recommended_by_command[key] = current
            current["history_score"] += 120
            current["risk_score"] += dependency_boost
            if "history co-failure" not in current["ranking_explanation"]:
                current["ranking_explanation"].append("history co-failure")
            if dependency_boost and "dependency risk boost" not in current["ranking_explanation"]:
                current["ranking_explanation"].append("dependency risk boost")
            if current["reason"] != "direct COVERS edge":
                current["reason"] = "history co-failure"
    recommended_tests = sorted(
        (
            {
                **item,
                "final_score": item["graph_score"] + item["history_score"] + item["risk_score"],
            }
            for item in recommended_by_command.values()
        ),
        key=lambda item: (-item["final_score"], -item["history_score"], item["command"]),
    )
    if not direct_test_seeds or mapped_count == 0:
        mapping_status = "unavailable"
    elif mapped_count == len(direct_test_seeds):
        mapping_status = "mapped"
    else:
        mapping_status = "partial"
    return {
        "task_id": task_id,
        "mapping_status": mapping_status,
        "recommended_tests": recommended_tests,
        "fallback_command": fallback_command,
        "detected_adapter": adapter_name,
        "direct_test_seed_count": len(direct_test_seeds),
        "ranking_explanation": [item["ranking_explanation"] for item in recommended_tests],
    }


def aggregate_test_counts(items: list[tuple[int | None, str]]) -> tuple[int | None, str]:
    counts = [count for count, status in items if status == "parsed" and count is not None]
    if counts and len(counts) == len(items):
        return sum(counts), "parsed"
    return None, "unknown"


def base_test_summary(
    *,
    task_id: str,
    command: list[str],
    commands: list[list[str]],
    requested_test_scope: str,
    effective_test_scope: str,
    test_scope_reason: str,
    full_suite: bool,
    output_path: pathlib.Path,
    adapter_name: str,
) -> dict:
    return {
        "task_id": task_id,
        "command": command,
        "commands": commands,
        "requested_test_scope": requested_test_scope,
        "effective_test_scope": effective_test_scope,
        "test_scope_reason": test_scope_reason,
        "status": "skipped",
        "tests_run": None,
        "test_count_status": "unknown",
        "tests_passed": False,
        "exit_code": None,
        "output_path": str(output_path.relative_to(output_path.parents[2])),
        "coverage_path": None,
        "coverage_status": "unavailable",
        "coverage_available": False,
        "coverage_reason": None,
        "totals": {},
        "full_suite": full_suite,
        "detected_adapter": adapter_name,
    }


def _run_test_scope_once(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    requested_test_scope: str = "configured",
    artifact_suffix: str = "",
    cli_test_command: list[str] | str | None = None,
) -> dict:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    project_root = build_graph.project_root_for(workspace_root, config)
    adapter_name = detect_language_adapter(project_root, config)
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    test_command_payload = resolve_test_command(
        workspace_root=workspace_root,
        project_root=project_root,
        config=config,
        adapter_name=adapter_name,
        profile_name=profile_name,
        cli_test_command=cli_test_command,
    )
    configured_command = list(test_command_payload.get("selected_test_command_argv") or [])
    recommend_payload = recommend_tests_for_task(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
    )
    requested_test_scope = requested_test_scope or "configured"

    suffix = artifact_suffix or ""
    output_path = workspace_root / ".ai" / "codegraph" / f"test-output-{task_id}{suffix}.log"
    coverage_data_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}{suffix}.data"
    coverage_json_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}{suffix}.json"
    recommended_tests = list(recommend_payload.get("recommended_tests") or [])
    targeted_commands = combine_recommended_commands(recommended_tests)

    effective_test_scope = requested_test_scope
    test_scope_reason = "configured test command"
    full_suite = requested_test_scope != "targeted"
    command_groups: list[list[str]]
    if requested_test_scope == "targeted":
        if targeted_commands:
            command_groups = targeted_commands
            full_suite = False
            if recommend_payload.get("mapping_status") == "partial":
                test_scope_reason = "running mapped direct tests only; some direct test seeds could not be mapped"
            else:
                test_scope_reason = "running directly mapped affected tests"
        else:
            effective_test_scope = "configured"
            command_groups = [configured_command] if configured_command else []
            full_suite = True
            test_scope_reason = "no direct test command mapping available"
    elif requested_test_scope == "full":
        command_groups = [configured_command] if configured_command else []
        test_scope_reason = "explicit full suite requested"
        full_suite = True
    else:
        command_groups = [configured_command] if configured_command else []
        test_scope_reason = "using configured test command"
        full_suite = True

    normalized_commands = [normalize_test_command(command) for command in command_groups if command]
    primary_command = normalized_commands[0] if normalized_commands else []
    preflight = preflight_test_command(primary_command, project_root, os.name)

    if not normalized_commands:
        summary = {
            "task_id": task_id,
            "command": primary_command,
            "commands": normalized_commands,
            "requested_test_scope": requested_test_scope,
            "effective_test_scope": "skipped",
            "test_scope_reason": f"no test command configured for adapter {adapter_name}",
            "status": "skipped",
            "tests_run": None,
            "test_count_status": "unknown",
            "tests_passed": False,
            "exit_code": None,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": None,
            "coverage_status": "unavailable",
            "coverage_available": False,
            "coverage_reason": f"no test command configured for adapter {adapter_name}",
            "totals": {},
            "full_suite": False,
            "detected_adapter": adapter_name,
            "recommended_tests": recommended_tests,
            "mapping_status": recommend_payload.get("mapping_status"),
            "fallback_command": recommend_payload.get("fallback_command", []),
            "failed_tests": [],
            "selected_test_command": test_command_payload.get("selected_test_command"),
            "test_command_source": test_command_payload.get("test_command_source"),
            "test_command_candidates": test_command_payload.get("test_command_candidates", []),
            "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
            "test_command_preflight": preflight,
            "recovery_commands": preflight.get("recovery_commands", []),
        }
        output_path.write_text(summary["coverage_reason"], encoding="utf-8")
        summary = enrich_test_summary_with_regression(workspace_root, summary, summary["coverage_reason"])
        write_json(paths["test_results_path"], summary)
        return summary

    if preflight.get("status") == "fail":
        summary = {
            "task_id": task_id,
            "command": primary_command,
            "commands": normalized_commands,
            "requested_test_scope": requested_test_scope,
            "effective_test_scope": "preflight_failed",
            "test_scope_reason": "test command preflight failed before execution",
            "status": "failed",
            "tests_run": None,
            "test_count_status": "unknown",
            "tests_passed": False,
            "exit_code": None,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": None,
            "coverage_status": "unavailable",
            "coverage_available": False,
            "coverage_reason": "test command preflight failed",
            "totals": {},
            "full_suite": full_suite,
            "detected_adapter": adapter_name,
            "recommended_tests": recommended_tests,
            "mapping_status": recommend_payload.get("mapping_status"),
            "fallback_command": recommend_payload.get("fallback_command", []),
            "failed_tests": [],
            "selected_test_command": test_command_payload.get("selected_test_command"),
            "test_command_source": test_command_payload.get("test_command_source"),
            "test_command_candidates": test_command_payload.get("test_command_candidates", []),
            "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
            "test_command_preflight": preflight,
            "recovery_commands": preflight.get("recovery_commands", []),
        }
        output_path.write_text("\n".join(issue["message"] for issue in preflight.get("issues", [])), encoding="utf-8")
        summary = enrich_test_summary_with_regression(workspace_root, summary, output_path.read_text(encoding="utf-8"))
        write_json(paths["test_results_path"], summary)
        return summary

    coverage_adapter = adapter_coverage_adapter(config, adapter_name, project_root)

    if coverage_adapter == "coveragepy" and len(normalized_commands) == 1:
        if not coveragepy_available():
            if coverage_json_path.exists():
                coverage_json_path.unlink()
            if coverage_data_path.exists():
                coverage_data_path.unlink()
            result = subprocess.run(
                normalized_commands[0],
                cwd=project_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            output_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
            parsed_tests_run, test_count_status = parse_test_count(
                result.stdout + "\n" + result.stderr,
                adapter_name,
            )
            summary = {
                "task_id": task_id,
                "command": normalized_commands[0],
                "commands": normalized_commands,
                "requested_test_scope": requested_test_scope,
                "effective_test_scope": effective_test_scope,
                "test_scope_reason": test_scope_reason,
                "status": "passed" if result.returncode == 0 else "failed",
                "tests_run": parsed_tests_run,
                "test_count_status": test_count_status,
                "tests_passed": result.returncode == 0,
                "exit_code": result.returncode,
                "output_path": str(output_path.relative_to(workspace_root)),
                "coverage_path": None,
                "coverage_status": "unavailable",
                "coverage_available": False,
                "coverage_reason": "coverage.py is not installed; ran tests without coverage",
                "totals": {},
                "full_suite": full_suite,
                "detected_adapter": adapter_name,
                "recommended_tests": recommended_tests,
                "mapping_status": recommend_payload.get("mapping_status"),
                "fallback_command": recommend_payload.get("fallback_command", []),
                "failed_tests": parse_failed_tests(result.stdout + "\n" + result.stderr, adapter_name),
                "selected_test_command": test_command_payload.get("selected_test_command"),
                "test_command_source": test_command_payload.get("test_command_source"),
                "test_command_candidates": test_command_payload.get("test_command_candidates", []),
                "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
                "test_command_preflight": preflight,
                "recovery_commands": preflight.get("recovery_commands", []),
            }
            summary = enrich_test_summary_with_regression(workspace_root, summary, result.stdout + "\n" + result.stderr)
            write_json(paths["test_results_path"], summary)
            record_test_command_history(
                workspace_root=workspace_root,
                command=summary.get("command") or [],
                source=summary.get("test_command_source") or "unknown",
                status=summary.get("status", "unknown"),
                adapter_name=adapter_name,
                profile_name=profile_name,
            )
            return summary

        coverage_command = [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--data-file={coverage_data_path}",
            *normalized_commands[0][1:],
        ]
        try:
            result = subprocess.run(
                coverage_command,
                cwd=project_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            output_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        except FileNotFoundError:
            result = subprocess.CompletedProcess(coverage_command, 1, "", "coverage.py is not installed")
            output_path.write_text(result.stderr, encoding="utf-8")
        parsed_tests_run, test_count_status = parse_test_count(
            result.stdout + "\n" + result.stderr,
            adapter_name,
        )

        coverage_status = "available"
        coverage_reason = None
        coverage_payload: dict = {}
        if result.returncode == 0:
            export = subprocess.run(
                [sys.executable, "-m", "coverage", "json", f"--data-file={coverage_data_path}", "-o", str(coverage_json_path)],
                cwd=project_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            if export.returncode == 0 and coverage_json_path.exists():
                coverage_payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            else:
                coverage_status = "unavailable"
                coverage_reason = export.stderr.strip() or "coverage json export failed"
        else:
            coverage_status = "tests_failed"
            coverage_reason = "configured test command failed"

        summary = {
            "task_id": task_id,
            "command": coverage_command,
            "commands": [coverage_command],
            "requested_test_scope": requested_test_scope,
            "effective_test_scope": effective_test_scope,
            "test_scope_reason": test_scope_reason,
            "status": "passed" if result.returncode == 0 else "failed",
            "tests_run": parsed_tests_run,
            "test_count_status": test_count_status,
            "tests_passed": result.returncode == 0,
            "exit_code": result.returncode,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": str(coverage_json_path.relative_to(workspace_root)) if coverage_json_path.exists() else None,
            "coverage_status": coverage_status,
            "coverage_available": coverage_status == "available",
            "coverage_reason": coverage_reason,
            "totals": coverage_payload.get("totals", {}),
            "full_suite": full_suite,
            "detected_adapter": adapter_name,
            "recommended_tests": recommended_tests,
            "mapping_status": recommend_payload.get("mapping_status"),
            "fallback_command": recommend_payload.get("fallback_command", []),
            "failed_tests": parse_failed_tests(result.stdout + "\n" + result.stderr, adapter_name),
            "selected_test_command": test_command_payload.get("selected_test_command"),
            "test_command_source": test_command_payload.get("test_command_source"),
            "test_command_candidates": test_command_payload.get("test_command_candidates", []),
            "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
            "test_command_preflight": preflight,
            "recovery_commands": preflight.get("recovery_commands", []),
        }
        summary = enrich_test_summary_with_regression(workspace_root, summary, result.stdout + "\n" + result.stderr)
        write_json(paths["test_results_path"], summary)
        record_test_command_history(
            workspace_root=workspace_root,
            command=normalized_commands[0],
            source=summary.get("test_command_source") or "unknown",
            status=summary.get("status", "unknown"),
            adapter_name=adapter_name,
            profile_name=profile_name,
        )
        return summary

    if coverage_adapter == "v8_family" and len(normalized_commands) == 1:
        coverage_dir = workspace_root / ".ai" / "codegraph" / f"v8-coverage-{task_id}"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        for stale in coverage_dir.glob("*.json"):
            stale.unlink()
        env = os.environ.copy()
        env["NODE_V8_COVERAGE"] = str(coverage_dir)
        result = subprocess.run(
            normalized_commands[0],
            cwd=project_root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        output_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        parsed_tests_run, test_count_status = parse_test_count(
            result.stdout + "\n" + result.stderr,
            adapter_name,
        )
        coverage_payload = {"result": [], "summary": {"files": {}}}
        coverage_status = "available"
        coverage_reason = None
        if result.returncode == 0:
            for raw_json in sorted(coverage_dir.glob("*.json")):
                try:
                    payload = json.loads(raw_json.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                coverage_payload["result"].append(payload)
                for script in payload.get("result", []):
                    relative_path = v8_relative_path(script.get("url", ""), project_root)
                    if not relative_path:
                        continue
                    functions = script.get("functions", [])
                    covered_functions = sum(
                        1
                        for item in functions
                        if any(section.get("count", 0) > 0 for section in item.get("ranges", []))
                    )
                    summary = coverage_payload["summary"]["files"].setdefault(
                        relative_path,
                        {"function_count": 0, "covered_function_count": 0, "range_count": 0, "covered_range_count": 0},
                    )
                    summary["function_count"] += len(functions)
                    summary["covered_function_count"] += covered_functions
                    for item in functions:
                        ranges = item.get("ranges", [])
                        summary["range_count"] += len(ranges)
                        summary["covered_range_count"] += sum(1 for section in ranges if section.get("count", 0) > 0)
            coverage_json_path.write_text(json.dumps(coverage_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            coverage_status = "tests_failed"
            coverage_reason = "configured test command failed"

        summary = {
            "task_id": task_id,
            "command": normalized_commands[0],
            "commands": normalized_commands,
            "requested_test_scope": requested_test_scope,
            "effective_test_scope": effective_test_scope,
            "test_scope_reason": test_scope_reason,
            "status": "passed" if result.returncode == 0 else "failed",
            "tests_run": parsed_tests_run,
            "test_count_status": test_count_status,
            "tests_passed": result.returncode == 0,
            "exit_code": result.returncode,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": str(coverage_json_path.relative_to(workspace_root)) if coverage_json_path.exists() else None,
            "coverage_status": coverage_status,
            "coverage_available": coverage_status == "available",
            "coverage_reason": coverage_reason,
            "totals": {
                "file_count": len(coverage_payload.get("summary", {}).get("files", {})),
            },
            "full_suite": full_suite,
            "detected_adapter": adapter_name,
            "recommended_tests": recommended_tests,
            "mapping_status": recommend_payload.get("mapping_status"),
            "fallback_command": recommend_payload.get("fallback_command", []),
            "failed_tests": parse_failed_tests(result.stdout + "\n" + result.stderr, adapter_name),
            "selected_test_command": test_command_payload.get("selected_test_command"),
            "test_command_source": test_command_payload.get("test_command_source"),
            "test_command_candidates": test_command_payload.get("test_command_candidates", []),
            "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
            "test_command_preflight": preflight,
            "recovery_commands": preflight.get("recovery_commands", []),
        }
        summary = enrich_test_summary_with_regression(workspace_root, summary, result.stdout + "\n" + result.stderr)
        write_json(paths["test_results_path"], summary)
        record_test_command_history(
            workspace_root=workspace_root,
            command=normalized_commands[0],
            source=summary.get("test_command_source") or "unknown",
            status=summary.get("status", "unknown"),
            adapter_name=adapter_name,
            profile_name=profile_name,
        )
        return summary

    outputs: list[str] = []
    parsed_counts: list[tuple[int | None, str]] = []
    exit_code = 0
    for command in normalized_commands:
        result = subprocess.run(
            command,
            cwd=project_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        outputs.append(" ".join(command))
        outputs.append(result.stdout)
        outputs.append(result.stderr)
        parsed_counts.append(parse_test_count(result.stdout + "\n" + result.stderr, adapter_name))
        if result.returncode != 0 and exit_code == 0:
            exit_code = result.returncode
    output_path.write_text("\n".join(outputs), encoding="utf-8")
    parsed_tests_run, test_count_status = aggregate_test_counts(parsed_counts)
    summary = {
        "task_id": task_id,
        "command": primary_command,
        "commands": normalized_commands,
        "requested_test_scope": requested_test_scope,
        "effective_test_scope": effective_test_scope,
        "test_scope_reason": test_scope_reason,
        "status": "passed" if exit_code == 0 else "failed",
        "tests_run": parsed_tests_run,
        "test_count_status": test_count_status,
        "tests_passed": exit_code == 0,
        "exit_code": exit_code,
        "output_path": str(output_path.relative_to(workspace_root)),
        "coverage_path": None,
        "coverage_status": "unavailable",
        "coverage_available": False,
        "coverage_reason": f"coverage adapter unavailable for {adapter_name}",
        "totals": {},
        "full_suite": full_suite,
        "detected_adapter": adapter_name,
        "recommended_tests": recommended_tests,
        "mapping_status": recommend_payload.get("mapping_status"),
        "fallback_command": recommend_payload.get("fallback_command", []),
        "failed_tests": parse_failed_tests("\n".join(outputs), adapter_name),
        "selected_test_command": test_command_payload.get("selected_test_command"),
        "test_command_source": test_command_payload.get("test_command_source"),
        "test_command_candidates": test_command_payload.get("test_command_candidates", []),
        "ignored_test_commands": test_command_payload.get("ignored_test_commands", []),
        "test_command_preflight": preflight,
        "recovery_commands": preflight.get("recovery_commands", []),
    }
    summary = enrich_test_summary_with_regression(workspace_root, summary, "\n".join(outputs))
    write_json(paths["test_results_path"], summary)
    record_test_command_history(
        workspace_root=workspace_root,
        command=primary_command,
        source=summary.get("test_command_source") or "unknown",
        status=summary.get("status", "unknown"),
        adapter_name=adapter_name,
        profile_name=profile_name,
    )
    return summary


def run_tests_with_coverage(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    requested_test_scope: str = "configured",
    shadow_full: bool = False,
    cli_test_command: list[str] | str | None = None,
) -> dict:
    primary = _run_test_scope_once(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        requested_test_scope=requested_test_scope,
        cli_test_command=cli_test_command,
    )
    if not shadow_full:
        return primary

    primary_scope = primary.get("effective_test_scope") or requested_test_scope
    if requested_test_scope == "targeted":
        shadow_scope = "configured"
        comparison = "targeted-vs-configured"
    elif primary_scope == "configured":
        shadow_scope = "full"
        comparison = "configured-vs-full"
    else:
        shadow_scope = "full"
        comparison = f"{primary_scope}-vs-full"

    shadow = _run_test_scope_once(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        requested_test_scope=shadow_scope,
        artifact_suffix="-shadow",
        cli_test_command=cli_test_command,
    )
    primary_failed = set(primary.get("failed_tests", []))
    shadow_failed = set(shadow.get("failed_tests", []))
    missed_failures = sorted(shadow_failed - primary_failed)
    shadow_failure_count = max(len(shadow_failed), 1)
    selection_quality = {
        "shadow_run": True,
        "comparison": comparison,
        "targeted_passed": bool(primary.get("tests_passed")),
        "shadow_passed": bool(shadow.get("tests_passed")),
        "missed_failures": missed_failures,
        "safe": not missed_failures,
        "precision": round((len(shadow_failed) - len(missed_failures)) / shadow_failure_count, 2),
        "miss_rate": round(len(missed_failures) / shadow_failure_count, 2),
    }
    primary["selection_quality"] = selection_quality
    primary["shadow_summary"] = {
        "requested_test_scope": shadow_scope,
        "effective_test_scope": shadow.get("effective_test_scope"),
        "status": shadow.get("status"),
        "tests_passed": shadow.get("tests_passed"),
        "failed_tests": shadow.get("failed_tests", []),
        "output_path": shadow.get("output_path"),
    }

    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    paths["test_results_path"].write_text(json.dumps(primary, ensure_ascii=False, indent=2), encoding="utf-8")
    return primary


def record_test_run(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str, test_summary: dict) -> str:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    run_id = f"testrun-{uuid.uuid4().hex[:12]}"
    with connect_db(paths["db_path"]) as conn:
        conn.execute(
            """
            INSERT INTO test_runs (
                run_id, task_id, command_json, status, exit_code, output_path,
                coverage_path, coverage_status, coverage_reason, attrs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_id,
                json.dumps(test_summary.get("command") or test_summary.get("commands") or [], ensure_ascii=False),
                test_summary["status"],
                test_summary["exit_code"],
                test_summary["output_path"],
                test_summary["coverage_path"],
                test_summary["coverage_status"],
                test_summary["coverage_reason"],
                json.dumps(
                    {
                        "totals": test_summary.get("totals", {}),
                        "detected_adapter": test_summary.get("detected_adapter"),
                        "commands": test_summary.get("commands", []),
                        "requested_test_scope": test_summary.get("requested_test_scope"),
                        "effective_test_scope": test_summary.get("effective_test_scope"),
                    },
                    ensure_ascii=False,
                ),
            ),
        )
    return run_id


def import_coverage(*, workspace_root: pathlib.Path, config_path: pathlib.Path, run_id: str, test_summary: dict) -> None:
    if not test_summary.get("coverage_path"):
        return
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    payload = json.loads((workspace_root / test_summary["coverage_path"]).read_text(encoding="utf-8"))
    with connect_db(paths["db_path"]) as conn:
        file_entries = payload.get("files", {}) or payload.get("summary", {}).get("files", {})
        for file_path, raw_data in file_entries.items():
            node_id = build_graph.file_node_id(file_path)
            target_node_id = node_id if conn.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone() else None
            conn.execute(
                """
                INSERT INTO coverage_observations (run_id, test_node_id, target_node_id, file_path, line_no, summary_json, raw_json)
                VALUES (?, NULL, ?, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    target_node_id,
                    file_path,
                    json.dumps(raw_data.get("summary", {}), ensure_ascii=False),
                    json.dumps(raw_data, ensure_ascii=False),
                ),
            )


def relation_diff(before: dict | None, after: dict | None) -> dict:
    before = before or {"callers": [], "callees": [], "tests": [], "rules": [], "importers": [], "imports": []}
    after = after or {"callers": [], "callees": [], "tests": [], "rules": [], "importers": [], "imports": []}
    payload: dict[str, list[str]] = {}
    for key in ("callers", "callees", "tests", "rules", "importers", "imports"):
        before_set = set(before.get(key, []))
        after_set = set(after.get(key, []))
        payload[f"{key}_added"] = sorted(after_set - before_set)
        payload[f"{key}_removed"] = sorted(before_set - after_set)
    return payload


def diff_files(before_snapshot: dict, after_snapshot: dict, changed_files: list[str]) -> list[dict]:
    file_diffs: list[dict] = []
    for file_path in sorted(set(changed_files)):
        before_file = before_snapshot["files"].get(file_path)
        after_file = after_snapshot["files"].get(file_path)
        before_hash = (before_file or {}).get("attrs", {}).get("content_hash")
        after_hash = (after_file or {}).get("attrs", {}).get("content_hash")
        if before_file and after_file:
            diff_kind = "modified" if before_hash != after_hash else "modified"
        elif after_file:
            diff_kind = "added"
        else:
            diff_kind = "removed"
        file_diffs.append(
            {
                "file_path": file_path,
                "diff_kind": diff_kind,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "summary": {
                    "before_exists": before_file is not None,
                    "after_exists": after_file is not None,
                },
            }
        )
    return file_diffs


def conservative_renames(removed: list[dict], added: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    remaining_removed = removed[:]
    remaining_added = added[:]
    renamed: list[dict] = []
    for removed_item in removed:
        matches = [
            added_item
            for added_item in remaining_added
            if added_item["file_path"] == removed_item["file_path"]
            and added_item["summary"].get("body_hash")
            and added_item["summary"].get("body_hash") == removed_item["summary"].get("body_hash")
        ]
        if len(matches) != 1:
            continue
        match = matches[0]
        renamed.append(
            {
                "file_path": removed_item["file_path"],
                "symbol_kind": "function",
                "diff_kind": "renamed",
                "before_symbol": removed_item["before_symbol"],
                "after_symbol": match["after_symbol"],
                "summary": {
                    "before_node_id": removed_item["summary"]["before_node_id"],
                    "after_node_id": match["summary"]["after_node_id"],
                    "body_hash": removed_item["summary"].get("body_hash"),
                },
            }
        )
        remaining_removed.remove(removed_item)
        remaining_added.remove(match)
    return remaining_removed, remaining_added, renamed


def diff_symbols(before_snapshot: dict, after_snapshot: dict, changed_files: list[str]) -> list[dict]:
    symbol_diffs: list[dict] = []
    for file_path in sorted(set(changed_files)):
        before_items = {item["symbol"]: item for item in before_snapshot["functions_by_file"].get(file_path, [])}
        after_items = {item["symbol"]: item for item in after_snapshot["functions_by_file"].get(file_path, [])}

        for symbol in sorted(before_items.keys() & after_items.keys()):
            before_item = before_items[symbol]
            after_item = after_items[symbol]
            if before_item["attrs"].get("body_hash") == after_item["attrs"].get("body_hash"):
                continue
            symbol_diffs.append(
                {
                    "file_path": file_path,
                    "symbol_kind": "function",
                    "diff_kind": "modified",
                    "before_symbol": symbol,
                    "after_symbol": symbol,
                    "summary": {
                        "before_node_id": before_item["node_id"],
                        "after_node_id": after_item["node_id"],
                        "before_body_hash": before_item["attrs"].get("body_hash"),
                        "after_body_hash": after_item["attrs"].get("body_hash"),
                    },
                }
            )

        removed = [
            {
                "file_path": file_path,
                "symbol_kind": "function",
                "diff_kind": "removed",
                "before_symbol": symbol,
                "after_symbol": None,
                "summary": {
                    "before_node_id": before_items[symbol]["node_id"],
                    "body_hash": before_items[symbol]["attrs"].get("body_hash"),
                },
            }
            for symbol in sorted(before_items.keys() - after_items.keys())
        ]
        added = [
            {
                "file_path": file_path,
                "symbol_kind": "function",
                "diff_kind": "added",
                "before_symbol": None,
                "after_symbol": symbol,
                "summary": {
                    "after_node_id": after_items[symbol]["node_id"],
                    "body_hash": after_items[symbol]["attrs"].get("body_hash"),
                },
            }
            for symbol in sorted(after_items.keys() - before_items.keys())
        ]

        removed, added, renamed = conservative_renames(removed, added)
        symbol_diffs.extend(renamed)
        symbol_diffs.extend(removed)
        symbol_diffs.extend(added)
    return symbol_diffs


def summarize_round(*, seed: str, changed_files: list[str], before_snapshot: dict, after_snapshot: dict, symbol_diffs: list[dict]) -> dict:
    function_diffs = {"added": [], "removed": [], "modified": [], "renamed": []}
    for item in symbol_diffs:
        bucket = function_diffs[item["diff_kind"]]
        if item["diff_kind"] == "renamed":
            bucket.append({"file_path": item["file_path"], "before_symbol": item["before_symbol"], "after_symbol": item["after_symbol"]})
        elif item["diff_kind"] == "modified":
            bucket.append({"file_path": item["file_path"], "symbol": item["after_symbol"]})
        elif item["diff_kind"] == "added":
            bucket.append({"file_path": item["file_path"], "symbol": item["after_symbol"]})
        else:
            bucket.append({"file_path": item["file_path"], "symbol": item["before_symbol"]})

    relation_targets = {seed}
    for item in symbol_diffs:
        if item["diff_kind"] == "removed":
            relation_targets.add(item["summary"]["before_node_id"])
        elif item["diff_kind"] == "renamed":
            relation_targets.add(item["summary"]["after_node_id"])
        else:
            relation_targets.add(item["summary"].get("after_node_id", item["summary"].get("before_node_id")))

    relation_diffs: dict[str, dict] = {}
    for node_id in sorted(target for target in relation_targets if target):
        relation_diffs[node_id] = relation_diff(before_snapshot["relations"].get(node_id), after_snapshot["relations"].get(node_id))

    return {
        "changed_files": changed_files,
        "function_diffs": function_diffs,
        "relation_diffs": relation_diffs,
    }


def diff_summary_lines(summary: dict) -> list[str]:
    added = ", ".join(item["symbol"] for item in summary["function_diffs"]["added"]) or "none"
    removed = ", ".join(item["symbol"] for item in summary["function_diffs"]["removed"]) or "none"
    modified = ", ".join(item["symbol"] for item in summary["function_diffs"]["modified"]) or "none"
    renamed = ", ".join(f"{item['before_symbol']}->{item['after_symbol']}" for item in summary["function_diffs"]["renamed"]) or "none"
    lines = [
        f"- changed_files: {', '.join(summary['changed_files']) if summary['changed_files'] else 'none'}",
        f"- functions_added: {added}",
        f"- functions_removed: {removed}",
        f"- functions_modified: {modified}",
        f"- functions_renamed: {renamed}",
    ]
    for node_id, relation in sorted(summary["relation_diffs"].items()):
        lines.append(
            f"- relation_diff[{node_id}]: "
            f"callers(+{len(relation['callers_added'])}/-{len(relation['callers_removed'])}), "
            f"callees(+{len(relation['callees_added'])}/-{len(relation['callees_removed'])}), "
            f"tests(+{len(relation['tests_added'])}/-{len(relation['tests_removed'])}), "
            f"rules(+{len(relation['rules_added'])}/-{len(relation['rules_removed'])})"
        )
    return lines


def changed_symbols_from_summary(summary: dict) -> list[str]:
    symbols: list[str] = []
    for item in summary.get("function_diffs", {}).get("added", []):
        if item.get("symbol"):
            symbols.append(item["symbol"])
    for item in summary.get("function_diffs", {}).get("modified", []):
        if item.get("symbol"):
            symbols.append(item["symbol"])
    for item in summary.get("function_diffs", {}).get("renamed", []):
        if item.get("after_symbol"):
            symbols.append(item["after_symbol"])
    return symbols


def record_pending_changes(
    *,
    workspace_root: pathlib.Path,
    changed_files: list[str],
    task_id: str,
    source: str,
    status: str,
) -> None:
    paths = runtime_paths(workspace_root)
    for changed_file in changed_files:
        append_jsonl(
            paths["pending_changes"],
            {
                "path": changed_file,
                "timestamp": utc_now(),
                "source": source,
                "task_id": task_id,
                "status": status,
            },
        )


def record_test_history(
    *,
    workspace_root: pathlib.Path,
    task_id: str,
    changed_files: list[str],
    changed_symbols: list[str],
    test_summary: dict,
    dependency_fingerprint_status: str,
    parser_trust: str,
    graph_trust: str,
    budget: str | None,
) -> None:
    paths = runtime_paths(workspace_root)
    append_jsonl(
        paths["test_history"],
        {
            "task_id": task_id,
            "changed_files": changed_files,
            "changed_symbols": changed_symbols,
            "recommended_tests": [item.get("seed") for item in test_summary.get("recommended_tests", [])],
            "executed_commands": test_summary.get("commands", []),
            "failed_tests": test_summary.get("failed_tests", []),
            "test_scope": test_summary.get("effective_test_scope"),
            "dependency_fingerprint_status": dependency_fingerprint_status,
            "parser_trust": parser_trust,
            "graph_trust": graph_trust,
            "budget": budget,
            "timestamp": utc_now(),
        },
    )


def backfill_test_history_budget(*, workspace_root: pathlib.Path, task_id: str, budget: str | None) -> None:
    if not budget:
        return
    paths = runtime_paths(workspace_root)
    history_path = paths["test_history"]
    if not history_path.exists():
        return
    rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    updated = False
    for row in reversed(rows):
        if row.get("task_id") != task_id:
            continue
        if row.get("budget") == budget:
            return
        row["budget"] = budget
        updated = True
        break
    if not updated:
        return
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def record_calibration(
    *,
    workspace_root: pathlib.Path,
    task_id: str,
    changed_files: list[str],
    selection_quality: dict,
) -> None:
    if not selection_quality:
        return
    paths = runtime_paths(workspace_root)
    append_jsonl(
        paths["calibration"],
        {
            "task_id": task_id,
            "changed_files": changed_files,
            "selection_quality": selection_quality,
            "timestamp": utc_now(),
        },
    )


def after_edit_update(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    seed: str,
    changed_files: list[str],
    report_mode: str = "brief",
    test_scope: str = "configured",
    shadow_full: bool = False,
    verification_budget: str | None = None,
    source: str = "after-edit",
    cli_test_command: list[str] | str | None = None,
) -> dict:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)

    before_snapshot = {"files": {}, "functions_by_file": {}, "relations": {}}
    if paths["db_path"].exists():
        with connect_db(paths["db_path"]) as conn:
            before_snapshot = build_graph.snapshot_for_files(conn, changed_files)
            before_snapshot["relations"][seed] = build_graph.relation_snapshot(conn, seed)

    graph_summary = build_graph.build_graph(workspace_root=workspace_root, config_path=config_path, changed_files=changed_files)

    with connect_db(paths["db_path"]) as conn:
        after_snapshot = build_graph.snapshot_for_files(conn, changed_files)
        after_snapshot["relations"][seed] = build_graph.relation_snapshot(conn, seed)

    symbol_diffs = diff_symbols(before_snapshot, after_snapshot, changed_files)
    file_diffs = diff_files(before_snapshot, after_snapshot, changed_files)
    round_summary = summarize_round(
        seed=seed,
        changed_files=changed_files,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        symbol_diffs=symbol_diffs,
    )

    test_summary = run_tests_with_coverage(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        requested_test_scope=test_scope,
        shadow_full=shadow_full,
        cli_test_command=cli_test_command,
    )
    report_summary = generate_report.generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        seed=seed,
        max_depth=None,
        mode=report_mode,
        changed_files=changed_files,
        test_summary=test_summary,
        build_decision=graph_summary.get("build_decision"),
    )
    test_signal = (report_summary.get("brief") or {}).get("test_signal", {})
    test_summary["affected_tests_found"] = test_signal.get("affected_tests_found", False)
    test_summary["coverage_relevance"] = test_signal.get("coverage_relevance")
    test_summary["full_suite"] = test_signal.get("full_suite", test_summary.get("full_suite", True))
    paths["test_results_path"].write_text(json.dumps(test_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = record_test_run(workspace_root=workspace_root, config_path=config_path, task_id=task_id, test_summary=test_summary)
    import_coverage(workspace_root=workspace_root, config_path=config_path, run_id=run_id, test_summary=test_summary)
    record_pending_changes(
        workspace_root=workspace_root,
        changed_files=changed_files,
        task_id=task_id,
        source=source,
        status="pending",
    )
    report_trust = report_summary.get("trust", {})
    record_test_history(
        workspace_root=workspace_root,
        task_id=task_id,
        changed_files=changed_files,
        changed_symbols=changed_symbols_from_summary(round_summary),
        test_summary=test_summary,
        dependency_fingerprint_status=(graph_summary.get("build_decision") or {}).get("dependency_fingerprint_status", "unknown"),
        parser_trust=report_trust.get("parser", "unknown"),
        graph_trust=report_trust.get("graph", (graph_summary.get("build_decision") or {}).get("graph_trust", "unknown")),
        budget=verification_budget,
    )
    record_calibration(
        workspace_root=workspace_root,
        task_id=task_id,
        changed_files=changed_files,
        selection_quality=test_summary.get("selection_quality", {}),
    )

    task_run_id = build_graph.record_task_run(
        db_path=paths["db_path"],
        task_id=task_id,
        seed_node_id=seed,
        command_name="after-edit",
        detected_adapter=graph_summary["detected_adapter"],
        report_path=str(pathlib.Path(report_summary["report_path"]).relative_to(workspace_root)),
        status="completed",
        attrs={"tests": test_summary["status"], "changed_files": changed_files},
    )
    edit_round_id = build_graph.write_edit_round(
        db_path=paths["db_path"],
        task_id=task_id,
        task_run_id=task_run_id,
        seed_node_id=seed,
        changed_files=changed_files,
        summary=round_summary,
    )
    build_graph.write_file_diffs(paths["db_path"], edit_round_id, file_diffs)
    build_graph.write_symbol_diffs(paths["db_path"], edit_round_id, symbol_diffs)

    append_post_change_note(
        pathlib.Path(report_summary["report_path"]),
        [
            f"- updated_at: {utc_now()}",
            f"- graph_refresh: complete ({graph_summary['node_count']} nodes, {graph_summary['edge_count']} edges)",
            f"- tests: {test_summary['status']} (exit_code={test_summary['exit_code']})",
            f"- tests_run: {test_summary.get('tests_run') if test_summary.get('tests_run') is not None else 'unknown'}",
            f"- tests_passed: {test_summary.get('tests_passed', False)}",
            f"- affected_tests_found: {test_summary.get('affected_tests_found', False)}",
            f"- coverage_status: {test_summary['coverage_status']}",
            f"- coverage_available: {test_summary.get('coverage_available', False)}",
            f"- coverage_relevance: {test_summary.get('coverage_relevance') or 'unknown'}",
            f"- coverage_reason: {test_summary['coverage_reason'] or 'none'}",
            *diff_summary_lines(round_summary),
        ],
    )
    return {
        "graph": graph_summary,
        "report": report_summary,
        "tests": test_summary,
        "run_id": run_id,
        "task_run_id": task_run_id,
        "edit_round_id": edit_round_id,
        "round_summary": round_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh graph and evidence after a code edit")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".zhanggong-impact-blueprint/config.json", help="Config path")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--seed", required=True, help="Seed node id")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file relative to the configured project root")
    parser.add_argument("--test-scope", choices=["targeted", "configured", "full"], default="configured", help="How broadly to run tests after the edit")
    args = parser.parse_args()
    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()
    summary = after_edit_update(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=args.task_id,
        seed=args.seed,
        changed_files=args.changed_file,
        test_scope=args.test_scope,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

