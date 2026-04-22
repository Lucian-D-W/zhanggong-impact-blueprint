#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone

from profiles import detect_python_test_start_dir, package_dependencies, package_json_data, package_manager, profile_test_command
from runtime_support import append_jsonl, read_jsonl, runtime_paths


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_explicit_command(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return len(value) > 0 and all(isinstance(item, str) and item.strip() for item in value)
    return False


def normalize_command(command: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if command is None:
        return []
    if isinstance(command, (list, tuple)):
        return [str(item).strip() for item in command if isinstance(item, str) and item.strip()]
    text = str(command).strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return [text]


def command_to_string(command: list[str] | str | None) -> str:
    normalized = normalize_command(command)
    if not normalized:
        return ""
    return " ".join(normalized)


def normalize_package_manager_command(manager: str | None, script_name: str) -> list[str]:
    resolved = manager or "npm"
    if resolved == "bun":
        return ["bun", "run", script_name]
    if resolved == "pnpm":
        return ["pnpm", "run", script_name]
    if resolved == "yarn":
        return ["yarn", script_name]
    return ["npm", "run", script_name]


def is_windows_platform(value: str | None = None) -> bool:
    raw = (value or sys.platform or os.name or "").lower().strip()
    if raw in {"nt", "win32", "windows", "cygwin", "msys"}:
        return True
    if raw.startswith("win"):
        return True
    return False


def adapter_default_command(adapter_name: str, project_root: pathlib.Path | None = None) -> list[str]:
    if adapter_name == "python":
        start_dir = detect_python_test_start_dir(project_root) if project_root else None
        return ["python", "-m", "unittest", "discover", "-s", start_dir or "tests", "-p", "test_*.py"]
    if adapter_name == "tsjs":
        return ["node", "--test"]
    return []


def repo_config_candidates(config: dict, adapter_name: str) -> list[dict]:
    candidates: list[dict] = []
    adapter_value = (config.get(adapter_name) or {}).get("test_command")
    root_value = config.get("test_command")
    verification_value = (config.get("verification") or {}).get("test_command")
    sources = [
        (f"{adapter_name}.test_command", adapter_value),
        ("test_command", root_value),
        ("verification.test_command", verification_value),
    ]
    for source_name, raw_value in sources:
        if not is_explicit_command(raw_value):
            continue
        command = normalize_command(raw_value)
        candidates.append(
            {
                "command": command,
                "source": f"repo_config:{source_name}",
                "reason": f"repo-local config explicitly sets {source_name}",
            }
        )
    return candidates


def recent_successful_command_candidate(workspace_root: pathlib.Path) -> dict | None:
    history_path = runtime_paths(workspace_root)["test_command_history"]
    for row in reversed(read_jsonl(history_path)):
        if row.get("status") != "passed":
            continue
        command = normalize_command(row.get("command_argv") or row.get("command"))
        if command:
            return {
                "command": command,
                "source": "recent_success",
                "reason": "reusing the most recent successful test command",
            }
    return None


def package_json_script_candidates(project_root: pathlib.Path) -> list[dict]:
    package_data = package_json_data(project_root)
    scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
    if not scripts:
        return []
    manager = package_manager(project_root, package_data)
    deps = package_dependencies(package_data)
    ordered_names = ["test:blueprint", "test:run", "test:unit", "test:node-cli", "test"]
    candidates: list[dict] = []
    for script_name in ordered_names:
        if script_name not in scripts:
            continue
        candidates.append(
            {
                "command": normalize_package_manager_command(manager, script_name),
                "source": f"package_json_script:{script_name}",
                "reason": f"package.json provides {script_name}",
            }
        )
    if "test" in scripts and "vitest" in deps:
        candidates.append(
            {
                "command": normalize_package_manager_command(manager, "test"),
                "source": "package_json_script:test",
                "reason": "vitest dependency with test script",
            }
        )
    if "test" in scripts and "jest" in deps:
        candidates.append(
            {
                "command": normalize_package_manager_command(manager, "test"),
                "source": "package_json_script:test",
                "reason": "jest dependency with test script",
            }
        )
    return candidates


def profile_default_candidate(profile_name: str, project_root: pathlib.Path, config: dict, adapter_name: str) -> dict | None:
    command = normalize_command(profile_test_command(profile_name, project_root, config, adapter_name))
    if not command:
        return None
    return {
        "command": command,
        "source": f"profile_default:{profile_name}",
        "reason": f"profile {profile_name} fallback",
    }


def adapter_default_candidate(project_root: pathlib.Path, config: dict, adapter_name: str) -> dict | None:
    command = adapter_default_command(adapter_name, project_root)
    if not command:
        return None
    return {
        "command": command,
        "source": "adapter_default",
        "reason": f"{adapter_name} adapter default",
    }


def rank_candidates(raw_candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered: list[dict] = []
    ignored: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for index, item in enumerate(raw_candidates, start=1):
        command = normalize_command(item.get("command"))
        if not command:
            continue
        key = tuple(command)
        payload = {
            "command": command,
            "command_string": command_to_string(command),
            "source": item.get("source", "unknown"),
            "rank": index,
            "reason": item.get("reason", ""),
        }
        if key in seen:
            ignored.append(
                {
                    "command": payload["command"],
                    "command_string": payload["command_string"],
                    "reason": f"duplicate of higher priority {payload['source']}",
                }
            )
            continue
        seen.add(key)
        ordered.append(payload)
    if ordered:
        selected = ordered[0]
        for candidate in ordered[1:]:
            ignored.append(
                {
                    "command": candidate["command"],
                    "command_string": candidate["command_string"],
                    "reason": f"lower priority than {selected['source']}",
                }
            )
    return ordered, ignored


def resolve_test_command(
    *,
    workspace_root: pathlib.Path,
    project_root: pathlib.Path,
    config: dict,
    adapter_name: str,
    profile_name: str,
    cli_test_command: list[str] | str | None = None,
) -> dict:
    raw_candidates: list[dict] = []
    cli_command = normalize_command(cli_test_command)
    if cli_command:
        raw_candidates.append(
            {
                "command": cli_command,
                "source": "cli_explicit",
                "reason": "explicit --test-command argument",
            }
        )
    raw_candidates.extend(repo_config_candidates(config, adapter_name))
    recent = recent_successful_command_candidate(workspace_root)
    if recent:
        raw_candidates.append(recent)
    raw_candidates.extend(package_json_script_candidates(project_root))
    profile_candidate = profile_default_candidate(profile_name, project_root, config, adapter_name)
    if profile_candidate:
        raw_candidates.append(profile_candidate)
    adapter_candidate = adapter_default_candidate(project_root, config, adapter_name)
    if adapter_candidate:
        raw_candidates.append(adapter_candidate)

    ordered, ignored = rank_candidates(raw_candidates)
    selected = ordered[0] if ordered else {"command": [], "command_string": "", "source": "none", "rank": None}
    return {
        "selected_test_command": selected["command_string"],
        "selected_test_command_argv": selected.get("command", []),
        "test_command_source": selected.get("source"),
        "test_command_candidates": ordered,
        "ignored_test_commands": ignored,
        "package_manager": package_manager(project_root, package_json_data(project_root)),
    }


def package_script_exists(project_root: pathlib.Path, command: list[str]) -> tuple[bool, str | None]:
    package_data = package_json_data(project_root)
    scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
    if len(command) < 2:
        return True, None
    executable = pathlib.Path(command[0]).name.lower()
    if executable in {"npm", "npm.cmd", "pnpm", "pnpm.cmd", "bun", "bun.exe"} and len(command) >= 3 and command[1] == "run":
        script_name = command[2]
    elif executable == "yarn" and len(command) >= 2:
        script_name = command[1]
    else:
        return True, None
    return script_name in scripts, script_name


def package_script_alternatives(project_root: pathlib.Path) -> list[str]:
    return [command_to_string(item.get("command")) for item in package_json_script_candidates(project_root)]


def preflight_test_command(command: list[str] | str | None, project_root: pathlib.Path, platform: str | None = None) -> dict:
    normalized = normalize_command(command)
    issues: list[dict] = []
    recovery_commands: list[str] = []
    active_platform = platform or sys.platform or os.name
    on_windows = is_windows_platform(active_platform)
    if not normalized:
        issues.append(
            {
                "kind": "missing_test_command",
                "message": "No executable test command was selected.",
                "suggested_fix": "Configure a repo-local test command or pass --test-command explicitly.",
                "severity": "fail",
            }
        )
    else:
        entry = normalized[0]
        script_candidate = project_root / entry
        if on_windows and entry.lower().endswith(".sh"):
            issues.append(
                {
                    "kind": "shell_script_on_windows",
                    "message": f"{entry} is a shell script and may not run directly on Windows.",
                    "suggested_fix": "Use npm run test:blueprint or a cross-platform node script.",
                    "severity": "fail",
                }
            )
            recovery_commands.extend(package_script_alternatives(project_root))
        if entry.lower().endswith(".sh") and script_candidate.exists():
            script_bytes = script_candidate.read_bytes()
            script_text = script_bytes.decode("utf-8", errors="replace")
            if b"\r\n" in script_bytes:
                issues.append(
                    {
                        "kind": "crlf_shell_script",
                        "message": f"{entry} contains CRLF line endings.",
                        "suggested_fix": "Convert the script to LF or replace it with a cross-platform package script.",
                        "severity": "fail" if on_windows else "warn",
                    }
                )
            if not script_text.startswith("#!"):
                issues.append(
                    {
                        "kind": "missing_shebang",
                        "message": f"{entry} does not start with a shebang.",
                        "suggested_fix": "Add a shebang or wrap the command in a package script.",
                        "severity": "warn",
                    }
                )
            if shutil.which("bash") is None and shutil.which("sh") is None:
                issues.append(
                    {
                        "kind": "missing_shell_runtime",
                        "message": "bash/sh is not available for the selected shell script.",
                        "suggested_fix": "Install bash or use a package.json script that runs cross-platform.",
                        "severity": "fail",
                    }
                )
        executable_name = pathlib.Path(entry).name.lower()
        if executable_name in {"npm", "npm.cmd"} and shutil.which("npm.cmd") is None and shutil.which("npm") is None:
            issues.append(
                {
                    "kind": "missing_npm",
                    "message": "npm is not available.",
                    "suggested_fix": "Install Node.js/npm or choose another executable test command.",
                    "severity": "fail",
                }
            )
        if executable_name in {"pnpm", "pnpm.cmd"} and shutil.which("pnpm.cmd") is None and shutil.which("pnpm") is None:
            issues.append(
                {
                    "kind": "missing_pnpm",
                    "message": "pnpm is not available.",
                    "suggested_fix": "Install pnpm or pick an npm/yarn/bun script.",
                    "severity": "fail",
                }
            )
        if executable_name in {"bun", "bun.exe"} and shutil.which("bun") is None:
            issues.append(
                {
                    "kind": "missing_bun",
                    "message": "bun is not available.",
                    "suggested_fix": "Install bun or select an npm/pnpm/yarn test script.",
                    "severity": "fail",
                }
            )
        script_exists, script_name = package_script_exists(project_root, normalized)
        if script_name and not script_exists:
            issues.append(
                {
                    "kind": "package_script_missing",
                    "message": f"package.json does not define {script_name}.",
                    "suggested_fix": "Choose an existing package.json script or update the repo-local config.",
                    "severity": "fail",
                }
            )
        if script_name:
            recovery_commands.extend(package_script_alternatives(project_root))

    has_fail = any(item.get("severity") == "fail" for item in issues)
    has_warn = any(item.get("severity") == "warn" for item in issues)
    status = "fail" if has_fail else "warn" if has_warn else "pass"
    deduped_recovery: list[str] = []
    seen: set[str] = set()
    for item in recovery_commands:
        if not item or item in seen or item == command_to_string(normalized):
            continue
        seen.add(item)
        deduped_recovery.append(item)
    return {
        "status": status,
        "issues": [
            {key: value for key, value in item.items() if key != "severity"}
            for item in issues
        ],
        "recovery_commands": deduped_recovery,
    }


TEMP_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:\\Users\\[^\\]+\\AppData\\Local\\Temp\\[^\s\"']+"),
    re.compile(r"(?i)/tmp/[^\s\"']+"),
    re.compile(r"(?i)/mnt/data/[^\s\"']+"),
)
TIMESTAMP_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-Z]+\b")
DURATION_PATTERNS = (
    re.compile(r"Ran (\d+) tests? in \d+(?:\.\d+)?s"),
    re.compile(r"duration \d+(?:\.\d+)?ms", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?ms\b"),
)
LINE_NUMBER_PATTERNS = (
    re.compile(r"(\.py|\.pyi|\.js|\.jsx|\.ts|\.tsx):\d+"),
    re.compile(r"line \d+"),
)
TMP_NAME_PATTERN = re.compile(r"\btmp[a-z0-9_-]{4,}\b", re.IGNORECASE)
HASH_SUFFIX_PATTERN = re.compile(r"\b[a-f0-9]{8,}\b", re.IGNORECASE)


def normalize_failure_output(output: str) -> str:
    normalized = output or ""
    for pattern in TEMP_PATH_PATTERNS:
        normalized = pattern.sub("<tmp>", normalized)
    normalized = TIMESTAMP_PATTERN.sub("<timestamp>", normalized)
    normalized = TMP_NAME_PATTERN.sub("tmp<id>", normalized)
    normalized = HASH_SUFFIX_PATTERN.sub("<id>", normalized)
    for pattern in DURATION_PATTERNS:
        if pattern.pattern.startswith("Ran "):
            normalized = pattern.sub(r"Ran \1 tests in <duration>", normalized)
        else:
            normalized = pattern.sub("<duration>", normalized)
    for pattern in LINE_NUMBER_PATTERNS:
        if pattern.pattern.startswith("("):
            normalized = pattern.sub(r"\1:<line>", normalized)
        else:
            normalized = pattern.sub("line <line>", normalized)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    return "\n".join(lines)


def _exception_lines(normalized_output: str) -> list[str]:
    lines: list[str] = []
    for line in normalized_output.splitlines():
        if re.search(r"(AssertionError|[A-Za-z]+Error|[A-Za-z]+Exception|FAIL:|ERROR:)", line):
            lines.append(line)
    return lines[:6]


def _project_frames(normalized_output: str) -> list[str]:
    frames: list[str] = []
    for line in normalized_output.splitlines():
        match = re.search(r'File "([^"]+)", line <line>(?:, in ([^ ]+))?', line)
        if not match:
            continue
        path = match.group(1).replace("\\", "/")
        symbol = match.group(2) or "<module>"
        frames.append(f"{path}:{symbol}")
    return frames[:4]


def compute_failure_signature(
    *,
    command: list[str],
    exit_code: int | None,
    output_text: str,
    failed_tests: list[str] | None = None,
    error_code: str | None = None,
) -> str | None:
    failed_tests = sorted(set(item for item in (failed_tests or []) if item))
    normalized_output = normalize_failure_output(output_text)
    if exit_code in (None, 0) and not normalized_output and not failed_tests:
        return None
    exception_lines = _exception_lines(normalized_output)
    excerpt_lines = normalized_output.splitlines()[:12]
    payload = {
        "error_code": error_code or ("test_failure" if failed_tests else f"exit_{exit_code if exit_code is not None else 'unknown'}"),
        "failed_tests": failed_tests,
        "exceptions": exception_lines,
        "project_frames": _project_frames(normalized_output),
        "excerpt": excerpt_lines,
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def failure_signature_from_output(command: list[str], exit_code: int | None, output_text: str, failed_tests: list[str] | None = None) -> str | None:
    return compute_failure_signature(
        command=command,
        exit_code=exit_code,
        output_text=output_text,
        failed_tests=failed_tests,
    )


def baseline_regression_status(*, baseline: dict | None, current: dict) -> dict:
    baseline = baseline or {}
    baseline_status = baseline.get("status", "unknown")
    current_status = current.get("status", "unknown")
    baseline_signature = baseline.get("failure_signature")
    current_signature = current.get("failure_signature")
    full_suite = bool(current.get("full_suite"))
    if baseline_status == "failed" and current_status == "failed":
        regression_status = "no_regression" if baseline_signature == current_signature else "new_failure"
    elif baseline_status == "failed" and current_status == "passed":
        regression_status = "improved" if full_suite else "no_regression"
    elif baseline_status == "passed" and current_status == "failed":
        regression_status = "new_failure"
    else:
        regression_status = "unknown" if current_status == "failed" else "no_regression"
    return {
        "baseline_status": baseline_status,
        "current_status": current_status,
        "regression_status": regression_status,
        "baseline_failure_signature": baseline_signature,
        "current_failure_signature": current_signature,
    }


def capture_baseline_payload(*, command: list[str], summary: dict, source: str) -> dict:
    return {
        "captured_at": utc_now(),
        "command": command_to_string(command),
        "status": summary.get("status", "unknown"),
        "failed_tests": list(summary.get("failed_tests") or []),
        "failure_signature": summary.get("failure_signature"),
        "stdout_excerpt": "\n".join((summary.get("output_excerpt_lines") or [])[:8]),
        "source": source,
    }


def record_test_command_history(
    *,
    workspace_root: pathlib.Path,
    command: list[str],
    source: str,
    status: str,
    adapter_name: str,
    profile_name: str | None,
) -> None:
    append_jsonl(
        runtime_paths(workspace_root)["test_command_history"],
        {
            "timestamp": utc_now(),
            "command": command_to_string(command),
            "command_argv": list(command),
            "source": source,
            "status": status,
            "adapter": adapter_name,
            "profile": profile_name,
        },
    )
