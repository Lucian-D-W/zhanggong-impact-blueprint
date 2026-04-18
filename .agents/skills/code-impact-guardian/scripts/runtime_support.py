#!/usr/bin/env python3
import json
import pathlib
import traceback
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CIGUserError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        suggested_next_step: str,
        output_paths: dict | None = None,
        recovery_commands: list[str] | None = None,
        alternatives: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.suggested_next_step = suggested_next_step
        self.output_paths = output_paths or {}
        self.recovery_commands = recovery_commands or []
        self.alternatives = alternatives or []


def runtime_paths(workspace_root: pathlib.Path) -> dict[str, pathlib.Path]:
    codegraph_dir = workspace_root / ".ai" / "codegraph"
    logs_dir = codegraph_dir / "logs"
    handoff_dir = codegraph_dir / "handoff"
    return {
        "codegraph_dir": codegraph_dir,
        "logs_dir": logs_dir,
        "events": logs_dir / "events.jsonl",
        "errors": logs_dir / "errors.jsonl",
        "last_run": logs_dir / "last-run.json",
        "last_error": logs_dir / "last-error.json",
        "context_resolution": codegraph_dir / "context-resolution.json",
        "build_decision": codegraph_dir / "build-decision.json",
        "seed_candidates": codegraph_dir / "seed-candidates.json",
        "next_action": codegraph_dir / "next-action.json",
        "handoff_dir": handoff_dir,
        "handoff_latest": handoff_dir / "latest.md",
    }


def ensure_runtime_dirs(workspace_root: pathlib.Path) -> dict[str, pathlib.Path]:
    paths = runtime_paths(workspace_root)
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)
    paths["handoff_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def relative_path_string(workspace_root: pathlib.Path, value: str | pathlib.Path | None) -> str | None:
    if value is None:
        return None
    path = pathlib.Path(value)
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except Exception:
        return str(path)


def normalize_output_paths(workspace_root: pathlib.Path, payload: dict | None) -> dict:
    if not payload:
        return {}
    normalized: dict[str, str | None] = {}
    for key, value in payload.items():
        normalized[key] = relative_path_string(workspace_root, value)
    return normalized


def append_jsonl(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_event(workspace_root: pathlib.Path, payload: dict) -> None:
    paths = ensure_runtime_dirs(workspace_root)
    append_jsonl(paths["events"], payload)
    write_json(paths["last_run"], payload)


def write_error(workspace_root: pathlib.Path, payload: dict) -> None:
    paths = ensure_runtime_dirs(workspace_root)
    append_jsonl(paths["errors"], payload)
    write_json(paths["last_error"], payload)


def write_handoff(
    workspace_root: pathlib.Path,
    *,
    task_id: str | None,
    command: str,
    status: str,
    failure_point: str,
    suggested_next_step: str,
    seed: str | None = None,
    report_path: str | None = None,
    test_results_path: str | None = None,
) -> pathlib.Path:
    paths = ensure_runtime_dirs(workspace_root)
    events = read_jsonl(paths["events"])
    last_task_path = paths["codegraph_dir"] / "last-task.json"
    last_task = read_json(last_task_path) or {}
    last_run = read_json(paths["last_run"]) or {}
    recent_success = next((item for item in reversed(events) if item.get("status") == "success"), None)
    recent_failure = next((item for item in reversed(events) if item.get("status") == "failed"), None)
    critical_paths = {
        "report": report_path or "none",
        "test_results": test_results_path or "none",
        "logs": str(paths["logs_dir"]),
        "last_error": str(paths["last_error"]) if paths["last_error"].exists() else "none",
        "last_task": str(last_task_path) if last_task_path.exists() else "none",
    }
    top_candidates = (last_task.get("seed_selection") or {}).get("top_candidates", [])
    candidate_summary = ", ".join(item.get("node_id", "") for item in top_candidates[:3]) or "none"
    fallback_used = bool(last_task.get("fallback_used"))
    build_mode = last_task.get("build_mode") or last_run.get("build_mode") or "unknown"
    trust_level = last_task.get("graph_trust") or last_task.get("trust_level") or last_run.get("graph_trust") or last_run.get("trust_level") or "unknown"
    report_completeness = (last_task.get("report_completeness") or {}).get("level", "unknown")
    test_signal = last_task.get("test_signal") or {}
    seed_confidence = (last_task.get("seed_selection") or {}).get("seed_confidence") or (last_task.get("context_resolution") or {}).get("seed_confidence")
    auto_context_used = bool((last_task.get("context_resolution") or {}).get("context_sources"))
    selected_reason = (last_task.get("seed_selection") or {}).get("reason") or "none"
    retry_step = recent_failure.get("command") if recent_failure else command
    lines = [
        "# Code Impact Guardian Handoff",
        "",
        f"- Timestamp: {utc_now()}",
        f"- Current task: {task_id or 'none'}",
        f"- Current phase: {command}",
        f"- Current status: {status}",
        f"- Seed: {seed or 'none'}",
        f"- Candidate seeds: {candidate_summary}",
        f"- Seed reason: {selected_reason}",
        f"- Seed confidence: {seed_confidence if seed_confidence is not None else 'unknown'}",
        f"- Auto context inference used: {'yes' if auto_context_used else 'no'}",
        f"- Fallback used: {'yes' if fallback_used else 'no'}",
        f"- Incremental build mode: {build_mode}",
        f"- Trust level: {trust_level}",
        f"- Report completeness: {report_completeness}",
        f"- Tests passed: {test_signal.get('tests_passed', False)}",
        f"- Affected tests found: {test_signal.get('affected_tests_found', False)}",
        f"- Recent successful step: {(recent_success or {}).get('command', 'none')} @ {(recent_success or {}).get('timestamp', 'n/a')}",
        f"- Recent failed step: {(recent_failure or {}).get('command', 'none')} @ {(recent_failure or {}).get('timestamp', 'n/a')}",
        f"- Failure point: {failure_point}",
        f"- Best retry step: {retry_step}",
        "",
        "## Critical paths",
        f"- Report: {critical_paths['report']}",
        f"- Test results: {critical_paths['test_results']}",
        f"- Logs: {critical_paths['logs']}",
        f"- Last error: {critical_paths['last_error']}",
        f"- Last task: {critical_paths['last_task']}",
        "",
        "## Next step",
        suggested_next_step,
        "",
    ]
    paths["handoff_latest"].write_text("\n".join(lines), encoding="utf-8")
    return paths["handoff_latest"]


def event_payload(
    *,
    command: str,
    workspace_root: pathlib.Path,
    project_root: str | None,
    profile: str | None,
    primary_adapter: str | None,
    supplemental_adapters: list[str] | None,
    task_id: str | None,
    seed: str | None,
    status: str,
    output_paths: dict | None,
    warning_count: int,
    error_code: str | None,
    retryable: bool,
    suggested_next_step: str,
    recovery_commands: list[str] | None = None,
    alternatives: list[dict] | None = None,
) -> dict:
    return {
        "timestamp": utc_now(),
        "command": command,
        "workspace_root": str(workspace_root),
        "project_root": project_root,
        "profile": profile,
        "primary_adapter": primary_adapter,
        "supplemental_adapters": supplemental_adapters or [],
        "task_id": task_id,
        "seed": seed,
        "status": status,
        "output_paths": output_paths or {},
        "warning_count": warning_count,
        "error_code": error_code,
        "retryable": retryable,
        "suggested_next_step": suggested_next_step,
        "recovery_commands": recovery_commands or [],
        "alternatives": alternatives or [],
    }


def error_payload_from_exception(
    *,
    command: str,
    workspace_root: pathlib.Path,
    project_root: str | None,
    profile: str | None,
    primary_adapter: str | None,
    supplemental_adapters: list[str] | None,
    task_id: str | None,
    seed: str | None,
    exc: Exception,
    debug: bool,
) -> dict:
    if isinstance(exc, CIGUserError):
        error_code = exc.error_code
        retryable = exc.retryable
        suggested_next_step = exc.suggested_next_step
        message = str(exc)
        output_paths = exc.output_paths
        recovery_commands = exc.recovery_commands
        alternatives = exc.alternatives
    else:
        error_code = "UNEXPECTED_ERROR"
        retryable = False
        suggested_next_step = "Run the same command again with --debug and inspect the latest error log."
        message = str(exc)
        output_paths = {}
        recovery_commands = []
        alternatives = []
    payload = event_payload(
        command=command,
        workspace_root=workspace_root,
        project_root=project_root,
        profile=profile,
        primary_adapter=primary_adapter,
        supplemental_adapters=supplemental_adapters,
        task_id=task_id,
        seed=seed,
        status="failed",
        output_paths=output_paths,
        warning_count=0,
        error_code=error_code,
        retryable=retryable,
        suggested_next_step=suggested_next_step,
        recovery_commands=recovery_commands,
        alternatives=alternatives,
    )
    payload["message"] = message
    if debug:
        payload["traceback"] = traceback.format_exc()
    return payload


def recent_command_status(events: list[dict], command_name: str) -> dict | None:
    for item in reversed(events):
        if item.get("command") == command_name:
            return {"timestamp": item.get("timestamp"), "status": item.get("status")}
    return None


def latest_success_timestamp(events: list[dict]) -> str | None:
    for item in reversed(events):
        if item.get("status") == "success":
            return item.get("timestamp")
    return None
