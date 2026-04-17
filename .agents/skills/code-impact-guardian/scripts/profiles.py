#!/usr/bin/env python3
import json
import pathlib


AUTO_PROFILE = "auto"
PYTHON_PROFILE = "python-basic"
GENERIC_PROFILE = "generic-file"


PROFILE_PRESETS = {
    PYTHON_PROFILE: {
        "language_adapter": "python",
        "doctor_checks": ["python_runtime", "git", "local_rules"],
    },
    GENERIC_PROFILE: {
        "language_adapter": "generic",
        "doctor_checks": ["git", "local_rules"],
    },
    "node-cli": {
        "language_adapter": "tsjs",
        "tsjs": {
            "source_globs": [
                "src/*.js",
                "src/**/*.js",
                "src/*.ts",
                "src/**/*.ts",
                "src/*.jsx",
                "src/**/*.jsx",
                "src/*.tsx",
                "src/**/*.tsx",
            ],
            "test_globs": [
                "tests/*.js",
                "tests/**/*.js",
                "tests/*.ts",
                "tests/**/*.ts",
                "tests/*.jsx",
                "tests/**/*.jsx",
                "tests/*.tsx",
                "tests/**/*.tsx",
            ],
            "test_command": ["node", "--test"],
            "coverage_adapter": "v8_family",
        },
        "rules": {"globs": ["docs/rules/*.md"]},
        "doctor_checks": ["node_runtime", "package_json", "profile_test_command", "local_rules"],
    },
    "react-vite": {
        "language_adapter": "tsjs",
        "tsjs": {
            "source_globs": [
                "src/*.js",
                "src/**/*.js",
                "src/*.ts",
                "src/**/*.ts",
                "src/*.jsx",
                "src/**/*.jsx",
                "src/*.tsx",
                "src/**/*.tsx",
            ],
            "test_globs": [
                "tests/*.js",
                "tests/**/*.js",
                "tests/*.ts",
                "tests/**/*.ts",
                "tests/*.jsx",
                "tests/**/*.jsx",
                "tests/*.tsx",
                "tests/**/*.tsx",
            ],
            "test_command": ["node", "--test"],
            "coverage_adapter": "v8_family",
        },
        "rules": {"globs": ["docs/rules/*.md"]},
        "doctor_checks": ["node_runtime", "package_json", "react_vite_markers", "profile_test_command", "local_rules"],
    },
    "next-basic": {
        "language_adapter": "tsjs",
        "doctor_checks": ["node_runtime", "package_json", "next_markers", "local_rules"],
    },
    "electron-renderer": {
        "language_adapter": "tsjs",
        "doctor_checks": ["node_runtime", "package_json", "electron_markers", "local_rules"],
    },
    "obsidian-plugin": {
        "language_adapter": "tsjs",
        "doctor_checks": ["node_runtime", "package_json", "obsidian_markers", "local_rules"],
    },
    "tauri-frontend": {
        "language_adapter": "tsjs",
        "doctor_checks": ["node_runtime", "package_json", "tauri_markers", "local_rules"],
    },
}


def configured_profile_name(config: dict) -> str:
    return config.get("project_profile", AUTO_PROFILE)


def merge_dicts(base: dict, updates: dict) -> dict:
    merged = json.loads(json.dumps(base))
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = json.loads(json.dumps(value))
    return merged


def apply_profile_preset(config: dict, profile_name: str) -> dict:
    preset = PROFILE_PRESETS.get(profile_name)
    if not preset:
        return config
    merged = merge_dicts(config, {key: value for key, value in preset.items() if key != "doctor_checks"})
    merged["project_profile"] = profile_name
    return merged


def package_json_data(project_root: pathlib.Path) -> dict:
    package_json = project_root / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def package_dependencies(package_data: dict) -> set[str]:
    deps = set(package_data.get("dependencies", {}).keys())
    deps.update(package_data.get("devDependencies", {}).keys())
    deps.update(package_data.get("peerDependencies", {}).keys())
    return deps


def has_any_file(project_root: pathlib.Path, patterns: list[str]) -> bool:
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        pure = pathlib.PurePosixPath(path.relative_to(project_root).as_posix())
        if any(pure.match(pattern) for pattern in patterns):
            return True
    return False


def detect_project_profile(project_root: pathlib.Path, config: dict, adapter_name: str) -> tuple[str, float, str]:
    configured = configured_profile_name(config)
    if configured != AUTO_PROFILE:
        return configured, 1.0, "configured"

    if adapter_name == "python":
        return PYTHON_PROFILE, 1.0, "python-files"
    if adapter_name == "generic":
        return GENERIC_PROFILE, 1.0, "generic-fallback"

    package_data = package_json_data(project_root)
    deps = package_dependencies(package_data)
    if (project_root / "src-tauri").exists():
        return "tauri-frontend", 0.95, "src-tauri"
    if (project_root / "manifest.json").exists() or "obsidian" in deps:
        return "obsidian-plugin", 0.9, "obsidian markers"
    if "electron" in deps:
        return "electron-renderer", 0.9, "electron dependency"
    if "next" in deps or any((project_root / name).exists() for name in ("next.config.js", "next.config.mjs", "next.config.ts")):
        return "next-basic", 0.95, "next markers"
    if ("react" in deps and "vite" in deps) or (
        has_any_file(project_root, ["src/**/*.jsx", "src/**/*.tsx", "src/*.jsx", "src/*.tsx"])
        and any((project_root / name).exists() for name in ("vite.config.js", "vite.config.mjs", "vite.config.ts"))
    ):
        return "react-vite", 0.88, "react + vite markers"
    return "node-cli", 0.7, "tsjs default"


def profile_test_command(profile_name: str, project_root: pathlib.Path, config: dict, adapter_name: str) -> list[str]:
    if adapter_name != "tsjs":
        return list(config.get(adapter_name, {}).get("test_command", []))

    package_data = package_json_data(project_root)
    scripts = package_data.get("scripts", {})
    if profile_name == "node-cli":
        if "test:node-cli" in scripts:
            return ["npm", "run", "test:node-cli"]
        return ["node", "--test"]
    if profile_name == "react-vite":
        if "test:react-vite" in scripts:
            return ["npm", "run", "test:react-vite"]
        if "test" in scripts:
            return ["npm", "run", "test"]
        return ["node", "--test"]
    if profile_name == "next-basic" and "test:next" in scripts:
        return ["npm", "run", "test:next"]
    if profile_name == "electron-renderer" and "test:electron" in scripts:
        return ["npm", "run", "test:electron"]
    if profile_name == "obsidian-plugin" and "test:obsidian" in scripts:
        return ["npm", "run", "test:obsidian"]
    if profile_name == "tauri-frontend" and "test:tauri" in scripts:
        return ["npm", "run", "test:tauri"]
    return list(config.get("tsjs", {}).get("test_command", []))


def profile_coverage_adapter(profile_name: str, config: dict, adapter_name: str) -> str:
    if adapter_name != "tsjs":
        return config.get(adapter_name, {}).get("coverage_adapter", "unavailable")
    if profile_name in {"node-cli", "react-vite"}:
        return "v8_family"
    return config.get("tsjs", {}).get("coverage_adapter", "unavailable")


def profile_doctor_checks(profile_name: str) -> list[str]:
    preset = PROFILE_PRESETS.get(profile_name, {})
    return list(preset.get("doctor_checks", []))

