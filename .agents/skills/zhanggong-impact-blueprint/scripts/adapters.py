#!/usr/bin/env python3
import pathlib

from parser_backends import (
    AdapterGraph,
    file_node_id,
    function_node_id,
    matches_any,
    parse_with_backend,
    test_node_id,
    iter_matching_files,
)
from profiles import detect_project_profile, package_json_data, profile_coverage_adapter, profile_test_command


PYTHON_ADAPTER = "python"
TSJS_ADAPTER = "tsjs"
GENERIC_ADAPTER = "generic"
SQL_POSTGRES_ADAPTER = "sql_postgres"
AUTO_ADAPTER = "auto"
PRIMARY_ADAPTERS = {PYTHON_ADAPTER, TSJS_ADAPTER, GENERIC_ADAPTER}
SUPPLEMENTAL_ADAPTERS = {PYTHON_ADAPTER, TSJS_ADAPTER, SQL_POSTGRES_ADAPTER}


def rule_node_id(rule_id: str) -> str:
    return f"rule:{rule_id}"


def normalize_adapter_name(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"", AUTO_ADAPTER, "none", "null"}:
        return None
    mapping = {
        "node": TSJS_ADAPTER,
        "javascript": TSJS_ADAPTER,
        "typescript": TSJS_ADAPTER,
        "py": PYTHON_ADAPTER,
    }
    normalized = mapping.get(normalized, normalized)
    if normalized in PRIMARY_ADAPTERS | {SQL_POSTGRES_ADAPTER}:
        return normalized
    return None


def configured_primary_adapter_name(config: dict) -> str:
    return normalize_adapter_name(config.get("primary_adapter"))


def configured_adapter_name(config: dict) -> str:
    return configured_primary_adapter_name(config) or AUTO_ADAPTER


def configured_supplemental_adapters(config: dict) -> list[str]:
    adapters: list[str] = []
    for item in list(config.get("supplemental_adapters", [])):
        normalized = normalize_adapter_name(item)
        if normalized and normalized in SUPPLEMENTAL_ADAPTERS and normalized not in adapters:
            adapters.append(normalized)
    if config.get("sql_postgres", {}).get("enabled") and SQL_POSTGRES_ADAPTER not in adapters:
        adapters.append(SQL_POSTGRES_ADAPTER)
    return adapters


def configured_language_adapter_name(config: dict) -> str | None:
    normalized = normalize_adapter_name(config.get("language_adapter"))
    if normalized in PRIMARY_ADAPTERS:
        return normalized
    return None


def adapter_file_matches(project_root: pathlib.Path, config: dict, adapter_name: str) -> list[pathlib.Path]:
    adapter_config = config.get(adapter_name, {}) or {}
    patterns = list(adapter_config.get("source_globs", [])) + list(adapter_config.get("test_globs", []))
    return iter_matching_files(project_root, patterns, exclude_dirs=config.get("graph", {}).get("exclude_dirs"))


def adapter_evidence(project_root: pathlib.Path, config: dict) -> dict[str, dict]:
    package_data = package_json_data(project_root)
    evidence: dict[str, dict] = {}
    python_files = adapter_file_matches(project_root, config, PYTHON_ADAPTER)
    tsjs_files = adapter_file_matches(project_root, config, TSJS_ADAPTER)
    python_score = len(python_files)
    tsjs_score = len(tsjs_files)
    if (project_root / "pyproject.toml").exists() or (project_root / "requirements.txt").exists():
        python_score += 2
    if package_data:
        tsjs_score += 3
    if (project_root / "package-lock.json").exists() or (project_root / "pnpm-lock.yaml").exists() or (project_root / "yarn.lock").exists() or (project_root / "bun.lock").exists() or (project_root / "bun.lockb").exists():
        tsjs_score += 1
    evidence[PYTHON_ADAPTER] = {
        "files": len(python_files),
        "score": python_score,
        "paths": [path.relative_to(project_root).as_posix() for path in python_files[:8]],
    }
    evidence[TSJS_ADAPTER] = {
        "files": len(tsjs_files),
        "score": tsjs_score,
        "paths": [path.relative_to(project_root).as_posix() for path in tsjs_files[:8]],
    }
    return evidence


def auto_detect_adapter_decision(project_root: pathlib.Path, config: dict) -> dict:
    evidence = adapter_evidence(project_root, config)
    python_score = evidence[PYTHON_ADAPTER]["score"]
    tsjs_score = evidence[TSJS_ADAPTER]["score"]
    adapter_conflicts: list[dict] = []
    if python_score and tsjs_score:
        adapter_conflicts.append(
            {
                "candidates": [TSJS_ADAPTER, PYTHON_ADAPTER],
                "reason": f"mixed-language repo detected (tsjs_score={tsjs_score}, python_score={python_score})",
            }
        )
    if tsjs_score >= python_score and tsjs_score > 0:
        primary = TSJS_ADAPTER
        adapter_confidence = "high" if tsjs_score - python_score >= 2 else "medium"
        reason = f"auto-detected tsjs because tsjs_score={tsjs_score} >= python_score={python_score}"
    elif python_score > 0:
        primary = PYTHON_ADAPTER
        adapter_confidence = "high" if python_score - tsjs_score >= 2 else "medium"
        reason = f"auto-detected python because python_score={python_score} > tsjs_score={tsjs_score}"
    else:
        primary = GENERIC_ADAPTER
        adapter_confidence = "low"
        reason = "no strong language markers found; using generic fallback"
    supplemental: list[str] = []
    if primary != TSJS_ADAPTER and tsjs_score > 0:
        supplemental.append(TSJS_ADAPTER)
    if primary != PYTHON_ADAPTER and python_score > 0:
        supplemental.append(PYTHON_ADAPTER)
    return {
        "primary_adapter": primary,
        "adapter_source": "auto_detected",
        "adapter_reason": reason,
        "supplemental_adapters": supplemental,
        "adapter_confidence": adapter_confidence,
        "adapter_conflicts": adapter_conflicts,
        "adapter_evidence": evidence,
    }


def active_configured_supplemental_adapters(project_root: pathlib.Path, config: dict, primary_adapter: str) -> list[str]:
    detected: list[str] = []
    for adapter_name in configured_supplemental_adapters(config):
        if adapter_name == primary_adapter:
            continue
        if adapter_name == SQL_POSTGRES_ADAPTER:
            sql_config = config.get(SQL_POSTGRES_ADAPTER, {})
            source_globs = sql_config.get("source_globs", [])
            test_globs = sql_config.get("test_globs", [])
            if sql_config.get("enabled") and any(path.exists() for path in iter_matching_files(project_root, source_globs + test_globs)):
                detected.append(adapter_name)
            continue
        if adapter_file_matches(project_root, config, adapter_name):
            detected.append(adapter_name)
    return detected


def effective_adapter_decision(config: dict, project_root: pathlib.Path) -> dict:
    configured_primary = configured_primary_adapter_name(config)
    language_adapter = configured_language_adapter_name(config)
    evidence = adapter_evidence(project_root, config)
    if configured_primary:
        primary_adapter = configured_primary
        adapter_source = "primary_adapter"
        adapter_reason = f"using explicit primary_adapter={primary_adapter}"
        adapter_confidence = "high"
        adapter_conflicts: list[dict] = []
        auto_decision = auto_detect_adapter_decision(project_root, config)
    elif language_adapter:
        primary_adapter = language_adapter
        raw_primary = config.get("primary_adapter", "missing")
        adapter_source = "language_adapter_fallback"
        adapter_reason = f"primary_adapter={raw_primary} treated as unset; using language_adapter={language_adapter}"
        adapter_confidence = "high"
        auto_decision = auto_detect_adapter_decision(project_root, config)
        adapter_conflicts = list(auto_decision.get("adapter_conflicts", []))
    else:
        auto_decision = auto_detect_adapter_decision(project_root, config)
        primary_adapter = auto_decision["primary_adapter"]
        adapter_source = auto_decision["adapter_source"]
        adapter_reason = auto_decision["adapter_reason"]
        adapter_confidence = auto_decision["adapter_confidence"]
        adapter_conflicts = list(auto_decision.get("adapter_conflicts", []))

    supplemental: list[str] = []
    inferred_supplemental = list(auto_decision.get("supplemental_adapters", []))
    for adapter_name, payload in evidence.items():
        if adapter_name != primary_adapter and payload.get("score", 0) > 0 and adapter_name not in inferred_supplemental:
            inferred_supplemental.append(adapter_name)
    for item in [*active_configured_supplemental_adapters(project_root, config, primary_adapter), *inferred_supplemental]:
        if item and item != primary_adapter and item not in supplemental:
            supplemental.append(item)
    return {
        "primary_adapter": primary_adapter,
        "language_adapter": language_adapter or primary_adapter,
        "configured_primary_adapter": configured_primary,
        "adapter_source": adapter_source,
        "adapter_reason": adapter_reason,
        "supplemental_adapters": supplemental,
        "adapter_conflicts": adapter_conflicts,
        "adapter_confidence": adapter_confidence,
        "adapter_evidence": evidence,
    }


def detect_primary_adapter(project_root: pathlib.Path, config: dict) -> str:
    return effective_adapter_decision(config, project_root)["primary_adapter"]

def detect_language_adapter(project_root: pathlib.Path, config: dict) -> str:
    return effective_adapter_decision(config, project_root)["primary_adapter"]


def detect_supplemental_adapters(project_root: pathlib.Path, config: dict) -> list[str]:
    return effective_adapter_decision(config, project_root)["supplemental_adapters"]


def detect_project_profile_name(project_root: pathlib.Path, config: dict, adapter_name: str | None = None) -> str:
    active_adapter = adapter_name or detect_primary_adapter(project_root, config)
    profile_name, _, _ = detect_project_profile(project_root, config, active_adapter)
    return profile_name


def adapter_test_command(config: dict, adapter_name: str, project_root: pathlib.Path) -> list[str]:
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    return profile_test_command(profile_name, project_root, config, adapter_name)


def adapter_coverage_adapter(config: dict, adapter_name: str, project_root: pathlib.Path) -> str:
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    return profile_coverage_adapter(profile_name, config, adapter_name)


def collect_adapter_graph(project_root: pathlib.Path, config: dict, adapter_name: str, include_files: list[str] | None = None) -> AdapterGraph:
    return parse_with_backend(adapter_name, project_root, config, include_files)
