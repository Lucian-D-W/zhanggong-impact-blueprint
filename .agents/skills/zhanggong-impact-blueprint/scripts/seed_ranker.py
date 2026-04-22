#!/usr/bin/env python3
import json
import pathlib
import sqlite3

from build_graph import graph_paths, load_config
from db_support import connect_db
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
            proximity_bonus = max(0.5, 5.0 - (distance * 2.0))
            score += proximity_bonus
            reasons.append(f"changed-line is near this definition (distance={distance}, +{proximity_bonus:.2f})")

    attrs = candidate.get("attrs", {})
    kind_bonus = candidate_kind_priority(attrs)
    if kind_bonus:
        score += kind_bonus
        reasons.append(f"definition_kind={attrs.get('definition_kind')}")

    if last_task:
        last_task_files = set(last_task.get("changed_files", []))
        same_file_overlap = bool(candidate["path"] in last_task_files and last_task_files)
        last_task_seed = last_task.get("seed")
        if last_task_seed == candidate["node_id"]:
            recent_seed_bonus = 0.75 if same_file_overlap else 0.5
            score += recent_seed_bonus
            reasons.append(f"recent task seed overlap (+{recent_seed_bonus:.2f})")
        elif isinstance(last_task_seed, str) and last_task.get("project_root") and last_task_seed.split(":")[-1] == candidate.get("symbol"):
            symbol_bonus = 0.6 if same_file_overlap else 0.35
            score += symbol_bonus
            reasons.append(f"symbol matches recent task context (+{symbol_bonus:.2f})")
        if same_file_overlap:
            score += 0.5
            reasons.append("same file as recent task (+0.50)")

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

    with connect_db(db_path) as conn:
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
                "start_line": candidate.get("start_line"),
                "end_line": candidate.get("end_line"),
                "score": score,
                "reasons": reasons,
                "attrs": candidate.get("attrs", {}),
            }
        )
    scored.sort(key=lambda item: (-item["score"], item["path"], item.get("symbol") or item["node_id"]))
    top_candidates = scored[:3]
    if not top_candidates:
        return {"selected_seed": None, "top_candidates": [], "candidate_count": 0, "confidence": 0.0, "reason": "no candidates available"}

    top_score = top_candidates[0]["score"]
    second_score = top_candidates[1]["score"] if len(top_candidates) > 1 else None
    confidence = confidence_from_score(top_score, second_score)
    selection_reason = "; ".join(top_candidates[0]["reasons"]) if top_candidates[0]["reasons"] else "highest ranked candidate"
    score_gap = top_score - second_score if second_score is not None else None
    top_has_line_anchor = any(reason.startswith("changed-line hits") or reason.startswith("changed-line is near") for reason in top_candidates[0]["reasons"])
    auto_select = len(top_candidates) == 1 or (
        confidence >= 0.85
        and (score_gap is None or score_gap >= 1.5)
    )
    if not auto_select and top_has_line_anchor and confidence >= 0.75 and (score_gap is None or score_gap >= 1.5):
        auto_select = True

    return {
        "selected_seed": top_candidates[0]["node_id"] if auto_select else None,
        "candidate_count": len(scored),
        "top_candidates": [
            {
                "node_id": item["node_id"],
                "kind": item["kind"],
                "path": item["path"],
                "symbol": item["symbol"],
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "confidence": confidence_from_score(item["score"]),
                "reason": "; ".join(item["reasons"]) or "ranked candidate",
                "reason_details": item["reasons"],
            }
            for item in top_candidates
        ],
        "confidence": confidence,
        "reason": selection_reason,
        "recent_task_influenced": any(
            any("recent task" in detail for detail in item["reasons"])
            for item in top_candidates
        ),
    }
