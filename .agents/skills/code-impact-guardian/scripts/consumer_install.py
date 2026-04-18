#!/usr/bin/env python3
import json
import pathlib
import shutil


SKILL_DIR = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES_DIR = SKILL_DIR / "templates"


def template_text(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def ensure_text_file(path: pathlib.Path, text: str) -> str:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(path)


def ensure_agents_md(workspace_root: pathlib.Path) -> str:
    return ensure_text_file(workspace_root / "AGENTS.md", template_text("AGENTS.template.md"))


def ensure_consumer_docs(workspace_root: pathlib.Path) -> dict[str, str]:
    return {
        "quickstart_path": ensure_text_file(workspace_root / "QUICKSTART.md", template_text("QUICKSTART.md")),
        "troubleshooting_path": ensure_text_file(workspace_root / "TROUBLESHOOTING.md", template_text("TROUBLESHOOTING.md")),
        "consumer_guide_path": ensure_text_file(workspace_root / "CONSUMER_GUIDE.md", template_text("CONSUMER_GUIDE.md")),
    }


def minimal_gitignore_entries() -> list[str]:
    return [
        ".ai/",
        "__pycache__/",
        "*.pyc",
        ".coverage",
        "coverage-*.json",
        "coverage-*.data",
    ]


def ensure_gitignore(workspace_root: pathlib.Path) -> str:
    gitignore_path = workspace_root / ".gitignore"
    existing_lines: list[str] = []
    if gitignore_path.exists():
        existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    to_append = [entry for entry in minimal_gitignore_entries() if entry not in existing_lines]
    if not gitignore_path.exists():
        gitignore_path.write_text("\n".join(minimal_gitignore_entries()) + "\n", encoding="utf-8")
    elif to_append:
        with gitignore_path.open("a", encoding="utf-8") as fh:
            if existing_lines and existing_lines[-1] != "":
                fh.write("\n")
            for entry in to_append:
                fh.write(f"{entry}\n")
    return str(gitignore_path)


def export_single_folder(skill_dir: pathlib.Path, out_dir: pathlib.Path) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(
        skill_dir,
        out_dir / "code-impact-guardian",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return {
        "status": "exported",
        "mode": "single-folder",
        "out_dir": str(out_dir),
        "exported_files": ["code-impact-guardian/"],
    }


def config_template_text(default_payload: dict) -> str:
    return json.dumps(default_payload, ensure_ascii=False, indent=2) + "\n"
