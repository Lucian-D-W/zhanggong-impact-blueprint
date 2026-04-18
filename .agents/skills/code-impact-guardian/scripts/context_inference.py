#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

from recent_task import read_last_task


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

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current_file = None
                continue
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
        "candidate_seeds": [],
        "confidence": 1.0 if explicit_seed else 0.0,
        "reason": "explicit parameters provided" if explicit_seed or explicit_files or explicit_lines else "no context inferred yet",
        "context_sources": [],
        "fallback_used": False,
        "out_of_scope_files": [],
    }

    if explicit_seed:
        payload["context_sources"].append("explicit_seed")
    if explicit_files:
        payload["context_sources"].append("explicit_changed_files")
    if explicit_lines:
        payload["context_sources"].append("explicit_changed_lines")

    def merge_diff(diff_payload: dict, source_name: str) -> None:
        if not payload["changed_files"] and diff_payload.get("changed_files"):
            payload["changed_files"] = list(diff_payload["changed_files"])
            payload["context_sources"].append(source_name)
        if not payload["changed_lines"] and diff_payload.get("changed_lines"):
            merged_lines: list[str] = []
            for items in diff_payload["changed_lines"].values():
                merged_lines.extend(items)
            payload["changed_lines"] = merged_lines
            if source_name not in payload["context_sources"]:
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
        if not payload["selected_seed"] and last_task.get("seed"):
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
        payload["confidence"] = 0.8 if payload["changed_lines"] else 0.65
        payload["reason"] = f"context inferred from {', '.join(payload['context_sources'])}"
    elif payload["selected_seed"] and not explicit_seed:
        payload["confidence"] = 0.72
        payload["reason"] = f"seed recovered from {', '.join(payload['context_sources'])}"

    return payload


def stdin_patch_if_available() -> str | None:
    if sys.stdin is None or sys.stdin.closed or sys.stdin.isatty():
        return None
    data = sys.stdin.read()
    return data or None
