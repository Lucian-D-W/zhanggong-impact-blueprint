#!/usr/bin/env python3
import argparse
import json
import pathlib
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import build_graph
import generate_report
from adapters import adapter_coverage_adapter, adapter_test_command, detect_language_adapter


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
    return command


def run_tests_with_coverage(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str) -> dict:
    config = build_graph.load_config(config_path)
    paths = build_graph.graph_paths(workspace_root, config)
    project_root = build_graph.project_root_for(workspace_root, config)
    adapter_name = detect_language_adapter(project_root, config)
    configured_command = adapter_test_command(config, adapter_name)
    command = normalize_test_command(configured_command)

    output_path = workspace_root / ".ai" / "codegraph" / f"test-output-{task_id}.log"
    coverage_data_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}.data"
    coverage_json_path = workspace_root / ".ai" / "codegraph" / f"coverage-{task_id}.json"

    if not command:
        summary = {
            "task_id": task_id,
            "command": [],
            "status": "skipped",
            "exit_code": None,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": None,
            "coverage_status": "unavailable",
            "coverage_reason": f"no test command configured for adapter {adapter_name}",
            "totals": {},
            "detected_adapter": adapter_name,
        }
        output_path.write_text(summary["coverage_reason"], encoding="utf-8")
        paths["test_results_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    coverage_adapter = adapter_coverage_adapter(config, adapter_name)

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
            "exit_code": result.returncode,
            "output_path": str(output_path.relative_to(workspace_root)),
            "coverage_path": str(coverage_json_path.relative_to(workspace_root)) if coverage_json_path.exists() else None,
            "coverage_status": coverage_status,
            "coverage_reason": coverage_reason,
            "totals": coverage_payload.get("totals", {}),
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
        "exit_code": result.returncode,
        "output_path": str(output_path.relative_to(workspace_root)),
        "coverage_path": None,
        "coverage_status": "unavailable",
        "coverage_reason": f"coverage adapter unavailable for {adapter_name}",
        "totals": {},
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
        for file_path, raw_data in payload.get("files", {}).items():
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


def after_edit_update(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str, seed: str, changed_files: list[str]) -> dict:
    graph_summary = build_graph.build_graph(workspace_root=workspace_root, config_path=config_path)
    report_summary = generate_report.generate_report(workspace_root=workspace_root, config_path=config_path, task_id=task_id, seed=seed, max_depth=None)
    test_summary = run_tests_with_coverage(workspace_root=workspace_root, config_path=config_path, task_id=task_id)
    run_id = record_test_run(workspace_root=workspace_root, config_path=config_path, task_id=task_id, test_summary=test_summary)
    import_coverage(workspace_root=workspace_root, config_path=config_path, run_id=run_id, test_summary=test_summary)

    append_post_change_note(
        pathlib.Path(report_summary["report_path"]),
        [
            f"- updated_at: {utc_now()}",
            f"- changed_files: {', '.join(changed_files) if changed_files else 'none'}",
            f"- graph_refresh: complete ({graph_summary['node_count']} nodes, {graph_summary['edge_count']} edges)",
            f"- tests: {test_summary['status']} (exit_code={test_summary['exit_code']})",
            f"- coverage_status: {test_summary['coverage_status']}",
            f"- coverage_reason: {test_summary['coverage_reason'] or 'none'}",
        ],
    )
    return {"graph": graph_summary, "report": report_summary, "tests": test_summary, "run_id": run_id}


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
    summary = after_edit_update(workspace_root=workspace_root, config_path=config_path, task_id=args.task_id, seed=args.seed, changed_files=args.changed_file)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
