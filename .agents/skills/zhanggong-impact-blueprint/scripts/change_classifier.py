#!/usr/bin/env python3
from __future__ import annotations

import copy
import fnmatch
import pathlib
import re

from identity import SKILL_DIR_FRAGMENT, STATE_CONFIG_RELATIVE_PATH, STATE_SCHEMA_RELATIVE_PATH


TEXT_DOC_SUFFIXES = {".md", ".txt", ".rst"}
IMAGE_SUFFIXES = {".drawio", ".excalidraw", ".png", ".jpg", ".jpeg", ".svg"}
CLASS_PRIORITY = {
    "bypass": 0,
    "lightweight": 1,
    "guarded": 2,
    "risk_sensitive": 3,
}
LEVEL_PRIORITY = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
WORKING_NOTE_NAME_HINTS = {
    "chaos",
    "journal",
    "log",
    "milestone",
    "note",
    "notes",
    "progress",
    "record",
    "status",
    "tracker",
    "worklog",
    "working",
}
WORKING_NOTE_STRONG_PATTERNS = [
    "working notes",
    "working note",
    "current status",
    "next steps",
    "in progress",
    "blocked",
]
WORKING_NOTE_SOFT_PATTERNS = [
    "handoff",
    "milestone",
    "plan",
    "progress",
    "stage ",
    "status",
    "todo",
]


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
        "AGENTS.md",
        f"{SKILL_DIR_FRAGMENT}/SKILL.md",
        f"{SKILL_DIR_FRAGMENT}/assets/templates/*.template.md",
        f"{SKILL_DIR_FRAGMENT}/references/*.md",
        ".ai/codegraph/runtime/*.md",
        ".ai/codegraph/runtime/**/*.md",
    ],
    "guarded_globs": [
        "src/**",
        "scripts/**",
        "tests/**",
        f"{SKILL_DIR_FRAGMENT}/**/*.py",
        STATE_CONFIG_RELATIVE_PATH,
        STATE_SCHEMA_RELATIVE_PATH,
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
        f"python {SKILL_DIR_FRAGMENT}/cig.py",
        f"{SKILL_DIR_FRAGMENT}/cig.py",
        "governs:",
        "docs/rules",
        "context_missing",
        "graph_trust",
    ],
}

DEFAULT_DOC_ROLES = {
    "working_note_globs": [],
    "protected_doc_globs": [
        "README.md",
        "AGENTS.md",
        f"{SKILL_DIR_FRAGMENT}/SKILL.md",
    ],
}

DEFAULT_MUTATION_GUARD = {
    "confirm_move_for_protected_docs": True,
    "confirm_archive_for_protected_docs": True,
    "delete_mode": "recycle_only",
    "require_strict_approval_for_permanent_delete": True,
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


def default_doc_roles() -> dict:
    return copy.deepcopy(DEFAULT_DOC_ROLES)


def default_mutation_guard() -> dict:
    return copy.deepcopy(DEFAULT_MUTATION_GUARD)


def _merge_glob_policy(defaults: dict, configured: dict | None) -> dict:
    merged = copy.deepcopy(defaults)
    for key, default_values in defaults.items():
        if isinstance(default_values, list):
            user_values = list((configured or {}).get(key) or [])
            merged[key] = [*user_values, *[item for item in default_values if item not in user_values]]
        else:
            merged[key] = (configured or {}).get(key, default_values)
    return merged


def merged_flow_policy(config: dict | None) -> dict:
    return _merge_glob_policy(DEFAULT_FLOW_POLICY, (config or {}).get("flow_policy") or {})


def merged_doc_roles(config: dict | None) -> dict:
    return _merge_glob_policy(DEFAULT_DOC_ROLES, (config or {}).get("doc_roles") or {})


def merged_mutation_guard(config: dict | None) -> dict:
    return _merge_glob_policy(DEFAULT_MUTATION_GUARD, (config or {}).get("mutation_guard") or {})


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


def _tokenize_name(path: str) -> set[str]:
    name = pathlib.PurePosixPath(path).stem.lower()
    return {token for token in re.split(r"[^a-z0-9]+", name) if token}


def looks_like_working_note(workspace_root: pathlib.Path, path: str) -> bool:
    normalized = path.lower()
    if not is_text_document(normalized):
        return False
    if normalized.startswith(("docs/archive/", "docs/demo/", "docs/rules/")):
        return False
    if is_review_or_runtime_doc(normalized):
        return False
    content = read_text_if_available(workspace_root, path).lower()
    if not content:
        return False
    strong_hits = sum(1 for pattern in WORKING_NOTE_STRONG_PATTERNS if pattern in content)
    soft_hits = sum(1 for pattern in WORKING_NOTE_SOFT_PATTERNS if pattern in content)
    bullet_lines = sum(
        1
        for line in content.splitlines()
        if line.lstrip().startswith(("- ", "* ", "1. ", "2. ", "3. "))
    )
    name_tokens = _tokenize_name(path)
    name_hint = bool(name_tokens & WORKING_NOTE_NAME_HINTS)
    if strong_hits >= 2:
        return True
    if strong_hits >= 1 and (name_hint or soft_hits >= 1 or bullet_lines >= 2):
        return True
    if name_hint and (soft_hits >= 2 or bullet_lines >= 2):
        return True
    return False


def doc_role_for_file(workspace_root: pathlib.Path, config: dict, changed_file: str) -> dict:
    path = normalize_path(changed_file, workspace_root)
    normalized = path.lower()
    doc_roles = merged_doc_roles(config)
    declared_protected_pattern = first_matching_pattern(path, doc_roles["protected_doc_globs"])
    if not is_text_document(path):
        return {
            "path": path,
            "doc_role": "non_doc",
            "role_source": "special_case",
            "declared_pattern": None,
            "protected_doc": bool(declared_protected_pattern),
            "protection_source": f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None,
        }
    if normalized.startswith("docs/rules/"):
        return {
            "path": path,
            "doc_role": "rule_doc",
            "role_source": "special_case",
            "declared_pattern": None,
            "protected_doc": True,
            "protection_source": "special_case:rule_doc",
        }
    declared_working_note_pattern = first_matching_pattern(path, doc_roles["working_note_globs"])
    if declared_working_note_pattern:
        return {
            "path": path,
            "doc_role": "working_note",
            "role_source": "declared",
            "declared_pattern": f"working_note_globs:{declared_working_note_pattern}",
            "protected_doc": bool(declared_protected_pattern),
            "protection_source": f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None,
        }
    if is_review_or_runtime_doc(path):
        protection_source = f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None
        return {
            "path": path,
            "doc_role": "guide_doc",
            "role_source": "special_case",
            "declared_pattern": None,
            "protected_doc": bool(declared_protected_pattern),
            "protection_source": protection_source,
        }
    if normalized.startswith(("docs/archive/", "docs/demo/")):
        return {
            "path": path,
            "doc_role": "archive_note",
            "role_source": "special_case",
            "declared_pattern": None,
            "protected_doc": bool(declared_protected_pattern),
            "protection_source": f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None,
        }
    if looks_like_working_note(workspace_root, path):
        return {
            "path": path,
            "doc_role": "working_note",
            "role_source": "heuristic",
            "declared_pattern": None,
            "protected_doc": bool(declared_protected_pattern),
            "protection_source": f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None,
        }
    return {
        "path": path,
        "doc_role": "generic_doc",
        "role_source": "default",
        "declared_pattern": None,
        "protected_doc": bool(declared_protected_pattern),
        "protection_source": f"protected_doc_globs:{declared_protected_pattern}" if declared_protected_pattern else None,
    }


def file_classification(workspace_root: pathlib.Path, config: dict, changed_file: str) -> dict:
    path = normalize_path(changed_file, workspace_root)
    flow_policy = merged_flow_policy(config)
    role_info = doc_role_for_file(workspace_root, config, path)
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

    doc_role = role_info["doc_role"]
    if doc_role == "rule_doc":
        matched.append((CLASS_PRIORITY["guarded"], "guarded", "special_case:rule_doc"))
    elif doc_role == "guide_doc":
        matched.append((CLASS_PRIORITY["lightweight"], "lightweight", "special_case:guide_doc"))
    elif doc_role == "working_note":
        matched.append((CLASS_PRIORITY["lightweight"], "lightweight", "special_case:working_note"))
    elif doc_role == "archive_note":
        matched.append((CLASS_PRIORITY["bypass"], "bypass", "special_case:archive_note"))
    elif plain_doc_bypass_candidate(path):
        matched.append((CLASS_PRIORITY["bypass"], "bypass", "special_case:plain_doc"))

    if pathlib.PurePosixPath(path).suffix.lower() in IMAGE_SUFFIXES:
        matched.append((CLASS_PRIORITY["bypass"], "bypass", "special_case:diagram_or_image"))

    if not matched:
        fallback_class = "bypass" if is_text_document(path) else "guarded"
        matched.append((CLASS_PRIORITY[fallback_class], fallback_class, f"special_case:default_{fallback_class}"))

    winner = max(matched, key=lambda item: item[0])
    guard_pattern = matching_guard_pattern(workspace_root, path, flow_policy["markdown_guard_patterns"])
    suppress_guard_promotion = doc_role in {"working_note", "archive_note"}
    if guard_pattern and winner[1] == "bypass" and not suppress_guard_promotion:
        winner = (
            CLASS_PRIORITY["lightweight"],
            "lightweight",
            f"markdown_guard_patterns:{guard_pattern}",
        )

    return {
        "path": path,
        "class": winner[1],
        "matched_rule": winner[2],
        "contains_guard_pattern": bool(guard_pattern),
        "guard_pattern": guard_pattern,
        "doc_role": doc_role,
        "role_source": role_info["role_source"],
        "declared_pattern": role_info["declared_pattern"],
        "protected_doc": role_info["protected_doc"],
        "protection_source": role_info["protection_source"],
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


def workflow_lane_for_class(change_class: str) -> str:
    return {
        "bypass": "bypass",
        "lightweight": "lightweight",
        "guarded": "full_guardian",
        "risk_sensitive": "full_guardian",
        "mixed": "full_guardian",
    }[change_class]


def lane_explanation_for_class(change_class: str) -> str:
    return {
        "bypass": "No runtime, rule, command, schema, config, or agent-behavior effect was detected.",
        "lightweight": "This can affect workflow or agent behavior, but no direct code behavior change was detected.",
        "guarded": "Source, tests, config, schema, rule, or command behavior may change, so use the full guardian lane.",
        "risk_sensitive": "Dependency, schema, env, SQL, or build/runtime configuration may change, so use the full guardian lane.",
        "mixed": "At least one file requires the full guardian lane, so the whole change uses full guardian.",
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
            "workflow_lane": "lightweight",
            "lane": "lightweight",
            "lane_explanation": "No changed files were supplied, so only health/context checks are useful.",
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
    role_codes = sorted({entry["doc_role"] for entry in file_entries if entry.get("doc_role") not in {None, "non_doc"}})
    reason_codes.extend(f"doc_role:{role}" for role in role_codes)
    if change_class == "mixed":
        reason_codes.append("mixed_change")
    if any(entry.get("contains_guard_pattern") for entry in file_entries):
        reason_codes.append("markdown_guard_pattern")

    return {
        "change_class": change_class,
        "effective_class": current_effective_class,
        "flow_level": flow_level_for_class(change_class),
        "workflow_lane": workflow_lane_for_class(current_effective_class),
        "lane": workflow_lane_for_class(current_effective_class),
        "lane_explanation": lane_explanation_for_class(current_effective_class),
        "verification_budget": verification_budget_for_class(current_effective_class),
        "recommended_test_scope": recommended_scope_for_class(current_effective_class),
        "reason_codes": reason_codes,
        "files": file_entries,
    }


def assess_mutation(workspace_root: pathlib.Path, config: dict, target_path: str, action: str) -> dict:
    path = normalize_path(target_path, workspace_root)
    classification = file_classification(workspace_root, config, path)
    mutation_guard = merged_mutation_guard(config)
    protected_doc = classification.get("protected_doc", False)
    doc_role = classification.get("doc_role")

    guard_level = "safe_edit"
    requires_user_confirmation = False
    requires_strict_user_approval = False
    allowed_without_approval = True
    delete_mode = "none"
    permanent_delete_allowed = True
    reason_codes: list[str] = []

    if action == "move":
        if protected_doc and mutation_guard.get("confirm_move_for_protected_docs", True):
            guard_level = "confirm_before_move"
            requires_user_confirmation = True
            allowed_without_approval = False
            reason_codes.append("protected_doc_move")
        else:
            reason_codes.append("move_allowed")
    elif action == "archive":
        if protected_doc and mutation_guard.get("confirm_archive_for_protected_docs", True):
            guard_level = "confirm_before_archive"
            requires_user_confirmation = True
            allowed_without_approval = False
            reason_codes.append("protected_doc_archive")
        else:
            reason_codes.append("archive_allowed")
    elif action == "delete":
        delete_mode = mutation_guard.get("delete_mode", "recycle_only")
        permanent_delete_allowed = False
        if delete_mode == "recycle_only":
            guard_level = "recycle_only_delete"
            reason_codes.append("recycle_only_delete")
        else:
            guard_level = "confirm_before_delete"
            requires_user_confirmation = True
            allowed_without_approval = False
            reason_codes.append("delete_requires_confirmation")
        if protected_doc:
            requires_user_confirmation = True
            allowed_without_approval = False
            reason_codes.append("protected_doc_delete")
    elif action == "permanent_delete":
        delete_mode = "permanent"
        permanent_delete_allowed = False
        guard_level = "never_delete_without_approval"
        requires_strict_user_approval = mutation_guard.get("require_strict_approval_for_permanent_delete", True)
        allowed_without_approval = False
        reason_codes.append("strict_approval_required")
    else:
        reason_codes.append("edit_allowed")

    if action == "edit":
        user_message = "This is a normal edit. Mutation protection does not block editing this file."
    elif guard_level == "confirm_before_move":
        user_message = "This document is protected. Confirm with the user before moving it."
    elif guard_level == "confirm_before_archive":
        user_message = "This document is protected. Confirm with the user before archiving it."
    elif guard_level == "recycle_only_delete":
        user_message = "Delete operations must go to the recycle bin or trash by default."
    else:
        user_message = "Permanent deletion requires explicit, strict user approval."

    return {
        "path": path,
        "action": action,
        "doc_role": doc_role,
        "role_source": classification.get("role_source"),
        "change_class": classification.get("class"),
        "guard_level": guard_level,
        "protected_doc": protected_doc,
        "requires_user_confirmation": requires_user_confirmation,
        "requires_strict_user_approval": requires_strict_user_approval,
        "allowed_without_approval": allowed_without_approval,
        "delete_mode": delete_mode,
        "permanent_delete_allowed": permanent_delete_allowed,
        "reason_codes": reason_codes,
        "user_message": user_message,
    }


def is_non_runtime_flow(change_summary: dict) -> bool:
    return change_summary.get("flow_level") in {"skip", "analyze_only", "health_only"}


def max_escalation_level(*levels: str) -> str:
    valid_levels = [level for level in levels if level in LEVEL_PRIORITY]
    if not valid_levels:
        return "L0"
    return max(valid_levels, key=lambda level: LEVEL_PRIORITY[level])

