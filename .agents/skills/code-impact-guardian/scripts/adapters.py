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
from profiles import detect_project_profile, profile_coverage_adapter, profile_test_command


PYTHON_ADAPTER = "python"
TSJS_ADAPTER = "tsjs"
GENERIC_ADAPTER = "generic"
AUTO_ADAPTER = "auto"


def rule_node_id(rule_id: str) -> str:
    return f"rule:{rule_id}"


def configured_adapter_name(config: dict) -> str:
    return config.get("language_adapter", AUTO_ADAPTER)


def detect_language_adapter(project_root: pathlib.Path, config: dict) -> str:
    configured = configured_adapter_name(config)
    if configured in {PYTHON_ADAPTER, TSJS_ADAPTER, GENERIC_ADAPTER}:
        return configured

    python_patterns = config.get("python", {}).get("source_globs", []) + config.get("python", {}).get("test_globs", [])
    tsjs_patterns = config.get("tsjs", {}).get("source_globs", []) + config.get("tsjs", {}).get("test_globs", [])

    if any(path.exists() for path in iter_matching_files(project_root, python_patterns)):
        return PYTHON_ADAPTER
    if any(path.exists() for path in iter_matching_files(project_root, tsjs_patterns)):
        return TSJS_ADAPTER
    return GENERIC_ADAPTER


def detect_project_profile_name(project_root: pathlib.Path, config: dict, adapter_name: str | None = None) -> str:
    active_adapter = adapter_name or detect_language_adapter(project_root, config)
    profile_name, _, _ = detect_project_profile(project_root, config, active_adapter)
    return profile_name


def adapter_test_command(config: dict, adapter_name: str, project_root: pathlib.Path) -> list[str]:
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    return profile_test_command(profile_name, project_root, config, adapter_name)


def adapter_coverage_adapter(config: dict, adapter_name: str, project_root: pathlib.Path) -> str:
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    return profile_coverage_adapter(profile_name, config, adapter_name)


def collect_adapter_graph(project_root: pathlib.Path, config: dict, adapter_name: str) -> AdapterGraph:
    return parse_with_backend(adapter_name, project_root, config)
