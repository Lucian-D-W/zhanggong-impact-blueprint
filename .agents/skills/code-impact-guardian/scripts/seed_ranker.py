#!/usr/bin/env python3
import json
import pathlib
import sqlite3

from build_graph import graph_paths, load_config
from recent_task import read_last_task


def parse_changed_line_specs(changed_lines: list[str]) -> dict[str, list[int]]:
    parsed: dict[str, list[int]] = {}
    for item in changed_lines:
        if ":" not in item:
            continue
        path, raw_line = item.rsplit(":", 1)
        try:
            line_no = int(raw_line)
        except ValueError:
            continue
        parsed.setdefault(path.replace("\\", "/"), []).append(line_no)
    return parsed


def candidate_kind_priority(attrs: dict) -> int:
    definition_kind = attrs.get("definition_kind")
    if definition_kind in {"react_component", "custom_hook", "sql_routine"}:
        return 2
    if definition_kind in {"exported_const_arrow", "function_declaration", "class_method"}:
        return 1
    return 0


def function_candidates_for_files(conn: sqlite3.Connection, changed_files: list[str]) -> list[dict]:
    if not changed_files:
        return []
    placeholders = ",".join("?" for _ in changed_files)
    rows = conn.execute(
        f"""
        SELECT node_id, kind, path, symbol, start_line, end_line, attrs_json
        FROM nodes
        WHERE kind = 'function' AND path IN ({placeholders})
        ORDER BY path, start_line, COALESCE(symbol, '')
        """,
        changed_files,
    ).fetchall()
    return [
        {
            "node_id": node_id,
            "kind": kind,
            "path": path,
            "symbol": symbol,
            "start_line": start_line,
            "end_line": end_line,
            "attrs": json.loads(attrs_json or "{}"),
        }
        for node_id, kind, path, symbol, start_line, end_line, attrs_json in rows
    ]


def file_candidates_for_files(conn: sqlite3.Connection, changed_files: list[str]) -> list[dict]:
    if not changed_files:
        return []
    placeholders = ",".join("?" for _ in changed_files)
    rows = conn.execute(
        f"""
        SELECT node_id, kind, path, symbol, start_line, end_line, attrs_json
        FROM nodes
        WHERE kind = 'file' AND path IN ({placeholders})
        ORDER BY path
        """,
        changed_files,
    ).fetchall()
    return [
        {
            "node_id": node_id,
            "kind": kind,
            "path": path,
            "symbol": symbol,
            "start_line": start_line,
            "end_line": end_line,
            "attrs": json.loads(attrs_json or "{}"),
        }
        for node_id, kind, path, symbol, start_line, end_line, attrs_json in rows
    ]


def score_candidate(candidate: dict, *, changed_line_map: dict[str, list[int]], last_task: dict | None) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    lines = changed_line_map.get(candidate["path"], [])
    start_line = candidate.get("start_line") or 1
    end_line = candidate.get("end_line") or start_line
    line_hits = [line_no for line_no in lines if start_line <= line_no <= end_line]
    if line_hits:
        score += 8.0
        reasons.append(f"changed-line hits {min(line_hits)}-{max(line_hits)} inside definition range")
    elif lines:
        distance = min(min(abs(line_no - start_line), abs(line_no - end_line)) for line_no in lines)
        if distance <= 3:
            score += 2.5
            reasons.append("changed-line is near this definition")

    attrs = candidate.get("attrs", {})
    kind_bonus = candidate_kind_priority(attrs)
    if kind_bonus:
        score += kind_bonus
        reasons.append(f"definition_kind={attrs.get('definition_kind')}")

    if last_task:
        if last_task.get("seed") == candidate["node_id"]:
            score += 5.0
            reasons.append("matches most recent task seed")
        elif last_task.get("project_root") and last_task.get("seed", "").split(":")[-1] == candidate.get("symbol"):
            score += 1.5
            reasons.append("symbol matches recent task context")
        if candidate["path"] in set(last_task.get("changed_files", [])):
            score += 1.0
            reasons.append("same file as recent task")

    if candidate["kind"] == "file":
        score += 0.5
        reasons.append("file-level fallback candidate")
    else:
        score += 1.0
        reasons.append("function/routine-level candidate")

    return score, reasons


def confidence_from_score(score: float, second_score: float | None = None) -> float:
    base = min(0.98, 0.35 + (score / 12.0))
    if second_score is not None:
        gap = score - second_score
        if gap >= 4:
            base = max(base, 0.92)
        elif gap >= 2:
            base = max(base, 0.82)
    return round(min(base, 0.99), 2)


def rank_seed_candidates(*, workspace_root: pathlib.Path, config_path: pathlib.Path, changed_files: list[str], changed_lines: list[str]) -> dict:
    config = load_config(config_path)
    db_path = graph_paths(workspace_root, config)["db_path"]
    changed_files = [item.replace("\\", "/") for item in changed_files]
    changed_line_map = parse_changed_line_specs(changed_lines)
    last_task = read_last_task(workspace_root)
    if not db_path.exists():
        return {"selected_seed": None, "top_candidates": [], "confidence": 0.0, "reason": "graph database missing"}

    with sqlite3.connect(db_path) as conn:
        candidates = function_candidates_for_files(conn, changed_files)
        if not candidates:
            candidates = file_candidates_for_files(conn, changed_files)
        if not candidates:
            candidates = function_candidates_for_files(conn, sorted({path for path in changed_line_map})) or file_candidates_for_files(conn, sorted({path for path in changed_line_map}))

    scored: list[dict] = []
    for candidate in candidates:
        score, reasons = score_candidate(candidate, changed_line_map=changed_line_map, last_task=last_task)
        scored.append(
            {
                "node_id": candidate["node_id"],
                "kind": candidate["kind"],
                "path": candidate["path"],
                "symbol": candidate.get("symbol"),
                "score": score,
                "reasons": reasons,
                "attrs": candidate.get("attrs", {}),
            }
        )
    scored.sort(key=lambda item: (-item["score"], item["path"], item.get("symbol") or item["node_id"]))
    top_candidates = scored[:3]
    if not top_candidates:
        return {"selected_seed": None, "top_candidates": [], "confidence": 0.0, "reason": "no candidates available"}

    top_score = top_candidates[0]["score"]
    second_score = top_candidates[1]["score"] if len(top_candidates) > 1 else None
    confidence = confidence_from_score(top_score, second_score)
    selection_reason = "; ".join(top_candidates[0]["reasons"]) if top_candidates[0]["reasons"] else "highest ranked candidate"
    auto_select = len(top_candidates) == 1 or confidence >= 0.85

    return {
        "selected_seed": top_candidates[0]["node_id"] if auto_select else None,
        "top_candidates": [
            {
                "node_id": item["node_id"],
                "kind": item["kind"],
                "path": item["path"],
                "symbol": item["symbol"],
                "confidence": confidence_from_score(item["score"]),
                "reason": "; ".join(item["reasons"]) or "ranked candidate",
            }
            for item in top_candidates
        ],
        "confidence": confidence,
        "reason": selection_reason,
    }
