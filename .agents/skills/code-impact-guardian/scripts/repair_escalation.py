#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
from typing import Any

from runtime_support import append_jsonl, read_json, read_jsonl, runtime_paths, utc_now, write_json


CONTRACT_KINDS = {
    "config_key",
    "env_var",
    "sql_table",
    "ipc_channel",
    "endpoint",
    "route",
}

PROJECT_FRAME_HINTS = ("src/", "tests/", "docs/", ".agents/", "scripts/", "migrations/", "schema/")


def reveal_level_for_repeat_count(repeat_count: int) -> str:
    if repeat_count >= 4:
        return "L3"
    if repeat_count >= 3:
        return "L2"
    if repeat_count >= 2:
        return "L1"
    return "L0"


def level_for_auto_mode(repeat_count: int) -> str:
    return reveal_level_for_repeat_count(repeat_count)


def normalize_failure_text(text: str) -> str:
    normalized = text.replace("\\", "/")
    normalized = re.sub(r"[A-Z]:/[^\s'\"]+", "<path>", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"/tmp/[^\s'\"]+", "<tmp>", normalized)
    normalized = re.sub(r"line \d+", "line <n>", normalized)
    normalized = re.sub(r":\d+(?=[:)\s])", ":<n>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?s\b", "<time>", normalized)
    normalized = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b", "<uuid>", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b[0-9a-f]{12,}\b", "<id>", normalized, flags=re.IGNORECASE)
    return normalized


def normalized_output_excerpt(text: str, *, limit: int = 500) -> str:
    normalized = normalize_failure_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    excerpt = " | ".join(lines[:8])
    if len(excerpt) > limit:
        excerpt = excerpt[: limit - 3] + "..."
    return excerpt


def read_test_output(workspace_root: pathlib.Path, test_summary: dict) -> str:
    output_path = test_summary.get("output_path")
    if not output_path:
        return ""
    path = workspace_root / output_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def traceback_signature_parts(output_text: str) -> tuple[str | None, str | None]:
    exception_type = None
    for pattern in (
        r"(?m)^([A-Za-z_][\w.]*(?:Error|Exception|Failure)):\s+",
        r"(?m)^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Failure)):",
    ):
        match = re.search(pattern, output_text)
        if match:
            exception_type = match.group(1)
            break

    top_project_frame = None
    for match in re.finditer(r'File "([^"]+)", line \d+, in ([^\s]+)', output_text):
        frame_path = match.group(1).replace("\\", "/")
        if any(hint in frame_path for hint in PROJECT_FRAME_HINTS):
            top_project_frame = f"{frame_path}:{match.group(2)}"
            break
    return exception_type, top_project_frame


def first_assertion_message(output_text: str) -> str | None:
    for pattern in (
        r"(?m)^AssertionError:\s+(.+)$",
        r"(?m)^\s*Expected\s+(.+)$",
        r"(?m)^\s*Error:\s+(.+)$",
    ):
        match = re.search(pattern, output_text)
        if match:
            return normalize_failure_text(match.group(1).strip())[:160]
    return None


def failure_signature(
    *,
    changed_files: list[str],
    failed_tests: list[str],
    error_code: str,
    output_text: str,
) -> tuple[str, str]:
    normalized_files = sorted({item.replace("\\", "/") for item in changed_files})
    normalized_tests = sorted(set(failed_tests))
    exception_type, top_project_frame = traceback_signature_parts(output_text)
    assertion = first_assertion_message(output_text)
    excerpt = normalized_output_excerpt(output_text)
    signature_payload = {
        "error_code": error_code,
        "failed_tests": normalized_tests[:5],
        "changed_files": normalized_files[:5],
        "exception_type": exception_type,
        "top_project_frame": top_project_frame,
        "assertion": assertion,
        "excerpt": excerpt,
    }
    digest = hashlib.sha1(json.dumps(signature_payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    parts = [error_code]
    if normalized_tests:
        parts.append(",".join(normalized_tests[:2]))
    elif exception_type:
        parts.append(exception_type)
    if normalized_files:
        parts.append(",".join(normalized_files[:2]))
    if top_project_frame:
        parts.append(top_project_frame)
    parts.append(digest)
    return "|".join(parts), excerpt


def repair_attempt_rows(workspace_root: pathlib.Path) -> list[dict]:
    return read_jsonl(runtime_paths(workspace_root)["repair_attempts"])


def latest_matching_attempt(rows: list[dict], changed_files: list[str] | None = None) -> dict | None:
    if not rows:
        return None
    if not changed_files:
        return rows[-1]
    changed = {item.replace("\\", "/") for item in changed_files}
    for row in reversed(rows):
        if changed & set(row.get("changed_files", [])):
            return row
    return rows[-1]


def active_loop_payload(workspace_root: pathlib.Path, changed_files: list[str] | None = None) -> dict:
    rows = repair_attempt_rows(workspace_root)
    latest = latest_matching_attempt(rows, changed_files)
    if latest is None:
        return {
            "active_loop": False,
            "repeat_count": 0,
            "failure_signature": None,
            "last_failed_tests": [],
            "chain_reveal_level": "L0",
            "recommended_escalation": "L0",
        }
    signature = latest.get("failure_signature")
    filtered = rows
    if changed_files:
        changed = {item.replace("\\", "/") for item in changed_files}
        filtered = [row for row in rows if changed & set(row.get("changed_files", []))]
    matching = [row for row in filtered if row.get("failure_signature") == signature]
    repeat_count = len(matching)
    chain_reveal_level = reveal_level_for_repeat_count(repeat_count)
    return {
        "active_loop": repeat_count > 0,
        "repeat_count": repeat_count,
        "failure_signature": signature,
        "last_failed_tests": latest.get("failed_tests", []),
        "chain_reveal_level": chain_reveal_level,
        "recommended_escalation": chain_reveal_level,
        "latest_attempt": latest,
    }


def loop_status_payload(
    *,
    workspace_root: pathlib.Path,
    changed_files: list[str] | None = None,
) -> dict:
    loop = active_loop_payload(workspace_root, changed_files)
    changed_files = changed_files or (loop.get("latest_attempt") or {}).get("changed_files") or []
    command_target = changed_files[0] if changed_files else "<path>"
    return {
        "active_loop": loop["active_loop"],
        "repeat_count": loop["repeat_count"],
        "failure_signature": loop["failure_signature"],
        "last_failed_tests": loop["last_failed_tests"],
        "recommended_escalation": loop["recommended_escalation"],
        "recommended_command": (
            "python .agents/skills/code-impact-guardian/cig.py analyze "
            f"--workspace-root . --changed-file {command_target} --escalation-level {loop['recommended_escalation']}"
        ),
    }


def _node_details_map(db_path: pathlib.Path, node_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not node_ids:
        return {}
    placeholders = ",".join("?" for _ in node_ids)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT node_id, kind, path, symbol FROM nodes WHERE node_id IN ({placeholders})",
            tuple(sorted(node_ids)),
        ).fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for node_id, kind, path, symbol in rows:
        payload[node_id] = {
            "node_id": node_id,
            "kind": kind,
            "path": path,
            "symbol": symbol,
        }
    return payload


def _node_id_path(node_details: dict[str, dict[str, Any]], node_id: str) -> str:
    detail = node_details.get(node_id)
    if detail and detail.get("path"):
        return detail["path"]
    parts = node_id.split(":", 2)
    if len(parts) >= 2:
        return parts[1]
    return node_id


def _edge_node_ids(entries: list[dict]) -> set[str]:
    node_ids: set[str] = set()
    for entry in entries:
        src = entry.get("src")
        dst = entry.get("dst")
        if src:
            node_ids.add(src)
        if dst:
            node_ids.add(dst)
    return node_ids


def _path_nodes(paths: list[str], depth_limit: int | None = None) -> list[str]:
    node_ids: list[str] = []
    for path in paths:
        parts = [part.strip() for part in str(path).split("->") if part.strip()]
        if depth_limit is not None:
            parts = parts[: depth_limit + 1]
        node_ids.extend(parts)
    return node_ids


def expanded_chain(
    *,
    workspace_root: pathlib.Path,
    report_json: dict | None,
    changed_files: list[str],
    level: str,
) -> dict:
    report_json = report_json or {}
    direct = report_json.get("direct") or {}
    transitive = report_json.get("transitive") or {}
    seed = report_json.get("seed")

    call_entries = list(direct.get("upstream") or []) + list(direct.get("downstream") or [])
    import_entries = list(direct.get("imports") or [])
    test_nodes = list(direct.get("tests") or [])
    rule_nodes = list(direct.get("rules") or [])

    node_ids: set[str] = set()
    node_ids.update(_edge_node_ids(call_entries))
    node_ids.update(_edge_node_ids(import_entries))
    node_ids.update(test_nodes)
    node_ids.update(rule_nodes)
    if seed:
        node_ids.add(seed)

    if level in {"L2", "L3"}:
        node_ids.update(_path_nodes(transitive.get("downstream_paths") or []))
        node_ids.update(_path_nodes(transitive.get("upstream_paths") or []))
        node_ids.update(_path_nodes(transitive.get("import_paths") or []))
        node_ids.update(_path_nodes(transitive.get("reverse_import_paths") or []))

    db_path = runtime_paths(workspace_root)["codegraph_dir"] / "codegraph.db"
    node_details = _node_details_map(db_path, node_ids)

    call_chain = sorted(
        {
            _node_id_path(node_details, entry.get("src") or "")
            for entry in call_entries
            if entry.get("src")
        }
        | {
            _node_id_path(node_details, entry.get("dst") or "")
            for entry in call_entries
            if entry.get("dst")
        }
    )
    import_chain = sorted(
        {
            _node_id_path(node_details, entry.get("src") or "")
            for entry in import_entries
            if entry.get("src")
        }
        | {
            _node_id_path(node_details, entry.get("dst") or "")
            for entry in import_entries
            if entry.get("dst")
        }
    )
    if level in {"L2", "L3"}:
        call_chain = sorted(set(call_chain) | {_node_id_path(node_details, item) for item in _path_nodes(transitive.get("downstream_paths") or []) + _path_nodes(transitive.get("upstream_paths") or [])})
        import_chain = sorted(set(import_chain) | {_node_id_path(node_details, item) for item in _path_nodes(transitive.get("import_paths") or []) + _path_nodes(transitive.get("reverse_import_paths") or [])})

    test_chain = sorted({_node_id_path(node_details, node_id) for node_id in test_nodes})
    rule_chain = sorted({_node_id_path(node_details, node_id) for node_id in rule_nodes})
    contract_chain = sorted(
        {
            detail["path"]
            for detail in node_details.values()
            if detail.get("kind") in CONTRACT_KINDS and detail.get("path")
        }
    )

    changed_paths = [item.replace("\\", "/") for item in changed_files]
    seed_path = ((report_json.get("definition") or {}).get("path")) or None
    must_read_first = []
    for item in [seed_path, *changed_paths, *call_chain[:2], *import_chain[:2], *test_chain[:2], *rule_chain[:2], *contract_chain[:2]]:
        if item and item not in must_read_first:
            must_read_first.append(item)

    return {
        "changed_files": changed_paths,
        "changed_symbols": sorted(
            {
                symbol
                for symbol in [((report_json.get("definition") or {}).get("symbol"))]
                if symbol
            }
        ),
        "call_chain": call_chain,
        "import_chain": import_chain,
        "test_chain": test_chain,
        "rule_chain": rule_chain,
        "contract_chain": contract_chain,
        "must_read_first": must_read_first,
        "summary": {
            "calls": len(call_chain),
            "imports": len(import_chain),
            "tests": len(test_chain),
            "rules": len(rule_chain),
            "contracts": len(contract_chain),
        },
    }


def recommended_test_scope_for_level(level: str, fallback_scope: str) -> str:
    if level == "L3":
        return "full"
    if level in {"L1", "L2"} and fallback_scope in {"none", "targeted"}:
        return "configured"
    return fallback_scope


def budget_floor_for_level(level: str, fallback_budget: str) -> str:
    if level == "L3":
        return "B4"
    if level in {"L1", "L2"} and fallback_budget in {"B0", "B1", "B2"}:
        return "B3"
    return fallback_budget


def record_failed_attempt(
    *,
    workspace_root: pathlib.Path,
    task_id: str,
    changed_files: list[str],
    changed_symbols: list[str],
    test_summary: dict,
    error_code: str,
    dependency_fingerprint_status: str,
    graph_trust: str,
    verification_budget: str,
) -> dict:
    output_text = read_test_output(workspace_root, test_summary)
    failure_sig, excerpt = failure_signature(
        changed_files=changed_files,
        failed_tests=test_summary.get("failed_tests", []),
        error_code=error_code,
        output_text=output_text,
    )
    existing = active_loop_payload(workspace_root, changed_files)
    repeat_count = existing["repeat_count"] + 1 if existing.get("failure_signature") == failure_sig else 1
    chain_reveal_level = reveal_level_for_repeat_count(repeat_count)
    payload = {
        "timestamp": utc_now(),
        "task_id": task_id,
        "changed_files": [item.replace("\\", "/") for item in changed_files],
        "changed_symbols": changed_symbols,
        "test_scope": test_summary.get("effective_test_scope") or test_summary.get("requested_test_scope") or "configured",
        "tests_passed": bool(test_summary.get("tests_passed")),
        "failed_tests": test_summary.get("failed_tests", []),
        "error_code": error_code,
        "error_fingerprint": failure_sig,
        "failure_signature": failure_sig,
        "normalized_output_excerpt": excerpt,
        "dependency_fingerprint_status": dependency_fingerprint_status,
        "graph_trust": graph_trust,
        "verification_budget": verification_budget,
        "chain_reveal_level": chain_reveal_level,
    }
    append_jsonl(runtime_paths(workspace_root)["repair_attempts"], payload)
    return {
        "repeat_count": repeat_count,
        "failure_signature": failure_sig,
        "chain_reveal_level": chain_reveal_level,
        "attempt": payload,
    }


def load_report_json(workspace_root: pathlib.Path, report_payload: dict | None = None) -> dict:
    report_payload = report_payload or {}
    json_report_path = report_payload.get("json_report_path")
    if json_report_path:
        path = pathlib.Path(json_report_path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    last_task = read_json(runtime_paths(workspace_root)["codegraph_dir"] / "last-task.json") or {}
    report_path = last_task.get("report_path")
    if not report_path:
        return {}
    candidate = workspace_root / report_path
    if not candidate.exists():
        return {}
    if candidate.suffix == ".json":
        return json.loads(candidate.read_text(encoding="utf-8"))
    json_candidate = candidate.with_suffix(".json")
    if json_candidate.exists():
        return json.loads(json_candidate.read_text(encoding="utf-8"))
    return {}


def write_loop_breaker_report(
    *,
    workspace_root: pathlib.Path,
    changed_files: list[str],
    repeat_count: int,
    failure_signature_value: str,
    level: str,
    report_json: dict | None,
) -> dict:
    chain = expanded_chain(
        workspace_root=workspace_root,
        report_json=report_json,
        changed_files=changed_files,
        level=level,
    )
    primary_path = changed_files[0] if changed_files else "<path>"
    payload = {
        "failure_signature": failure_signature_value,
        "repeat_count": repeat_count,
        "chain_reveal_level": level,
        "suspected_loop_reason": [
            "same failing test repeated",
            "same changed file repeated",
            "targeted verification missed wider dependency",
        ],
        "expanded_chain": {
            "changed_files": chain["changed_files"],
            "changed_symbols": chain["changed_symbols"],
            "call_chain": chain["call_chain"],
            "import_chain": chain["import_chain"],
            "test_chain": chain["test_chain"],
            "rule_chain": chain["rule_chain"],
            "contract_chain": chain["contract_chain"],
        },
        "must_read_first": chain["must_read_first"],
        "recommended_commands": [
            "python .agents/skills/code-impact-guardian/cig.py analyze "
            f"--workspace-root . --changed-file {primary_path} --escalation-level {level}",
            "python .agents/skills/code-impact-guardian/cig.py finish --workspace-root . --test-scope full",
        ],
        "agent_instruction": "Do not continue local patching until the expanded chain is reviewed.",
    }
    write_json(runtime_paths(workspace_root)["loop_breaker_report"], payload)
    return payload


def diagnose_loop_payload(
    *,
    workspace_root: pathlib.Path,
    changed_files: list[str],
) -> dict:
    loop = active_loop_payload(workspace_root, changed_files)
    report_json = load_report_json(workspace_root)
    chain = expanded_chain(
        workspace_root=workspace_root,
        report_json=report_json,
        changed_files=changed_files,
        level=loop["recommended_escalation"],
    )
    return {
        "active_loop": loop["active_loop"],
        "repeat_count": loop["repeat_count"],
        "failure_signature": loop["failure_signature"],
        "chain_reveal_level": loop["chain_reveal_level"],
        "recommended_escalation": loop["recommended_escalation"],
        "expanded_chain_summary": chain["summary"],
        "must_read_first": chain["must_read_first"],
    }
