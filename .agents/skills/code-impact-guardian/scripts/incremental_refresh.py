#!/usr/bin/env python3
import json
import pathlib

from doc_sources import collect_rule_documents_from_sources
from parser_backends import iter_matching_files, sha1_text


def manifest_path(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".ai" / "codegraph" / "build-manifest.json"


def load_manifest(workspace_root: pathlib.Path) -> dict | None:
    path = manifest_path(workspace_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_manifest(workspace_root: pathlib.Path, payload: dict) -> pathlib.Path:
    path = manifest_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def tracked_source_files(project_root: pathlib.Path, config: dict) -> dict[str, str]:
    tracked: dict[str, str] = {}
    pattern_groups = [
        config.get("python", {}).get("source_globs", []),
        config.get("python", {}).get("test_globs", []),
        config.get("tsjs", {}).get("source_globs", []),
        config.get("tsjs", {}).get("test_globs", []),
        config.get("generic", {}).get("source_globs", []),
        config.get("sql_postgres", {}).get("source_globs", []),
        config.get("sql_postgres", {}).get("test_globs", []),
    ]
    for patterns in pattern_groups:
        for path in iter_matching_files(project_root, patterns):
            tracked[path.relative_to(project_root).as_posix()] = sha1_text(path.read_text(encoding="utf-8", errors="replace"))
    for document in collect_rule_documents_from_sources(project_root, config):
        absolute = project_root / pathlib.PurePosixPath(document["relative_path"])
        if absolute.exists():
            tracked[document["relative_path"]] = sha1_text(absolute.read_text(encoding="utf-8", errors="replace"))
    return tracked


def refresh_plan(*, workspace_root: pathlib.Path, project_root: pathlib.Path, config: dict, changed_files: list[str] | None = None) -> dict:
    current = tracked_source_files(project_root, config)
    previous = load_manifest(workspace_root) or {}
    previous_files = previous.get("files", {})
    changed_by_hash = sorted(
        path
        for path, digest in current.items()
        if previous_files.get(path) != digest
    )
    removed_files = sorted(path for path in previous_files.keys() if path not in current)
    all_changed = sorted(set(changed_by_hash) | set(removed_files))
    if not previous_files:
        return {"build_mode": "full", "changed_files": all_changed, "reason": "no previous manifest", "files": current}
    if not all_changed:
        return {"build_mode": "reused", "changed_files": [], "reason": "no tracked file changed", "files": current}
    rule_globs = config.get("rules", {}).get("globs", [])
    if removed_files or any(pathlib.PurePosixPath(item).match(pattern) for item in all_changed for pattern in rule_globs):
        return {"build_mode": "full", "changed_files": all_changed, "reason": "removed or rule files changed", "files": current}
    if len(all_changed) <= 3:
        return {"build_mode": "incremental", "changed_files": all_changed, "reason": "small tracked change set", "files": current}
    return {"build_mode": "full", "changed_files": all_changed, "reason": "change set too large for safe incremental refresh", "files": current}
