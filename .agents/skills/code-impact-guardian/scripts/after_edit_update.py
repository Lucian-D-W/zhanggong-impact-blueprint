#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import build_graph
import generate_report
from adapters import adapter_coverage_adapter, adapter_test_command, detect_language_adapter
from parser_backends import v8_relative_path


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


def run_tests_with_coverage(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str) -> dict:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    project_root = build_graph.project_root_for(workspace_root, config)
    adapter_name = detect_language_adapter(project_root, config)
    configured_command = adapter_test_command(config, adapter_name, project_root)
    command = normalize_test_command(configured_command)

    output_path = workspace_root / ".ai" / "codegraph" / f"test-output-{task_id}.log"
    coverage_data_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}.data"
    coverage_json_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}.json"

    if not command:
        summary = {
            "task_id": task_id,
            "command": [],
            "status": "skipped",
            "tests_run": 0,
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
        }
        output_path.write_text(summary["coverage_reason"], encoding="utf-8")
        paths["test_results_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    coverage_adapter = adapter_coverage_adapter(config, adapter_name, project_root)

    if coverage_adapter == "coveragepy":
        coverage_command = [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--data-file={coverage_data_path}",
            *command[1:],
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
            "status": "passed" if result.returncode == 0 else "failed",
            "tests_run": 1,
            "tests_passed": result.returncode == 0,
            "exit_code": result.returncode,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": str(coverage_json_path.relative_to(workspace_root)) if coverage_json_path.exists() else None,
            "coverage_status": coverage_status,
            "coverage_available": coverage_status == "available",
            "coverage_reason": coverage_reason,
            "totals": coverage_payload.get("totals", {}),
            "full_suite": True,
            "detected_adapter": adapter_name,
        }
        paths["test_results_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    if coverage_adapter == "v8_family":
        coverage_dir = workspace_root / ".ai" / "codegraph" / f"v8-coverage-{task_id}"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        for stale in coverage_dir.glob("*.json"):
            stale.unlink()
        env = os.environ.copy()
        env["NODE_V8_COVERAGE"] = str(coverage_dir)
        result = subprocess.run(
            command,
            cwd=project_root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        output_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
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
            "command": command,
            "status": "passed" if result.returncode == 0 else "failed",
            "tests_run": 1,
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
            "full_suite": True,
            "detected_adapter": adapter_name,
        }
        paths["test_results_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    result = subprocess.run(
        command,
        cwd=project_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    output_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    summary = {
        "task_id": task_id,
        "command": command,
        "status": "passed" if result.returncode == 0 else "failed",
        "tests_run": 1,
        "tests_passed": result.returncode == 0,
        "exit_code": result.returncode,
        "output_path": str(output_path.relative_to(workspace_root)),
        "coverage_path": None,
        "coverage_status": "unavailable",
        "coverage_available": False,
        "coverage_reason": f"coverage adapter unavailable for {adapter_name}",
        "totals": {},
        "full_suite": True,
        "detected_adapter": adapter_name,
    }
    paths["test_results_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def record_test_run(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str, test_summary: dict) -> str:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    run_id = f"testrun-{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(paths["db_path"]) as conn:
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
                json.dumps(test_summary["command"], ensure_ascii=False),
                test_summary["status"],
                test_summary["exit_code"],
                test_summary["output_path"],
                test_summary["coverage_path"],
                test_summary["coverage_status"],
                test_summary["coverage_reason"],
                json.dumps({"totals": test_summary.get("totals", {}), "detected_adapter": test_summary.get("detected_adapter")}, ensure_ascii=False),
            ),
        )
        conn.commit()
    return run_id


def import_coverage(*, workspace_root: pathlib.Path, config_path: pathlib.Path, run_id: str, test_summary: dict) -> None:
    if not test_summary.get("coverage_path"):
        return
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    payload = json.loads((workspace_root / test_summary["coverage_path"]).read_text(encoding="utf-8"))
    with sqlite3.connect(paths["db_path"]) as conn:
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
        conn.commit()


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


def after_edit_update(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    seed: str,
    changed_files: list[str],
    report_mode: str = "brief",
) -> dict:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)

    before_snapshot = {"files": {}, "functions_by_file": {}, "relations": {}}
    if paths["db_path"].exists():
        with sqlite3.connect(paths["db_path"]) as conn:
            before_snapshot = build_graph.snapshot_for_files(conn, changed_files)
            before_snapshot["relations"][seed] = build_graph.relation_snapshot(conn, seed)

    graph_summary = build_graph.build_graph(workspace_root=workspace_root, config_path=config_path, changed_files=changed_files)

    with sqlite3.connect(paths["db_path"]) as conn:
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

    test_summary = run_tests_with_coverage(workspace_root=workspace_root, config_path=config_path, task_id=task_id)
    report_summary = generate_report.generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=task_id,
        seed=seed,
        max_depth=None,
        mode=report_mode,
        changed_files=changed_files,
        test_summary=test_summary,
    )
    test_signal = (report_summary.get("brief") or {}).get("test_signal", {})
    test_summary["affected_tests_found"] = test_signal.get("affected_tests_found", False)
    test_summary["coverage_relevance"] = test_signal.get("coverage_relevance")
    test_summary["full_suite"] = test_signal.get("full_suite", test_summary.get("full_suite", True))
    paths["test_results_path"].write_text(json.dumps(test_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = record_test_run(workspace_root=workspace_root, config_path=config_path, task_id=task_id, test_summary=test_summary)
    import_coverage(workspace_root=workspace_root, config_path=config_path, run_id=run_id, test_summary=test_summary)

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
            f"- tests_run: {test_summary.get('tests_run', 0)}",
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
    parser.add_argument("--config", default=".code-impact-guardian/config.json", help="Config path")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--seed", required=True, help="Seed node id")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file relative to the configured project root")
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
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
