#!/usr/bin/env python3
import json
import pathlib

from doc_sources import collect_rule_documents_from_sources
from parser_backends import iter_matching_files, sha1_text


DEPENDENCY_FINGERPRINT_FILES = (
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "tsconfig.json",
)

DEPENDENCY_FINGERPRINT_GLOBS = (
    "vite.config.*",
    "next.config.*",
)


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


def dependency_fingerprint_files(project_root: pathlib.Path, config: dict) -> dict[str, str]:
    tracked: dict[str, str] = {}
    del config
    for file_name in DEPENDENCY_FINGERPRINT_FILES:
        candidate = project_root / file_name
        if candidate.exists() and candidate.is_file():
            relative = candidate.relative_to(project_root).as_posix()
            tracked[relative] = sha1_text(candidate.read_text(encoding="utf-8", errors="replace"))
    for pattern in DEPENDENCY_FINGERPRINT_GLOBS:
        for candidate in sorted(project_root.glob(pattern)):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(project_root).as_posix()
            tracked[relative] = sha1_text(candidate.read_text(encoding="utf-8", errors="replace"))
    return tracked


def refresh_plan(*, workspace_root: pathlib.Path, project_root: pathlib.Path, config: dict, changed_files: list[str] | None = None) -> dict:
    current = tracked_source_files(project_root, config)
    current_dependency_fingerprint = dependency_fingerprint_files(project_root, config)
    previous = load_manifest(workspace_root) or {}
    previous_files = previous.get("files", {})
    previous_meta = previous.get("meta", {}) if isinstance(previous.get("meta"), dict) else {}
    previous_dependency_fingerprint = (
        previous_meta.get("dependency_fingerprint")
        if isinstance(previous_meta.get("dependency_fingerprint"), dict)
        else {}
    )
    changed_by_hash = sorted(
        path
        for path, digest in current.items()
        if previous_files.get(path) != digest
    )
    removed_files = sorted(path for path in previous_files.keys() if path not in current)
    changed_dependency_files = sorted(
        path
        for path, digest in current_dependency_fingerprint.items()
        if previous_dependency_fingerprint and previous_dependency_fingerprint.get(path) != digest
    )
    removed_dependency_files = sorted(
        path
        for path in previous_dependency_fingerprint.keys()
        if path not in current_dependency_fingerprint
    )
    dependency_files = sorted(set(changed_dependency_files) | set(removed_dependency_files))
    all_changed = sorted(set(changed_by_hash) | set(removed_files) | set(dependency_files))
    if not previous_files:
        return {
            "build_mode": "full",
            "changed_files": all_changed,
            "dependency_files": dependency_files,
            "dependency_fingerprint": current_dependency_fingerprint,
            "reason": "no previous manifest",
            "files": current,
        }
    if not all_changed:
        return {
            "build_mode": "reused",
            "changed_files": [],
            "dependency_files": dependency_files,
            "dependency_fingerprint": current_dependency_fingerprint,
            "reason": "no tracked file changed",
            "files": current,
        }
    rule_globs = config.get("rules", {}).get("globs", [])
    if removed_files or any(pathlib.PurePosixPath(item).match(pattern) for item in all_changed for pattern in rule_globs):
        return {
            "build_mode": "full",
            "changed_files": all_changed,
            "dependency_files": dependency_files,
            "dependency_fingerprint": current_dependency_fingerprint,
            "reason": "removed or rule files changed",
            "files": current,
        }
    if len(all_changed) <= 3:
        return {
            "build_mode": "incremental",
            "changed_files": all_changed,
            "dependency_files": dependency_files,
            "dependency_fingerprint": current_dependency_fingerprint,
            "reason": "small tracked change set",
            "files": current,
        }
    return {
        "build_mode": "full",
        "changed_files": all_changed,
        "dependency_files": dependency_files,
        "dependency_fingerprint": current_dependency_fingerprint,
        "reason": "change set too large for safe incremental refresh",
        "files": current,
    }
