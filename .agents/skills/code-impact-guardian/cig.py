#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys


SKILL_DIR = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import after_edit_update  # noqa: E402
import build_graph  # noqa: E402
import generate_report  # noqa: E402
import list_seeds  # noqa: E402
from adapters import detect_language_adapter  # noqa: E402


def template_root() -> pathlib.Path:
    return SKILL_DIR.parents[2]


def copy_template(source_root: pathlib.Path, destination_root: pathlib.Path) -> None:
    ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")
    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(source_root, destination_root, ignore=ignore)


def init_git_repo(workspace_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Code Impact Guardian Demo"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "user.email", "demo@example.invalid"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=workspace_root, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initialize demo workspace"], cwd=workspace_root, check=True, capture_output=True, text=True)


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def config_path_for(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".code-impact-guardian" / "config.json"


def set_fixture_config(workspace_root: pathlib.Path, fixture: str, persist: bool) -> pathlib.Path:
    config_path = config_path_for(workspace_root)
    payload = load_json(config_path)
    payload["project_root"] = f"examples/{fixture}"
    payload["language_adapter"] = "auto"
    if persist:
        write_json(config_path, payload)
        return config_path
    temp_config_path = workspace_root / ".ai" / "codegraph" / f"demo-{fixture}-config.json"
    temp_config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(temp_config_path, payload)
    return temp_config_path


def apply_python_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "python_minimal" / "src" / "app.py"
    original = target.read_text(encoding="utf-8")
    if 'DEMO_RELEASE_TRACK = "baseline"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "baseline"', 'DEMO_RELEASE_TRACK = "edited-by-demo"')
    elif 'DEMO_RELEASE_TRACK = "edited-by-demo"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "edited-by-demo"', 'DEMO_RELEASE_TRACK = "baseline"')
    else:
        raise RuntimeError("Demo edit marker not found in python fixture")
    if updated == original:
        raise RuntimeError("Python demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/app.py"


def apply_tsjs_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "tsjs_minimal" / "src" / "math.js"
    original = target.read_text(encoding="utf-8")
    if 'const DEMO_TSJS_TRACK = "baseline";' in original:
        updated = original.replace('const DEMO_TSJS_TRACK = "baseline";', 'const DEMO_TSJS_TRACK = "edited-by-demo";')
    elif 'const DEMO_TSJS_TRACK = "edited-by-demo";' in original:
        updated = original.replace('const DEMO_TSJS_TRACK = "edited-by-demo";', 'const DEMO_TSJS_TRACK = "baseline";')
    else:
        raise RuntimeError("Demo edit marker not found in tsjs fixture")
    if updated == original:
        raise RuntimeError("TS/JS demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/math.js"


def apply_generic_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "generic_minimal" / "src" / "settings.conf"
    original = target.read_text(encoding="utf-8")
    if "release_track=baseline" in original:
        updated = original.replace("release_track=baseline", "release_track=edited-by-demo")
    elif "release_track=edited-by-demo" in original:
        updated = original.replace("release_track=edited-by-demo", "release_track=baseline")
    else:
        raise RuntimeError("Demo edit marker not found in generic fixture")
    if updated == original:
        raise RuntimeError("Generic demo edit did not change the file")
    target.write_text(updated, encoding="utf-8")
    return "src/settings.conf"


def fixture_spec(fixture: str) -> dict:
    specs = {
        "python_minimal": {
            "task_id": "demo-login-impact",
            "seed": "fn:src/app.py:login",
            "edit": apply_python_demo_edit,
        },
        "tsjs_minimal": {
            "task_id": "demo-tsjs-impact",
            "seed": "fn:src/math.js:add",
            "edit": apply_tsjs_demo_edit,
        },
        "generic_minimal": {
            "task_id": "demo-generic-impact",
            "seed": "file:src/settings.conf",
            "edit": apply_generic_demo_edit,
        },
    }
    if fixture not in specs:
        raise SystemExit(f"Unsupported fixture: {fixture}")
    return specs[fixture]


def detect_payload(workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    config = build_graph.load_config(config_path)
    project_root = build_graph.project_root_for(workspace_root, config)
    return {
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "configured_adapter": config.get("language_adapter", "auto"),
        "detected_adapter": detect_language_adapter(project_root, config),
    }


def run_demo(fixture: str, workspace: str | None) -> pathlib.Path:
    source_root = template_root()
    workspace_root = pathlib.Path(workspace).resolve() if workspace else source_root
    if workspace:
        copy_template(source_root, workspace_root)
        init_git_repo(workspace_root)
    config_path = set_fixture_config(workspace_root, fixture, persist=bool(workspace))
    spec = fixture_spec(fixture)
    build_graph.build_graph(workspace_root=workspace_root, config_path=config_path)
    generate_report.generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=spec["task_id"],
        seed=spec["seed"],
    )
    changed_file = spec["edit"](workspace_root)
    after_edit_update.after_edit_update(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=spec["task_id"],
        seed=spec["seed"],
        changed_files=[changed_file],
    )
    return workspace_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Code Impact Guardian entry point")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect the active adapter")
    detect_parser.add_argument("--workspace-root", default=".")
    detect_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    build_parser = subparsers.add_parser("build", help="Build or refresh the graph")
    build_parser.add_argument("--workspace-root", default=".")
    build_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    seeds_parser = subparsers.add_parser("seeds", help="List current seeds")
    seeds_parser.add_argument("--workspace-root", default=".")
    seeds_parser.add_argument("--config", default=".code-impact-guardian/config.json")

    report_parser = subparsers.add_parser("report", help="Generate an impact report")
    report_parser.add_argument("--workspace-root", default=".")
    report_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    report_parser.add_argument("--task-id", required=True)
    report_parser.add_argument("--seed", required=True)
    report_parser.add_argument("--max-depth", type=int, default=None)

    after_parser = subparsers.add_parser("after-edit", help="Refresh graph, report, evidence, and tests after an edit")
    after_parser.add_argument("--workspace-root", default=".")
    after_parser.add_argument("--config", default=".code-impact-guardian/config.json")
    after_parser.add_argument("--task-id", required=True)
    after_parser.add_argument("--seed", required=True)
    after_parser.add_argument("--changed-file", action="append", default=[])

    demo_parser = subparsers.add_parser("demo", help="Run a fixture end-to-end demo")
    demo_parser.add_argument("--fixture", choices=["python_minimal", "tsjs_minimal", "generic_minimal"], default="python_minimal")
    demo_parser.add_argument("--workspace", default=None)

    args = parser.parse_args()

    if args.command == "demo":
        workspace_root = run_demo(args.fixture, args.workspace)
        print(workspace_root)
        return 0

    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()

    if args.command == "detect":
        print(json.dumps(detect_payload(workspace_root, config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "build":
        print(json.dumps(build_graph.build_graph(workspace_root=workspace_root, config_path=config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "seeds":
        print(json.dumps(list_seeds.list_seeds(workspace_root=workspace_root, config_path=config_path), ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        print(
            json.dumps(
                generate_report.generate_report(
                    workspace_root=workspace_root,
                    config_path=config_path,
                    task_id=args.task_id,
                    seed=args.seed,
                    max_depth=args.max_depth,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "after-edit":
        print(
            json.dumps(
                after_edit_update.after_edit_update(
                    workspace_root=workspace_root,
                    config_path=config_path,
                    task_id=args.task_id,
                    seed=args.seed,
                    changed_files=args.changed_file,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
