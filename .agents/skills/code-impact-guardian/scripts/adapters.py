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
SQL_POSTGRES_ADAPTER = "sql_postgres"
AUTO_ADAPTER = "auto"


def rule_node_id(rule_id: str) -> str:
    return f"rule:{rule_id}"


def configured_primary_adapter_name(config: dict) -> str:
    return config.get("primary_adapter", config.get("language_adapter", AUTO_ADAPTER))


def configured_adapter_name(config: dict) -> str:
    return configured_primary_adapter_name(config)


def configured_supplemental_adapters(config: dict) -> list[str]:
    adapters = list(config.get("supplemental_adapters", []))
    if config.get("sql_postgres", {}).get("enabled") and SQL_POSTGRES_ADAPTER not in adapters:
        adapters.append(SQL_POSTGRES_ADAPTER)
    return adapters


def detect_primary_adapter(project_root: pathlib.Path, config: dict) -> str:
    configured = configured_primary_adapter_name(config)
    if configured in {PYTHON_ADAPTER, TSJS_ADAPTER, GENERIC_ADAPTER}:
        return configured

    python_patterns = config.get("python", {}).get("source_globs", []) + config.get("python", {}).get("test_globs", [])
    tsjs_patterns = config.get("tsjs", {}).get("source_globs", []) + config.get("tsjs", {}).get("test_globs", [])

    if any(path.exists() for path in iter_matching_files(project_root, python_patterns)):
        return PYTHON_ADAPTER
    if any(path.exists() for path in iter_matching_files(project_root, tsjs_patterns)):
        return TSJS_ADAPTER
    return GENERIC_ADAPTER


def detect_language_adapter(project_root: pathlib.Path, config: dict) -> str:
    return detect_primary_adapter(project_root, config)


def detect_supplemental_adapters(project_root: pathlib.Path, config: dict) -> list[str]:
    detected: list[str] = []
    for adapter_name in configured_supplemental_adapters(config):
        if adapter_name == SQL_POSTGRES_ADAPTER:
            sql_config = config.get(SQL_POSTGRES_ADAPTER, {})
            source_globs = sql_config.get("source_globs", [])
            test_globs = sql_config.get("test_globs", [])
            if sql_config.get("enabled") and any(path.exists() for path in iter_matching_files(project_root, source_globs + test_globs)):
                detected.append(adapter_name)
    return detected


def detect_project_profile_name(project_root: pathlib.Path, config: dict, adapter_name: str | None = None) -> str:
    active_adapter = adapter_name or detect_primary_adapter(project_root, config)
    profile_name, _, _ = detect_project_profile(project_root, config, active_adapter)
    return profile_name


def adapter_test_command(config: dict, adapter_name: str, project_root: pathlib.Path) -> list[str]:
    supplemental_detected = detect_supplemental_adapters(project_root, config)
    if adapter_name == GENERIC_ADAPTER:
        for supplemental in supplemental_detected:
            supplemental_command = list(config.get(supplemental, {}).get("test_command", []))
            if supplemental_command:
                return supplemental_command
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    command = profile_test_command(profile_name, project_root, config, adapter_name)
    if command:
        return command
    for supplemental in supplemental_detected:
        supplemental_command = list(config.get(supplemental, {}).get("test_command", []))
        if supplemental_command:
            return supplemental_command
    return command


def adapter_coverage_adapter(config: dict, adapter_name: str, project_root: pathlib.Path) -> str:
    supplemental_detected = detect_supplemental_adapters(project_root, config)
    if adapter_name == GENERIC_ADAPTER:
        for supplemental in supplemental_detected:
            supplemental_coverage = config.get(supplemental, {}).get("coverage_adapter", "unavailable")
            if supplemental_coverage:
                return supplemental_coverage
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    coverage_adapter = profile_coverage_adapter(profile_name, config, adapter_name)
    if coverage_adapter != "unavailable":
        return coverage_adapter
    for supplemental in supplemental_detected:
        supplemental_coverage = config.get(supplemental, {}).get("coverage_adapter", "unavailable")
        if supplemental_coverage != "unavailable":
            return supplemental_coverage
    return coverage_adapter


def collect_adapter_graph(project_root: pathlib.Path, config: dict, adapter_name: str, include_files: list[str] | None = None) -> AdapterGraph:
    return parse_with_backend(adapter_name, project_root, config, include_files)
