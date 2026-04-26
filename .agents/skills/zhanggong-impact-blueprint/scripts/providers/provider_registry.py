from __future__ import annotations

import json
import pathlib

import build_graph
from db_support import connect_db

from .base import GraphProvider
from .gitnexus_provider import GitNexusProvider
from .internal_provider import InternalGraphProvider


PROVIDERS: dict[str, GraphProvider] = {
    "gitnexus": GitNexusProvider(),
    "internal": InternalGraphProvider(),
}


def _settings(config: dict, provider_name: str) -> dict:
    providers = config.get("providers") or {}
    return dict(providers.get(provider_name) or {})


def configured_provider_name(config: dict) -> str:
    configured = str(config.get("graph_provider") or "gitnexus").strip().lower()
    return configured if configured in PROVIDERS else "internal"


def get_provider(provider_name: str) -> GraphProvider:
    return PROVIDERS.get(provider_name, PROVIDERS["internal"])


def _provider_authority(
    *,
    graph_provider: str,
    effective_provider: str | None,
    provider_fallback: bool,
) -> str:
    if provider_fallback:
        return "fallback"
    if effective_provider and effective_provider == graph_provider:
        return "primary"
    if effective_provider:
        return "delegated"
    return "unavailable"


def _normalize_state(*, graph_provider: str, requested_state: dict, effective_provider: str | None, provider_status: str, provider_reason: str, provider_fallback: bool = False, fallback_provider: str | None = None, provider_fallback_reason: str | None = None) -> dict:
    authority = _provider_authority(
        graph_provider=graph_provider,
        effective_provider=effective_provider,
        provider_fallback=provider_fallback,
    )
    return {
        "graph_provider": graph_provider,
        "provider_status": provider_status,
        "provider_reason": provider_reason,
        "provider_fallback": provider_fallback,
        "provider_fallback_reason": provider_fallback_reason,
        "fallback_provider": fallback_provider,
        "provider_effective": effective_provider,
        "provider_authority": authority,
        "provider_role": "fact_source",
        "workflow_owner": "zhanggong",
        "provider_install_hint": requested_state.get("provider_install_hint"),
        "provider_index_status": requested_state.get("provider_index_status", "unknown"),
        "provider_available": bool(requested_state.get("available", False)),
        "provider_side_effects": list(requested_state.get("external_side_effects") or []),
        "provider_side_effects_suppressed": list(requested_state.get("suppressed_side_effects") or []),
        "provider_git_info_exclude_path": requested_state.get("git_info_exclude_path"),
        "provider_evidence_summary": [],
        "provider_overlay": {
            "source": effective_provider or graph_provider,
            "provider_authority": authority,
            "provider_role": "fact_source",
            "affected_contracts": [],
            "architecture_chains": [],
            "atlas_views": [],
            "must_read_first": [],
            "uncertainty": [],
            "provider_evidence": [],
            "external_side_effects": list(requested_state.get("external_side_effects") or []),
            "suppressed_side_effects": list(requested_state.get("suppressed_side_effects") or []),
            "raw": {},
        },
    }


def resolve_provider(*, workspace_root: pathlib.Path, config: dict, bootstrap: bool) -> tuple[GraphProvider | None, dict]:
    requested_name = configured_provider_name(config)
    requested_provider = get_provider(requested_name)
    requested_state = requested_provider.ensure_ready(workspace_root, config) if bootstrap else requested_provider.health(workspace_root, config)
    if requested_state.get("ready"):
        state = _normalize_state(
            graph_provider=requested_name,
            requested_state=requested_state,
            effective_provider=requested_name,
            provider_status="ready",
            provider_reason=requested_state.get("provider_reason") or f"{requested_name} provider is ready.",
        )
        return requested_provider, state

    if requested_name != "internal" and _settings(config, requested_name).get("fallback_to_internal", True):
        internal_provider = get_provider("internal")
        internal_state = internal_provider.ensure_ready(workspace_root, config) if bootstrap else internal_provider.health(workspace_root, config)
        if internal_state.get("ready"):
            reason = requested_state.get("provider_reason") or f"{requested_name} provider is unavailable."
            state = _normalize_state(
                graph_provider=requested_name,
                requested_state=requested_state,
                effective_provider="internal",
                provider_status="fallback",
                provider_reason=f"{reason} Falling back to zhanggong internal graph.",
                provider_fallback=True,
                fallback_provider="internal",
                provider_fallback_reason=reason,
            )
            state["provider_side_effects"] = list(
                requested_state.get("external_side_effects") or internal_state.get("external_side_effects") or []
            )
            state["provider_side_effects_suppressed"] = list(requested_state.get("suppressed_side_effects") or [])
            state["provider_git_info_exclude_path"] = requested_state.get("git_info_exclude_path")
            return internal_provider, state

    reason = requested_state.get("provider_reason") or f"{requested_name} provider is unavailable."
    state = _normalize_state(
        graph_provider=requested_name,
        requested_state=requested_state,
        effective_provider=None,
        provider_status="failed",
        provider_reason=reason,
    )
    return None, state


def seed_context_from_graph(*, workspace_root: pathlib.Path, config: dict, seed: str | None, changed_files: list[str] | None = None) -> dict:
    payload = {
        "seed": seed,
        "node_id": seed,
        "kind": None,
        "name": None,
        "path": None,
        "symbol": None,
        "changed_files": list(changed_files or []),
    }
    if not seed:
        return payload
    paths = build_graph.graph_paths(workspace_root, config)
    if paths["db_path"].exists():
        with connect_db(paths["db_path"]) as conn:
            row = conn.execute(
                "SELECT node_id, kind, name, path, symbol, attrs_json FROM nodes WHERE node_id = ?",
                (seed,),
            ).fetchone()
            if row:
                attrs = json.loads(row[5] or "{}")
                payload.update(
                    {
                        "node_id": row[0],
                        "kind": row[1],
                        "name": row[2],
                        "path": row[3],
                        "symbol": row[4],
                        "attrs": attrs,
                    }
                )
                return payload
    parts = str(seed).split(":", 2)
    if len(parts) == 3:
        payload["kind"] = parts[0]
        payload["path"] = parts[1]
        payload["symbol"] = parts[2]
        payload["name"] = parts[2]
    elif len(parts) == 2:
        payload["kind"] = parts[0]
        payload["path"] = parts[1]
        payload["name"] = parts[1]
    return payload


def collect_provider_analysis(*, workspace_root: pathlib.Path, config: dict, seed_context: dict, bootstrap: bool = True) -> dict:
    provider, state = resolve_provider(workspace_root=workspace_root, config=config, bootstrap=bootstrap)
    if not provider:
        return state
    if not any(seed_context.get(key) for key in ("seed", "symbol", "path")):
        return state
    provider_result = provider.analyze_change(workspace_root, config, seed_context) or {}
    overlay = provider_result.get("provider_overlay") or {}
    state["provider_evidence_summary"] = list(provider_result.get("provider_evidence_summary") or [])
    state["provider_overlay"] = {
        **state.get("provider_overlay", {}),
        **overlay,
        "external_side_effects": list(overlay.get("external_side_effects") or state.get("provider_side_effects") or []),
    }
    return state
