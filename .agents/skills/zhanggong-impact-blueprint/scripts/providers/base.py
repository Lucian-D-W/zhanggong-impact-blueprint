from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod


class GraphProvider(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self, workspace_root: pathlib.Path, config: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def ensure_ready(self, workspace_root: pathlib.Path, config: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def analyze_change(self, workspace_root: pathlib.Path, config: dict, seed_context: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def impact(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def context(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def health(self, workspace_root: pathlib.Path, config: dict) -> dict:
        raise NotImplementedError
