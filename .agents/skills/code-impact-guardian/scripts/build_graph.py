#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from adapters import (
    AdapterGraph,
    GENERIC_ADAPTER,
    detect_language_adapter,
    file_node_id,
    function_node_id,
    rule_node_id,
    test_node_id,
    collect_adapter_graph,
    matches_any,
)


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


def resolved_language_adapter(workspace_root: pathlib.Path, config_path: pathlib.Path) -> str:
    config = load_config(config_path)
    project_root = project_root_for(workspace_root, config)
    return detect_language_adapter(project_root, config)


def collect_rule_documents(*, workspace_root: pathlib.Path, project_root: pathlib.Path, config: dict, git: dict, known_nodes: set[str]) -> tuple[list[Node], list[Edge], list[Evidence], list[tuple[str, str, str, str]]]:
    rules_config = config.get("rules", {})
    rule_globs = rules_config.get("globs", [])
    if not rule_globs:
        return [], [], [], []

    nodes: list[Node] = []
    edges: list[Edge] = []
    evidence_rows: list[Evidence] = []
    rule_docs: list[tuple[str, str, str, str]] = []

    for rule_file in sorted(project_root.rglob("*.md")):
        relative = rule_file.relative_to(project_root).as_posix()
        if not matches_any(relative, rule_globs):
            continue
        text = rule_file.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        rule_name = str(frontmatter.get("id", pathlib.Path(relative).stem))
        governs = frontmatter.get("governs", [])
        if isinstance(governs, str):
            governs = [governs]
        markdown_file_id = file_node_id(relative)
        nodes.append(Node(markdown_file_id, "file", rule_file.name, relative, attrs_json=json.dumps({"kind": "rule-file"}, ensure_ascii=False)))
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
                attrs_json=json.dumps({"summary": frontmatter.get("summary", "")}, ensure_ascii=False),
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


def adapter_graph_to_rows(*, workspace_root: pathlib.Path, config: dict, git: dict, adapter_name: str, adapter_graph: AdapterGraph) -> tuple[list[Node], list[Edge], list[Evidence]]:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    evidence_rows: list[Evidence] = []

    for file_record in adapter_graph.files:
        relative = file_record["path"]
        nodes[file_node_id(relative)] = Node(
            node_id=file_node_id(relative),
            kind="file",
            name=pathlib.PurePosixPath(relative).name,
            path=relative,
            attrs_json=json.dumps({"kind": "test-file" if file_record.get("is_test_file") else "source-file", "adapter": adapter_name}, ensure_ascii=False),
        )

    for function_record in adapter_graph.functions:
        nodes[function_record["node_id"]] = Node(
            node_id=function_record["node_id"],
            kind="function",
            name=function_record["name"],
            path=function_record["path"],
            symbol=function_record["symbol"],
            start_line=function_record["start_line"],
            end_line=function_record["end_line"],
            attrs_json=json.dumps({"language": function_record["language"]}, ensure_ascii=False),
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
        nodes[test_record["node_id"]] = Node(
            node_id=test_record["node_id"],
            kind="test",
            name=test_record["name"],
            path=test_record["path"],
            symbol=test_record["symbol"],
            start_line=test_record["start_line"],
            end_line=test_record["end_line"],
            attrs_json=json.dumps({"language": test_record["language"]}, ensure_ascii=False),
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
                attrs_json=json.dumps({"kind": "source-file", "adapter": adapter_name}, ensure_ascii=False),
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


def build_graph(*, workspace_root: pathlib.Path, config_path: pathlib.Path) -> dict:
    config = load_config(config_path)
    paths = graph_paths(workspace_root, config)
    paths["report_dir"].mkdir(parents=True, exist_ok=True)
    paths["build_log_path"].parent.mkdir(parents=True, exist_ok=True)
    ensure_schema(paths["db_path"], schema_path_for(workspace_root))
    project_root = project_root_for(workspace_root, config)
    git = get_git_context(workspace_root)
    adapter_name = detect_language_adapter(project_root, config)
    adapter_graph = collect_adapter_graph(project_root, config, adapter_name)

    nodes, edges, evidence_rows = adapter_graph_to_rows(
        workspace_root=workspace_root,
        config=config,
        git=git,
        adapter_name=adapter_name,
        adapter_graph=adapter_graph,
    )
    known_nodes = {node.node_id for node in nodes}
    rule_nodes, rule_edges, rule_evidence, rule_docs = collect_rule_documents(
        workspace_root=workspace_root,
        project_root=project_root,
        config=config,
        git=git,
        known_nodes=known_nodes,
    )
    all_nodes = {node.node_id: node for node in nodes}
    for node in rule_nodes:
        all_nodes[node.node_id] = node
    all_edges = {(edge.src_id, edge.edge_type, edge.dst_id): edge for edge in edges}
    for edge in rule_edges:
        all_edges[(edge.src_id, edge.edge_type, edge.dst_id)] = edge
    all_evidence = {item.evidence_id: item for item in evidence_rows}
    for item in rule_evidence:
        all_evidence[item.evidence_id] = item

    with sqlite3.connect(paths["db_path"]) as conn:
        clear_graph_tables(conn)
        upsert_nodes(conn, list(all_nodes.values()))
        upsert_evidence(conn, list(all_evidence.values()))
        upsert_edges(conn, list(all_edges.values()))
        upsert_rule_documents(conn, rule_docs)
        conn.commit()

    summary = {
        "timestamp": utc_now(),
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "git_sha": git["git_sha"],
        "node_count": len(all_nodes),
        "edge_count": len(all_edges),
        "evidence_count": len(all_evidence),
        "configured_language_adapter": config.get("language_adapter", "auto"),
        "detected_adapter": adapter_name,
        "available_function_seeds": sorted(node_id for node_id, node in all_nodes.items() if node.kind == "function"),
        "available_file_seeds": sorted(node_id for node_id, node in all_nodes.items() if node.kind == "file"),
    }
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
