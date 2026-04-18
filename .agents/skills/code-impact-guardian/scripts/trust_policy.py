#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime, timezone


GENERATED_PATTERNS = (
    "dist/",
    "build/",
    ".next/",
    ".turbo/",
    ".cache/",
    "coverage/",
    "__pycache__/",
    "generated/",
    "gen/",
    "out/",
)

def stable_hash(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def config_fingerprint(*, config: dict, profile_name: str, primary_adapter: str, supplemental_adapters: list[str]) -> str:
    relevant = {
        "project_root": config.get("project_root"),
        "project_profile": profile_name,
        "primary_adapter": primary_adapter,
        "supplemental_adapters": supplemental_adapters,
        "rules": config.get("rules", {}),
        "python": config.get("python", {}),
        "tsjs": config.get("tsjs", {}),
        "generic": config.get("generic", {}),
        "sql_postgres": config.get("sql_postgres", {}),
    }
    return stable_hash(relevant)


def is_generated_or_cache_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(token in normalized for token in GENERATED_PATTERNS) or normalized.endswith((".pyc", ".map"))


def adapter_scope_for_path(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if normalized.endswith((".py",)):
        return "python"
    if normalized.endswith((".js", ".ts", ".jsx", ".tsx")):
        return "tsjs"
    if normalized.endswith(".sql"):
        return "sql_postgres"
    return "generic"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def manifest_age_hours(previous_manifest: dict | None) -> float | None:
    if not previous_manifest:
        return None
    timestamp = previous_manifest.get("timestamp")
    if not timestamp:
        return None
    try:
        created_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max((utc_now() - created_at).total_seconds() / 3600.0, 0.0)


def should_shadow_verify(*, build_mode: str, changed_files: list[str], tracked_count: int) -> bool:
    if build_mode != "incremental":
        return False
    if not changed_files or len(changed_files) > 2:
        return False
    return tracked_count <= 40


def build_decision(
    *,
    previous_manifest: dict | None,
    plan: dict,
    config: dict,
    profile_name: str,
    primary_adapter: str,
    supplemental_adapters: list[str],
    requested_changed_files: list[str] | None,
) -> dict:
    changed_files = list(plan.get("changed_files", []))
    reason_codes: list[str] = []
    generated_noise_source = requested_changed_files or changed_files
    generated_noise = sorted(path for path in generated_noise_source if is_generated_or_cache_file(path))
    dependency_files = sorted(plan.get("dependency_files", []))
    current_dependency_fingerprint = plan.get("dependency_fingerprint") or {}
    config_hash = config_fingerprint(
        config=config,
        profile_name=profile_name,
        primary_adapter=primary_adapter,
        supplemental_adapters=supplemental_adapters,
    )

    previous_meta = (previous_manifest or {}).get("meta", {})
    previous_hash = previous_meta.get("config_fingerprint")
    previous_profile = previous_meta.get("profile_name")
    previous_primary = previous_meta.get("primary_adapter")
    previous_supplemental = previous_meta.get("supplemental_adapters", [])
    previous_dependency_fingerprint = (
        previous_meta.get("dependency_fingerprint")
        if isinstance(previous_meta.get("dependency_fingerprint"), dict)
        else None
    )
    tracked_count = len(plan.get("files", {}))
    ttl_hours = float(config.get("graph", {}).get("freshness_ttl_hours", 24))
    age_hours = manifest_age_hours(previous_manifest)
    dependency_fingerprint_status = "not_applicable"
    if current_dependency_fingerprint:
        if previous_dependency_fingerprint is None:
            dependency_fingerprint_status = "unknown"
        elif current_dependency_fingerprint == previous_dependency_fingerprint:
            dependency_fingerprint_status = "unchanged"
        else:
            dependency_fingerprint_status = "changed"

    if not previous_manifest:
        reason_codes.append("NO_PREVIOUS_MANIFEST")
    if previous_hash and previous_hash != config_hash:
        reason_codes.append("CONFIG_CHANGED")
    if previous_profile and previous_profile != profile_name:
        reason_codes.append("PROFILE_CHANGED")
    if previous_primary and previous_primary != primary_adapter:
        reason_codes.append("PRIMARY_ADAPTER_CHANGED")
    if previous_supplemental != supplemental_adapters:
        reason_codes.append("SUPPLEMENTAL_ADAPTERS_CHANGED")
    if len(changed_files) >= 6:
        reason_codes.append("LARGE_CHANGESET")
    if any(path.endswith(".md") and "/rules/" in path.replace("\\", "/") for path in changed_files):
        reason_codes.append("RULE_FILES_CHANGED")
    if any(adapter_scope_for_path(path) != primary_adapter for path in changed_files if adapter_scope_for_path(path) != "generic"):
        if any(adapter_scope_for_path(path) == primary_adapter for path in changed_files):
            reason_codes.append("CROSS_ADAPTER_BOUNDARY")
    if generated_noise:
        reason_codes.append("GENERATED_OR_CACHE_NOISE_PRESENT")
    if plan.get("build_mode") == "reused":
        reason_codes.append("REUSED_PREVIOUS_GRAPH")
    if plan.get("build_mode") == "reused" and age_hours is not None and age_hours > ttl_hours:
        reason_codes.append("GRAPH_TTL_EXCEEDED")

    decision_mode = "incremental" if plan.get("build_mode") in {"incremental", "reused"} else "full"
    if dependency_fingerprint_status == "changed":
        reason_codes.append("DEPENDENCY_FINGERPRINT_CHANGED")
    elif dependency_fingerprint_status == "unknown":
        reason_codes.append("DEPENDENCY_FINGERPRINT_UNKNOWN")
    if any(code in reason_codes for code in {"NO_PREVIOUS_MANIFEST", "CONFIG_CHANGED", "PROFILE_CHANGED", "PRIMARY_ADAPTER_CHANGED", "SUPPLEMENTAL_ADAPTERS_CHANGED", "RULE_FILES_CHANGED", "CROSS_ADAPTER_BOUNDARY", "DEPENDENCY_FINGERPRINT_CHANGED"}):
        decision_mode = "full"

    execution_mode = plan.get("build_mode", decision_mode)
    if decision_mode == "full":
        graph_freshness = "fresh"
    elif execution_mode == "reused":
        if age_hours is None:
            graph_freshness = "unknown"
        else:
            graph_freshness = "fresh" if age_hours <= ttl_hours else "stale"
    else:
        graph_freshness = "fresh"

    graph_trust = "medium"
    if generated_noise or "GRAPH_TTL_EXCEEDED" in reason_codes:
        graph_trust = "low"
    elif any(code in reason_codes for code in {"CONFIG_CHANGED", "PROFILE_CHANGED", "PRIMARY_ADAPTER_CHANGED", "SUPPLEMENTAL_ADAPTERS_CHANGED", "RULE_FILES_CHANGED", "CROSS_ADAPTER_BOUNDARY", "DEPENDENCY_FINGERPRINT_CHANGED", "DEPENDENCY_FINGERPRINT_UNKNOWN"}):
        graph_trust = "medium"
    elif execution_mode == "reused":
        graph_trust = "high" if graph_freshness == "fresh" else "medium"
    elif decision_mode == "incremental":
        graph_trust = "high" if not changed_files else "medium"
    else:
        graph_trust = "high" if not reason_codes else "medium"

    if graph_freshness != "fresh":
        graph_trust = "medium" if graph_trust == "high" else graph_trust
    if dependency_fingerprint_status in {"changed", "unknown"} and graph_trust == "high":
        graph_trust = "medium"
    if generated_noise:
        graph_trust = "low"

    return {
        "build_mode": decision_mode,
        "execution_mode": execution_mode,
        "trust_level": graph_trust,
        "graph_trust": graph_trust,
        "reason_codes": reason_codes or ["DEFAULT_SAFE_PATH"],
        "verification_status": "skipped",
        "verification_reason": "shadow verification not requested",
        "generated_noise": generated_noise,
        "dependency_files": dependency_files,
        "graph_freshness": graph_freshness,
        "ttl_hours": ttl_hours,
        "manifest_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "dependency_fingerprint_status": dependency_fingerprint_status,
        "tracked_file_count": tracked_count,
        "config_fingerprint": config_hash,
        "shadow_verify": should_shadow_verify(
            build_mode=decision_mode,
            changed_files=changed_files,
            tracked_count=tracked_count,
        ),
    }


def apply_shadow_verification_result(decision: dict, *, matched: bool, detail: str) -> dict:
    updated = dict(decision)
    updated["verification_status"] = "matched" if matched else "mismatched"
    updated["verification_reason"] = detail
    if not matched:
        updated["build_mode"] = "full"
        updated["trust_level"] = "low"
        updated["graph_trust"] = "low"
        updated["reason_codes"] = [*updated.get("reason_codes", []), "SHADOW_VERIFICATION_MISMATCH"]
    return updated
