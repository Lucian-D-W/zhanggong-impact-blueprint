#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

from recent_task import read_last_task
from trust_policy import is_generated_or_cache_file


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def project_relative_path(path: str, workspace_root: pathlib.Path, project_root: pathlib.Path) -> str | None:
    normalized = normalize_relative_path(path)
    workspace_relative_root = project_root.resolve().relative_to(workspace_root.resolve()).as_posix()
    if normalized == workspace_relative_root:
        return "."
    prefix = f"{workspace_relative_root}/" if workspace_relative_root != "." else ""
    if prefix and normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    candidate = project_root / pathlib.PurePosixPath(normalized)
    if candidate.exists():
        try:
            return candidate.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            return None
    if "/" not in normalized:
        return normalized
    return normalized


def parse_unified_diff(
    diff_text: str,
    *,
    workspace_root: pathlib.Path,
    project_root: pathlib.Path,
) -> dict:
    changed_files: list[str] = []
    changed_line_map: dict[str, set[int]] = {}
    out_of_scope_files: list[str] = []
    current_file: str | None = None
    deleted_file: str | None = None

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("--- "):
            source = line[4:].strip()
            if source == "/dev/null":
                deleted_file = None
            elif source.startswith("a/"):
                deleted_file = source[2:]
            else:
                deleted_file = source
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                if deleted_file is None:
                    current_file = None
                    continue
                target = deleted_file
            if target.startswith("b/"):
                target = target[2:]
            relative = project_relative_path(target, workspace_root, project_root)
            if relative is None:
                out_of_scope_files.append(normalize_relative_path(target))
                current_file = None
                continue
            current_file = normalize_relative_path(relative)
            if current_file not in changed_files:
                changed_files.append(current_file)
            changed_line_map.setdefault(current_file, set())
            continue
        if current_file is None:
            continue
        hunk = HUNK_RE.match(line)
        if not hunk:
            continue
        start = int(hunk.group(1))
        count = int(hunk.group(2) or "1")
        if count == 0:
            changed_line_map.setdefault(current_file, set()).add(start)
            continue
        for line_no in range(start, start + count):
            changed_line_map.setdefault(current_file, set()).add(line_no)

    return {
        "changed_files": changed_files,
        "changed_lines": {
            path: [f"{path}:{line_no}" for line_no in sorted(lines)]
            for path, lines in changed_line_map.items()
            if lines
        },
        "out_of_scope_files": sorted(set(out_of_scope_files)),
    }


def run_git_diff(workspace_root: pathlib.Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def infer_context(
    *,
    workspace_root: pathlib.Path,
    project_root: pathlib.Path,
    explicit_seed: str | None,
    explicit_changed_files: list[str],
    explicit_changed_lines: list[str],
    patch_file: pathlib.Path | None = None,
    stdin_patch: str | None = None,
) -> dict:
    explicit_files = [normalize_relative_path(item) for item in explicit_changed_files if item]
    explicit_lines = [normalize_relative_path(item) for item in explicit_changed_lines if item]
    payload = {
        "selected_seed": explicit_seed,
        "changed_files": explicit_files,
        "changed_lines": explicit_lines,
        "effective_changed_files": list(explicit_files),
        "effective_changed_lines": list(explicit_lines),
        "candidate_seeds": [],
        "seed_confidence": 1.0 if explicit_seed else 0.0,
        "reason": "explicit parameters provided" if explicit_seed or explicit_files or explicit_lines else "no context inferred yet",
        "context_sources": [],
        "fallback_used": False,
        "out_of_scope_files": [],
        "noise_files": [],
        "context_status": "missing",
        "context_source": "explicit_seed" if explicit_seed else "explicit_changed_file" if explicit_files else "explicit_changed_line" if explicit_lines else "missing",
        "explicit_context_files": list(explicit_files),
        "background_dirty_files": [],
        "background_dirty_files_count": 0,
        "background_dirty_files_used_for_seed": False,
    }

    if explicit_seed:
        payload["context_sources"].append("explicit_seed")
    if explicit_files:
        payload["context_sources"].append("explicit_changed_files")
    if explicit_lines:
        payload["context_sources"].append("explicit_changed_lines")

    def merge_diff(diff_payload: dict, source_name: str) -> None:
        diff_files = [normalize_relative_path(item) for item in diff_payload.get("changed_files", []) if item]
        diff_lines: list[str] = []
        for items in diff_payload.get("changed_lines", {}).values():
            diff_lines.extend(normalize_relative_path(item) for item in items if item)
        explicit_files_locked = "explicit_changed_files" in payload["context_sources"]
        explicit_lines_locked = "explicit_changed_lines" in payload["context_sources"]
        if explicit_files_locked and source_name.startswith("git_"):
            payload["background_dirty_files"] = sorted(set(payload["background_dirty_files"]) | set(diff_files))
            payload["background_dirty_files_count"] = len(payload["background_dirty_files"])
            return
        merged = False
        if diff_files and not explicit_files_locked:
            payload["changed_files"] = sorted(set(payload["changed_files"]) | set(diff_files))
            merged = True
        if diff_lines and not explicit_lines_locked:
            payload["changed_lines"] = sorted(set(payload["changed_lines"]) | set(diff_lines))
            merged = True
        if merged and source_name not in payload["context_sources"]:
            payload["context_sources"].append(source_name)
        payload["out_of_scope_files"] = sorted(set(payload["out_of_scope_files"]) | set(diff_payload.get("out_of_scope_files", [])))

    if (not payload["changed_files"] or not payload["changed_lines"]) and patch_file and patch_file.exists():
        merge_diff(
            parse_unified_diff(
                patch_file.read_text(encoding="utf-8", errors="replace"),
                workspace_root=workspace_root,
                project_root=project_root,
            ),
            "patch_file",
        )

    if (not payload["changed_files"] or not payload["changed_lines"]) and stdin_patch:
        merge_diff(
            parse_unified_diff(
                stdin_patch,
                workspace_root=workspace_root,
                project_root=project_root,
            ),
            "stdin_patch",
        )

    if not payload["changed_files"] or not payload["changed_lines"]:
        working_tree_diff = run_git_diff(workspace_root, ["diff", "--unified=0"])
        if working_tree_diff:
            merge_diff(
                parse_unified_diff(
                    working_tree_diff,
                    workspace_root=workspace_root,
                    project_root=project_root,
                ),
                "git_working_tree",
            )

    if not payload["changed_files"] or not payload["changed_lines"]:
        staged_diff = run_git_diff(workspace_root, ["diff", "--cached", "--unified=0"])
        if staged_diff:
            merge_diff(
                parse_unified_diff(
                    staged_diff,
                    workspace_root=workspace_root,
                    project_root=project_root,
                ),
                "git_staged",
            )

    if not payload["changed_files"] or not payload["selected_seed"]:
        last_task = read_last_task(workspace_root) or {}
        if not payload["changed_files"] and last_task.get("changed_files"):
            payload["changed_files"] = [normalize_relative_path(item) for item in last_task.get("changed_files", [])]
            payload["context_sources"].append("last_task")
        if not payload["selected_seed"] and not payload["changed_files"] and last_task.get("seed"):
            payload["selected_seed"] = last_task.get("seed")
            payload["context_sources"].append("last_task_seed")
        if not payload["changed_lines"]:
            seed_selection = last_task.get("seed_selection") or {}
            inferred_lines: list[str] = []
            for candidate in seed_selection.get("top_candidates", []):
                path = candidate.get("path")
                if path and path in payload["changed_files"]:
                    inferred_lines.append(f"{path}:{candidate.get('start_line', 1)}")
            if inferred_lines:
                payload["changed_lines"] = inferred_lines
                payload["context_sources"].append("last_task_candidates")

    if payload["changed_files"] and not payload["reason"].startswith("explicit"):
        payload["seed_confidence"] = 0.8 if payload["changed_lines"] else 0.65
        payload["reason"] = f"context inferred from {', '.join(payload['context_sources'])}"
        if "patch_file" in payload["context_sources"]:
            payload["context_source"] = "patch_file"
        elif "stdin_patch" in payload["context_sources"]:
            payload["context_source"] = "stdin_patch"
        elif "git_working_tree" in payload["context_sources"]:
            payload["context_source"] = "git_dirty_worktree"
            payload["background_dirty_files_used_for_seed"] = True
        elif "last_task" in payload["context_sources"]:
            payload["context_source"] = "recent_task"
    elif payload["selected_seed"] and not explicit_seed:
        payload["seed_confidence"] = 0.72
        payload["reason"] = f"seed recovered from {', '.join(payload['context_sources'])}"
        payload["context_source"] = "recent_task_seed"

    if payload["changed_files"]:
        retained_files: list[str] = []
        retained_lines: list[str] = []
        noise_files: list[str] = []
        changed_line_map: dict[str, list[str]] = {}
        for item in payload["changed_lines"]:
            changed_line_map.setdefault(item.rsplit(":", 1)[0], []).append(item)
        for file_path in payload["changed_files"]:
            if is_generated_or_cache_file(file_path):
                noise_files.append(file_path)
                continue
            retained_files.append(file_path)
            retained_lines.extend(changed_line_map.get(file_path, []))
        if retained_files != payload["changed_files"]:
            payload["effective_changed_files"] = retained_files
            payload["effective_changed_lines"] = retained_lines
            payload["noise_files"] = sorted(set(noise_files))
            if noise_files:
                payload["context_sources"].append("generated_noise_filtered")
        else:
            payload["effective_changed_files"] = list(payload["changed_files"])
            payload["effective_changed_lines"] = list(payload["changed_lines"])

    if payload["selected_seed"] and payload["effective_changed_files"]:
        payload["context_status"] = "resolved"
    elif payload["effective_changed_files"] or payload["selected_seed"] or payload["out_of_scope_files"] or payload["noise_files"]:
        payload["context_status"] = "partial"
    else:
        payload["context_status"] = "missing"

    return payload


def stdin_patch_if_available() -> str | None:
    if sys.stdin is None or sys.stdin.closed or sys.stdin.isatty():
        return None
    data = sys.stdin.read()
    return data or None
