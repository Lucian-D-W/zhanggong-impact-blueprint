#!/usr/bin/env python3
import argparse
import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from build_graph import get_git_context, graph_paths, load_config, record_task_run, resolved_language_adapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


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


def generate_report(*, workspace_root: pathlib.Path, config_path: pathlib.Path, task_id: str, seed: str, max_depth: int | None = None) -> dict:
    config = load_config(config_path)
    paths = graph_paths(workspace_root, config)
    report_dir = paths["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    git = get_git_context(workspace_root)
    max_depth = max_depth or config["impact"]["max_depth"]

    with sqlite3.connect(paths["db_path"]) as conn:
        seed_row = conn.execute("SELECT node_id, kind FROM nodes WHERE node_id = ?", (seed,)).fetchone()
        if not seed_row:
            raise SystemExit(f"Seed node not found: {seed}")

        _, seed_kind = seed_row
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
    mermaid_path = report_dir / f"impact-{task_id}.mmd"

    lines = [
        "# Impact Report",
        "",
        "## Task",
        f"- task_id: {task_id}",
        f"- generated_at: {utc_now()}",
        f"- git_sha: {git['git_sha']}",
        f"- seed: {seed}",
        f"- seed_kind: {sections['seed_kind']}",
        "",
        "## Direct Impact",
    ]
    if sections["seed_kind"] == "function":
        lines.append("- owning file:")
        lines.extend([f"  - `{src_id}`" for src_id, _, _ in sections["owning_files"]] or ["  - none"])
    else:
        lines.append("- seed file:")
        lines.append(f"  - `{seed}`")

    upstream_label = "direct upstream callers:" if sections["seed_kind"] == "function" else "direct upstream importers:"
    downstream_label = "direct downstream callees:" if sections["seed_kind"] == "function" else "direct downstream imports:"
    lines.append(f"- {upstream_label}")
    lines.extend([f"  - `{src_id}` --{edge_type}--> `{dst_id}`" for src_id, edge_type, dst_id in sections["direct_upstream"]] or ["  - none"])
    lines.append(f"- {downstream_label}")
    lines.extend([f"  - `{src_id}` --{edge_type}--> `{dst_id}`" for src_id, edge_type, dst_id in sections["direct_downstream"]] or ["  - none"])
    lines.append("- direct tests:")
    lines.extend([f"  - `{src_id}`" for src_id in related_test_names] or ["  - none"])
    lines.append("- direct rules:")
    lines.extend([f"  - `{src_id}`" for src_id in related_rule_names] or ["  - none"])

    if sections["seed_kind"] == "function":
        lines.append("- direct file imports:")
    else:
        lines.append("- direct file imports:")
    lines.extend([f"  - `{src_id}` --IMPORTS--> `{dst_id}`" for src_id, _, dst_id in sections["direct_imports"]] or ["  - none"])

    lines.extend(
        [
            "",
            "## Transitive Impact",
            f"- max_depth: {max_depth}",
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
    mermaid_path.write_text(mermaid, encoding="utf-8")

    detected_adapter = resolved_language_adapter(workspace_root, config_path)

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
                json.dumps({"max_depth": max_depth, "seed_kind": sections["seed_kind"]}, ensure_ascii=False),
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
        "mermaid_path": str(mermaid_path),
        "task_run_id": task_run_id,
        "detected_adapter": detected_adapter,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an impact report from the direct-edge graph")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".code-impact-guardian/config.json", help="Config path")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--seed", required=True, help="Seed node id")
    parser.add_argument("--max-depth", type=int, default=None, help="Override transitive depth")
    args = parser.parse_args()
    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()
    summary = generate_report(workspace_root=workspace_root, config_path=config_path, task_id=args.task_id, seed=args.seed, max_depth=args.max_depth)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
