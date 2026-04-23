#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys


def template_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def copy_template(source_root: pathlib.Path, destination_root: pathlib.Path) -> None:
    base_ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")

    def ignore(current_dir: str, entries: list[str]) -> set[str]:
        ignored = set(base_ignore(current_dir, entries))
        if pathlib.Path(current_dir).name == ".zhanggong-impact-blueprint":
            ignored.add("config.json")
        return {entry for entry in entries if entry in ignored}

    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(source_root, destination_root, ignore=ignore)


def init_git_repo(workspace_root: pathlib.Path) -> None:
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "ZG Impact Blueprint Demo"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "user.email", "demo@example.invalid"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=workspace_root, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initialize demo workspace"], cwd=workspace_root, check=True, capture_output=True, text=True)


def run_python(script_path: pathlib.Path, workspace_root: pathlib.Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script_path), "--workspace-root", str(workspace_root), *args], cwd=workspace_root, check=True, text=True)


def apply_demo_edit(workspace_root: pathlib.Path) -> str:
    target = workspace_root / "examples" / "python_minimal" / "src" / "app.py"
    original = target.read_text(encoding="utf-8")
    if 'DEMO_RELEASE_TRACK = "baseline"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "baseline"', 'DEMO_RELEASE_TRACK = "edited-by-demo"')
    elif 'DEMO_RELEASE_TRACK = "edited-by-demo"' in original:
        updated = original.replace('DEMO_RELEASE_TRACK = "edited-by-demo"', 'DEMO_RELEASE_TRACK = "baseline"')
    else:
        raise RuntimeError("Demo edit marker not found in app.py")
    if updated == original:
        raise RuntimeError("Demo edit did not change app.py")
    target.write_text(updated, encoding="utf-8")
    return "src/app.py"


def execute_demo(workspace_root: pathlib.Path) -> None:
    cig_script = workspace_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
    build_script = workspace_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts" / "build_graph.py"
    report_script = workspace_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts" / "generate_report.py"
    after_script = workspace_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts" / "after_edit_update.py"
    config_path = workspace_root / ".zhanggong-impact-blueprint" / "config.json"

    if workspace_root == template_root():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        payload["project_root"] = "examples/python_minimal"
        payload["primary_adapter"] = "auto"
        payload["language_adapter"] = "auto"
        payload.setdefault("python", {})
        payload["python"]["source_globs"] = ["src/*.py", "src/**/*.py"]
        payload["python"]["test_globs"] = ["tests/*.py", "tests/**/*.py"]
        payload["python"]["test_command"] = ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        payload["python"]["coverage_adapter"] = "coveragepy"
        config_path = workspace_root / ".ai" / "codegraph" / "demo-phase1-config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        subprocess.run(
            [sys.executable, str(cig_script), "init", "--workspace-root", str(workspace_root), "--project-root", "examples/python_minimal"],
            cwd=workspace_root,
            check=True,
            text=True,
        )
    run_python(build_script, workspace_root, "--config", str(config_path))
    run_python(report_script, workspace_root, "--config", str(config_path), "--task-id", "demo-login-impact", "--seed", "fn:src/app.py:login")
    changed_file = apply_demo_edit(workspace_root)
    run_python(after_script, workspace_root, "--config", str(config_path), "--task-id", "demo-login-impact", "--seed", "fn:src/app.py:login", "--changed-file", changed_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Stage 1 end-to-end demo")
    parser.add_argument("--workspace", default=None, help="Optional workspace to copy the template into before running the demo")
    args = parser.parse_args()

    source_root = template_root()
    if args.workspace:
        workspace_root = pathlib.Path(args.workspace).resolve()
        copy_template(source_root, workspace_root)
        init_git_repo(workspace_root)
        execute_demo(workspace_root)
        print(workspace_root)
        return 0

    execute_demo(source_root)
    print(source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

