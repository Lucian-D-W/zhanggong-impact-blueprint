#!/usr/bin/env python3
import argparse
import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from adapters import detect_project_profile_name
from build_graph import get_git_context, graph_paths, load_config, project_root_for, record_task_run, resolved_language_adapter
from db_support import connect_db
from trust_policy import trust_lowering_reasons

TRUST_ORDER = {"low": 0, "medium": 1, "high": 2}
CONTRACT_NODE_KINDS = {
    "endpoint",
    "route",
    "component",
    "prop",
    "event",
    "config_key",
    "env_var",
    "sql_table",
    "ipc_channel",
    "obsidian_command",
    "playwright_flow",
}
CONTRACT_EDGE_TYPES = {
    "READS_CONFIG",
    "READS_ENV",
    "EMITS_EVENT",
    "HANDLES_EVENT",
    "QUERIES_TABLE",
    "MUTATES_TABLE",
    "ROUTES_TO",
    "RENDERS_COMPONENT",
    "USES_PROP",
    "REGISTER_COMMAND",
    "IPC_SENDS",
    "IPC_HANDLES",
    "DEPENDS_ON",
    "EXPOSES_ENDPOINT",
    "USES_ENDPOINT",
}


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


def unique_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def merge_provider_contracts(base: list[dict], extra: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str, str], dict] = {}
    for item in [*base, *extra]:
        files = unique_strings(list(item.get("files") or []))
        key = (
            item.get("node_id") or item.get("name") or "",
            item.get("relationship") or "",
            item.get("kind") or "",
        )
        if key in merged:
            merged[key]["confidence"] = max(float(merged[key].get("confidence") or 0.0), float(item.get("confidence") or 0.0))
            merged[key]["files"] = unique_strings(list(merged[key].get("files") or []) + files)
            if item.get("provider_evidence") and not merged[key].get("provider_evidence"):
                merged[key]["provider_evidence"] = item.get("provider_evidence")
            continue
        merged[key] = {
            **item,
            "files": files,
        }
    return sorted(merged.values(), key=lambda item: (item.get("kind", ""), item.get("name", ""), item.get("relationship", "")))


def merge_provider_chains(base: list[dict], extra: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for item in [*base, *extra]:
        nodes = tuple(sorted(node.get("node_id", "") for node in item.get("nodes", [])))
        key = (item.get("chain_type", ""), item.get("summary", ""), nodes)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def provider_uncertainty_view_payload(provider_overlay: dict) -> dict | None:
    uncertainties = unique_strings(list(provider_overlay.get("uncertainty") or []))
    if not uncertainties:
        return None
    contracts = list(provider_overlay.get("affected_contracts") or [])
    read_first = unique_strings(list(provider_overlay.get("must_read_first") or []))
    supporting_edges: list[dict] = []
    for view in provider_overlay.get("atlas_views") or []:
        supporting_edges.extend(view.get("supporting_edges") or [])
    return {
        "view_type": "uncertainty",
        "title": "Provider uncertainty view",
        "why_this_view": "GitNexus returned useful graph signals, but some of them should still be treated as hints instead of proof.",
        "confidence": "low",
        "primary_contracts": [
            {
                "node_id": item.get("node_id"),
                "kind": item.get("kind"),
                "name": item.get("name"),
                "path": (item.get("files") or [""])[0],
            }
            for item in contracts[:4]
        ],
        "read_first": read_first,
        "supporting_edges": supporting_edges[:8],
        "uncertainties": uncertainties,
    }


def contract_node_ref(node_id: str, kind: str, name: str, path: str) -> dict:
    return {
        "node_id": node_id,
        "kind": kind,
        "name": name,
        "path": path,
    }


def contract_edge_payload(edge: dict) -> dict:
    return {
        "src": edge["src_id"],
        "src_kind": edge["src_kind"],
        "src_name": edge["src_name"],
        "src_path": edge["src_path"],
        "edge_type": edge["edge_type"],
        "dst": edge["dst_id"],
        "dst_kind": edge["dst_kind"],
        "dst_name": edge["dst_name"],
        "dst_path": edge["dst_path"],
        "confidence": edge["confidence"],
        "attrs": edge["attrs"],
    }


def contract_context_edges(conn: sqlite3.Connection, *, seed: str, sections: dict, changed_files: list[str]) -> list[dict]:
    relevant_ids: set[str] = {seed}
    for bucket in (
        sections["owning_files"],
        sections["direct_upstream"],
        sections["direct_downstream"],
        sections["direct_tests"],
        sections["direct_rules"],
        sections["direct_imports"],
    ):
        for src_id, _, dst_id in bucket:
            relevant_ids.add(src_id)
            relevant_ids.add(dst_id)

    if changed_files:
        placeholders = ",".join("?" for _ in changed_files)
        rows = conn.execute(
            f"SELECT node_id FROM nodes WHERE path IN ({placeholders})",
            tuple(changed_files),
        ).fetchall()
        relevant_ids.update(row[0] for row in rows)

    if not relevant_ids and not changed_files:
        return []

    filters: list[str] = []
    params: list[str] = []
    if relevant_ids:
        placeholders = ",".join("?" for _ in relevant_ids)
        filters.extend(
            [
                f"e.src_id IN ({placeholders})",
                f"e.dst_id IN ({placeholders})",
            ]
        )
        params.extend(sorted(relevant_ids))
        params.extend(sorted(relevant_ids))
    if changed_files:
        placeholders = ",".join("?" for _ in changed_files)
        filters.extend(
            [
                f"src.path IN ({placeholders})",
                f"dst.path IN ({placeholders})",
            ]
        )
        params.extend(changed_files)
        params.extend(changed_files)

    sql = f"""
        SELECT
            e.src_id,
            e.edge_type,
            e.dst_id,
            e.confidence,
            e.attrs_json,
            src.kind,
            src.name,
            src.path,
            dst.kind,
            dst.name,
            dst.path
        FROM edges e
        JOIN nodes src ON src.node_id = e.src_id
        JOIN nodes dst ON dst.node_id = e.dst_id
        WHERE {" OR ".join(filters)}
        ORDER BY e.edge_type, e.src_id, e.dst_id
    """
    rows = conn.execute(sql, tuple(params)).fetchall()
    payload: list[dict] = []
    for row in rows:
        edge = {
            "src_id": row[0],
            "edge_type": row[1],
            "dst_id": row[2],
            "confidence": row[3],
            "attrs": json.loads(row[4] or "{}"),
            "src_kind": row[5],
            "src_name": row[6],
            "src_path": row[7],
            "dst_kind": row[8],
            "dst_name": row[9],
            "dst_path": row[10],
        }
        if (
            edge["edge_type"] in CONTRACT_EDGE_TYPES
            or edge["src_kind"] in CONTRACT_NODE_KINDS
            or edge["dst_kind"] in CONTRACT_NODE_KINDS
        ):
            payload.append(edge)
    return payload


def affected_contracts_payload(contract_edges: list[dict]) -> list[dict]:
    entries: dict[tuple[str, str], dict] = {}
    for edge in contract_edges:
        contract_sides = []
        if edge["src_kind"] in CONTRACT_NODE_KINDS:
            contract_sides.append(("src", edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]))
        if edge["dst_kind"] in CONTRACT_NODE_KINDS:
            contract_sides.append(("dst", edge["dst_id"], edge["dst_kind"], edge["dst_name"], edge["dst_path"]))
        for _, node_id, kind, name, path in contract_sides:
            key = (node_id, edge["edge_type"])
            entry = entries.setdefault(
                key,
                {
                    "node_id": node_id,
                    "kind": kind,
                    "name": name,
                    "relationship": edge["edge_type"],
                    "confidence": edge["confidence"],
                    "files": [],
                },
            )
            entry["confidence"] = max(entry["confidence"], edge["confidence"])
            entry["files"] = unique_strings(entry["files"] + [path, edge["src_path"], edge["dst_path"]])
    return sorted(entries.values(), key=lambda item: (item["kind"], item["name"], item["relationship"]))


def _append_chain(chains: list[dict], *, chain_type: str, summary: str, nodes: list[dict], edges: list[dict]) -> None:
    node_refs = unique_strings([node["node_id"] for node in nodes])
    ordered_nodes = [node for node in nodes if node["node_id"] in node_refs]
    dedup_nodes: list[dict] = []
    seen_nodes: set[str] = set()
    for node in ordered_nodes:
        if node["node_id"] in seen_nodes:
            continue
        seen_nodes.add(node["node_id"])
        dedup_nodes.append(node)
    dedup_edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (edge["src"], edge["edge_type"], edge["dst"])
        if key in seen_edges:
            continue
        seen_edges.add(key)
        dedup_edges.append(edge)
    chains.append(
        {
            "chain_type": chain_type,
            "summary": summary,
            "nodes": dedup_nodes,
            "edges": dedup_edges,
        }
    )


def architecture_chains_payload(contract_edges: list[dict]) -> list[dict]:
    chains: list[dict] = []
    route_edges = [edge for edge in contract_edges if edge["edge_type"] == "ROUTES_TO" and edge["src_kind"] == "route" and edge["dst_kind"] == "component"]
    render_edges = [edge for edge in contract_edges if edge["edge_type"] == "RENDERS_COMPONENT" and edge["src_kind"] == "component" and edge["dst_kind"] == "component"]
    prop_edges = [edge for edge in contract_edges if edge["edge_type"] == "USES_PROP" and edge["src_kind"] == "component" and edge["dst_kind"] == "prop"]
    for route_edge in route_edges:
        reachable_components = {route_edge["dst_id"]}
        chain_edges = [contract_edge_payload(route_edge)]
        frontier = {route_edge["dst_id"]}
        for _ in range(3):
            next_frontier: set[str] = set()
            for render_edge in render_edges:
                if render_edge["src_id"] in frontier and render_edge["dst_id"] not in reachable_components:
                    reachable_components.add(render_edge["dst_id"])
                    next_frontier.add(render_edge["dst_id"])
                    chain_edges.append(contract_edge_payload(render_edge))
            frontier = next_frontier
            if not frontier:
                break
        reachable_prop_edges = [edge for edge in prop_edges if edge["src_id"] in reachable_components]
        if not reachable_prop_edges:
            continue
        chain_edges.extend(contract_edge_payload(edge) for edge in reachable_prop_edges)
        prop_names = ", ".join(unique_strings([edge["dst_name"] for edge in reachable_prop_edges]))
        component_names = ", ".join(unique_strings([route_edge["dst_name"]] + [edge["dst_name"] for edge in render_edges if edge["dst_id"] in reachable_components]))
        nodes: list[dict] = [
            contract_node_ref(route_edge["src_id"], route_edge["src_kind"], route_edge["src_name"], route_edge["src_path"]),
            contract_node_ref(route_edge["dst_id"], route_edge["dst_kind"], route_edge["dst_name"], route_edge["dst_path"]),
        ]
        for edge in render_edges:
            if edge["src_id"] in reachable_components or edge["dst_id"] in reachable_components:
                nodes.append(contract_node_ref(edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]))
                nodes.append(contract_node_ref(edge["dst_id"], edge["dst_kind"], edge["dst_name"], edge["dst_path"]))
        for edge in reachable_prop_edges:
            nodes.append(contract_node_ref(edge["dst_id"], edge["dst_kind"], edge["dst_name"], edge["dst_path"]))
        _append_chain(
            chains,
            chain_type="route_component_prop",
            summary=f"route {route_edge['src_name']} reaches component {component_names} and prop {prop_names}",
            nodes=nodes,
            edges=chain_edges,
        )

    def grouped_contract_chains(chain_type: str, send_type: str, handle_type: str, kind: str, send_label: str, handle_label: str) -> None:
        sends = [edge for edge in contract_edges if edge["edge_type"] == send_type and edge["dst_kind"] == kind]
        handles = [edge for edge in contract_edges if edge["edge_type"] == handle_type and edge["dst_kind"] == kind]
        for node_id in sorted({edge["dst_id"] for edge in sends} & {edge["dst_id"] for edge in handles}):
            send_edge = next(edge for edge in sends if edge["dst_id"] == node_id)
            handle_edge = next(edge for edge in handles if edge["dst_id"] == node_id)
            contract = contract_node_ref(send_edge["dst_id"], send_edge["dst_kind"], send_edge["dst_name"], send_edge["dst_path"])
            _append_chain(
                chains,
                chain_type=chain_type,
                summary=f"{send_edge['src_name']} {send_label} {send_edge['dst_name']}; {handle_edge['src_name']} {handle_label} {handle_edge['dst_name']}",
                nodes=[
                    contract_node_ref(send_edge["src_id"], send_edge["src_kind"], send_edge["src_name"], send_edge["src_path"]),
                    contract,
                    contract_node_ref(handle_edge["src_id"], handle_edge["src_kind"], handle_edge["src_name"], handle_edge["src_path"]),
                ],
                edges=[contract_edge_payload(send_edge), contract_edge_payload(handle_edge)],
            )

    grouped_contract_chains("event", "EMITS_EVENT", "HANDLES_EVENT", "event", "emits", "handles")
    grouped_contract_chains("ipc", "IPC_SENDS", "IPC_HANDLES", "ipc_channel", "sends", "handles")

    sql_groups: dict[str, list[dict]] = {}
    for edge in contract_edges:
        if edge["edge_type"] not in {"QUERIES_TABLE", "MUTATES_TABLE", "DEPENDS_ON"} or edge["dst_kind"] != "sql_table":
            continue
        sql_groups.setdefault(edge["dst_id"], []).append(edge)
    for table_id, edges in sorted(sql_groups.items()):
        query_edges = [edge for edge in edges if edge["edge_type"] == "QUERIES_TABLE"]
        mutation_edges = [edge for edge in edges if edge["edge_type"] == "MUTATES_TABLE"]
        if not query_edges and not mutation_edges:
            continue
        table_edge = (query_edges or mutation_edges)[0]
        summary_parts = []
        if query_edges:
            summary_parts.append("queries")
        if mutation_edges:
            summary_parts.append("mutations")
        _append_chain(
            chains,
            chain_type="sql",
            summary=f"table {table_edge['dst_name']} links to {' and '.join(summary_parts)} in {', '.join(unique_strings([edge['src_name'] for edge in edges]))}",
            nodes=[contract_node_ref(table_id, "sql_table", table_edge["dst_name"], table_edge["dst_path"])]
            + [contract_node_ref(edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]) for edge in edges],
            edges=[contract_edge_payload(edge) for edge in edges],
        )

    env_config_groups: dict[str, list[dict]] = {}
    for edge in contract_edges:
        if edge["edge_type"] not in {"READS_ENV", "READS_CONFIG", "DEPENDS_ON"}:
            continue
        if edge["dst_kind"] not in {"env_var", "config_key"}:
            continue
        env_config_groups.setdefault(edge["dst_id"], []).append(edge)
    for contract_id, edges in sorted(env_config_groups.items()):
        first = edges[0]
        chain_type = "env" if first["dst_kind"] == "env_var" else "config"
        summary = f"{first['dst_kind']} {first['dst_name']} is read by {', '.join(unique_strings([edge['src_name'] for edge in edges]))}"
        _append_chain(
            chains,
            chain_type=chain_type,
            summary=summary,
            nodes=[contract_node_ref(contract_id, first["dst_kind"], first["dst_name"], first["dst_path"])]
            + [contract_node_ref(edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]) for edge in edges],
            edges=[contract_edge_payload(edge) for edge in edges],
        )

    command_groups: dict[str, list[dict]] = {}
    for edge in contract_edges:
        if edge["dst_kind"] != "obsidian_command":
            continue
        if edge["edge_type"] not in {"REGISTER_COMMAND", "DEPENDS_ON"}:
            continue
        command_groups.setdefault(edge["dst_id"], []).append(edge)
    for command_id, edges in sorted(command_groups.items()):
        if len(edges) < 2:
            continue
        first = edges[0]
        _append_chain(
            chains,
            chain_type="obsidian_command",
            summary=f"command {first['dst_name']} is registered and invoked across {', '.join(unique_strings([edge['src_name'] for edge in edges]))}",
            nodes=[contract_node_ref(command_id, "obsidian_command", first["dst_name"], first["dst_path"])]
            + [contract_node_ref(edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]) for edge in edges],
            edges=[contract_edge_payload(edge) for edge in edges],
        )

    flow_routes = [edge for edge in contract_edges if edge["edge_type"] == "ROUTES_TO" and edge["src_kind"] == "playwright_flow" and edge["dst_kind"] == "route"]
    flow_endpoints = [edge for edge in contract_edges if edge["edge_type"] == "USES_ENDPOINT" and edge["src_kind"] == "playwright_flow" and edge["dst_kind"] == "endpoint"]
    for flow_id in sorted({edge["src_id"] for edge in flow_routes} | {edge["src_id"] for edge in flow_endpoints}):
        related_routes = [edge for edge in flow_routes if edge["src_id"] == flow_id]
        related_endpoints = [edge for edge in flow_endpoints if edge["src_id"] == flow_id]
        if not related_routes and not related_endpoints:
            continue
        flow_edge = (related_routes or related_endpoints)[0]
        route_names = ", ".join(unique_strings([edge["dst_name"] for edge in related_routes])) or "none"
        endpoint_names = ", ".join(unique_strings([edge["dst_name"] for edge in related_endpoints])) or "none"
        _append_chain(
            chains,
            chain_type="endpoint_route_flow",
            summary=f"playwright flow {flow_edge['src_name']} visits {route_names} and calls {endpoint_names}",
            nodes=[contract_node_ref(flow_id, "playwright_flow", flow_edge["src_name"], flow_edge["src_path"])]
            + [contract_node_ref(edge["dst_id"], edge["dst_kind"], edge["dst_name"], edge["dst_path"]) for edge in related_routes + related_endpoints],
            edges=[contract_edge_payload(edge) for edge in related_routes + related_endpoints],
        )

    endpoint_groups: dict[str, list[dict]] = {}
    for edge in contract_edges:
        if edge["dst_kind"] != "endpoint" or edge["edge_type"] not in {"USES_ENDPOINT", "EXPOSES_ENDPOINT"}:
            continue
        endpoint_groups.setdefault(edge["dst_id"], []).append(edge)
    for endpoint_id, edges in sorted(endpoint_groups.items()):
        uses = [edge for edge in edges if edge["edge_type"] == "USES_ENDPOINT"]
        exposes = [edge for edge in edges if edge["edge_type"] == "EXPOSES_ENDPOINT"]
        if not uses and not exposes:
            continue
        first = (uses or exposes)[0]
        _append_chain(
            chains,
            chain_type="endpoint",
            summary=f"endpoint {first['dst_name']} is exposed by {', '.join(unique_strings([edge['src_name'] for edge in exposes])) or 'unknown'} and used by {', '.join(unique_strings([edge['src_name'] for edge in uses])) or 'unknown'}",
            nodes=[contract_node_ref(endpoint_id, "endpoint", first["dst_name"], first["dst_path"])]
            + [contract_node_ref(edge["src_id"], edge["src_kind"], edge["src_name"], edge["src_path"]) for edge in edges],
            edges=[contract_edge_payload(edge) for edge in edges],
        )

    return chains


def confidence_label(values: list[float]) -> str:
    floor = min(values or [0.0])
    if floor >= 0.85:
        return "high"
    if floor >= 0.65:
        return "medium"
    return "low"


def compact_contract_ref(node: dict) -> dict:
    return {
        "node_id": node["node_id"],
        "kind": node["kind"],
        "name": node["name"],
        "path": node["path"],
    }


def contract_refs_from_chain(chain: dict) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()
    for node in chain.get("nodes", []):
        if node.get("kind") not in CONTRACT_NODE_KINDS:
            continue
        node_id = node.get("node_id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        refs.append(compact_contract_ref(node))
    return refs


def chain_read_first(chain: dict) -> list[str]:
    values: list[str] = []
    for node in chain.get("nodes", []):
        path = node.get("path")
        if path:
            values.append(path)
    for edge in chain.get("edges", []):
        for key in ("src_path", "dst_path"):
            if edge.get(key):
                values.append(edge[key])
    return unique_strings(values)


def chain_title(chain_type: str) -> str:
    if chain_type == "ipc":
        return "IPC bilateral view"
    if chain_type == "event":
        return "Event bilateral view"
    if chain_type == "endpoint":
        return "Endpoint bilateral view"
    if chain_type == "obsidian_command":
        return "Command bilateral view"
    if chain_type in {"route_component_prop", "endpoint_route_flow"}:
        return "Page flow view"
    if chain_type == "sql":
        return "Data flow view"
    if chain_type in {"env", "config"}:
        return "Config surface view"
    return "Atlas view"


def chain_view_type(chain_type: str) -> str | None:
    if chain_type in {"ipc", "event", "endpoint", "obsidian_command"}:
        return "bilateral_contract"
    if chain_type in {"route_component_prop", "endpoint_route_flow"}:
        return "page_flow"
    if chain_type == "sql":
        return "data_flow"
    if chain_type in {"env", "config"}:
        return "config_surface"
    return None


def why_this_view(chain: dict) -> str:
    chain_type = chain.get("chain_type")
    contracts = contract_refs_from_chain(chain)
    primary_name = contracts[0]["name"] if contracts else "this contract surface"
    if chain_type == "ipc":
        return f"This change touches ipc_channel `{primary_name}`; review both the send side and the handle side before editing."
    if chain_type == "event":
        return f"This change touches event `{primary_name}`; review both the emit side and the handle side together."
    if chain_type == "endpoint":
        return f"This change touches endpoint `{primary_name}`; review both the exposing backend path and the caller path."
    if chain_type == "obsidian_command":
        return f"This change touches command `{primary_name}`; review both registration and invocation paths."
    if chain_type == "route_component_prop":
        return f"This change touches page route `{primary_name}`; review the route, component chain, and prop surface together."
    if chain_type == "endpoint_route_flow":
        return f"This change touches a page flow around `{primary_name}`; review the route and flow path together."
    if chain_type == "sql":
        return f"This change touches sql_table `{primary_name}`; review query, mutation, and schema-adjacent paths together."
    if chain_type in {"env", "config"}:
        return f"This change touches configuration surface `{primary_name}`; review every reader path before editing."
    return chain.get("summary") or "Review the linked architecture chain before editing."


def atlas_view_from_chain(chain: dict) -> dict | None:
    view_type = chain_view_type(chain.get("chain_type"))
    if not view_type:
        return None
    edges = list(chain.get("edges", []))
    edge_confidences = [float(edge.get("confidence") or 0.0) for edge in edges]
    low_confidence = [edge for edge in edges if edge.get("edge_type") == "DEPENDS_ON" or float(edge.get("confidence") or 0.0) < 0.85]
    uncertainties = [
        (
            f"{edge.get('edge_type')} for `{edge.get('dst_name') or edge.get('dst')}` is a low-confidence hint; "
            "treat it as evidence to review, not proof."
        )
        for edge in low_confidence
    ]
    return {
        "view_type": view_type,
        "title": chain_title(chain.get("chain_type")),
        "why_this_view": why_this_view(chain),
        "confidence": confidence_label(edge_confidences),
        "primary_contracts": contract_refs_from_chain(chain),
        "read_first": chain_read_first(chain),
        "supporting_edges": edges,
        "uncertainties": unique_strings(uncertainties),
    }


def uncertainty_view_payload(
    affected_contracts: list[dict],
    architecture_chains: list[dict],
    *,
    report_completeness: dict | None = None,
) -> dict | None:
    supporting_edges: list[dict] = []
    uncertainties: list[str] = []
    primary_contracts: list[dict] = []
    read_first: list[str] = []
    seen_contracts: set[str] = set()
    for contract in affected_contracts:
        relationship = contract.get("relationship")
        confidence = float(contract.get("confidence") or 0.0)
        if relationship != "DEPENDS_ON" and confidence >= 0.85:
            continue
        node_id = contract.get("node_id")
        if node_id and node_id not in seen_contracts:
            seen_contracts.add(node_id)
            primary_contracts.append(
                {
                    "node_id": node_id,
                    "kind": contract.get("kind"),
                    "name": contract.get("name"),
                    "path": (contract.get("files") or [""])[0],
                }
            )
        read_first.extend(contract.get("files") or [])
        supporting_edges.append(
            {
                "relationship": relationship,
                "kind": contract.get("kind"),
                "name": contract.get("name"),
                "confidence": confidence,
                "files": contract.get("files", []),
            }
        )
        uncertainties.append(
            f"{relationship} for `{contract.get('name')}` is low-confidence fallback evidence. Do not treat it as proof."
        )
    for chain in architecture_chains:
        for edge in chain.get("edges", []):
            if edge.get("edge_type") != "DEPENDS_ON" and float(edge.get("confidence") or 0.0) >= 0.85:
                continue
            read_first.extend([edge.get("src_path"), edge.get("dst_path")])
            supporting_edges.append(edge)
            uncertainties.append(
                f"{edge.get('edge_type')} from `{edge.get('src_name')}` to `{edge.get('dst_name')}` is a hint, not proof."
            )
    if (report_completeness or {}).get("level") == "low":
        uncertainties.append(
            "Report completeness is low for this seed, so broaden your reading before relying on a narrow local patch."
        )
    uncertainties = unique_strings(uncertainties)
    if not uncertainties:
        return None
    return {
        "view_type": "uncertainty",
        "title": "Uncertainty view",
        "why_this_view": "Some contract matches are fallback evidence or the context is incomplete. Review them as hints, not conclusions.",
        "confidence": "low",
        "primary_contracts": primary_contracts,
        "read_first": unique_strings(read_first),
        "supporting_edges": supporting_edges,
        "uncertainties": uncertainties,
    }


def compress_atlas_views(
    atlas_views: list[dict],
    *,
    full_contracts_path: str,
    limit_per_type: int = 3,
) -> tuple[list[dict], dict]:
    def view_priority(view: dict) -> tuple[int, int, int, str]:
        edges = view.get("supporting_edges") or []
        edge_types = {
            edge.get("edge_type")
            for edge in edges
            if isinstance(edge, dict) and edge.get("edge_type")
        }
        confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(view.get("confidence"), 3)
        uncertainty_penalty = len(view.get("uncertainties") or [])
        mutation_bonus = 0 if "MUTATES_TABLE" in edge_types else 1
        bilateral_bonus = 0 if {"IPC_SENDS", "IPC_HANDLES"} & edge_types or {"EMITS_EVENT", "HANDLES_EVENT"} & edge_types else 1
        data_bonus = mutation_bonus if view.get("view_type") == "data_flow" else bilateral_bonus
        read_first = view.get("read_first") or [""]
        return (
            data_bonus,
            confidence_rank,
            uncertainty_penalty,
            read_first[0],
        )

    deduped: list[dict] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for view in atlas_views:
        contract_key = tuple(
            sorted(
                f"{item.get('kind')}:{item.get('name')}"
                for item in view.get("primary_contracts", [])
                if item.get("name")
            )
        )
        read_key = tuple(view.get("read_first", [])[:3])
        key = (view.get("view_type", ""), contract_key, read_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(view)
    per_type: dict[str, list[dict]] = {}
    for view in deduped:
        per_type.setdefault(view.get("view_type", "unknown"), []).append(view)
    compressed: list[dict] = []
    omitted_count = 0
    for view_type, views in per_type.items():
        views = sorted(views, key=view_priority)
        kept = views[:limit_per_type]
        omitted = max(0, len(views) - len(kept))
        if omitted and kept:
            kept[-1] = {
                **kept[-1],
                "more_contracts_omitted": True,
                "omitted_count": omitted,
                "full_contracts_path": full_contracts_path,
            }
        compressed.extend(kept)
        omitted_count += omitted
    summary = {
        "view_count": len(compressed),
        "primary_views": unique_strings([view["view_type"] for view in compressed if view.get("view_type") != "uncertainty"]),
        "uncertainty_count": len([view for view in compressed if view.get("view_type") == "uncertainty"]),
        "omitted_count": omitted_count,
        "more_contracts_omitted": omitted_count > 0,
        "full_contracts_path": full_contracts_path,
    }
    return compressed, summary


def summarize_contracts_for_agent(
    affected_contracts: list[dict],
    architecture_chains: list[dict],
    *,
    report_completeness: dict | None,
    full_contracts_path: str,
) -> tuple[list[dict], dict]:
    atlas_views = [view for chain in architecture_chains if (view := atlas_view_from_chain(chain))]
    uncertainty_view = uncertainty_view_payload(
        affected_contracts,
        architecture_chains,
        report_completeness=report_completeness,
    )
    if uncertainty_view:
        atlas_views.append(uncertainty_view)
    return compress_atlas_views(atlas_views, full_contracts_path=full_contracts_path)


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


def report_completeness_payload(*, seed_kind: str, context_resolution: dict | None, fallback_used: bool) -> dict:
    context_status = (context_resolution or {}).get("context_status", "resolved")
    if context_status == "missing":
        return {"level": "low", "reason": "context_missing"}
    if fallback_used or seed_kind == "file":
        return {"level": "low", "reason": "file_level_or_fallback"}
    if context_status == "partial":
        return {"level": "medium", "reason": "context_partial"}
    return {"level": "high", "reason": "function_or_routine_seed_with_resolved_context"}


def test_signal_payload(*, sections: dict, test_summary: dict | None) -> dict:
    affected_tests_found = bool(sections["direct_tests"])
    if not test_summary:
        return {
            "status": "not-run",
            "tests_run": None,
            "test_count_status": "unknown",
            "tests_passed": False,
            "coverage_available": False,
            "affected_tests_found": affected_tests_found,
            "coverage_relevance": "not-run",
            "full_suite": False,
            "requested_test_scope": None,
            "effective_test_scope": "not-run",
            "test_scope_reason": "tests have not run yet",
        }
    status = test_summary.get("status")
    full_suite = bool(test_summary.get("full_suite"))
    coverage_available = test_summary.get("coverage_status") == "available"
    effective_test_scope = test_summary.get("effective_test_scope") or ("full" if full_suite else "configured")
    if status == "passed" and not affected_tests_found:
        relevance = "tests-passed-but-no-directly-affected-tests-identified"
    elif status == "passed" and coverage_available:
        relevance = "direct-impact-covered-by-available-coverage"
    elif status == "passed":
        relevance = "direct-impact-tests-identified-but-coverage-unavailable"
    elif status == "failed":
        relevance = "test-command-failed"
    else:
        relevance = "tests-skipped-or-unavailable"
    return {
        "status": status,
        "tests_run": test_summary.get("tests_run"),
        "test_count_status": test_summary.get("test_count_status", "unknown"),
        "tests_passed": status == "passed",
        "coverage_available": coverage_available,
        "affected_tests_found": affected_tests_found,
        "coverage_relevance": relevance,
        "full_suite": full_suite,
        "requested_test_scope": test_summary.get("requested_test_scope"),
        "effective_test_scope": effective_test_scope,
        "test_scope_reason": test_summary.get("test_scope_reason"),
    }


def clamp_trust_level(*levels: str) -> str:
    normalized = [level for level in levels if level in TRUST_ORDER]
    if not normalized:
        return "unknown"
    return min(normalized, key=lambda item: TRUST_ORDER[item])


def parser_trust_payload(seed_detail: dict | None, report_completeness: dict) -> str:
    attrs = (seed_detail or {}).get("attrs", {})
    if attrs.get("parser_warning"):
        return "low"
    parser_confidence = attrs.get("parser_confidence")
    if isinstance(parser_confidence, (int, float)):
        if parser_confidence >= 0.95:
            return "high"
        if parser_confidence >= 0.75:
            return "medium"
        return "low"
    if report_completeness.get("level") == "low":
        return "medium"
    return "high"


def dependency_trust_level(status: str) -> str:
    if status in {"unknown", "changed"}:
        return "medium"
    if status in {"unchanged", "not_applicable"}:
        return "high"
    return "medium"


def test_signal_trust_value(test_signal: dict) -> str:
    status = test_signal.get("status")
    effective_scope = test_signal.get("effective_test_scope")
    if status == "failed":
        return "failed"
    if status == "passed":
        return f"{effective_scope}-pass"
    if status == "skipped":
        return "skipped"
    return "not-run"


def test_signal_trust_level(signal_value: str) -> str:
    if signal_value in {"targeted-pass", "configured-pass", "full-pass"}:
        return "high"
    if signal_value == "failed":
        return "low"
    return "medium"


def coverage_trust_value(test_signal: dict) -> str:
    if test_signal.get("coverage_available") and test_signal.get("affected_tests_found"):
        return "direct-covered"
    if test_signal.get("affected_tests_found"):
        return "direct-tests-no-coverage"
    return "unknown"


def coverage_trust_level(value: str) -> str:
    if value == "direct-covered":
        return "high"
    return "medium"


def context_trust_value(*, context_resolution: dict | None, report_completeness: dict) -> str:
    if report_completeness.get("level") == "low":
        if bool((context_resolution or {}).get("fallback_used")):
            return "fallback"
        return "partial"
    if (context_resolution or {}).get("context_status") == "partial":
        return "partial"
    return "explicit"


def context_trust_level(value: str) -> str:
    if value == "explicit":
        return "high"
    if value == "partial":
        return "medium"
    return "low"


def multidimensional_trust_payload(
    *,
    build_decision: dict | None,
    seed_detail: dict | None = None,
    report_completeness: dict | None = None,
    test_signal: dict | None = None,
    context_resolution: dict | None = None,
    **_ignored,
) -> dict:
    build_decision = build_decision or {}
    report_completeness = report_completeness or {}
    test_signal = test_signal or {}
    baseline = build_decision.get("trust") or {}
    graph = build_decision.get("graph_trust", build_decision.get("trust_level", baseline.get("graph", "unknown")))
    parser = parser_trust_payload(seed_detail, report_completeness)
    raw_dependency = build_decision.get("dependency_fingerprint_status", baseline.get("dependency", "unknown"))
    dependency = "unchanged" if raw_dependency == "not_applicable" else raw_dependency
    test_signal_value = test_signal_trust_value(test_signal)
    coverage = coverage_trust_value(test_signal)
    context = context_trust_value(context_resolution=context_resolution, report_completeness=report_completeness)
    overall = clamp_trust_level(
        graph,
        parser,
        dependency_trust_level(dependency),
        test_signal_trust_level(test_signal_value),
        coverage_trust_level(coverage),
        context_trust_level(context),
    )
    baseline_axes = build_decision.get("trust_axes") or baseline.get("trust_axes") or {}
    graph_freshness = build_decision.get("graph_freshness", baseline_axes.get("graph_freshness", "unknown"))
    workspace_noise = baseline_axes.get("workspace_noise", "high" if build_decision.get("generated_noise") else "low")
    dependency_confidence = {
        "unchanged": "high",
        "not_applicable": "high",
        "changed": "low",
        "unknown": "low",
    }.get(raw_dependency, "unknown")
    context_confidence = {
        "explicit": "explicit",
        "partial": "inferred",
        "fallback": "fallback",
    }.get(context, "missing" if context == "missing" else "inferred")
    adapter_confidence = build_decision.get("adapter_confidence", baseline_axes.get("adapter_confidence", "medium"))
    test_signal_axis = {
        "covered": "direct",
        "not-run": "none",
        "direct": "direct",
        "mapped": "direct",
        "configured": "configured",
        "full": "full",
        "unknown": "unknown",
    }.get(test_signal_value, "configured" if test_signal.get("full_suite") else "unknown")
    trust_axes = {
        "graph_freshness": graph_freshness,
        "workspace_noise": workspace_noise,
        "dependency_confidence": dependency_confidence,
        "context_confidence": context_confidence,
        "adapter_confidence": adapter_confidence,
        "test_signal": test_signal_axis,
        "overall_trust": overall,
    }
    trust_explanation: list[str] = []
    lowering_reasons = trust_lowering_reasons(
        workspace_noise=workspace_noise,
        dependency_confidence=dependency_confidence,
        context_confidence=context_confidence,
        adapter_confidence=adapter_confidence,
        test_signal=test_signal_axis,
    )
    if graph_freshness == "fresh" and overall in {"medium", "low"} and lowering_reasons:
        trust_explanation.append(f"Graph is fresh, but overall trust is {overall} because " + ", ".join(lowering_reasons[:2]) + ".")
    if dependency_confidence in {"low", "unknown"} and not any("Dependency confidence" in item for item in trust_explanation):
        trust_explanation.append(f"Dependency confidence is {dependency_confidence}, which lowers overall trust without marking the graph stale.")
    return {
        "graph": graph,
        "parser": parser,
        "dependency": dependency,
        "test_signal": test_signal_value,
        "coverage": coverage,
        "context": context,
        "overall": overall,
        "trust_axes": trust_axes,
        "trust_explanation": trust_explanation,
    }


def user_summary_payload(
    *,
    seed: str,
    changed_files: list[str],
    sections: dict,
    next_tests: list[str],
    report_completeness: dict,
) -> str:
    direct_refs: list[str] = []
    direct_refs.extend(src_id for src_id, _, _ in sections["direct_tests"][:2])
    direct_refs.extend(src_id for src_id, _, _ in sections["direct_rules"][:2])
    direct_refs.extend(dst_id for _, _, dst_id in sections["direct_downstream"][:2])
    linked = ", ".join(direct_refs[:3]) or "no direct linked tests or rules yet"
    if report_completeness["level"] == "low":
        return (
            f"I inferred `{seed}` as the current seed, but the report is still incomplete. "
            f"It links to {linked}, so I do not recommend editing until the context is narrowed or confirmed."
        )
    next_test = next_tests[0] if next_tests else f"Run the nearest test for `{seed}`."
    changed = ", ".join(changed_files[:2]) or "the current diff"
    return (
        f"I identified `{seed}` as the main impact seed for {changed}. "
        f"It directly links to {linked}; next I would {next_test}"
    )


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
    secondary_seeds: list[str],
    seed_mode: str | None,
    seed_reason: str | None,
    changed_files: list[str],
    sections: dict,
    build_decision: dict | None,
    top_risks: list[str],
    next_tests: list[str],
    key_evidence_paths: list[str],
    next_step: str | None,
    seed_confidence: float | None,
    recent_task_influenced: bool,
    report_completeness: dict,
    test_signal: dict,
    user_summary: str,
    trust: dict,
) -> dict:
    decision = build_decision or {}
    return {
        "selected_seed": seed,
        "secondary_seeds": secondary_seeds,
        "seed_mode": seed_mode,
        "why_this_seed": seed_reason or "seed selected from current context",
        "seed_confidence": seed_confidence,
        "recent_task_influenced": recent_task_influenced,
        "changed_files_summary": changed_files or ["none"],
        "direct_impact_summary": {
            "callers": len(sections["direct_upstream"]),
            "callees": len(sections["direct_downstream"]),
            "tests": len(sections["direct_tests"]),
            "rules": len(sections["direct_rules"]),
        },
        "build_trust_summary": {
            "build_mode": decision.get("execution_mode") or decision.get("build_mode"),
            "graph_trust": decision.get("graph_trust", decision.get("trust_level")),
            "trust_level": decision.get("graph_trust", decision.get("trust_level")),
            "reason_codes": decision.get("reason_codes", []),
            "verification_status": decision.get("verification_status"),
            "graph_freshness": decision.get("graph_freshness"),
            "dependency_fingerprint_status": decision.get("dependency_fingerprint_status"),
        },
        "graph_trust": decision.get("graph_trust", decision.get("trust_level")),
        "trust": trust,
        "report_completeness": report_completeness,
        "test_signal": test_signal,
        "top_risks": top_risks[:3],
        "next_tests": next_tests[:3],
        "key_evidence_paths": key_evidence_paths[:4],
        "next_step": next_step or "Read the brief report, then edit the code if the selected seed looks right.",
        "user_summary": user_summary,
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
    context_resolution: dict | None,
) -> None:
    attrs = (seed_detail or {}).get("attrs", {})
    reference_hints = reference_hints_payload(seed_detail)
    if mode == "brief":
        metadata_lines = ["## Definition metadata"]
        if seed_detail:
            metadata_keys = [
                "definition_kind",
                "class_name",
                "qualified_name",
                "sql_kind",
                "language",
                "is_component",
                "is_hook",
                "parser_confidence",
                "parser_warning",
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
        multidimensional_trust = brief.get("trust", {})
        lines = [
            "# Impact Brief",
            "",
            f"- summary: {brief['user_summary']}",
            f"- selected_seed: `{brief['selected_seed']}`",
            f"- why_this_seed: {brief['why_this_seed']}",
            f"- seed_confidence: {brief.get('seed_confidence')}",
            f"- recent_task_influenced: {brief.get('recent_task_influenced', False)}",
            f"- changed_files: {', '.join(brief['changed_files_summary'])}",
            f"- direct_impact: callers={impact['callers']}, callees={impact['callees']}, tests={impact['tests']}, rules={impact['rules']}",
            f"- graph_provider: {brief.get('graph_provider') or 'internal'} ({brief.get('provider_status') or 'unknown'})",
            f"- provider_reason: {brief.get('provider_reason') or 'none'}",
            f"- build_trust: mode={trust.get('build_mode') or 'unknown'}, graph_trust={trust.get('graph_trust') or trust.get('trust_level') or 'unknown'}, freshness={trust.get('graph_freshness') or 'unknown'}, dependencies={trust.get('dependency_fingerprint_status') or 'unknown'}, reasons={', '.join(trust.get('reason_codes', [])) or 'none'}, verification={trust.get('verification_status') or 'skipped'}",
            f"- trust: overall={multidimensional_trust.get('overall', 'unknown')}, graph={multidimensional_trust.get('graph', 'unknown')}, parser={multidimensional_trust.get('parser', 'unknown')}, dependency={multidimensional_trust.get('dependency', 'unknown')}, test_signal={multidimensional_trust.get('test_signal', 'unknown')}, coverage={multidimensional_trust.get('coverage', 'unknown')}, context={multidimensional_trust.get('context', 'unknown')}",
            f"- report_completeness: {brief['report_completeness']['level']} ({brief['report_completeness']['reason']})",
            f"- test_signal: tests_run={brief['test_signal']['tests_run']}, tests_passed={brief['test_signal']['tests_passed']}, coverage_available={brief['test_signal']['coverage_available']}, affected_tests_found={brief['test_signal']['affected_tests_found']}, coverage_relevance={brief['test_signal']['coverage_relevance']}, requested_scope={brief['test_signal'].get('requested_test_scope')}, effective_scope={brief['test_signal'].get('effective_test_scope')}",
            f"- top_risks: {' | '.join(brief['top_risks']) if brief['top_risks'] else 'none'}",
            f"- next_tests: {' | '.join(brief['next_tests']) if brief['next_tests'] else 'none'}",
            f"- next_step: {brief['next_step']}",
            "",
            "## Context",
            f"- context_status: {(context_resolution or {}).get('context_status', 'resolved')}",
            f"- fallback_used: {bool((context_resolution or {}).get('fallback_used'))}",
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
            f"- context_status: {(context_resolution or {}).get('context_status', 'resolved')}",
            "",
            "## Definition metadata",
        ]
    if seed_detail:
        lines.append(f"- node_path: `{seed_detail['path']}`")
        lines.append(f"- node_symbol: `{seed_detail['symbol'] or seed_detail['name']}`")
        for key, value in sorted(attrs.items()):
            if key == "reference_hints":
                continue
            if mode == "brief" and key not in {"definition_kind", "class_name", "qualified_name", "sql_kind", "language", "resolved_sql_targets", "unresolved_sql_hints", "parser_confidence", "parser_warning"}:
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
    context_resolution: dict | None = None,
    test_summary: dict | None = None,
    provider_analysis: dict | None = None,
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

    with connect_db(paths["db_path"]) as conn:
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
        contract_edges = contract_context_edges(
            conn,
            seed=seed,
            sections=sections,
            changed_files=changed_files,
        )
        affected_contracts = affected_contracts_payload(contract_edges)
        architecture_chains = architecture_chains_payload(contract_edges)

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
    report_completeness = report_completeness_payload(
        seed_kind=sections["seed_kind"],
        context_resolution=context_resolution,
        fallback_used=bool((seed_selection or {}).get("fallback_used")),
    )
    provider_overlay = dict((provider_analysis or {}).get("provider_overlay") or {})
    affected_contracts = merge_provider_contracts(affected_contracts, list(provider_overlay.get("affected_contracts") or []))
    architecture_chains = merge_provider_chains(architecture_chains, list(provider_overlay.get("architecture_chains") or []))
    atlas_views, atlas_summary = summarize_contracts_for_agent(
        affected_contracts,
        architecture_chains,
        report_completeness=report_completeness,
        full_contracts_path=str(json_report_path.relative_to(workspace_root)),
    )
    provider_atlas_views = list(provider_overlay.get("atlas_views") or [])
    provider_uncertainty_view = provider_uncertainty_view_payload(provider_overlay)
    if provider_uncertainty_view:
        provider_atlas_views.append(provider_uncertainty_view)
    if provider_atlas_views:
        atlas_views, atlas_summary = compress_atlas_views(
            [*atlas_views, *provider_atlas_views],
            full_contracts_path=str(json_report_path.relative_to(workspace_root)),
        )
    test_signal = test_signal_payload(sections=sections, test_summary=test_summary)
    trust = multidimensional_trust_payload(
        build_decision=build_decision,
        seed_detail=seed_detail,
        report_completeness=report_completeness,
        test_signal=test_signal,
        context_resolution=context_resolution,
    )
    user_summary = user_summary_payload(
        seed=seed,
        changed_files=changed_files,
        sections=sections,
        next_tests=next_tests,
        report_completeness=report_completeness,
    )
    provider_must_read_first = unique_strings(list(provider_overlay.get("must_read_first") or []))
    key_evidence_paths = unique_strings(key_evidence_paths + provider_must_read_first)
    provider_metadata = {
        "graph_provider": (provider_analysis or {}).get("graph_provider"),
        "provider_status": (provider_analysis or {}).get("provider_status"),
        "provider_reason": (provider_analysis or {}).get("provider_reason"),
        "provider_fallback": (provider_analysis or {}).get("provider_fallback"),
        "fallback_provider": (provider_analysis or {}).get("fallback_provider"),
        "provider_effective": (provider_analysis or {}).get("provider_effective"),
        "provider_index_status": (provider_analysis or {}).get("provider_index_status"),
        "provider_install_hint": (provider_analysis or {}).get("provider_install_hint"),
        "provider_evidence_summary": list((provider_analysis or {}).get("provider_evidence_summary") or []),
        "provider_side_effects": list((provider_analysis or {}).get("provider_side_effects") or []),
        "provider_side_effects_suppressed": list((provider_analysis or {}).get("provider_side_effects_suppressed") or []),
        "provider_git_info_exclude_path": (provider_analysis or {}).get("provider_git_info_exclude_path"),
    }
    brief = brief_payload(
        seed=seed,
        secondary_seeds=list((seed_selection or {}).get("secondary_seeds", [])),
        seed_mode=(seed_selection or {}).get("mode"),
        seed_reason=(seed_selection or {}).get("reason"),
        changed_files=changed_files,
        sections=sections,
        build_decision=build_decision,
        top_risks=top_risks,
        next_tests=next_tests,
        key_evidence_paths=key_evidence_paths,
        next_step=next_step,
        seed_confidence=(seed_selection or {}).get("seed_confidence", (seed_selection or {}).get("confidence")),
        recent_task_influenced=bool((seed_selection or {}).get("recent_task_influenced")),
        report_completeness=report_completeness,
        test_signal=test_signal,
        user_summary=user_summary,
        trust=trust,
    )
    brief.update(provider_metadata)
    brief["must_read_first"] = key_evidence_paths[:6]
    json_payload = {
        "task_id": task_id,
        "generated_at": utc_now(),
        "git_sha": git["git_sha"],
        "mode": mode,
        "seed": seed,
        "secondary_seeds": list((seed_selection or {}).get("secondary_seeds", [])),
        "seed_mode": (seed_selection or {}).get("mode"),
        "seed_kind": sections["seed_kind"],
        "changed_files": changed_files,
        "detected_adapter": detected_adapter,
        "detected_profile": detected_profile,
        "adapter": {
            "primary_adapter": detected_adapter,
            "supplemental_adapters": list((build_decision or {}).get("supplemental_adapters", [])),
            "adapter_source": (build_decision or {}).get("adapter_source"),
            "adapter_reason": (build_decision or {}).get("adapter_reason"),
            "adapter_conflicts": (build_decision or {}).get("adapter_conflicts", []),
            "adapter_confidence": (build_decision or {}).get("adapter_confidence"),
        },
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
        "affected_contracts": affected_contracts,
        "architecture_chains": architecture_chains,
        "atlas_views": atlas_views,
        "atlas_summary": atlas_summary,
        "brief": brief,
        "provider": provider_metadata,
        "provider_overlay": provider_overlay,
        "trust": trust,
        "trust_axes": trust.get("trust_axes", {}),
        "trust_explanation": trust.get("trust_explanation", []),
        "seed_selection": seed_selection or {},
        "build_decision": build_decision or {},
        "context_resolution": context_resolution or {},
        "report_completeness": report_completeness,
        "test_signal": test_signal,
        "user_summary": user_summary,
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
        context_resolution=context_resolution,
    )
    json_report_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mermaid_path.write_text(mermaid, encoding="utf-8")

    with connect_db(paths["db_path"]) as conn:
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
                json.dumps({"max_depth": max_depth, "seed_kind": sections["seed_kind"], "mode": mode, "json_report_path": str(json_report_path.relative_to(workspace_root)), "brief": brief, "report_completeness": report_completeness, "test_signal": test_signal, "trust": trust, "atlas_summary": atlas_summary}, ensure_ascii=False),
            ),
        )

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
        "direct_tests": related_test_names,
        "direct_rules": related_rule_names,
        "user_summary": user_summary,
        "changed_files": changed_files,
        "definition": seed_detail or {"node_id": seed, "kind": sections["seed_kind"]},
        "direct": json_payload["direct"],
        "affected_contracts": affected_contracts,
        "architecture_chains": architecture_chains,
        "atlas_views": atlas_views,
        "atlas_summary": atlas_summary,
        "report_completeness": report_completeness,
        "test_signal": test_signal,
        "trust": trust,
        "provider": provider_metadata,
        "provider_overlay": provider_overlay,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an impact report from the direct-edge graph")
    parser.add_argument("--workspace-root", default=".", help="Workspace root")
    parser.add_argument("--config", default=".zhanggong-impact-blueprint/config.json", help="Config path")
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

