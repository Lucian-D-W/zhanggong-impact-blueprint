#!/usr/bin/env python3
from __future__ import annotations

import copy
import fnmatch
import pathlib


TEXT_DOC_SUFFIXES = {".md", ".txt", ".rst"}
IMAGE_SUFFIXES = {".drawio", ".excalidraw", ".png", ".jpg", ".jpeg", ".svg"}
CLASS_PRIORITY = {
    "bypass": 0,
    "lightweight": 1,
    "guarded": 2,
    "risk_sensitive": 3,
}
LEVEL_PRIORITY = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


DEFAULT_FLOW_POLICY = {
    "bypass_globs": [
        "docs/archive/**",
        "docs/demo/**",
        "**/*.drawio",
        "**/*.excalidraw",
        "**/*.png",
        "**/*.jpg",
        "**/*.jpeg",
        "**/*.svg",
    ],
    "lightweight_globs": [
        "README.md",
        "AGENTS.md",
        ".agents/skills/code-impact-guardian/SKILL.md",
        ".ai/codegraph/runtime/*.md",
        ".ai/codegraph/runtime/**/*.md",
    ],
    "guarded_globs": [
        "src/**",
        "scripts/**",
        "tests/**",
        ".agents/skills/code-impact-guardian/**/*.py",
        ".code-impact-guardian/config.json",
        ".code-impact-guardian/schema.sql",
        "docs/rules/**",
    ],
    "risk_sensitive_globs": [
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "poetry.lock",
        "tsconfig.json",
        "vite.config.*",
        "next.config.*",
        ".env",
        ".env.*",
        "migrations/**",
        "schema/**",
        "**/*.sql",
    ],
    "markdown_guard_patterns": [
        "test_command",
        "verification budget",
        "finish --test-scope",
        "python .agents/skills/code-impact-guardian/cig.py",
        "governs:",
        "docs/rules",
        "context_missing",
        "graph_trust",
    ],
}


def normalize_path(path: str | pathlib.Path, workspace_root: pathlib.Path | None = None) -> str:
    candidate = pathlib.Path(path)
    if workspace_root is not None:
        try:
            candidate = candidate.resolve().relative_to(workspace_root.resolve())
        except Exception:
            pass
    normalized = candidate.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.replace("\\", "/")


def is_text_document(path: str) -> bool:
    return pathlib.PurePosixPath(path).suffix.lower() in TEXT_DOC_SUFFIXES


def is_review_or_runtime_doc(path: str) -> bool:
    normalized = path.lower()
    name = pathlib.PurePosixPath(normalized).name
    return (
        normalized.startswith(".ai/codegraph/runtime/")
        or "handoff" in name
        or "review_guide" in name
        or "review-guide" in name
        or name == "agents.md"
        or name == "readme.md"
        or name == "skill.md"
    )


def plain_doc_bypass_candidate(path: str) -> bool:
    normalized = path.lower()
    if not is_text_document(normalized):
        return False
    if normalized.startswith("docs/rules/"):
        return False
    if is_review_or_runtime_doc(normalized):
        return False
    return True


def default_flow_policy() -> dict:
    return copy.deepcopy(DEFAULT_FLOW_POLICY)


def merged_flow_policy(config: dict | None) -> dict:
    flow_policy = (config or {}).get("flow_policy") or {}
    merged = default_flow_policy()
    for key, default_values in DEFAULT_FLOW_POLICY.items():
        user_values = list(flow_policy.get(key) or [])
        merged[key] = [*user_values, *[item for item in default_values if item not in user_values]]
    return merged


def _pattern_variants(pattern: str) -> list[str]:
    variants = {pattern}
    current = pattern
    while "**/" in current:
        current = current.replace("**/", "", 1)
        variants.add(current)
    return list(variants)


def path_matches(path: str, pattern: str) -> bool:
    normalized_path = path.lower()
    normalized_pattern = pattern.replace("\\", "/").lower()
    return any(fnmatch.fnmatch(normalized_path, variant) for variant in _pattern_variants(normalized_pattern))


def first_matching_pattern(path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if path_matches(path, pattern):
            return pattern
    return None


def read_text_if_available(workspace_root: pathlib.Path, relative_path: str) -> str:
    path = workspace_root / relative_path
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def matching_guard_pattern(workspace_root: pathlib.Path, path: str, patterns: list[str]) -> str | None:
    if not is_text_document(path):
        return None
    content = read_text_if_available(workspace_root, path).lower()
    if not content:
        return None
    for pattern in patterns:
        if pattern.lower() in content:
            return pattern
    return None


def file_classification(workspace_root: pathlib.Path, config: dict, changed_file: str) -> dict:
    path = normalize_path(changed_file, workspace_root)
    flow_policy = merged_flow_policy(config)
    matched: list[tuple[int, str, str]] = []

    risk_pattern = first_matching_pattern(path, flow_policy["risk_sensitive_globs"])
    if risk_pattern:
        matched.append((CLASS_PRIORITY["risk_sensitive"], "risk_sensitive", f"risk_sensitive_globs:{risk_pattern}"))

    guarded_pattern = first_matching_pattern(path, flow_policy["guarded_globs"])
    if guarded_pattern:
        matched.append((CLASS_PRIORITY["guarded"], "guarded", f"guarded_globs:{guarded_pattern}"))

    lightweight_pattern = first_matching_pattern(path, flow_policy["lightweight_globs"])
    if lightweight_pattern:
        matched.append((CLASS_PRIORITY["lightweight"], "lightweight", f"lightweight_globs:{lightweight_pattern}"))

    bypass_pattern = first_matching_pattern(path, flow_policy["bypass_globs"])
    if bypass_pattern:
        matched.append((CLASS_PRIORITY["bypass"], "bypass", f"bypass_globs:{bypass_pattern}"))

    if path.lower().startswith("docs/rules/"):
        matched.append((CLASS_PRIORITY["guarded"], "guarded", "special_case:docs_rules"))

    if is_review_or_runtime_doc(path):
        matched.append((CLASS_PRIORITY["lightweight"], "lightweight", "special_case:runtime_or_review_doc"))

    if plain_doc_bypass_candidate(path):
        matched.append((CLASS_PRIORITY["bypass"], "bypass", "special_case:plain_doc"))

    if pathlib.PurePosixPath(path).suffix.lower() in IMAGE_SUFFIXES:
        matched.append((CLASS_PRIORITY["bypass"], "bypass", "special_case:diagram_or_image"))

    if not matched:
        fallback_class = "bypass" if is_text_document(path) else "guarded"
        matched.append((CLASS_PRIORITY[fallback_class], fallback_class, f"special_case:default_{fallback_class}"))

    winner = max(matched, key=lambda item: item[0])
    guard_pattern = matching_guard_pattern(workspace_root, path, flow_policy["markdown_guard_patterns"])
    if guard_pattern and winner[1] in {"bypass", "lightweight"}:
        winner = (
            CLASS_PRIORITY["guarded"],
            "guarded",
            f"markdown_guard_patterns:{guard_pattern}",
        )

    return {
        "path": path,
        "class": winner[1],
        "matched_rule": winner[2],
        "contains_guard_pattern": bool(guard_pattern),
        "guard_pattern": guard_pattern,
    }


def effective_class(change_class: str, file_entries: list[dict]) -> str:
    if change_class != "mixed":
        return change_class
    return max(
        (entry["class"] for entry in file_entries),
        key=lambda value: CLASS_PRIORITY[value],
        default="guarded",
    )


def flow_level_for_class(change_class: str) -> str:
    return {
        "bypass": "skip",
        "lightweight": "analyze_only",
        "guarded": "full_guardian",
        "risk_sensitive": "full_guardian",
        "mixed": "full_guardian",
    }[change_class]


def verification_budget_for_class(change_class: str) -> str:
    return {
        "bypass": "B0",
        "lightweight": "B1",
        "guarded": "B2",
        "risk_sensitive": "B4",
        "mixed": "B2",
    }[change_class]


def recommended_scope_for_class(change_class: str) -> str:
    return {
        "bypass": "none",
        "lightweight": "none",
        "guarded": "targeted",
        "risk_sensitive": "full",
        "mixed": "targeted",
    }[change_class]


def classify_change(workspace_root: pathlib.Path, config: dict, changed_files: list[str]) -> dict:
    if not changed_files:
        return {
            "change_class": "lightweight",
            "effective_class": "lightweight",
            "flow_level": "health_only",
            "verification_budget": "B1",
            "recommended_test_scope": "none",
            "reason_codes": ["no_changed_files"],
            "files": [],
        }

    file_entries = [file_classification(workspace_root, config, changed_file) for changed_file in changed_files]
    classes = {entry["class"] for entry in file_entries}
    has_low = bool(classes & {"bypass", "lightweight"})
    has_high = bool(classes & {"guarded", "risk_sensitive"})
    if has_low and has_high:
        change_class = "mixed"
    elif "risk_sensitive" in classes:
        change_class = "risk_sensitive"
    elif "guarded" in classes:
        change_class = "guarded"
    elif "lightweight" in classes:
        change_class = "lightweight"
    else:
        change_class = "bypass"

    current_effective_class = effective_class(change_class, file_entries)
    reason_codes = sorted({entry["class"] for entry in file_entries})
    if change_class == "mixed":
        reason_codes.append("mixed_change")
    if any(entry.get("contains_guard_pattern") for entry in file_entries):
        reason_codes.append("markdown_guard_pattern")

    return {
        "change_class": change_class,
        "effective_class": current_effective_class,
        "flow_level": flow_level_for_class(change_class),
        "verification_budget": verification_budget_for_class(current_effective_class),
        "recommended_test_scope": recommended_scope_for_class(current_effective_class),
        "reason_codes": reason_codes,
        "files": file_entries,
    }


def is_non_runtime_flow(change_summary: dict) -> bool:
    return change_summary.get("flow_level") in {"skip", "analyze_only", "health_only"}


def max_escalation_level(*levels: str) -> str:
    valid_levels = [level for level in levels if level in LEVEL_PRIORITY]
    if not valid_levels:
        return "L0"
    return max(valid_levels, key=lambda level: LEVEL_PRIORITY[level])
