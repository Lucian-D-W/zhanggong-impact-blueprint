#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from adapters import (
    AdapterGraph,
    SQL_POSTGRES_ADAPTER,
    collect_adapter_graph,
    configured_supplemental_adapters,
    detect_language_adapter,
    detect_project_profile_name,
    detect_supplemental_adapters,
    file_node_id,
    rule_node_id,
)
from doc_sources import collect_rule_documents_from_sources
from incremental_refresh import load_manifest, refresh_plan, save_manifest


@dataclass
class Node:
    node_id: str
    kind: str
    name: str
    path: str
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    attrs_json: str = "{}"


@dataclass
class Evidence:
    evidence_id: str
    repo_source_id: str
    git_sha: str
    file_path: str
    start_line: int | None
    end_line: int | None
    diff_ref: str | None
    blame_ref: str | None
    permalink: str | None
    stable_link: str | None
    extractor: str
    confidence: float
    attrs_json: str


@dataclass
class Edge:
    src_id: str
    edge_type: str
    dst_id: str
    evidence_id: str | None = None
    confidence: float = 1.0
    attrs_json: str = "{}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config(config_path: pathlib.Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def schema_path_for(workspace_root: pathlib.Path) -> pathlib.Path:
    return workspace_root / ".code-impact-guardian" / "schema.sql"


def graph_paths(workspace_root: pathlib.Path, config: dict) -> dict:
    graph = config["graph"]
    return {
        "db_path": workspace_root / graph["db_path"],
        "report_dir": workspace_root / graph["report_dir"],
        "build_log_path": workspace_root / graph["build_log_path"],
        "test_results_path": workspace_root / graph["test_results_path"],
    }


def project_root_for(workspace_root: pathlib.Path, config: dict) -> pathlib.Path:
    return (workspace_root / config["project_root"]).resolve()


def repo_source_id(workspace_root: pathlib.Path) -> str:
    return workspace_root.resolve().name


def get_git_context(workspace_root: pathlib.Path) -> dict:
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        diff_ref = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace_root,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        blame_ref = git_sha
    except subprocess.CalledProcessError:
        git_sha = "UNCOMMITTED"
        diff_ref = "WORKTREE"
        blame_ref = None
    return {"git_sha": git_sha, "diff_ref": diff_ref, "blame_ref": blame_ref}


def ensure_schema(db_path: pathlib.Path, schema_path: pathlib.Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end_marker = "\n---\n"
    end_index = text.find(end_marker, 4)
    if end_index == -1:
        return {}, text
    block = text[4:end_index]
    body = text[end_index + len(end_marker) :]
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            data.setdefault(current_key, [])
            assert isinstance(data[current_key], list)
            data[current_key].append(line.split("- ", 1)[1].strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        data[current_key] = value if value else []
    return data, body


def attrs_dict(attrs_json: str | None) -> dict:
    if not attrs_json:
        return {}
    return json.loads(attrs_json)


def make_evidence_id(*parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()
    return f"ev:{digest[:16]}"


def make_evidence(
    *,
    workspace_root: pathlib.Path,
    git: dict,
    extractor: str,
    relative_path: str,
    start_line: int | None,
    end_line: int | None,
    attrs: dict | None = None,
    confidence: float = 1.0,
) -> Evidence:
    attrs = attrs or {}
    return Evidence(
        evidence_id=make_evidence_id(extractor, relative_path, str(start_line), str(end_line), json.dumps(attrs, sort_keys=True)),
        repo_source_id=repo_source_id(workspace_root),
        git_sha=git["git_sha"],
        file_path=relative_path,
        start_line=start_line,
        end_line=end_line,
        diff_ref=git["diff_ref"],
        blame_ref=git["blame_ref"],
        permalink=None,
        stable_link=None,
        extractor=extractor,
        confidence=confidence,
        attrs_json=json.dumps(attrs, ensure_ascii=False, sort_keys=True),
    )


def clear_graph_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM rule_documents")
    conn.execute("DELETE FROM evidence")
    conn.execute("DELETE FROM nodes")


def upsert_nodes(conn: sqlite3.Connection, nodes: list[Node]) -> None:
    conn.executemany(
        """
        INSERT INTO nodes (node_id, kind, name, path, symbol, start_line, end_line, attrs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            kind = excluded.kind,
            name = excluded.name,
            path = excluded.path,
            symbol = excluded.symbol,
            start_line = excluded.start_line,
            end_line = excluded.end_line,
            attrs_json = excluded.attrs_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        [(node.node_id, node.kind, node.name, node.path, node.symbol, node.start_line, node.end_line, node.attrs_json) for node in nodes],
    )


def upsert_evidence(conn: sqlite3.Connection, evidence_rows: list[Evidence]) -> None:
    conn.executemany(
        """
        INSERT INTO evidence (
            evidence_id, repo_source_id, git_sha, file_path, start_line, end_line,
            diff_ref, blame_ref, permalink, stable_link, extractor, confidence, attrs_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
            repo_source_id = excluded.repo_source_id,
            git_sha = excluded.git_sha,
            file_path = excluded.file_path,
            start_line = excluded.start_line,
            end_line = excluded.end_line,
            diff_ref = excluded.diff_ref,
            blame_ref = excluded.blame_ref,
            permalink = excluded.permalink,
            stable_link = excluded.stable_link,
            extractor = excluded.extractor,
            confidence = excluded.confidence,
            attrs_json = excluded.attrs_json
        """,
        [
            (
                item.evidence_id,
                item.repo_source_id,
                item.git_sha,
                item.file_path,
                item.start_line,
                item.end_line,
                item.diff_ref,
                item.blame_ref,
                item.permalink,
                item.stable_link,
                item.extractor,
                item.confidence,
                item.attrs_json,
            )
            for item in evidence_rows
        ],
    )


def upsert_edges(conn: sqlite3.Connection, edges: list[Edge]) -> None:
    conn.executemany(
        """
        INSERT INTO edges (src_id, edge_type, dst_id, is_direct, evidence_id, confidence, attrs_json)
        VALUES (?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(src_id, edge_type, dst_id, is_direct) DO UPDATE SET
            evidence_id = excluded.evidence_id,
            confidence = excluded.confidence,
            attrs_json = excluded.attrs_json
        """,
        [(edge.src_id, edge.edge_type, edge.dst_id, edge.evidence_id, edge.confidence, edge.attrs_json) for edge in edges],
    )


def upsert_rule_documents(conn: sqlite3.Connection, rule_docs: list[tuple[str, str, str, str]]) -> None:
    conn.executemany(
        """
        INSERT INTO rule_documents (rule_node_id, markdown_path, frontmatter_json, body_markdown)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(rule_node_id) DO UPDATE SET
            markdown_path = excluded.markdown_path,
            frontmatter_json = excluded.frontmatter_json,
            body_markdown = excluded.body_markdown,
            updated_at = CURRENT_TIMESTAMP
        """,
        rule_docs,
    )


def next_edit_round_index(conn: sqlite3.Connection, task_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(round_index), 0) FROM edit_rounds WHERE task_id = ?", (task_id,)).fetchone()
    return int(row[0]) + 1


def record_task_run(
    *,
    db_path: pathlib.Path,
    task_id: str,
    seed_node_id: str,
    command_name: str,
    detected_adapter: str,
    report_path: str | None,
    status: str,
    attrs: dict | None = None,
) -> str:
    task_run_id = f"taskrun-{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO task_runs (
                task_run_id, task_id, seed_node_id, command_name,
                detected_adapter, report_path, status, attrs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_run_id,
                task_id,
                seed_node_id,
                command_name,
                detected_adapter,
                report_path,
                status,
                json.dumps(attrs or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    return task_run_id


def node_snapshot(conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT node_id, kind, name, path, symbol, start_line, end_line, attrs_json FROM nodes WHERE node_id = ?",
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
        "start_line": row[5],
        "end_line": row[6],
        "attrs": attrs_dict(row[7]),
    }


def relation_snapshot(conn: sqlite3.Connection, node_id: str) -> dict:
    node = node_snapshot(conn, node_id)
    if not node:
        return {
            "node_id": node_id,
            "kind": None,
            "callers": [],
            "callees": [],
            "tests": [],
            "rules": [],
            "importers": [],
            "imports": [],
        }
    if node["kind"] == "file":
        return {
            "node_id": node_id,
            "kind": "file",
            "callers": [],
            "callees": [],
            "tests": [],
            "rules": [row[0] for row in conn.execute("SELECT src_id FROM edges WHERE edge_type = 'GOVERNS' AND dst_id = ? ORDER BY src_id", (node_id,)).fetchall()],
            "importers": [row[0] for row in conn.execute("SELECT src_id FROM edges WHERE edge_type = 'IMPORTS' AND dst_id = ? ORDER BY src_id", (node_id,)).fetchall()],
            "imports": [row[0] for row in conn.execute("SELECT dst_id FROM edges WHERE edge_type = 'IMPORTS' AND src_id = ? ORDER BY dst_id", (node_id,)).fetchall()],
        }
    return {
        "node_id": node_id,
        "kind": node["kind"],
        "callers": [row[0] for row in conn.execute("SELECT src_id FROM edges WHERE edge_type = 'CALLS' AND dst_id = ? ORDER BY src_id", (node_id,)).fetchall()],
        "callees": [row[0] for row in conn.execute("SELECT dst_id FROM edges WHERE edge_type = 'CALLS' AND src_id = ? ORDER BY dst_id", (node_id,)).fetchall()],
        "tests": [row[0] for row in conn.execute("SELECT src_id FROM edges WHERE edge_type = 'COVERS' AND dst_id = ? ORDER BY src_id", (node_id,)).fetchall()],
        "rules": [row[0] for row in conn.execute("SELECT src_id FROM edges WHERE edge_type = 'GOVERNS' AND dst_id = ? ORDER BY src_id", (node_id,)).fetchall()],
        "importers": [],
        "imports": [],
    }


def snapshot_for_files(conn: sqlite3.Connection, file_paths: list[str]) -> dict:
    payload = {"files": {}, "functions_by_file": {}, "relations": {}}
    for file_path in sorted(set(file_paths)):
        file_id = file_node_id(file_path)
        file_row = node_snapshot(conn, file_id)
        if file_row:
            payload["files"][file_path] = file_row
        function_rows = conn.execute(
            """
            SELECT node_id, path, symbol, attrs_json
            FROM nodes
            WHERE kind = 'function' AND path = ?
            ORDER BY symbol
            """,
            (file_path,),
        ).fetchall()
        function_entries: list[dict] = []
        for node_id, path, symbol, attrs_json in function_rows:
            entry = {"node_id": node_id, "path": path, "symbol": symbol, "attrs": attrs_dict(attrs_json)}
            function_entries.append(entry)
            payload["relations"][node_id] = relation_snapshot(conn, node_id)
        payload["functions_by_file"][file_path] = function_entries
    return payload


def write_edit_round(
    *,
    db_path: pathlib.Path,
    task_id: str,
    task_run_id: str,
    seed_node_id: str,
    changed_files: list[str],
    summary: dict,
) -> str:
    edit_round_id = f"editround-{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(db_path) as conn:
        round_index = next_edit_round_index(conn, task_id)
        conn.execute(
            """
            INSERT INTO edit_rounds (
                edit_round_id, task_id, task_run_id, round_index,
                seed_node_id, changed_files_json, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edit_round_id,
                task_id,
                task_run_id,
                round_index,
                seed_node_id,
                json.dumps(changed_files, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        conn.commit()
    return edit_round_id


def write_file_diffs(db_path: pathlib.Path, edit_round_id: str, file_diffs: list[dict]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO file_diffs (
                edit_round_id, file_path, diff_kind, before_hash, after_hash, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    edit_round_id,
                    item["file_path"],
                    item["diff_kind"],
                    item.get("before_hash"),
                    item.get("after_hash"),
                    json.dumps(item.get("summary", {}), ensure_ascii=False),
                )
                for item in file_diffs
            ],
        )
        conn.commit()


def write_symbol_diffs(db_path: pathlib.Path, edit_round_id: str, symbol_diffs: list[dict]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO symbol_diffs (
                edit_round_id, file_path, symbol_kind, diff_kind,
                before_symbol, after_symbol, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    edit_round_id,
                    item["file_path"],
                    item["symbol_kind"],
                    item["diff_kind"],
                    item.get("before_symbol"),
                    item.get("after_symbol"),
                    json.dumps(item.get("summary", {}), ensure_ascii=False),
                )
                for item in symbol_diffs
            ],
        )
        conn.commit()


def resolved_language_adapter(workspace_root: pathlib.Path, config_path: pathlib.Path) -> str:
    config = load_config(config_path)
    project_root = project_root_for(workspace_root, config)
    return detect_language_adapter(project_root, config)


def resolved_supplemental_adapters(workspace_root: pathlib.Path, config_path: pathlib.Path) -> list[str]:
    config = load_config(config_path)
    project_root = project_root_for(workspace_root, config)
    return detect_supplemental_adapters(project_root, config)


def collect_rule_documents(
    *,
    workspace_root: pathlib.Path,
    project_root: pathlib.Path,
    config: dict,
    git: dict,
    known_nodes: set[str],
) -> tuple[list[Node], list[Edge], list[Evidence], list[tuple[str, str, str, str]]]:
    documents = collect_rule_documents_from_sources(project_root, config)
    if not documents:
        return [], [], [], []

    nodes: list[Node] = []
    edges: list[Edge] = []
    evidence_rows: list[Evidence] = []
    rule_docs: list[tuple[str, str, str, str]] = []

    for document in documents:
        relative = document["relative_path"]
        text = document["text"]
        frontmatter, body = parse_frontmatter(text)
        rule_name = str(frontmatter.get("id", pathlib.Path(relative).stem))
        governs = frontmatter.get("governs", [])
        if isinstance(governs, str):
            governs = [governs]
        markdown_file_id = file_node_id(relative)
        nodes.append(
            Node(
                markdown_file_id,
                "file",
                pathlib.PurePosixPath(relative).name,
                relative,
                attrs_json=json.dumps({"kind": "rule-file", "doc_source": document["source_adapter"]}, ensure_ascii=False),
            )
        )
        rule_id_full = rule_node_id(rule_name)
        nodes.append(
            Node(
                node_id=rule_id_full,
                kind="rule",
                name=rule_name,
                path=relative,
                symbol=rule_name,
                start_line=1,
                end_line=len(text.splitlines()),
                attrs_json=json.dumps({"summary": frontmatter.get("summary", ""), "doc_source": document["source_adapter"]}, ensure_ascii=False),
            )
        )
        define_evidence = make_evidence(
            workspace_root=workspace_root,
            git=git,
            extractor="markdown_rule",
            relative_path=relative,
            start_line=1,
            end_line=len(text.splitlines()),
            attrs={"edge_type": "DEFINES", "rule": rule_name},
        )
        evidence_rows.append(define_evidence)
        edges.append(Edge(markdown_file_id, "DEFINES", rule_id_full, define_evidence.evidence_id))
        rule_docs.append((rule_id_full, relative, json.dumps(frontmatter, ensure_ascii=False), body))

        for target_id in governs:
            if target_id not in known_nodes:
                continue
            governs_evidence = make_evidence(
                workspace_root=workspace_root,
                git=git,
                extractor="markdown_rule",
                relative_path=relative,
                start_line=1,
                end_line=len(text.splitlines()),
                attrs={"edge_type": "GOVERNS", "rule": rule_id_full, "target": target_id},
            )
            evidence_rows.append(governs_evidence)
            edges.append(Edge(rule_id_full, "GOVERNS", target_id, governs_evidence.evidence_id))
    return nodes, edges, evidence_rows, rule_docs


def adapter_graph_to_rows(
    *,
    workspace_root: pathlib.Path,
    git: dict,
    adapter_name: str,
    profile_name: str,
    adapter_graph: AdapterGraph,
) -> tuple[list[Node], list[Edge], list[Evidence]]:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    evidence_rows: list[Evidence] = []

    for file_record in adapter_graph.files:
        relative = file_record["path"]
        attrs = {
            "kind": "test-file" if file_record.get("is_test_file") else "source-file",
            "adapter": adapter_name,
            "profile": profile_name,
            "content_hash": file_record.get("content_hash"),
        }
        attrs.update(file_record.get("attrs", {}))
        nodes[file_node_id(relative)] = Node(
            node_id=file_node_id(relative),
            kind="file",
            name=pathlib.PurePosixPath(relative).name,
            path=relative,
            attrs_json=json.dumps(attrs, ensure_ascii=False),
        )

    for function_record in adapter_graph.functions:
        attrs = {
            "language": function_record["language"],
            "body_hash": function_record.get("body_hash"),
            "adapter": adapter_name,
            "profile": profile_name,
        }
        attrs.update(function_record.get("attrs", {}))
        nodes[function_record["node_id"]] = Node(
            node_id=function_record["node_id"],
            kind="function",
            name=function_record["name"],
            path=function_record["path"],
            symbol=function_record["symbol"],
            start_line=function_record["start_line"],
            end_line=function_record["end_line"],
            attrs_json=json.dumps(attrs, ensure_ascii=False),
        )
        evidence = make_evidence(
            workspace_root=workspace_root,
            git=git,
            extractor=f"{adapter_name}_define_scan",
            relative_path=function_record["path"],
            start_line=function_record["start_line"],
            end_line=function_record["end_line"],
            attrs={"edge_type": "DEFINES", "symbol": function_record["symbol"]},
        )
        evidence_rows.append(evidence)
        edges.append(Edge(file_node_id(function_record["path"]), "DEFINES", function_record["node_id"], evidence.evidence_id))

    for test_record in adapter_graph.tests:
        attrs = {
            "language": test_record["language"],
            "body_hash": test_record.get("body_hash"),
            "adapter": adapter_name,
            "profile": profile_name,
        }
        attrs.update(test_record.get("attrs", {}))
        nodes[test_record["node_id"]] = Node(
            node_id=test_record["node_id"],
            kind="test",
            name=test_record["name"],
            path=test_record["path"],
            symbol=test_record["symbol"],
            start_line=test_record["start_line"],
            end_line=test_record["end_line"],
            attrs_json=json.dumps(attrs, ensure_ascii=False),
        )
        evidence = make_evidence(
            workspace_root=workspace_root,
            git=git,
            extractor=f"{adapter_name}_test_scan",
            relative_path=test_record["path"],
            start_line=test_record["start_line"],
            end_line=test_record["end_line"],
            attrs={"edge_type": "DEFINES", "symbol": test_record["symbol"]},
        )
        evidence_rows.append(evidence)
        edges.append(Edge(file_node_id(test_record["path"]), "DEFINES", test_record["node_id"], evidence.evidence_id))

    for import_record in adapter_graph.imports:
        target_path = import_record["dst_id"].split("file:", 1)[1]
        if import_record["dst_id"] not in nodes:
            nodes[import_record["dst_id"]] = Node(
                node_id=import_record["dst_id"],
                kind="file",
                name=pathlib.PurePosixPath(target_path).name,
                path=target_path,
                attrs_json=json.dumps({"kind": "source-file", "adapter": adapter_name, "profile": profile_name}, ensure_ascii=False),
            )
        evidence = make_evidence(
            workspace_root=workspace_root,
            git=git,
            extractor=import_record["extractor"],
            relative_path=import_record["relative_path"],
            start_line=import_record["start_line"],
            end_line=import_record["end_line"],
            attrs={"edge_type": "IMPORTS", "target": import_record["dst_id"]},
        )
        evidence_rows.append(evidence)
        edges.append(Edge(import_record["src_id"], "IMPORTS", import_record["dst_id"], evidence.evidence_id))

    known_nodes = set(nodes)
    for edge_type, records in (("CALLS", adapter_graph.calls), ("COVERS", adapter_graph.covers)):
        for record in records:
            if record["src_id"] not in known_nodes or record["dst_id"] not in known_nodes:
                continue
            evidence = make_evidence(
                workspace_root=workspace_root,
                git=git,
                extractor=record["extractor"],
                relative_path=record["relative_path"],
                start_line=record["start_line"],
                end_line=record["end_line"],
                attrs={"edge_type": edge_type, "source": record["src_id"], "target": record["dst_id"]},
            )
            evidence_rows.append(evidence)
            edges.append(Edge(record["src_id"], edge_type, record["dst_id"], evidence.evidence_id))

    return list(nodes.values()), edges, evidence_rows


def unique_sql_target(hint: str, sql_index: dict[str, list[str]]) -> str | None:
    exact = sql_index.get(hint, [])
    if len(exact) == 1:
        return exact[0]
    base = sql_index.get(hint.split(".")[-1], [])
    if len(base) == 1:
        return base[0]
    return None


def augment_sql_hint_links(
    *,
    workspace_root: pathlib.Path,
    git: dict,
    nodes: dict[str, Node],
    edges: dict[tuple[str, str, str], Edge],
    evidence_rows: dict[str, Evidence],
    target_node_ids: set[str] | None = None,
) -> None:
    sql_index: dict[str, list[str]] = {}
    for node in nodes.values():
        if node.kind != "function":
            continue
        attrs = attrs_dict(node.attrs_json)
        if "sql_kind" not in attrs:
            continue
        qualified_name = attrs.get("qualified_name") or node.symbol or node.name
        for key in {qualified_name, str(qualified_name).split(".")[-1]}:
            sql_index.setdefault(str(key), []).append(node.node_id)

    for node in nodes.values():
        if node.kind != "function":
            continue
        if target_node_ids and node.node_id not in target_node_ids:
            continue
        attrs = attrs_dict(node.attrs_json)
        if "sql_kind" in attrs:
            continue
        hints = list(attrs.get("sql_query_hints", []))
        if not hints:
            continue
        resolved: list[str] = []
        unresolved: list[str] = []
        for hint in hints:
            target_id = unique_sql_target(hint, sql_index)
            if target_id:
                resolved.append(target_id)
                evidence = make_evidence(
                    workspace_root=workspace_root,
                    git=git,
                    extractor="cross_adapter_sql_hint",
                    relative_path=node.path,
                    start_line=node.start_line,
                    end_line=node.end_line,
                    attrs={"edge_type": "CALLS", "hint": hint, "target": target_id},
                    confidence=0.9,
                )
                evidence_rows[evidence.evidence_id] = evidence
                edges[(node.node_id, "CALLS", target_id)] = Edge(
                    node.node_id,
                    "CALLS",
                    target_id,
                    evidence.evidence_id,
                    confidence=0.9,
                    attrs_json=json.dumps({"hint": hint, "cross_adapter": True}, ensure_ascii=False),
                )
            else:
                unresolved.append(hint)
        attrs["resolved_sql_targets"] = sorted(set(resolved))
        attrs["unresolved_sql_hints"] = sorted(set(unresolved))
        node.attrs_json = json.dumps(attrs, ensure_ascii=False)


def fetch_existing_nodes(conn: sqlite3.Connection) -> dict[str, Node]:
    rows = conn.execute(
        "SELECT node_id, kind, name, path, symbol, start_line, end_line, attrs_json FROM nodes"
    ).fetchall()
    return {
        node_id: Node(
            node_id=node_id,
            kind=kind,
            name=name,
            path=path,
            symbol=symbol,
            start_line=start_line,
            end_line=end_line,
            attrs_json=attrs_json or "{}",
        )
        for node_id, kind, name, path, symbol, start_line, end_line, attrs_json in rows
    }


def node_ids_for_paths(conn: sqlite3.Connection, file_paths: list[str]) -> list[str]:
    if not file_paths:
        return []
    placeholders = ",".join("?" for _ in file_paths)
    rows = conn.execute(
        f"SELECT node_id FROM nodes WHERE path IN ({placeholders})",
        file_paths,
    ).fetchall()
    return [row[0] for row in rows]


def delete_paths_from_graph(conn: sqlite3.Connection, file_paths: list[str]) -> None:
    if not file_paths:
        return
    node_ids = node_ids_for_paths(conn, file_paths)
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        conn.execute(f"DELETE FROM edges WHERE src_id IN ({placeholders}) OR dst_id IN ({placeholders})", node_ids * 2)
        conn.execute(f"DELETE FROM nodes WHERE node_id IN ({placeholders})", node_ids)
    path_placeholders = ",".join("?" for _ in file_paths)
    conn.execute(f"DELETE FROM evidence WHERE file_path IN ({path_placeholders})", file_paths)
    conn.execute(f"DELETE FROM rule_documents WHERE markdown_path IN ({path_placeholders})", file_paths)


def function_and_test_ids_by_path(conn: sqlite3.Connection, file_path: str) -> set[str]:
    rows = conn.execute(
        "SELECT node_id FROM nodes WHERE path = ? AND kind IN ('function', 'test')",
        (file_path,),
    ).fetchall()
    return {row[0] for row in rows}


def has_external_incoming_edges(conn: sqlite3.Connection, file_paths: list[str]) -> bool:
    if not file_paths:
        return False
    placeholders = ",".join("?" for _ in file_paths)
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM edges e
        JOIN nodes src ON src.node_id = e.src_id
        JOIN nodes dst ON dst.node_id = e.dst_id
        WHERE dst.path IN ({placeholders})
          AND src.path NOT IN ({placeholders})
          AND e.edge_type IN ('CALLS', 'COVERS', 'GOVERNS', 'IMPORTS')
        """,
        file_paths + file_paths,
    ).fetchone()
    return bool(row and row[0])


def summary_from_db(
    *,
    conn: sqlite3.Connection,
    workspace_root: pathlib.Path,
    project_root: pathlib.Path,
    git: dict,
    config: dict,
    adapter_name: str,
    profile_name: str,
    supplemental_adapters: list[str],
    build_mode: str,
    changed_files: list[str],
    stale_reason: str,
    warnings: list[str] | None = None,
) -> dict:
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    evidence_count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    available_function_seeds = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'function' ORDER BY node_id").fetchall()]
    available_file_seeds = [row[0] for row in conn.execute("SELECT node_id FROM nodes WHERE kind = 'file' ORDER BY node_id").fetchall()]
    return {
        "timestamp": utc_now(),
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "git_sha": git["git_sha"],
        "node_count": node_count,
        "edge_count": edge_count,
        "evidence_count": evidence_count,
        "configured_language_adapter": config.get("language_adapter", "auto"),
        "configured_primary_adapter": config.get("primary_adapter", config.get("language_adapter", "auto")),
        "detected_adapter": adapter_name,
        "primary_adapter": adapter_name,
        "detected_profile": profile_name,
        "supplemental_adapters_configured": configured_supplemental_adapters(config),
        "supplemental_adapters_detected": supplemental_adapters,
        "available_function_seeds": available_function_seeds,
        "available_file_seeds": available_file_seeds,
        "build_mode": build_mode,
        "changed_files": changed_files,
        "stale_reason": stale_reason,
        "warnings": warnings or [],
    }


def build_graph(*, workspace_root: pathlib.Path, config_path: pathlib.Path, changed_files: list[str] | None = None, force_full: bool = False) -> dict:
    config = load_config(config_path)
    paths = graph_paths(workspace_root, config)
    paths["report_dir"].mkdir(parents=True, exist_ok=True)
    paths["build_log_path"].parent.mkdir(parents=True, exist_ok=True)
    ensure_schema(paths["db_path"], schema_path_for(workspace_root))
    project_root = project_root_for(workspace_root, config)
    git = get_git_context(workspace_root)
    adapter_name = detect_language_adapter(project_root, config)
    supplemental_adapters = detect_supplemental_adapters(project_root, config)
    profile_name = detect_project_profile_name(project_root, config, adapter_name)
    warnings: list[str] = []
    plan = refresh_plan(
        workspace_root=workspace_root,
        project_root=project_root,
        config=config,
        changed_files=changed_files,
    )
    if force_full:
        plan["build_mode"] = "full"
        plan["reason"] = "forced full rebuild"
    changed_files = [item.replace("\\", "/") for item in plan.get("changed_files", [])]
    adapter_order = [adapter_name, *supplemental_adapters]

    if plan["build_mode"] == "reused" and paths["db_path"].exists():
        with sqlite3.connect(paths["db_path"]) as conn:
            summary = summary_from_db(
                conn=conn,
                workspace_root=workspace_root,
                project_root=project_root,
                git=git,
                config=config,
                adapter_name=adapter_name,
                profile_name=profile_name,
                supplemental_adapters=supplemental_adapters,
                build_mode="reused",
                changed_files=[],
                stale_reason=plan["reason"],
                warnings=warnings,
            )
        save_manifest(workspace_root, {"timestamp": utc_now(), "files": plan["files"], "summary": summary})
        with paths["build_log_path"].open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return summary

    if plan["build_mode"] == "incremental" and paths["db_path"].exists():
        try:
            partial_nodes: dict[str, Node] = {}
            partial_edges: dict[tuple[str, str, str], Edge] = {}
            partial_evidence: dict[str, Evidence] = {}
            with sqlite3.connect(paths["db_path"]) as conn:
                if has_external_incoming_edges(conn, changed_files):
                    raise RuntimeError("external direct edges target the changed files")
                existing_nodes = fetch_existing_nodes(conn)
                before_ids_by_path = {file_path: function_and_test_ids_by_path(conn, file_path) for file_path in changed_files}

            for active_adapter in adapter_order:
                adapter_graph = collect_adapter_graph(project_root, config, active_adapter, include_files=changed_files)
                nodes, edges, evidence_rows = adapter_graph_to_rows(
                    workspace_root=workspace_root,
                    git=git,
                    adapter_name=active_adapter,
                    profile_name=profile_name,
                    adapter_graph=adapter_graph,
                )
                for node in nodes:
                    partial_nodes[node.node_id] = node
                for edge in edges:
                    partial_edges[(edge.src_id, edge.edge_type, edge.dst_id)] = edge
                for evidence in evidence_rows:
                    partial_evidence[evidence.evidence_id] = evidence

            for file_path in changed_files:
                before_ids = before_ids_by_path.get(file_path, set())
                after_ids = {
                    node.node_id
                    for node in partial_nodes.values()
                    if node.path == file_path and node.kind in {"function", "test"}
                }
                if before_ids and before_ids != after_ids:
                    raise RuntimeError(f"symbol set changed for {file_path}")

            combined_nodes = {node_id: node for node_id, node in existing_nodes.items() if node.path not in set(changed_files)}
            combined_nodes.update(partial_nodes)
            augment_sql_hint_links(
                workspace_root=workspace_root,
                git=git,
                nodes=combined_nodes,
                edges=partial_edges,
                evidence_rows=partial_evidence,
                target_node_ids=set(partial_nodes),
            )
            partial_nodes = {node_id: node for node_id, node in combined_nodes.items() if node.path in set(changed_files)}

            with sqlite3.connect(paths["db_path"]) as conn:
                delete_paths_from_graph(conn, changed_files)
                upsert_nodes(conn, list(partial_nodes.values()))
                upsert_evidence(conn, list(partial_evidence.values()))
                upsert_edges(conn, list(partial_edges.values()))
                conn.commit()
                summary = summary_from_db(
                    conn=conn,
                    workspace_root=workspace_root,
                    project_root=project_root,
                    git=git,
                    config=config,
                    adapter_name=adapter_name,
                    profile_name=profile_name,
                    supplemental_adapters=supplemental_adapters,
                    build_mode="incremental",
                    changed_files=changed_files,
                    stale_reason=plan["reason"],
                    warnings=warnings,
                )
            save_manifest(workspace_root, {"timestamp": utc_now(), "files": plan["files"], "summary": summary})
            with paths["build_log_path"].open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
            return summary
        except Exception as exc:
            warnings.append(f"incremental_refresh_fallback: {exc}")

    all_nodes: dict[str, Node] = {}
    all_edges: dict[tuple[str, str, str], Edge] = {}
    all_evidence: dict[str, Evidence] = {}
    rule_docs: list[tuple[str, str, str, str]] = []

    for active_adapter in adapter_order:
        try:
            adapter_graph = collect_adapter_graph(project_root, config, active_adapter)
        except Exception as exc:
            if active_adapter != adapter_name:
                warnings.append(f"supplemental {active_adapter} failed and was skipped: {exc}")
                continue
            raise
        nodes, edges, evidence_rows = adapter_graph_to_rows(
            workspace_root=workspace_root,
            git=git,
            adapter_name=active_adapter,
            profile_name=profile_name,
            adapter_graph=adapter_graph,
        )
        for node in nodes:
            all_nodes[node.node_id] = node
        for edge in edges:
            all_edges[(edge.src_id, edge.edge_type, edge.dst_id)] = edge
        for evidence in evidence_rows:
            all_evidence[evidence.evidence_id] = evidence

    augment_sql_hint_links(
        workspace_root=workspace_root,
        git=git,
        nodes=all_nodes,
        edges=all_edges,
        evidence_rows=all_evidence,
    )

    known_nodes = set(all_nodes)
    rule_nodes, rule_edges, rule_evidence, rule_docs = collect_rule_documents(
        workspace_root=workspace_root,
        project_root=project_root,
        config=config,
        git=git,
        known_nodes=known_nodes,
    )
    for node in rule_nodes:
        all_nodes[node.node_id] = node
    for edge in rule_edges:
        all_edges[(edge.src_id, edge.edge_type, edge.dst_id)] = edge
    for item in rule_evidence:
        all_evidence[item.evidence_id] = item

    with sqlite3.connect(paths["db_path"]) as conn:
        clear_graph_tables(conn)
        upsert_nodes(conn, list(all_nodes.values()))
        upsert_evidence(conn, list(all_evidence.values()))
        upsert_edges(conn, list(all_edges.values()))
        upsert_rule_documents(conn, rule_docs)
        conn.commit()
        summary = summary_from_db(
            conn=conn,
            workspace_root=workspace_root,
            project_root=project_root,
            git=git,
            config=config,
            adapter_name=adapter_name,
            profile_name=profile_name,
            supplemental_adapters=supplemental_adapters,
            build_mode="full",
            changed_files=changed_files,
            stale_reason=plan["reason"],
            warnings=warnings,
        )

    save_manifest(workspace_root, {"timestamp": utc_now(), "files": plan["files"], "summary": summary})
    with paths["build_log_path"].open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or refresh the direct-edge graph")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".code-impact-guardian/config.json", help="Config path")
    args = parser.parse_args()
    workspace_root = pathlib.Path(args.workspace_root).resolve()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = (workspace_root / config_path).resolve()
    summary = build_graph(workspace_root=workspace_root, config_path=config_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
