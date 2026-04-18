#!/usr/bin/env python3
import argparse
import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from adapters import detect_project_profile_name
from build_graph import get_git_context, graph_paths, load_config, project_root_for, record_task_run, resolved_language_adapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def node_details(conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT node_id, kind, name, path, symbol, attrs_json FROM nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "node_id": row[0],
        "kind": row[1],
        "name": row[2],
        "path": row[3],
        "symbol": row[4],
        "attrs": json.loads(row[5] or "{}"),
    }


def recursive_paths(conn: sqlite3.Connection, seed: str, edge_type: str, max_depth: int, reverse: bool = False) -> list[str]:
    if reverse:
        sql = """
        WITH RECURSIVE walk(depth, current_id, path) AS (
          SELECT 1, e.src_id, e.src_id || ' -> ' || e.dst_id
          FROM edges e
          WHERE e.dst_id = ? AND e.edge_type = ?
          UNION ALL
          SELECT w.depth + 1, e.src_id, e.src_id || ' -> ' || w.path
          FROM walk w
          JOIN edges e ON e.dst_id = w.current_id
          WHERE e.edge_type = ? AND w.depth < ?
        )
        SELECT path FROM walk;
        """
        return [row[0] for row in conn.execute(sql, (seed, edge_type, edge_type, max_depth)).fetchall()]
    sql = """
    WITH RECURSIVE walk(depth, current_id, path) AS (
      SELECT 1, e.dst_id, e.src_id || ' -> ' || e.dst_id
      FROM edges e
      WHERE e.src_id = ? AND e.edge_type = ?
      UNION ALL
      SELECT w.depth + 1, e.dst_id, w.path || ' -> ' || e.dst_id
      FROM walk w
      JOIN edges e ON e.src_id = w.current_id
      WHERE e.edge_type = ? AND w.depth < ?
    )
    SELECT path FROM walk;
    """
    return [row[0] for row in conn.execute(sql, (seed, edge_type, edge_type, max_depth)).fetchall()]


def evidence_for_edges(conn: sqlite3.Connection, edge_rows: list[tuple[str, str, str]]) -> list[str]:
    lines: list[str] = []
    for src_id, edge_type, dst_id in edge_rows:
        row = conn.execute(
            """
            SELECT ev.git_sha, ev.file_path, ev.start_line, ev.end_line, ev.diff_ref, ev.blame_ref, ev.extractor
            FROM edges e
            LEFT JOIN evidence ev ON ev.evidence_id = e.evidence_id
            WHERE e.src_id = ? AND e.edge_type = ? AND e.dst_id = ?
            """,
            (src_id, edge_type, dst_id),
        ).fetchone()
        if not row:
            continue
        git_sha, file_path, start_line, end_line, diff_ref, blame_ref, extractor = row
        lines.append(
            f"- `{src_id}` --{edge_type}--> `{dst_id}` from `{file_path}`:{start_line}-{end_line} "
            f"(git_sha={git_sha}, diff_ref={diff_ref}, blame_ref={blame_ref}, extractor={extractor})"
        )
    return lines


def mermaid_from_edges(edge_rows: list[tuple[str, str, str]], seed: str) -> str:
    lines = ["flowchart LR"]
    seen: set[tuple[str, str]] = set()
    for src_id, _, dst_id in edge_rows:
        if (src_id, dst_id) in seen:
            continue
        seen.add((src_id, dst_id))
        lines.append(f'  "{src_id}" --> "{dst_id}"')
    if len(lines) == 1:
        lines.append(f'  "{seed}"')
    return "\n".join(lines) + "\n"


def function_report_sections(conn: sqlite3.Connection, seed: str, max_depth: int) -> dict:
    owning_files = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'DEFINES' AND dst_id = ? AND src_id LIKE 'file:%'", (seed,))
    direct_upstream = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'CALLS' AND dst_id = ?", (seed,))
    direct_downstream = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'CALLS' AND src_id = ?", (seed,))
    direct_tests = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'COVERS' AND dst_id = ?", (seed,))
    direct_rules = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'GOVERNS' AND dst_id = ?", (seed,))

    direct_imports: list[tuple[str, str, str]] = []
    for file_src, _, _ in owning_files:
        direct_imports.extend(fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'IMPORTS' AND src_id = ?", (file_src,)))

    return {
        "seed_kind": "function",
        "owning_files": owning_files,
        "direct_upstream": direct_upstream,
        "direct_downstream": direct_downstream,
        "direct_tests": direct_tests,
        "direct_rules": direct_rules,
        "direct_imports": direct_imports,
        "downstream_paths": recursive_paths(conn, seed, "CALLS", max_depth, reverse=False),
        "upstream_paths": recursive_paths(conn, seed, "CALLS", max_depth, reverse=True),
        "import_paths": [path for file_src, _, _ in owning_files for path in recursive_paths(conn, file_src, "IMPORTS", max_depth, reverse=False)],
        "reverse_import_paths": [path for file_src, _, _ in owning_files for path in recursive_paths(conn, file_src, "IMPORTS", max_depth, reverse=True)],
    }


def file_report_sections(conn: sqlite3.Connection, seed: str, max_depth: int) -> dict:
    direct_upstream = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'IMPORTS' AND dst_id = ?", (seed,))
    direct_downstream = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'IMPORTS' AND src_id = ?", (seed,))
    direct_rules = fetch_all(conn, "SELECT src_id, edge_type, dst_id FROM edges WHERE edge_type = 'GOVERNS' AND dst_id = ?", (seed,))
    return {
        "seed_kind": "file",
        "owning_files": [(seed, "SELF", seed)],
        "direct_upstream": direct_upstream,
        "direct_downstream": direct_downstream,
        "direct_tests": [],
        "direct_rules": direct_rules,
        "direct_imports": direct_downstream,
        "downstream_paths": recursive_paths(conn, seed, "IMPORTS", max_depth, reverse=False),
        "upstream_paths": recursive_paths(conn, seed, "IMPORTS", max_depth, reverse=True),
        "import_paths": recursive_paths(conn, seed, "IMPORTS", max_depth, reverse=False),
        "reverse_import_paths": recursive_paths(conn, seed, "IMPORTS", max_depth, reverse=True),
    }


def reference_hints_payload(seed_detail: dict | None) -> dict:
    attrs = (seed_detail or {}).get("attrs", {})
    return attrs.get("reference_hints", {}) or {}


def relationship_payload(seed_detail: dict | None, sections: dict) -> dict:
    attrs = (seed_detail or {}).get("attrs", {})
    confirmed_edges = [
        {"src": src_id, "edge_type": edge_type, "dst": dst_id}
        for src_id, edge_type, dst_id in (
            sections["owning_files"]
            + sections["direct_upstream"]
            + sections["direct_downstream"]
            + sections["direct_tests"]
            + sections["direct_rules"]
            + sections["direct_imports"]
        )
    ]
    high_confidence_hints = [
        {"type": "sql_query_hint", "value": value}
        for value in attrs.get("unresolved_sql_hints", [])
    ]
    metadata_only = []
    for view_hint in attrs.get("sql_view_hints", []):
        metadata_only.append({"type": "sql_view_hint", **view_hint})
    for name, values in reference_hints_payload(seed_detail).items():
        if values:
            metadata_only.append({"type": f"reference_{name}", "values": values})
    return {
        "confirmed_edges": confirmed_edges,
        "high_confidence_hints": high_confidence_hints,
        "metadata_only": metadata_only,
    }


def top_risks_payload(sections: dict, risk_api: str, risk_state: str, risk_coverage: str) -> list[str]:
    risks: list[str] = []
    if risk_api == "high":
        risks.append("This seed has direct upstream dependents, so signature or behavior changes can break callers.")
    if risk_state == "high":
        risks.append("This seed has direct downstream links or governing rules, so side-effect changes need extra care.")
    if risk_coverage != "covered-by-direct-tests":
        risks.append("Direct test coverage is missing or unavailable, so manual verification matters more.")
    if not risks:
        risks.append("Direct impact looks contained, but verify behavior with the nearest targeted test.")
    return risks[:3]


def next_tests_payload(sections: dict, seed: str) -> list[str]:
    direct_tests = [src_id for src_id, _, _ in sections["direct_tests"]]
    if direct_tests:
        return [f"Run direct test seed `{item}`." for item in direct_tests]
    return [f"Run the smallest test that exercises `{seed}` after the edit."]


def key_evidence_paths_payload(seed_detail: dict | None, evidence_lines: list[str], changed_files: list[str]) -> list[str]:
    paths: list[str] = []
    if seed_detail and seed_detail.get("path"):
        paths.append(seed_detail["path"])
    paths.extend(changed_files)
    for line in evidence_lines:
        if " from `" in line:
            candidate = line.split(" from `", 1)[1].split("`", 1)[0]
            paths.append(candidate)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in paths:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered[:6]


def brief_payload(
    *,
    seed: str,
    seed_reason: str | None,
    changed_files: list[str],
    sections: dict,
    build_decision: dict | None,
    top_risks: list[str],
    next_tests: list[str],
    key_evidence_paths: list[str],
    next_step: str | None,
) -> dict:
    decision = build_decision or {}
    return {
        "selected_seed": seed,
        "why_this_seed": seed_reason or "seed selected from current context",
        "changed_files_summary": changed_files or ["none"],
        "direct_impact_summary": {
            "callers": len(sections["direct_upstream"]),
            "callees": len(sections["direct_downstream"]),
            "tests": len(sections["direct_tests"]),
            "rules": len(sections["direct_rules"]),
        },
        "build_trust_summary": {
            "build_mode": decision.get("build_mode"),
            "trust_level": decision.get("trust_level"),
            "reason_codes": decision.get("reason_codes", []),
            "verification_status": decision.get("verification_status"),
        },
        "top_risks": top_risks[:3],
        "next_tests": next_tests[:3],
        "key_evidence_paths": key_evidence_paths[:4],
        "next_step": next_step or "Read the brief report, then edit the code if the selected seed looks right.",
    }


def write_markdown_report(
    *,
    report_path: pathlib.Path,
    mode: str,
    task_id: str,
    git_sha: str,
    seed: str,
    sections: dict,
    detected_adapter: str,
    detected_profile: str,
    seed_detail: dict | None,
    changed_files: list[str],
    risk_api: str,
    risk_state: str,
    risk_coverage: str,
    top_risks: list[str],
    next_tests: list[str],
    evidence_lines: list[str],
    key_evidence_paths: list[str],
    mermaid: str,
    brief: dict,
) -> None:
    attrs = (seed_detail or {}).get("attrs", {})
    reference_hints = reference_hints_payload(seed_detail)
    if mode == "brief":
        metadata_lines = ["## Definition metadata"]
        if seed_detail:
            metadata_keys = [
                "definition_kind",
                "qualified_name",
                "sql_kind",
                "language",
                "is_component",
                "is_hook",
            ]
            added_metadata = False
            for key in metadata_keys:
                if key not in attrs:
                    continue
                value = attrs.get(key)
                if isinstance(value, list):
                    rendered = ", ".join(str(item) for item in value) if value else "none"
                else:
                    rendered = str(value)
                metadata_lines.append(f"- {key}: {rendered}")
                added_metadata = True
            if not added_metadata:
                metadata_lines.append("- none")
        else:
            metadata_lines.append("- unavailable")

        hint_lines = [
            "## Reference hints",
            f"- imports: {', '.join(reference_hints.get('imports', [])) or 'none'}",
            f"- exports: {', '.join(reference_hints.get('exports', [])) or 'none'}",
            f"- references: {', '.join(reference_hints.get('references', [])) or 'none'}",
            f"- resolved_call_targets: {', '.join(reference_hints.get('resolved_call_targets', [])) or 'none'}",
        ]
        impact = brief["direct_impact_summary"]
        trust = brief["build_trust_summary"]
        lines = [
            "# Impact Brief",
            "",
            f"- selected_seed: `{brief['selected_seed']}`",
            f"- why_this_seed: {brief['why_this_seed']}",
            f"- changed_files: {', '.join(brief['changed_files_summary'])}",
            f"- direct_impact: callers={impact['callers']}, callees={impact['callees']}, tests={impact['tests']}, rules={impact['rules']}",
            f"- build_trust: mode={trust.get('build_mode') or 'unknown'}, trust={trust.get('trust_level') or 'unknown'}, reasons={', '.join(trust.get('reason_codes', [])) or 'none'}, verification={trust.get('verification_status') or 'skipped'}",
            f"- top_risks: {' | '.join(brief['top_risks']) if brief['top_risks'] else 'none'}",
            f"- next_tests: {' | '.join(brief['next_tests']) if brief['next_tests'] else 'none'}",
            f"- next_step: {brief['next_step']}",
            "",
            "## Direct Impact",
            f"- callers: {', '.join(src_id for src_id, _, _ in sections['direct_upstream']) or 'none'}",
            f"- callees: {', '.join(dst_id for _, _, dst_id in sections['direct_downstream']) or 'none'}",
            f"- tests: {', '.join(src_id for src_id, _, _ in sections['direct_tests']) or 'none'}",
            f"- rules: {', '.join(src_id for src_id, _, _ in sections['direct_rules']) or 'none'}",
            "",
            *metadata_lines,
            "",
            *hint_lines,
            "",
            "## Key evidence paths",
            *[f"- `{item}`" for item in key_evidence_paths[:4]],
            "",
            "## Post-change note",
            "- pending",
        ]
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    else:
        lines = [
            "# Impact Report",
            "",
            "## Task",
            f"- task_id: {task_id}",
            f"- generated_at: {utc_now()}",
            f"- git_sha: {git_sha}",
            f"- seed: {seed}",
            f"- seed_kind: {sections['seed_kind']}",
            f"- detected_adapter: {detected_adapter}",
            f"- detected_profile: {detected_profile}",
            f"- report_mode: {mode}",
            f"- changed_files: {', '.join(changed_files) if changed_files else 'none'}",
            "",
            "## Definition metadata",
        ]
    if seed_detail:
        lines.append(f"- node_path: `{seed_detail['path']}`")
        lines.append(f"- node_symbol: `{seed_detail['symbol'] or seed_detail['name']}`")
        for key, value in sorted(attrs.items()):
            if key == "reference_hints":
                continue
            if mode == "brief" and key not in {"definition_kind", "qualified_name", "sql_kind", "language", "resolved_sql_targets", "unresolved_sql_hints"}:
                continue
            if isinstance(value, list):
                rendered = ", ".join(str(item) for item in value) if value else "none"
            else:
                rendered = str(value)
            lines.append(f"- {key}: {rendered}")
    else:
        lines.append("- unavailable")

    lines.extend(
        [
            "",
            "## Reference hints",
            f"- imports: {', '.join(reference_hints.get('imports', [])) or 'none'}",
            f"- exports: {', '.join(reference_hints.get('exports', [])) or 'none'}",
            f"- references: {', '.join(reference_hints.get('references', [])) or 'none'}",
            f"- resolved_call_targets: {', '.join(reference_hints.get('resolved_call_targets', [])) or 'none'}",
        ]
    )

    lines.extend(["", "## Direct Impact"])
    if sections["seed_kind"] == "function":
        lines.append("- owning file:")
        lines.extend([f"  - `{src_id}`" for src_id, _, _ in sections["owning_files"]] or ["  - none"])
    else:
        lines.append("- seed file:")
        lines.append(f"  - `{seed}`")
    lines.append("- direct callers/importers:")
    lines.extend([f"  - `{src_id}` --{edge_type}--> `{dst_id}`" for src_id, edge_type, dst_id in sections["direct_upstream"]] or ["  - none"])
    lines.append("- direct callees/imports:")
    lines.extend([f"  - `{src_id}` --{edge_type}--> `{dst_id}`" for src_id, edge_type, dst_id in sections["direct_downstream"]] or ["  - none"])
    lines.append("- direct tests:")
    lines.extend([f"  - `{src_id}`" for src_id, _, _ in sections["direct_tests"]] or ["  - none"])
    lines.append("- direct rules:")
    lines.extend([f"  - `{src_id}`" for src_id, _, _ in sections["direct_rules"]] or ["  - none"])
    lines.append("- direct file imports:")
    lines.extend([f"  - `{src_id}` --IMPORTS--> `{dst_id}`" for src_id, _, dst_id in sections["direct_imports"]] or ["  - none"])

    if mode != "brief":
        lines.extend(
            [
                "",
                "## Transitive Impact",
                f"- max_depth: {attrs.get('max_depth', 'configured')}",
                "- downstream paths:",
            ]
        )
        lines.extend([f"  - `{path}`" for path in sections["downstream_paths"]] or ["  - none"])
        lines.append("- upstream paths:")
        lines.extend([f"  - `{path}`" for path in sections["upstream_paths"]] or ["  - none"])
        lines.append("- import paths:")
        lines.extend([f"  - `{path}`" for path in sections["import_paths"]] or ["  - none"])
        lines.append("- reverse import paths:")
        lines.extend([f"  - `{path}`" for path in sections["reverse_import_paths"]] or ["  - none"])

    lines.extend(
        [
            "",
            "## Top risks",
            *[f"- {item}" for item in top_risks],
            "",
            "## Next tests",
            *[f"- {item}" for item in next_tests],
            "",
            "## Key evidence paths",
            *[f"- `{item}`" for item in key_evidence_paths],
            "",
            "## Risks",
            f"- api_compatibility: {risk_api}",
            f"- state_or_side_effects: {risk_state}",
            f"- coverage_status: {risk_coverage}",
            "",
            "## Evidence",
        ]
    )
    lines.extend(evidence_lines or ["- no direct evidence rows found"])
    lines.extend(
        [
            "",
            "## Mermaid",
            "```mermaid",
            mermaid.rstrip(),
            "```",
            "",
            "## Post-change note",
            "- pending",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(
    *,
    workspace_root: pathlib.Path,
    config_path: pathlib.Path,
    task_id: str,
    seed: str,
    max_depth: int | None = None,
    mode: str = "default",
    changed_files: list[str] | None = None,
    seed_selection: dict | None = None,
    build_decision: dict | None = None,
    next_step: str | None = None,
) -> dict:
    config = load_config(config_path)
    paths = graph_paths(workspace_root, config)
    report_dir = paths["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    git = get_git_context(workspace_root)
    max_depth = max_depth or config["impact"]["max_depth"]
    changed_files = [item.replace("\\", "/") for item in (changed_files or [])]
    detected_adapter = resolved_language_adapter(workspace_root, config_path)
    project_root = project_root_for(workspace_root, config)
    detected_profile = detect_project_profile_name(project_root, config, detected_adapter)

    with sqlite3.connect(paths["db_path"]) as conn:
        seed_row = conn.execute("SELECT node_id, kind FROM nodes WHERE node_id = ?", (seed,)).fetchone()
        if not seed_row:
            raise SystemExit(f"Seed node not found: {seed}")

        _, seed_kind = seed_row
        seed_detail = node_details(conn, seed)
        if seed_kind == "file":
            sections = file_report_sections(conn, seed, max_depth)
        else:
            sections = function_report_sections(conn, seed, max_depth)

        related_test_names = [src_id for src_id, _, _ in sections["direct_tests"]]
        related_rule_names = [src_id for src_id, _, _ in sections["direct_rules"]]
        evidence_lines = evidence_for_edges(
            conn,
            sections["owning_files"] + sections["direct_upstream"] + sections["direct_downstream"] + sections["direct_tests"] + sections["direct_rules"] + sections["direct_imports"],
        )

    risk_api = "high" if sections["direct_upstream"] else "low"
    risk_state = "high" if sections["direct_rules"] or sections["direct_downstream"] else "medium"
    risk_coverage = "covered-by-direct-tests" if related_test_names else "coverage-unavailable-until-after-edit"

    mermaid_edges = sections["direct_upstream"] + sections["direct_downstream"] + sections["direct_tests"] + sections["direct_rules"] + sections["direct_imports"]
    if sections["seed_kind"] == "function":
        mermaid_edges = sections["owning_files"] + mermaid_edges
    mermaid = mermaid_from_edges(mermaid_edges, seed)
    report_path = report_dir / f"impact-{task_id}.md"
    json_report_path = report_dir / f"impact-{task_id}.json"
    mermaid_path = report_dir / f"impact-{task_id}.mmd"
    seed_detail = dict(seed_detail or {})
    if seed_detail:
        seed_detail.setdefault("attrs", {})
        seed_detail["attrs"]["max_depth"] = max_depth
    top_risks = top_risks_payload(sections, risk_api, risk_state, risk_coverage)
    next_tests = next_tests_payload(sections, seed)
    key_evidence_paths = key_evidence_paths_payload(seed_detail, evidence_lines, changed_files)
    relationships = relationship_payload(seed_detail, sections)
    brief = brief_payload(
        seed=seed,
        seed_reason=(seed_selection or {}).get("reason"),
        changed_files=changed_files,
        sections=sections,
        build_decision=build_decision,
        top_risks=top_risks,
        next_tests=next_tests,
        key_evidence_paths=key_evidence_paths,
        next_step=next_step,
    )
    json_payload = {
        "task_id": task_id,
        "generated_at": utc_now(),
        "git_sha": git["git_sha"],
        "mode": mode,
        "seed": seed,
        "seed_kind": sections["seed_kind"],
        "changed_files": changed_files,
        "detected_adapter": detected_adapter,
        "detected_profile": detected_profile,
        "definition": seed_detail or {"node_id": seed, "kind": sections["seed_kind"]},
        "reference_hints": reference_hints_payload(seed_detail),
        "direct": {
            "owning_files": [src_id for src_id, _, _ in sections["owning_files"]],
            "upstream": [{"src": src_id, "edge_type": edge_type, "dst": dst_id} for src_id, edge_type, dst_id in sections["direct_upstream"]],
            "downstream": [{"src": src_id, "edge_type": edge_type, "dst": dst_id} for src_id, edge_type, dst_id in sections["direct_downstream"]],
            "tests": related_test_names,
            "rules": related_rule_names,
            "imports": [{"src": src_id, "edge_type": edge_type, "dst": dst_id} for src_id, edge_type, dst_id in sections["direct_imports"]],
        },
        "top_risks": top_risks,
        "next_tests": next_tests,
        "key_evidence_paths": key_evidence_paths,
        "relationships": relationships,
        "brief": brief,
        "seed_selection": seed_selection or {},
        "build_decision": build_decision or {},
        "transitive": {
            "max_depth": max_depth,
            "downstream_paths": sections["downstream_paths"],
            "upstream_paths": sections["upstream_paths"],
            "import_paths": sections["import_paths"],
            "reverse_import_paths": sections["reverse_import_paths"],
        },
        "risk_levels": {
            "api_compatibility": risk_api,
            "state_or_side_effects": risk_state,
            "coverage_status": risk_coverage,
        },
        "evidence_lines": evidence_lines,
    }

    write_markdown_report(
        report_path=report_path,
        mode=mode,
        task_id=task_id,
        git_sha=git["git_sha"],
        seed=seed,
        sections=sections,
        detected_adapter=detected_adapter,
        detected_profile=detected_profile,
        seed_detail=seed_detail,
        changed_files=changed_files,
        risk_api=risk_api,
        risk_state=risk_state,
        risk_coverage=risk_coverage,
        top_risks=top_risks,
        next_tests=next_tests,
        evidence_lines=evidence_lines,
        key_evidence_paths=key_evidence_paths,
        mermaid=mermaid,
        brief=brief,
    )
    json_report_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mermaid_path.write_text(mermaid, encoding="utf-8")

    with sqlite3.connect(paths["db_path"]) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO impact_reports (report_id, task_id, seed_node_id, git_sha, report_path, attrs_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"impact-{task_id}",
                task_id,
                seed,
                git["git_sha"],
                str(report_path.relative_to(workspace_root)),
                json.dumps({"max_depth": max_depth, "seed_kind": sections["seed_kind"], "mode": mode, "json_report_path": str(json_report_path.relative_to(workspace_root)), "brief": brief}, ensure_ascii=False),
            ),
        )
        conn.commit()

    task_run_id = record_task_run(
        db_path=paths["db_path"],
        task_id=task_id,
        seed_node_id=seed,
        command_name="report",
        detected_adapter=detected_adapter,
        report_path=str(report_path.relative_to(workspace_root)),
        status="completed",
        attrs={
            "seed_kind": sections["seed_kind"],
            "mode": mode,
            "direct_counts": {
                "upstream": len(sections["direct_upstream"]),
                "downstream": len(sections["direct_downstream"]),
                "tests": len(sections["direct_tests"]),
                "rules": len(sections["direct_rules"]),
            },
        },
    )

    return {
        "task_id": task_id,
        "seed": seed,
        "git_sha": git["git_sha"],
        "report_path": str(report_path),
        "json_report_path": str(json_report_path),
        "mermaid_path": str(mermaid_path),
        "task_run_id": task_run_id,
        "detected_adapter": detected_adapter,
        "detected_profile": detected_profile,
        "mode": mode,
        "brief": brief,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an impact report from the direct-edge graph")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".code-impact-guardian/config.json", help="Config path")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--seed", required=True, help="Seed node id")
    parser.add_argument("--max-depth", type=int, default=None, help="Override transitive depth")
    parser.add_argument("--mode", choices=["brief", "default", "full"], default="default", help="Report detail mode")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file relative to project root")
    args = parser.parse_args()
    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()
    summary = generate_report(
        workspace_root=workspace_root,
        config_path=config_path,
        task_id=args.task_id,
        seed=args.seed,
        max_depth=args.max_depth,
        mode=args.mode,
        changed_files=args.changed_file,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
