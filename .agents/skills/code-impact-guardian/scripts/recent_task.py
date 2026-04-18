#!/usr/bin/env python3
import json
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone

from build_graph import graph_paths, load_config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def last_task_path(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".ai" / "codegraph" / "last-task.json"


def read_last_task(workspace_root: pathlib.Path) -> dict | None:
    path = last_task_path(workspace_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_last_task(workspace_root: pathlib.Path, payload: dict) -> pathlib.Path:
    path = last_task_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def auto_task_id(*, seed: str | None, changed_files: list[str] | None, prefix: str = "task") -> str:
    slug = "impact"
    if seed:
        slug = seed.split(":")[-1].replace("/", "-").replace(".", "-")
    elif changed_files:
        slug = pathlib.Path(changed_files[0]).stem.replace(".", "-")
    unique = uuid.uuid4().hex[:8]
    return f"{prefix}-{slug}-{unique}"


def seed_candidates_for_changed_files(workspace_root: pathlib.Path, config_path: pathlib.Path, changed_files: list[str]) -> list[dict]:
    config = load_config(config_path)
    db_path = graph_paths(workspace_root, config)["db_path"]
    normalized = [path.replace("\\", "/") for path in changed_files]
    if not normalized or not db_path.exists():
        return []
    placeholders = ",".join("?" for _ in normalized)
    with sqlite3.connect(db_path) as conn:
        function_rows = conn.execute(
            f"""
            SELECT node_id, kind, path, symbol, attrs_json
            FROM nodes
            WHERE kind = 'function' AND path IN ({placeholders})
            ORDER BY path, COALESCE(symbol, ''), node_id
            """,
            normalized,
        ).fetchall()
        if function_rows:
            return [
                {
                    "node_id": node_id,
                    "kind": kind,
                    "path": path,
                    "symbol": symbol,
                    "attrs": json.loads(attrs_json or "{}"),
                }
                for node_id, kind, path, symbol, attrs_json in function_rows
            ]
        file_rows = conn.execute(
            f"""
            SELECT node_id, kind, path, symbol, attrs_json
            FROM nodes
            WHERE kind = 'file' AND path IN ({placeholders})
            ORDER BY path, node_id
            """,
            normalized,
        ).fetchall()
    return [
        {
            "node_id": node_id,
            "kind": kind,
            "path": path,
            "symbol": symbol,
            "attrs": json.loads(attrs_json or "{}"),
        }
        for node_id, kind, path, symbol, attrs_json in file_rows
    ]


def latest_seed_candidates(workspace_root: pathlib.Path, config_path: pathlib.Path) -> list[dict]:
    config = load_config(config_path)
    db_path = graph_paths(workspace_root, config)["db_path"]
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        function_rows = conn.execute(
            """
            SELECT node_id, kind, path, symbol, attrs_json
            FROM nodes
            WHERE kind = 'function'
            ORDER BY path, COALESCE(symbol, ''), node_id
            """
        ).fetchall()
        if function_rows:
            return [
                {
                    "node_id": node_id,
                    "kind": kind,
                    "path": path,
                    "symbol": symbol,
                    "attrs": json.loads(attrs_json or "{}"),
                }
                for node_id, kind, path, symbol, attrs_json in function_rows
            ]
        file_rows = conn.execute(
            """
            SELECT node_id, kind, path, symbol, attrs_json
            FROM nodes
            WHERE kind = 'file'
            ORDER BY path, node_id
            """
        ).fetchall()
    return [
        {
            "node_id": node_id,
            "kind": kind,
            "path": path,
            "symbol": symbol,
            "attrs": json.loads(attrs_json or "{}"),
        }
        for node_id, kind, path, symbol, attrs_json in file_rows
    ]
