from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

from .base import GraphProvider


def _unique_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _confidence_label(values: list[float]) -> str:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return "low"
    score = max(usable)
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _command_exists(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = argv[0]
    if pathlib.Path(executable).exists():
        return True
    return shutil.which(executable) is not None


def _resolved_argv(argv: list[str]) -> list[str]:
    if not argv:
        return []
    executable = argv[0]
    if pathlib.Path(executable).exists():
        return argv
    resolved = shutil.which(executable)
    return [resolved, *argv[1:]] if resolved else argv


def _json_or_none(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _symbol_kind(raw_kind: str | None) -> str:
    value = (raw_kind or "").lower()
    if value in {"function", "method", "class", "interface", "file"}:
        return "function" if value in {"method", "class", "interface"} else value
    return "function"


ROOT_SIDE_EFFECT_FILES = ("AGENTS.md", "CLAUDE.md", ".gitignore")
ROOT_SIDE_EFFECT_DIRS = (".claude",)


class GitNexusProvider(GraphProvider):
    name = "gitnexus"

    def _settings(self, config: dict) -> dict:
        providers = config.get("providers") or {}
        gitnexus = providers.get(self.name) or {}
        return {
            "enabled": bool(gitnexus.get("enabled", True)),
            "command": gitnexus.get("command", "gitnexus"),
            "mode": gitnexus.get("mode", "cli"),
            "bootstrap": gitnexus.get("bootstrap", "auto"),
            "fallback_to_internal": bool(gitnexus.get("fallback_to_internal", True)),
            "skip_agents_md": bool(gitnexus.get("skip_agents_md", True)),
            "use_npx": bool(gitnexus.get("use_npx", False)),
        }

    def _command_argv(self, config: dict) -> list[str]:
        command = self._settings(config).get("command", "gitnexus")
        if isinstance(command, list):
            return [str(item) for item in command if str(item).strip()]
        text = str(command).strip()
        return [text] if text else ["gitnexus"]

    def _fallback_command_argv(self, config: dict) -> list[str] | None:
        if not self._settings(config).get("use_npx"):
            return None
        argv = ["npx", "gitnexus"]
        return argv if _command_exists(argv) else None

    def _resolve_cli(self, config: dict) -> tuple[list[str] | None, str | None]:
        primary = self._command_argv(config)
        if _command_exists(primary):
            return _resolved_argv(primary), None
        fallback = self._fallback_command_argv(config)
        if fallback:
            return _resolved_argv(fallback), None
        install_hint = "Install GitNexus and ensure `gitnexus` is on PATH. Default flow does not use `npx` unless `providers.gitnexus.use_npx=true`."
        return None, install_hint

    def _run(self, workspace_root: pathlib.Path, config: dict, args: list[str]) -> dict:
        base_argv, install_hint = self._resolve_cli(config)
        if not base_argv:
            return {
                "ok": False,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "command": [],
                "reason": "gitnexus command not found",
                "install_hint": install_hint,
            }
        command = [*base_argv, *args]
        result = subprocess.run(
            command,
            cwd=workspace_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
            "reason": None,
            "install_hint": None,
        }

    def _parse_status(self, text: str) -> dict:
        lowered = text.lower()
        if "up-to-date" in lowered or "up to date" in lowered or "indexed and ready" in lowered:
            return {
                "ready": True,
                "provider_status": "ready",
                "provider_reason": "gitnexus indexed repo is available",
                "provider_index_status": "indexed",
            }
        if "repository not indexed" in lowered:
            return {
                "ready": False,
                "provider_status": "failed",
                "provider_reason": "gitnexus repository is not indexed yet",
                "provider_index_status": "not_indexed",
            }
        if "not a git repository" in lowered:
            return {
                "ready": False,
                "provider_status": "failed",
                "provider_reason": "workspace is not a git repository, so GitNexus needs --skip-git bootstrap",
                "provider_index_status": "not_indexed",
            }
        return {
            "ready": False,
            "provider_status": "failed",
            "provider_reason": text.strip() or "gitnexus status returned an unknown result",
            "provider_index_status": "unknown",
        }

    def _is_git_repo(self, workspace_root: pathlib.Path) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _has_non_ascii_path(self, workspace_root: pathlib.Path) -> bool:
        return any(ord(char) > 127 for char in str(workspace_root))

    def _side_effects(self, workspace_root: pathlib.Path) -> list[str]:
        candidates = [
            workspace_root / "CLAUDE.md",
            workspace_root / ".claude",
            workspace_root / ".claude" / "skills",
        ]
        side_effects = [str(path.relative_to(workspace_root)).replace("\\", "/") for path in candidates if path.exists()]
        gitignore_path = workspace_root / ".gitignore"
        if gitignore_path.exists():
            text = gitignore_path.read_text(encoding="utf-8", errors="replace")
            if ".gitnexus" in {line.strip() for line in text.splitlines()}:
                side_effects.append(".gitignore:.gitnexus")
        return _unique_strings(side_effects)

    def _snapshot_side_effects(self, workspace_root: pathlib.Path) -> dict:
        files: dict[str, dict] = {}
        for relative in ROOT_SIDE_EFFECT_FILES:
            path = workspace_root / relative
            files[relative] = {
                "exists": path.exists(),
                "text": path.read_text(encoding="utf-8", errors="replace") if path.exists() else None,
            }
        directories: dict[str, dict] = {}
        for relative in ROOT_SIDE_EFFECT_DIRS:
            path = workspace_root / relative
            directories[relative] = {
                "exists": path.exists(),
            }
        return {
            "files": files,
            "directories": directories,
        }

    def _quarantine_root(self, workspace_root: pathlib.Path) -> pathlib.Path:
        return workspace_root / ".ai" / "codegraph" / "provider-side-effects" / self.name

    def _unique_quarantine_path(self, workspace_root: pathlib.Path, relative_path: str) -> pathlib.Path:
        target = self._quarantine_root(workspace_root) / relative_path
        candidate = target
        counter = 1
        while candidate.exists():
            suffix = f".{counter}"
            candidate = target.parent / f"{target.name}{suffix}"
            counter += 1
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def _quarantine_path(self, workspace_root: pathlib.Path, path: pathlib.Path) -> str:
        relative = str(path.relative_to(workspace_root)).replace("\\", "/")
        target = self._unique_quarantine_path(workspace_root, relative)
        shutil.move(str(path), str(target))
        return str(target.relative_to(workspace_root)).replace("\\", "/")

    def _ensure_git_info_exclude(self, workspace_root: pathlib.Path, pattern: str) -> str | None:
        git_dir = workspace_root / ".git"
        if not git_dir.exists():
            return None
        exclude_path = git_dir / "info" / "exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.exists() else ""
        lines = [line.strip() for line in existing.splitlines()]
        if pattern not in lines:
            if existing and not existing.endswith("\n"):
                existing += "\n"
            existing += pattern + "\n"
            exclude_path.write_text(existing, encoding="utf-8")
        return str(exclude_path.relative_to(workspace_root)).replace("\\", "/")

    def _suppress_side_effects(self, workspace_root: pathlib.Path, snapshot: dict) -> dict:
        suppressed: list[dict] = []
        for relative in ROOT_SIDE_EFFECT_FILES:
            path = workspace_root / relative
            before = (snapshot.get("files") or {}).get(relative) or {}
            before_exists = bool(before.get("exists"))
            before_text = before.get("text")
            if not path.exists() and not before_exists:
                continue
            if before_exists:
                current_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
                if current_text != before_text:
                    path.write_text(before_text or "", encoding="utf-8")
                    suppressed.append(
                        {
                            "path": relative,
                            "action": "restored",
                        }
                    )
            elif path.exists():
                quarantined_to = self._quarantine_path(workspace_root, path)
                suppressed.append(
                    {
                        "path": relative,
                        "action": "quarantined",
                        "quarantined_to": quarantined_to,
                    }
                )
        for relative in ROOT_SIDE_EFFECT_DIRS:
            path = workspace_root / relative
            before = (snapshot.get("directories") or {}).get(relative) or {}
            if not before.get("exists") and path.exists():
                quarantined_to = self._quarantine_path(workspace_root, path)
                suppressed.append(
                    {
                        "path": relative,
                        "action": "quarantined",
                        "quarantined_to": quarantined_to,
                    }
                )
        gitnexus_dir = workspace_root / ".gitnexus"
        exclude_path = None
        if gitnexus_dir.exists():
            exclude_path = self._ensure_git_info_exclude(workspace_root, ".gitnexus")
        return {
            "visible_side_effects": self._side_effects(workspace_root),
            "suppressed_side_effects": suppressed,
            "git_info_exclude_path": exclude_path,
        }

    def detect(self, workspace_root: pathlib.Path, config: dict) -> dict:
        settings = self._settings(config)
        if not settings["enabled"]:
            return {
                "provider": self.name,
                "available": False,
                "ready": False,
                "provider_status": "failed",
                "provider_reason": "gitnexus provider is disabled in config.",
                "provider_index_status": "disabled",
                "provider_install_hint": None,
                "provider_effective": None,
            }
        argv, install_hint = self._resolve_cli(config)
        return {
            "provider": self.name,
            "available": bool(argv),
            "ready": False,
            "provider_status": "failed" if not argv else "ready",
            "provider_reason": "gitnexus CLI detected." if argv else "gitnexus command not found",
            "provider_index_status": "unknown" if argv else "command_missing",
            "provider_install_hint": install_hint,
            "provider_effective": self.name if argv else None,
        }

    def ensure_ready(self, workspace_root: pathlib.Path, config: dict) -> dict:
        detected = self.detect(workspace_root, config)
        if not detected.get("available"):
            return detected
        status_run = self._run(workspace_root, config, ["status"])
        status_text = "\n".join([status_run.get("stdout", ""), status_run.get("stderr", "")]).strip()
        parsed_status = self._parse_status(status_text)
        if parsed_status["ready"]:
            return {
                **detected,
                **parsed_status,
                "external_side_effects": self._side_effects(workspace_root),
            }
        settings = self._settings(config)
        if settings.get("bootstrap") != "auto":
            return {
                **detected,
                **parsed_status,
                "external_side_effects": self._side_effects(workspace_root),
            }
        git_repo = self._is_git_repo(workspace_root)
        if not git_repo and self._has_non_ascii_path(workspace_root):
            return {
                **detected,
                "provider_status": "failed",
                "provider_reason": "GitNexus `--skip-git` is unreliable on Windows non-ASCII paths; using internal fallback instead.",
                "provider_index_status": "index_failed",
                "provider_install_hint": "Move or mirror the repo to an ASCII path if you want GitNexus indexing here. Stage 20 keeps workflow alive via internal fallback.",
                "external_side_effects": self._side_effects(workspace_root),
            }
        side_effect_snapshot = self._snapshot_side_effects(workspace_root)
        analyze_args = ["analyze"]
        if not git_repo:
            analyze_args.extend(["--skip-git", "--force"])
        if settings.get("skip_agents_md", True):
            analyze_args.append("--skip-agents-md")
        analyze_run = self._run(workspace_root, config, analyze_args)
        side_effect_result = self._suppress_side_effects(workspace_root, side_effect_snapshot)
        if not analyze_run.get("ok"):
            reason_text = "\n".join([analyze_run.get("stdout", ""), analyze_run.get("stderr", "")]).strip()
            return {
                **detected,
                "provider_status": "failed",
                "provider_reason": reason_text or "gitnexus analyze failed",
                "provider_index_status": "index_failed",
                "provider_install_hint": analyze_run.get("install_hint"),
                "external_side_effects": side_effect_result.get("visible_side_effects", []),
                "suppressed_side_effects": side_effect_result.get("suppressed_side_effects", []),
                "git_info_exclude_path": side_effect_result.get("git_info_exclude_path"),
            }
        verify_run = self._run(workspace_root, config, ["status"])
        verify_text = "\n".join([verify_run.get("stdout", ""), verify_run.get("stderr", "")]).strip()
        parsed_verify = self._parse_status(verify_text)
        if parsed_verify["ready"]:
            return {
                **detected,
                **parsed_verify,
                "provider_reason": "gitnexus indexed repo is available",
                "external_side_effects": side_effect_result.get("visible_side_effects", []),
                "suppressed_side_effects": side_effect_result.get("suppressed_side_effects", []),
                "git_info_exclude_path": side_effect_result.get("git_info_exclude_path"),
            }
        return {
            **detected,
            "provider_status": "failed",
            "provider_reason": verify_text or "gitnexus analyze completed, but status did not report an indexed repo.",
            "provider_index_status": "index_failed",
            "provider_install_hint": "Run `gitnexus status` manually and confirm the repo was indexed. On Windows, do not rely on `npx` unless you explicitly opted into it.",
            "external_side_effects": side_effect_result.get("visible_side_effects", []),
            "suppressed_side_effects": side_effect_result.get("suppressed_side_effects", []),
            "git_info_exclude_path": side_effect_result.get("git_info_exclude_path"),
        }

    def _target_name(self, target: dict) -> str | None:
        symbol = str(target.get("symbol") or "").strip()
        if symbol:
            return symbol
        path = str(target.get("path") or "").strip()
        if not path:
            return None
        return pathlib.Path(path).stem

    def _repo_name(self, workspace_root: pathlib.Path) -> str:
        return workspace_root.resolve().name

    def context(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        target_name = self._target_name(target)
        if not target_name:
            return {"status": "failed", "reason": "seed does not expose a stable symbol name for GitNexus context lookup"}
        args = ["context", target_name, "-r", self._repo_name(workspace_root)]
        if target.get("path"):
            args.extend(["-f", str(target["path"])])
        result = self._run(workspace_root, config, args)
        payload = _json_or_none(result.get("stdout", ""))
        if not result.get("ok") or not payload:
            reason = "\n".join([result.get("stdout", ""), result.get("stderr", "")]).strip()
            return {"status": "failed", "reason": reason or "gitnexus context returned no JSON payload"}
        return {"status": "ok", "payload": payload}

    def _impact_direction(self, workspace_root: pathlib.Path, config: dict, target: dict, direction: str) -> dict:
        target_name = self._target_name(target)
        if not target_name:
            return {"status": "failed", "reason": "seed does not expose a stable symbol name for GitNexus impact lookup"}
        args = ["impact", target_name, "-r", self._repo_name(workspace_root), "-d", direction]
        depth = int((config.get("impact") or {}).get("max_depth", 3) or 3)
        args.extend(["--depth", str(depth)])
        result = self._run(workspace_root, config, args)
        payload = _json_or_none(result.get("stdout", ""))
        if not result.get("ok") or not payload:
            reason = "\n".join([result.get("stdout", ""), result.get("stderr", "")]).strip()
            return {"status": "failed", "reason": reason or f"gitnexus impact {direction} returned no JSON payload"}
        return {"status": "ok", "payload": payload}

    def impact(self, workspace_root: pathlib.Path, config: dict, target: dict) -> dict:
        return {
            "upstream": self._impact_direction(workspace_root, config, target, "upstream"),
            "downstream": self._impact_direction(workspace_root, config, target, "downstream"),
        }

    def _contract_entry(self, target: dict, item: dict, relationship: str) -> dict:
        confidence = float(item.get("confidence") or 0.5)
        file_path = item.get("filePath") or target.get("path")
        symbol_kind = _symbol_kind(item.get("type"))
        return {
            "node_id": item.get("id") or item.get("uid") or f"{symbol_kind}:{file_path}:{item.get('name')}",
            "kind": symbol_kind,
            "name": item.get("name") or target.get("symbol") or file_path,
            "relationship": relationship,
            "confidence": confidence,
            "files": _unique_strings([file_path, target.get("path")]),
            "provider_evidence": {
                "source": self.name,
                "tool": "impact",
                "symbol": target.get("symbol") or target.get("seed"),
                "confidence": _confidence_label([confidence]),
            },
        }

    def _process_chain(self, target: dict, process: dict, label: str) -> dict:
        process_name = process.get("name") or process.get("id") or "unknown-process"
        process_path = process.get("filePath") or target.get("path")
        confidence = 0.9 if process.get("earliest_broken_step") else 0.75
        return {
            "chain_type": "provider_process",
            "summary": f"GitNexus {label} process `{process_name}` is linked to `{target.get('symbol') or target.get('seed')}`.",
            "nodes": [
                {
                    "node_id": target.get("seed") or target.get("node_id"),
                    "kind": target.get("kind") or "function",
                    "name": target.get("symbol") or target.get("seed"),
                    "path": target.get("path"),
                },
                {
                    "node_id": process.get("id") or f"process:{process_name}",
                    "kind": "function",
                    "name": process_name,
                    "path": process_path,
                },
            ],
            "edges": [
                {
                    "src": target.get("seed") or target.get("node_id"),
                    "src_name": target.get("symbol") or target.get("seed"),
                    "src_path": target.get("path"),
                    "edge_type": "CALLS",
                    "dst": process.get("id") or f"process:{process_name}",
                    "dst_name": process_name,
                    "dst_path": process_path,
                    "confidence": confidence,
                }
            ],
        }

    def _bilateral_view(self, target: dict, contracts: list[dict]) -> dict | None:
        if not contracts:
            return None
        supporting_edges = []
        for item in contracts[:6]:
            supporting_edges.append(
                {
                    "src": target.get("seed") or target.get("node_id"),
                    "src_name": target.get("symbol") or target.get("seed"),
                    "src_path": target.get("path"),
                    "edge_type": item.get("relationship") or "CALLS",
                    "dst": item.get("node_id"),
                    "dst_name": item.get("name"),
                    "dst_path": (item.get("files") or [""])[0],
                    "confidence": item.get("confidence", 0.5),
                }
            )
        uncertainties = [
            f"{edge['edge_type']} for `{edge['dst_name']}` is low-confidence provider evidence."
            for edge in supporting_edges
            if float(edge.get("confidence") or 0.0) < 0.85
        ]
        return {
            "view_type": "bilateral_contract",
            "title": "GitNexus graph neighborhood",
            "why_this_view": "GitNexus found nearby symbol-level relationships that help widen the first reading pass before editing.",
            "confidence": _confidence_label([float(item.get("confidence") or 0.0) for item in contracts]),
            "primary_contracts": [
                {
                    "node_id": item.get("node_id"),
                    "kind": item.get("kind"),
                    "name": item.get("name"),
                    "path": (item.get("files") or [""])[0],
                }
                for item in contracts[:4]
            ],
            "read_first": _unique_strings([target.get("path"), *[(item.get("files") or [""])[0] for item in contracts[:6]]]),
            "supporting_edges": supporting_edges,
            "uncertainties": _unique_strings(uncertainties),
        }

    def _page_flow_view(self, target: dict, processes: list[dict], *, label: str) -> dict | None:
        if not processes:
            return None
        supporting_edges = []
        read_first = [target.get("path")]
        for process in processes[:6]:
            process_name = process.get("name") or process.get("id") or "unknown-process"
            process_path = process.get("filePath") or target.get("path")
            read_first.append(process_path)
            supporting_edges.append(
                {
                    "src": target.get("seed") or target.get("node_id"),
                    "src_name": target.get("symbol") or target.get("seed"),
                    "src_path": target.get("path"),
                    "edge_type": "CALLS",
                    "dst": process.get("id") or f"process:{process_name}",
                    "dst_name": process_name,
                    "dst_path": process_path,
                    "confidence": 0.75,
                }
            )
        return {
            "view_type": "page_flow",
            "title": f"GitNexus {label} process view",
            "why_this_view": "GitNexus surfaced process-level flow fragments that are useful for the first read before editing.",
            "confidence": "medium",
            "primary_contracts": [
                {
                    "node_id": target.get("seed") or target.get("node_id"),
                    "kind": target.get("kind") or "function",
                    "name": target.get("symbol") or target.get("seed"),
                    "path": target.get("path"),
                }
            ],
            "read_first": _unique_strings(read_first),
            "supporting_edges": supporting_edges,
            "uncertainties": [],
        }

    def analyze_change(self, workspace_root: pathlib.Path, config: dict, seed_context: dict) -> dict:
        target = dict(seed_context)
        context_result = self.context(workspace_root, config, target)
        impact_result = self.impact(workspace_root, config, target)
        uncertainties: list[str] = []
        evidence_summary: list[str] = []
        contracts: list[dict] = []
        architecture_chains: list[dict] = []
        atlas_views: list[dict] = []
        provider_evidence: list[dict] = []
        must_read_first = [target.get("path")]

        context_payload = (context_result or {}).get("payload") or {}
        if context_result.get("status") == "ok":
            incoming_calls = list(((context_payload.get("incoming") or {}).get("calls") or []))
            outgoing_calls = list(((context_payload.get("outgoing") or {}).get("calls") or []))
            processes = list(context_payload.get("processes") or [])
            evidence_summary.append(
                f"gitnexus context resolved `{self._target_name(target) or target.get('seed')}` with {len(incoming_calls)} incoming, {len(outgoing_calls)} outgoing, and {len(processes)} process fragments."
            )
            for item in outgoing_calls[:8]:
                contracts.append(self._contract_entry(target, item, "CALLS"))
                must_read_first.append(item.get("filePath"))
                provider_evidence.append(
                    {
                        "source": self.name,
                        "tool": "context",
                        "symbol": item.get("name"),
                        "confidence": "medium",
                    }
                )
            if processes:
                atlas_view = self._page_flow_view(target, processes, label="context")
                if atlas_view:
                    atlas_views.append(atlas_view)
                for process in processes[:6]:
                    architecture_chains.append(self._process_chain(target, process, "context"))
                    must_read_first.append(process.get("filePath"))
        else:
            uncertainties.append(context_result.get("reason") or "gitnexus context lookup failed")

        downstream = ((impact_result.get("downstream") or {}).get("payload") or {})
        if (impact_result.get("downstream") or {}).get("status") == "ok":
            impacted_count = int(downstream.get("impactedCount") or 0)
            risk = str(downstream.get("risk") or "unknown")
            evidence_summary.append(
                f"gitnexus downstream impact found {impacted_count} affected symbols with risk {risk}."
            )
            for depth_items in (downstream.get("byDepth") or {}).values():
                for item in depth_items[:8]:
                    contracts.append(self._contract_entry(target, item, item.get("relationType") or "CALLS"))
                    must_read_first.append(item.get("filePath"))
            affected_processes = list(downstream.get("affected_processes") or [])
            if affected_processes:
                atlas_view = self._page_flow_view(target, affected_processes, label="impact")
                if atlas_view:
                    atlas_views.append(atlas_view)
                for process in affected_processes[:6]:
                    architecture_chains.append(self._process_chain(target, process, "impact"))
                    must_read_first.append(process.get("filePath"))
        else:
            uncertainties.append((impact_result.get("downstream") or {}).get("reason") or "gitnexus downstream impact lookup failed")

        upstream = ((impact_result.get("upstream") or {}).get("payload") or {})
        if (impact_result.get("upstream") or {}).get("status") == "ok":
            impacted_count = int(upstream.get("impactedCount") or 0)
            evidence_summary.append(f"gitnexus upstream impact found {impacted_count} dependants.")
            for depth_items in (upstream.get("byDepth") or {}).values():
                for item in depth_items[:4]:
                    contracts.append(self._contract_entry(target, item, item.get("relationType") or "REFERENCED_BY"))
                    must_read_first.append(item.get("filePath"))
        else:
            uncertainties.append((impact_result.get("upstream") or {}).get("reason") or "gitnexus upstream impact lookup failed")

        contracts = sorted(
            {
                (item["node_id"], item["relationship"]): item
                for item in contracts
            }.values(),
            key=lambda item: (item.get("kind", ""), item.get("name", ""), item.get("relationship", "")),
        )
        bilateral_view = self._bilateral_view(target, contracts)
        if bilateral_view:
            atlas_views.insert(0, bilateral_view)
        if not target.get("symbol"):
            uncertainties.append("GitNexus received a file-level seed without a stable symbol, so provider results may stay shallow.")
        return {
            "provider_evidence_summary": _unique_strings(evidence_summary),
            "provider_overlay": {
                "source": self.name,
                "affected_contracts": contracts,
                "architecture_chains": architecture_chains,
                "atlas_views": atlas_views,
                "must_read_first": _unique_strings(must_read_first),
                "uncertainty": _unique_strings(uncertainties),
                "provider_evidence": provider_evidence[:12],
                "external_side_effects": self._side_effects(workspace_root),
                "raw": {
                    "context": context_payload,
                    "impact_upstream": upstream,
                    "impact_downstream": downstream,
                },
            },
        }

    def health(self, workspace_root: pathlib.Path, config: dict) -> dict:
        detected = self.detect(workspace_root, config)
        if not detected.get("available"):
            return detected
        status_run = self._run(workspace_root, config, ["status"])
        text = "\n".join([status_run.get("stdout", ""), status_run.get("stderr", "")]).strip()
        return {
            **detected,
            **self._parse_status(text),
            "external_side_effects": self._side_effects(workspace_root),
        }
