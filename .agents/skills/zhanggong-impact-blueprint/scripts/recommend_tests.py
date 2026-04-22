#!/usr/bin/env python3
import pathlib


def default_test_directories() -> list[str]:
    return ["tests", "test"]


def detect_test_directories(project_root: pathlib.Path) -> list[str]:
    return [name for name in default_test_directories() if (project_root / name).exists()]
