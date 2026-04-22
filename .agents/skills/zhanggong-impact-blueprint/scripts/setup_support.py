#!/usr/bin/env python3
import json
import pathlib


SETUP_MANAGED_START = "# >>> zhanggong-impact-blueprint >>>"
SETUP_MANAGED_END = "# <<< zhanggong-impact-blueprint <<<"


def normalize_setup_mode(*, minimal: bool = False, full: bool = False) -> str:
    if full:
        return "full"
    return "minimal"


def managed_gitignore_entries() -> list[str]:
    return [
        ".ai/",
        "__pycache__/",
        "*.pyc",
        ".coverage",
        "coverage-*.json",
        "coverage-*.data",
    ]


def managed_gitignore_block() -> str:
    return "\n".join([SETUP_MANAGED_START, *managed_gitignore_entries(), SETUP_MANAGED_END]) + "\n"


def upsert_managed_block(path: pathlib.Path, block: str) -> tuple[str, bool]:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        start = existing.find(SETUP_MANAGED_START)
        end = existing.find(SETUP_MANAGED_END)
        if start != -1 and end != -1 and end >= start:
            end += len(SETUP_MANAGED_END)
            updated = existing[:start].rstrip() + "\n" + block + existing[end:].lstrip("\n")
            path.write_text(updated, encoding="utf-8")
            return "updated", True
        path.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")
        return "updated", True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(block, encoding="utf-8")
    return "created", True


def write_json_if_missing(path: pathlib.Path, payload: dict) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def write_text_if_missing(path: pathlib.Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
