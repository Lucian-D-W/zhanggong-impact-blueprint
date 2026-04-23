from __future__ import annotations

import pathlib

from .base import GraphProvider


class InternalGraphProvider(GraphProvider):
    name = "internal"

    def _enabled(self, config: dict) -> bool:
        providers = config.get("providers") or {}
        internal = providers.get("internal") or {}
        return bool(internal.get("enabled", True))

    def detect(self, workspace_root: pathlib.Path, config: dict) -> dict:
        enabled = self._enabled(config)
        return {
            "provider": self.name,
            "available": enabled,
            "ready": enabled,
            "provider_status": "ready" if enabled else "failed",
            "provider_reason": "zhanggong internal graph provider is available." if enabled else "internal provider is disabled in config.",
            "provider_index_status": "internal_graph" if enabled else "disabled",
            "provider_install_hint": None,
            "provider_effective": self.name if enabled else None,
        }

    def ensure_ready(self, workspace_root: pathlib.Path, config: dict) -> dict:
        return self.detect(workspace_root, config)

    def analyze_change(self, workspace_root: pathlib.Path, config: dict, seed_context: dict) -> dict:
        target = seed_context.get("symbol") or seed_context.get("path") or seed_context.get("seed") or "current seed"
        return {
            "provider_evidence_summary": [f"Using zhanggong internal graph for `{target}`."],
            "provider_overlay": {
                "source": self.name,
                "affected_contracts": [],
                "architecture_chains": [],
                "atlas_views": [],
                "must_read_first": [],
                "uncertainty": [],
                "provider_evidence": [],
                "external_side_effects": [],
                "raw": {},
            },
        }

    def impact(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        return {
            "status": "unavailable",
            "reason": "internal provider impact is supplied by the existing zhanggong report pipeline.",
        }

    def context(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        return {
            "status": "unavailable",
            "reason": "internal provider context is supplied by the existing zhanggong report pipeline.",
        }

    def health(self, workspace_root: pathlib.Path, config: dict) -> dict:
        return self.detect(workspace_root, config)
