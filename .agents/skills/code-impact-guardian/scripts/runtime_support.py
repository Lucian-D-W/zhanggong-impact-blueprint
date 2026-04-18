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
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.suggested_next_step = suggested_next_step
        self.output_paths = output_paths or {}


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
    lines = [
        "# Code Impact Guardian Handoff",
        "",
        f"- Timestamp: {utc_now()}",
        f"- Command: {command}",
        f"- Status: {status}",
        f"- Task: {task_id or 'none'}",
        f"- Seed: {seed or 'none'}",
        f"- Failure point: {failure_point}",
        f"- Latest report: {report_path or 'none'}",
        f"- Latest test results: {test_results_path or 'none'}",
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
    else:
        error_code = "UNEXPECTED_ERROR"
        retryable = False
        suggested_next_step = "Run the same command again with --debug and inspect the latest error log."
        message = str(exc)
        output_paths = {}
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
