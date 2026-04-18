#!/usr/bin/env python3
import hashlib
import json
import pathlib


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
    generated_noise = sorted(path for path in (requested_changed_files or []) if is_generated_or_cache_file(path))
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
    tracked_count = len(plan.get("files", {}))

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

    decision_mode = "incremental" if plan.get("build_mode") in {"incremental", "reused"} else "full"
    if any(code in reason_codes for code in {"NO_PREVIOUS_MANIFEST", "CONFIG_CHANGED", "PROFILE_CHANGED", "PRIMARY_ADAPTER_CHANGED", "SUPPLEMENTAL_ADAPTERS_CHANGED", "RULE_FILES_CHANGED", "CROSS_ADAPTER_BOUNDARY"}):
        decision_mode = "full"

    trust_level = "high"
    if decision_mode == "incremental":
        trust_level = "medium" if changed_files else "high"
        if generated_noise:
            trust_level = "low"
        if "REUSED_PREVIOUS_GRAPH" in reason_codes:
            trust_level = "high"
    elif reason_codes:
        trust_level = "high" if len(reason_codes) <= 2 else "medium"

    return {
        "build_mode": decision_mode,
        "trust_level": trust_level,
        "reason_codes": reason_codes or ["DEFAULT_SAFE_PATH"],
        "verification_status": "skipped",
        "verification_reason": "shadow verification not requested",
        "generated_noise": generated_noise,
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
        updated["reason_codes"] = [*updated.get("reason_codes", []), "SHADOW_VERIFICATION_MISMATCH"]
    return updated
