#!/usr/bin/env python3
import pathlib

from runtime_support import read_json, read_jsonl, runtime_paths, utc_now, write_json


INTERNAL_STATE_INCONSISTENCY = "INTERNAL_STATE_INCONSISTENCY"


def assert_final_state_consistency(final_state: dict, test_results: dict) -> None:
    if bool(final_state.get("tests_passed")) != bool(test_results.get("tests_passed")):
        raise ValueError(INTERNAL_STATE_INCONSISTENCY)


def final_state_payload(
    *,
    task_status: str,
    last_successful_step: str,
    tests_passed: bool,
    test_results_path: str,
    effective_test_scope: str,
    regression_status: str,
    handoff_status: str,
    baseline_status: str,
    current_status: str,
    last_error: dict | None,
) -> dict:
    return {
        "task_status": task_status,
        "last_successful_step": last_successful_step,
        "tests_passed": tests_passed,
        "test_results_path": test_results_path,
        "effective_test_scope": effective_test_scope,
        "regression_status": regression_status,
        "handoff_status": handoff_status,
        "baseline_status": baseline_status,
        "current_status": current_status,
        "last_error": last_error,
    }


def render_handoff(
    *,
    workspace_root: pathlib.Path,
    task_id: str | None,
    command: str,
    seed: str | None,
    report_path: str | None,
    final_state: dict,
    suggested_next_step: str,
    notes: list[str] | None = None,
) -> str:
    paths = runtime_paths(workspace_root)
    events = read_jsonl(paths["events"])
    recent_success = next((item for item in reversed(events) if item.get("status") == "success"), None)
    recent_failure = next((item for item in reversed(events) if item.get("status") == "failed"), None)
    last_error = final_state.get("last_error")
    lines = [
        "# ZG Impact Blueprint Handoff",
        "",
        f"- Timestamp: {utc_now()}",
        f"- Current task: {task_id or 'none'}",
        f"- Current phase: {command}",
        f"- Task status: {final_state.get('task_status', 'unknown')}",
        f"- Handoff status: {final_state.get('handoff_status', 'unknown')}",
        f"- Seed: {seed or 'none'}",
        f"- Tests passed: {bool(final_state.get('tests_passed'))}",
        f"- Effective test scope: {final_state.get('effective_test_scope', 'unknown')}",
        f"- Baseline status: {final_state.get('baseline_status', 'unknown')}",
        f"- Current status: {final_state.get('current_status', 'unknown')}",
        f"- Regression status: {final_state.get('regression_status', 'unknown')}",
        f"- Recent successful step: {final_state.get('last_successful_step', (recent_success or {}).get('command', 'none'))} @ {(recent_success or {}).get('timestamp', 'n/a') if final_state.get('last_successful_step') != command else utc_now()}",
        f"- Recent failed step: {(recent_failure or {}).get('command', 'none')} @ {(recent_failure or {}).get('timestamp', 'n/a')}",
        "",
        "## Critical paths",
        f"- Report: {report_path or 'none'}",
        f"- Test results: {final_state.get('test_results_path') or 'none'}",
        "",
    ]
    if last_error:
        lines.insert(-1, f"- Last error: {paths['last_error']}")
    if notes:
        lines.append("## Notes")
        lines.extend(f"- {item}" for item in notes if item)
        lines.append("")
    if last_error:
        lines.append("## Last error")
        lines.append(f"- Code: {last_error.get('error_code', 'none')}")
        lines.append(f"- Message: {last_error.get('message', 'none')}")
        lines.append("")
    lines.extend(
        [
            "## Next step",
            suggested_next_step,
            "",
        ]
    )
    return "\n".join(lines)


def write_consistent_handoff(
    *,
    workspace_root: pathlib.Path,
    task_id: str | None,
    command: str,
    seed: str | None,
    report_path: str | None,
    final_state: dict,
    test_results: dict,
    suggested_next_step: str,
    notes: list[str] | None = None,
) -> pathlib.Path:
    assert_final_state_consistency(final_state, test_results)
    paths = runtime_paths(workspace_root)
    handoff_text = render_handoff(
        workspace_root=workspace_root,
        task_id=task_id,
        command=command,
        seed=seed,
        report_path=report_path,
        final_state=final_state,
        suggested_next_step=suggested_next_step,
        notes=notes,
    )
    paths["handoff_latest"].write_text(handoff_text, encoding="utf-8")
    write_json(paths["status_json"], final_state)
    return paths["handoff_latest"]
