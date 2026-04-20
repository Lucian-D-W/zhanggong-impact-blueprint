#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re


CONTRACT_KINDS = {
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

HTTP_METHODS = "get|post|put|patch|delete"
UPPERCASE_JSX_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")
JSX_ROUTE_RE = re.compile(r"""path\s*:\s*['"]([^'"]+)['"][\s\S]{0,200}?element\s*:\s*<([A-Z][A-Za-z0-9_]*)\b""")
JSX_ROUTE_COMPONENT_RE = re.compile(r"""<Route\b[\s\S]{0,120}?path\s*=\s*['"]([^'"]+)['"][\s\S]{0,120}?element\s*=\s*\{\s*<([A-Z][A-Za-z0-9_]*)\b""")

LITERAL_ENV_PATTERNS = [
    (re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b"), "process.env literal"),
    (re.compile(r"""\bprocess\.env\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""), "process.env bracket literal"),
    (re.compile(r"\bimport\.meta\.env\.([A-Z][A-Z0-9_]*)\b"), "import.meta.env literal"),
    (re.compile(r"""\bDeno\.env\.get\(\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\)"""), "Deno.env.get literal"),
    (re.compile(r"""\bos\.environ\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""), "os.environ literal"),
    (re.compile(r"""\bos\.getenv\(\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\)"""), "os.getenv literal"),
    (re.compile(r"""\benviron\.get\(\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\)"""), "environ.get literal"),
]
LITERAL_CONFIG_PATTERNS = [
    (re.compile(r"""\bconfig\.get\(\s*['"]([^'"]+)['"]\s*\)"""), "config.get literal"),
    (re.compile(r"""\bgetConfig\(\s*['"]([^'"]+)['"]\s*\)"""), "getConfig literal"),
    (re.compile(r"""\bsettings\.([A-Za-z_][A-Za-z0-9_]*)\b"""), "settings property literal"),
    (re.compile(r"""\bsettings\[\s*['"]([^'"]+)['"]\s*\]"""), "settings bracket literal"),
]
CLIENT_ENDPOINT_PATTERNS = [
    (re.compile(r"""\bfetch\(\s*['"]([^'"]+)['"]"""), "fetch literal"),
    (re.compile(r"""\baxios\.(?:%s)\(\s*['"]([^'"]+)['"]""" % HTTP_METHODS), "axios literal"),
    (re.compile(r"""\b(?:request|client\.(?:%s))\(\s*['"]([^'"]+)['"]""" % HTTP_METHODS), "request/client literal"),
]
BACKEND_ENDPOINT_PATTERNS = [
    re.compile(r"""\b(?:app|router|fastify)\.(?:%s)\(\s*['"]([^'"]+)['"](?:\s*,\s*([A-Za-z_][A-Za-z0-9_]*))?""" % HTTP_METHODS),
    re.compile(r"""@(?:app|router)\.(?:%s)\(\s*['"]([^'"]+)['"]\s*\)\s*\ndef\s+([A-Za-z_][A-Za-z0-9_]*)""" % HTTP_METHODS),
]
EVENT_EMIT_LITERAL_PATTERNS = [
    (re.compile(r"""\b(?:window|document)\.dispatchEvent\(\s*new\s+CustomEvent\(\s*['"]([^'"]+)['"]"""), "CustomEvent literal"),
    (re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]*\.emit\(\s*['"]([^'"]+)['"]"""), "EventEmitter.emit literal"),
    (re.compile(r"""\b(?:publish|dispatch)\(\s*['"]([^'"]+)['"]"""), "publish/dispatch literal"),
]
EVENT_HANDLE_LITERAL_PATTERNS = [
    (re.compile(r"""\b(?:window|document)\.addEventListener\(\s*['"]([^'"]+)['"]"""), "addEventListener literal"),
    (re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]*\.(?:on|listen)\(\s*['"]([^'"]+)['"]"""), "EventEmitter.on/listen literal"),
    (re.compile(r"""\bsubscribe\(\s*['"]([^'"]+)['"]"""), "subscribe literal"),
]
IPC_SEND_LITERAL_PATTERNS = [
    (re.compile(r"""\bipcRenderer\.(?:send|invoke)\(\s*['"]([^'"]+)['"]"""), "ipcRenderer literal"),
    (re.compile(r"""\binvoke\(\s*['"]([^'"]+)['"]"""), "tauri invoke literal"),
    (re.compile(r"""\bemit\(\s*['"]([^'"]+)['"]"""), "tauri emit literal"),
]
IPC_HANDLE_LITERAL_PATTERNS = [
    (re.compile(r"""\bipcMain\.(?:handle|on)\(\s*['"]([^'"]+)['"]"""), "ipcMain literal"),
    (re.compile(r"""\blisten\(\s*['"]([^'"]+)['"]"""), "tauri listen literal"),
]
SQL_SELECT_RE = re.compile(r"(?is)\bselect\b[\s\S]{0,300}?\bfrom\s+([a-z_][a-z0-9_\.]*)")
SQL_JOIN_RE = re.compile(r"(?is)\bjoin\s+([a-z_][a-z0-9_\.]*)")
SQL_INSERT_RE = re.compile(r"(?is)\binsert\s+into\s+([a-z_][a-z0-9_\.]*)")
SQL_UPDATE_RE = re.compile(r"(?is)\bupdate\s+([a-z_][a-z0-9_\.]*)")
SQL_DELETE_RE = re.compile(r"(?is)\bdelete\s+from\s+([a-z_][a-z0-9_\.]*)")
SQL_CREATE_TABLE_RE = re.compile(r"(?is)\bcreate\s+table\s+([a-z_][a-z0-9_\.]*)")
SQL_ALTER_TABLE_RE = re.compile(r"(?is)\balter\s+table\s+([a-z_][a-z0-9_\.]*)")
SQL_DROP_TABLE_RE = re.compile(r"(?is)\bdrop\s+table\s+([a-z_][a-z0-9_\.]*)")
SQL_INDEX_ON_RE = re.compile(r"(?is)\bcreate\s+index\b[\s\S]{0,120}?\bon\s+([a-z_][a-z0-9_\.]*)")
OBSIDIAN_REGISTER_RE = re.compile(r"""addCommand\(\s*\{[\s\S]{0,200}?id\s*:\s*['"]([^'"]+)['"]""")
OBSIDIAN_EXECUTE_RE = re.compile(r"""(?:app\.)?commands\.executeCommandById\(\s*['"]([^'"]+)['"]""")
PLAYWRIGHT_TEST_RE = re.compile(r"""(?:^|\b)(?:test|it)\(\s*['"]([^'"]+)['"]""")
PLAYWRIGHT_GOTO_RE = re.compile(r"""page\.goto\(\s*['"]([^'"]+)['"]""")
PLAYWRIGHT_URL_RE = re.compile(r"""toHaveURL\(\s*['"]([^'"]+)['"]""")


def contract_confidence(signal: str, *, literal: bool = True, fallback: bool = False) -> dict:
    if fallback:
        return {"confidence": 0.55, "confidence_reason": f"{signal} but relationship type is uncertain"}
    if literal:
        return {"confidence": 0.9, "confidence_reason": signal}
    return {"confidence": 0.72, "confidence_reason": signal}


def scope_line(scope: dict, offset: int) -> int:
    return int(scope.get("start_line") or 1) + scope["text"][:offset].count("\n")


def base_name(value: str) -> str:
    return value.split(".")[-1]


def route_from_fs_path(relative_path: str) -> str | None:
    pure = pathlib.PurePosixPath(relative_path)
    parts = list(pure.parts)
    if "app" in parts and pure.name.startswith("page."):
        index = parts.index("app")
        route_parts = parts[index + 1 : -1]
    elif "pages" in parts and pure.suffix in {".js", ".jsx", ".ts", ".tsx"}:
        index = parts.index("pages")
        route_parts = parts[index + 1 :]
        if route_parts and route_parts[-1].startswith("index."):
            route_parts = route_parts[:-1]
        elif route_parts:
            route_parts[-1] = pathlib.PurePosixPath(route_parts[-1]).stem
    else:
        return None
    if not route_parts:
        return "/"
    normalized: list[str] = []
    for part in route_parts:
        if part.startswith("[") and part.endswith("]"):
            normalized.append(f":{part[1:-1]}")
        else:
            normalized.append(part)
    return "/" + "/".join(item for item in normalized if item)


def component_node_id(relative_path: str, name: str) -> str:
    return f"component:{relative_path}:{name}"


def prop_node_id(relative_path: str, component_name: str, prop_name: str) -> str:
    return f"prop:{relative_path}:{component_name}:{prop_name}"


def flow_node_id(relative_path: str, name: str) -> str:
    return f"playwright_flow:{relative_path}:{name}"


def generic_node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def dynamic_contract_name(kind: str, token: str) -> str:
    cleaned = re.sub(r"\s+", " ", token.strip())
    cleaned = cleaned[:48] if cleaned else "dynamic"
    return f"dynamic:{kind}:{cleaned}"


def empty_artifacts() -> dict:
    return {"nodes": [], "edges": []}


def link_contracts(*artifacts: dict) -> dict:
    merged = {"nodes": [], "edges": []}
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    for artifact in artifacts:
        for node in artifact.get("nodes", []):
            node_id = node["node_id"]
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            merged["nodes"].append(node)
        for edge in artifact.get("edges", []):
            edge_key = (edge["src_id"], edge["edge_type"], edge["dst_id"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            merged["edges"].append(edge)
    return merged


def _add_node(artifact: dict, *, node_id: str, kind: str, name: str, path: str, symbol: str, start_line: int, end_line: int, attrs: dict) -> None:
    artifact["nodes"].append(
        {
            "node_id": node_id,
            "kind": kind,
            "name": name,
            "path": path,
            "symbol": symbol,
            "start_line": start_line,
            "end_line": end_line,
            "attrs": attrs,
        }
    )


def _add_edge(
    artifact: dict,
    *,
    src_id: str,
    edge_type: str,
    dst_id: str,
    relative_path: str,
    start_line: int,
    end_line: int,
    confidence: float,
    attrs: dict,
) -> None:
    artifact["edges"].append(
        {
            "src_id": src_id,
            "edge_type": edge_type,
            "dst_id": dst_id,
            "relative_path": relative_path,
            "start_line": start_line,
            "end_line": end_line,
            "confidence": confidence,
            "extractor": attrs["extractor"],
            "attrs": attrs,
        }
    )


def _ensure_contract_node(
    artifact: dict,
    *,
    kind: str,
    value: str,
    relative_path: str,
    line_no: int,
    extractor: str,
    confidence_reason: str,
    node_id: str | None = None,
) -> str:
    resolved_node_id = node_id or generic_node_id(kind, value)
    _add_node(
        artifact,
        node_id=resolved_node_id,
        kind=kind,
        name=value,
        path=relative_path,
        symbol=value,
        start_line=line_no,
        end_line=line_no,
        attrs={
            "contract_value": value,
            "extractor": extractor,
            "confidence_reason": confidence_reason,
        },
    )
    return resolved_node_id


def extract_props_from_component_scope(scope: dict, source_text: str) -> list[str]:
    header = "\n".join(source_text.splitlines()[scope["start_line"] - 1 : min(scope["start_line"] + 3, scope["end_line"])])
    destructured = re.search(r"""\(\s*\{\s*([^}]+)\}\s*\)""", header)
    props: list[str] = []
    if destructured:
        for part in destructured.group(1).split(","):
            candidate = part.strip().split(":", 1)[0].split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate):
                props.append(candidate)
    return sorted(set(props))


def _scopes_for_source(
    *,
    relative_path: str,
    source_text: str,
    function_records: list[dict],
    test_records: list[dict],
) -> dict:
    lines = source_text.splitlines()
    ordered_function_records = sorted(function_records, key=lambda item: int(item.get("start_line") or 1))
    function_scopes: list[dict] = []
    test_scopes: list[dict] = []
    component_scopes: list[dict] = []
    component_names: set[str] = set()
    component_props: dict[str, set[str]] = {}

    for index, record in enumerate(ordered_function_records):
        start_line = max(int(record.get("start_line") or 1), 1)
        end_line = max(int(record.get("end_line") or start_line), start_line)
        next_start = None
        if index + 1 < len(ordered_function_records):
            next_start = int(ordered_function_records[index + 1].get("start_line") or end_line)
        if next_start:
            end_line = min(end_line, max(next_start - 1, start_line))
        text = "\n".join(lines[start_line - 1 : end_line])
        scope = {
            "node_id": record["node_id"],
            "kind": "function",
            "name": record["name"],
            "path": relative_path,
            "start_line": start_line,
            "end_line": end_line,
            "text": text,
            "attrs": record.get("attrs", {}),
        }
        function_scopes.append(scope)
        if record.get("attrs", {}).get("is_component"):
            component_id = component_node_id(relative_path, record["name"])
            component_scope = {
                **scope,
                "node_id": component_id,
                "kind": "component",
                "source_node_id": record["node_id"],
            }
            component_scopes.append(component_scope)
            component_names.add(record["name"])
            component_props[record["name"]] = set(extract_props_from_component_scope(component_scope, source_text))

    ordered_test_records = sorted(test_records, key=lambda item: int(item.get("start_line") or 1))
    for index, record in enumerate(ordered_test_records):
        start_line = max(int(record.get("start_line") or 1), 1)
        end_line = max(int(record.get("end_line") or start_line), start_line)
        next_start = None
        if index + 1 < len(ordered_test_records):
            next_start = int(ordered_test_records[index + 1].get("start_line") or end_line)
        if next_start:
            end_line = max(end_line, max(next_start - 1, start_line))
        elif end_line <= start_line:
            end_line = max(len(lines), start_line)
        test_scopes.append(
            {
                "node_id": record["node_id"],
                "kind": "test",
                "name": record["name"],
                "path": relative_path,
                "start_line": start_line,
                "end_line": end_line,
                "text": "\n".join(lines[start_line - 1 : end_line]),
                "attrs": record.get("attrs", {}),
            }
        )
    return {
        "file_scope": {
            "node_id": f"file:{relative_path}",
            "kind": "file",
            "name": pathlib.PurePosixPath(relative_path).name,
            "path": relative_path,
            "start_line": 1,
            "end_line": max(len(lines), 1),
            "text": source_text,
            "attrs": {},
        },
        "function_scopes": function_scopes,
        "test_scopes": test_scopes,
        "component_scopes": component_scopes,
        "component_names": component_names,
        "component_props": component_props,
    }


def _record_literal_contract(
    artifact: dict,
    *,
    scope: dict,
    kind: str,
    value: str,
    edge_type: str,
    extractor: str,
    line_no: int,
    confidence_reason: str,
    node_id: str | None = None,
    dependency_kind: str,
) -> None:
    confidence_info = contract_confidence(confidence_reason, literal=True)
    resolved_node_id = _ensure_contract_node(
        artifact,
        kind=kind,
        value=value,
        relative_path=scope["path"],
        line_no=line_no,
        extractor=extractor,
        confidence_reason=confidence_info["confidence_reason"],
        node_id=node_id,
    )
    _add_edge(
        artifact,
        src_id=scope["node_id"],
        edge_type=edge_type,
        dst_id=resolved_node_id,
        relative_path=scope["path"],
        start_line=line_no,
        end_line=line_no,
        confidence=confidence_info["confidence"],
        attrs={
            "dependency_kind": dependency_kind,
            "extractor": extractor,
            "confidence_reason": confidence_info["confidence_reason"],
        },
    )


def _record_depends_on(
    artifact: dict,
    *,
    scope: dict,
    kind: str,
    value: str,
    extractor: str,
    line_no: int,
    dependency_kind: str,
    confidence_reason: str,
    node_id: str | None = None,
) -> None:
    confidence_info = contract_confidence(confidence_reason, fallback=True)
    resolved_node_id = _ensure_contract_node(
        artifact,
        kind=kind,
        value=value,
        relative_path=scope["path"],
        line_no=line_no,
        extractor=extractor,
        confidence_reason=confidence_info["confidence_reason"],
        node_id=node_id,
    )
    _add_edge(
        artifact,
        src_id=scope["node_id"],
        edge_type="DEPENDS_ON",
        dst_id=resolved_node_id,
        relative_path=scope["path"],
        start_line=line_no,
        end_line=line_no,
        confidence=min(confidence_info["confidence"], 0.65),
        attrs={
            "dependency_kind": dependency_kind,
            "extractor": extractor,
            "confidence_reason": confidence_info["confidence_reason"],
        },
    )


def extract_env_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], *scopes["test_scopes"], scopes["file_scope"]]:
        for pattern, reason in LITERAL_ENV_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="env_var",
                    value=match.group(1),
                    edge_type="READS_ENV",
                    extractor="env_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="env_read",
                )
        for match in re.finditer(r"""\b(?:process\.env|os\.environ)\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*\]""", scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="env_var",
                value=dynamic_contract_name("env", match.group(1)),
                extractor="env_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="env_read",
                confidence_reason="dynamic env key",
            )
        for match in re.finditer(r"""\b(?:os\.getenv|environ\.get|Deno\.env\.get)\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)""", scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="env_var",
                value=dynamic_contract_name("env", match.group(1)),
                extractor="env_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="env_read",
                confidence_reason="dynamic env accessor argument",
            )
    return artifact


def extract_config_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], scopes["file_scope"]]:
        for pattern, reason in LITERAL_CONFIG_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="config_key",
                    value=match.group(1),
                    edge_type="READS_CONFIG",
                    extractor="config_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="config_read",
                )
        for match in re.finditer(r"""\b(?:config\.get|getConfig)\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)""", scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="config_key",
                value=dynamic_contract_name("config", match.group(1)),
                extractor="config_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="config_read",
                confidence_reason="dynamic config key",
            )
        for match in re.finditer(r"""\bsettings\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*\]""", scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="config_key",
                value=dynamic_contract_name("config", match.group(1)),
                extractor="config_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="config_read",
                confidence_reason="dynamic settings key",
            )
    return artifact


def extract_endpoint_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    function_by_name = {scope["name"]: scope for scope in scopes["function_scopes"]}
    for scope in [*scopes["function_scopes"], *scopes["test_scopes"], scopes["file_scope"]]:
        for pattern, reason in CLIENT_ENDPOINT_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                endpoint = match.group(1)
                if not endpoint.startswith("/"):
                    continue
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="endpoint",
                    value=endpoint,
                    edge_type="USES_ENDPOINT",
                    extractor="endpoint_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="endpoint_use",
                )
    for pattern in BACKEND_ENDPOINT_PATTERNS:
        for match in pattern.finditer(source_text):
            endpoint = match.group(1)
            if not endpoint.startswith("/"):
                continue
            handler_name = match.group(2) if match.lastindex and match.lastindex >= 2 else None
            scope = function_by_name.get(handler_name) if handler_name else None
            scope = scope or scopes["file_scope"]
            _record_literal_contract(
                artifact,
                scope=scope,
                kind="endpoint",
                value=endpoint,
                edge_type="EXPOSES_ENDPOINT",
                extractor="endpoint_scan",
                line_no=source_text[: match.start()].count("\n") + 1,
                confidence_reason="backend endpoint literal",
                dependency_kind="endpoint_expose",
            )
    return artifact


def extract_route_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    component_names = set(scopes["component_names"])
    component_ids = {name: component_node_id(relative_path, name) for name in component_names}

    for pattern in (JSX_ROUTE_RE, JSX_ROUTE_COMPONENT_RE):
        for match in pattern.finditer(source_text):
            route_name = match.group(1)
            component_name = match.group(2)
            line_no = source_text[: match.start()].count("\n") + 1
            route_id = _ensure_contract_node(
                artifact,
                kind="route",
                value=route_name,
                relative_path=relative_path,
                line_no=line_no,
                extractor="route_scan",
                confidence_reason="router path literal",
            )
            component_id = component_ids.get(component_name, component_node_id(relative_path, component_name))
            _ensure_contract_node(
                artifact,
                kind="component",
                value=component_name,
                relative_path=relative_path,
                line_no=line_no,
                extractor="component_scan",
                confidence_reason="route element literal",
                node_id=component_id,
            )
            _add_edge(
                artifact,
                src_id=route_id,
                edge_type="ROUTES_TO",
                dst_id=component_id,
                relative_path=relative_path,
                start_line=line_no,
                end_line=line_no,
                confidence=0.88,
                attrs={
                    "dependency_kind": "route_component",
                    "extractor": "route_scan",
                    "confidence_reason": "route path literal and JSX element literal",
                },
            )

    fs_route = route_from_fs_path(relative_path)
    if fs_route:
        route_id = _ensure_contract_node(
            artifact,
            kind="route",
            value=fs_route,
            relative_path=relative_path,
            line_no=1,
            extractor="route_fs_scan",
            confidence_reason="file-system route inference",
        )
        if scopes["component_scopes"]:
            component_scope = scopes["component_scopes"][0]
            _ensure_contract_node(
                artifact,
                kind="component",
                value=component_scope["name"],
                relative_path=relative_path,
                line_no=component_scope["start_line"],
                extractor="component_scan",
                confidence_reason="component definition",
                node_id=component_scope["node_id"],
            )
            _add_edge(
                artifact,
                src_id=route_id,
                edge_type="ROUTES_TO",
                dst_id=component_scope["node_id"],
                relative_path=relative_path,
                start_line=1,
                end_line=1,
                confidence=0.86,
                attrs={
                    "dependency_kind": "route_component",
                    "extractor": "route_fs_scan",
                    "confidence_reason": "file-system route to page component",
                },
            )
    return artifact


def extract_component_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    component_names = set(scopes["component_names"])
    for component_scope in scopes["component_scopes"]:
        props = scopes["component_props"].get(component_scope["name"], set())
        _ensure_contract_node(
            artifact,
            kind="component",
            value=component_scope["name"],
            relative_path=relative_path,
            line_no=component_scope["start_line"],
            extractor="component_scan",
            confidence_reason="component definition",
            node_id=component_scope["node_id"],
        )
        for prop_name in sorted(props):
            prop_id = prop_node_id(relative_path, component_scope["name"], prop_name)
            _ensure_contract_node(
                artifact,
                kind="prop",
                value=prop_name,
                relative_path=relative_path,
                line_no=component_scope["start_line"],
                extractor="component_scan",
                confidence_reason="destructured prop parameter",
                node_id=prop_id,
            )
            _add_edge(
                artifact,
                src_id=component_scope["node_id"],
                edge_type="USES_PROP",
                dst_id=prop_id,
                relative_path=relative_path,
                start_line=component_scope["start_line"],
                end_line=component_scope["start_line"],
                confidence=0.84,
                attrs={
                    "dependency_kind": "component_prop",
                    "extractor": "component_scan",
                    "confidence_reason": "destructured prop parameter",
                },
            )
        for match in UPPERCASE_JSX_TAG_RE.finditer(component_scope["text"]):
            child_name = match.group(1)
            if child_name == component_scope["name"]:
                continue
            line_no = scope_line(component_scope, match.start())
            child_id = component_node_id(relative_path, child_name)
            _ensure_contract_node(
                artifact,
                kind="component",
                value=child_name,
                relative_path=relative_path,
                line_no=line_no,
                extractor="component_scan",
                confidence_reason="JSX component reference",
                node_id=child_id,
            )
            if child_name in component_names:
                _add_edge(
                    artifact,
                    src_id=component_scope["node_id"],
                    edge_type="RENDERS_COMPONENT",
                    dst_id=child_id,
                    relative_path=relative_path,
                    start_line=line_no,
                    end_line=line_no,
                    confidence=0.87,
                    attrs={
                        "dependency_kind": "component_render",
                        "extractor": "component_scan",
                        "confidence_reason": "literal JSX component tag",
                    },
                )
            else:
                _record_depends_on(
                    artifact,
                    scope=component_scope,
                    kind="component",
                    value=child_name,
                    extractor="component_scan",
                    line_no=line_no,
                    dependency_kind="component_render",
                    confidence_reason="dynamic or imported JSX component",
                    node_id=child_id,
                )
    return artifact


def extract_event_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], scopes["file_scope"]]:
        for pattern, reason in EVENT_EMIT_LITERAL_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="event",
                    value=match.group(1),
                    edge_type="EMITS_EVENT",
                    extractor="event_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="event_emit",
                )
        for pattern, reason in EVENT_HANDLE_LITERAL_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="event",
                    value=match.group(1),
                    edge_type="HANDLES_EVENT",
                    extractor="event_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="event_handle",
                )
        for match in re.finditer(r"""\b(?:emit|publish|dispatch)\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,|\))""", scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="event",
                value=dynamic_contract_name("event", match.group(1)),
                extractor="event_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="event_emit",
                confidence_reason="dynamic event name",
            )
    return artifact


def extract_ipc_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], scopes["file_scope"]]:
        for pattern, reason in IPC_SEND_LITERAL_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="ipc_channel",
                    value=match.group(1),
                    edge_type="IPC_SENDS",
                    extractor="ipc_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="ipc_send",
                )
        for pattern, reason in IPC_HANDLE_LITERAL_PATTERNS:
            for match in pattern.finditer(scope["text"]):
                _record_literal_contract(
                    artifact,
                    scope=scope,
                    kind="ipc_channel",
                    value=match.group(1),
                    edge_type="IPC_HANDLES",
                    extractor="ipc_scan",
                    line_no=scope_line(scope, match.start()),
                    confidence_reason=reason,
                    dependency_kind="ipc_handle",
                )
    return artifact


def extract_sql_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], scopes["file_scope"]]:
        query_tables = {
            *SQL_SELECT_RE.findall(scope["text"]),
            *SQL_JOIN_RE.findall(scope["text"]),
        }
        mutation_tables = {
            *SQL_INSERT_RE.findall(scope["text"]),
            *SQL_UPDATE_RE.findall(scope["text"]),
            *SQL_DELETE_RE.findall(scope["text"]),
        }
        for table_name in sorted(base_name(item) for item in query_tables):
            _record_literal_contract(
                artifact,
                scope=scope,
                kind="sql_table",
                value=table_name,
                edge_type="QUERIES_TABLE",
                extractor="sql_scan",
                line_no=scope["start_line"],
                confidence_reason="literal SQL query",
                dependency_kind="sql_query",
            )
        for table_name in sorted(base_name(item) for item in mutation_tables):
            _record_literal_contract(
                artifact,
                scope=scope,
                kind="sql_table",
                value=table_name,
                edge_type="MUTATES_TABLE",
                extractor="sql_scan",
                line_no=scope["start_line"],
                confidence_reason="literal SQL mutation",
                dependency_kind="sql_mutation",
            )

    for pattern in (SQL_CREATE_TABLE_RE, SQL_ALTER_TABLE_RE, SQL_DROP_TABLE_RE, SQL_INDEX_ON_RE):
        for match in pattern.finditer(source_text):
            _record_literal_contract(
                artifact,
                scope=scopes["file_scope"],
                kind="sql_table",
                value=base_name(match.group(1)),
                edge_type="MUTATES_TABLE",
                extractor="sql_schema_scan",
                line_no=source_text[: match.start()].count("\n") + 1,
                confidence_reason="migration or schema literal",
                dependency_kind="sql_schema_change",
            )
    return artifact


def extract_obsidian_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for scope in [*scopes["function_scopes"], scopes["file_scope"]]:
        for match in OBSIDIAN_REGISTER_RE.finditer(scope["text"]):
            _record_literal_contract(
                artifact,
                scope=scope,
                kind="obsidian_command",
                value=match.group(1),
                edge_type="REGISTER_COMMAND",
                extractor="obsidian_scan",
                line_no=scope_line(scope, match.start()),
                confidence_reason="addCommand literal id",
                dependency_kind="command_register",
            )
        for match in OBSIDIAN_EXECUTE_RE.finditer(scope["text"]):
            _record_depends_on(
                artifact,
                scope=scope,
                kind="obsidian_command",
                value=match.group(1),
                extractor="obsidian_scan",
                line_no=scope_line(scope, match.start()),
                dependency_kind="command_use",
                confidence_reason="command invocation literal but invocation relationship is generic",
            )
    return artifact


def extract_playwright_contracts(*, relative_path: str, source_text: str, scopes: dict) -> dict:
    artifact = empty_artifacts()
    for test_scope in scopes["test_scopes"]:
        playwright_text = test_scope["text"] if test_scope["text"].strip() else source_text
        flow_match = PLAYWRIGHT_TEST_RE.search(playwright_text)
        if not flow_match:
            continue
        flow_name = flow_match.group(1)
        flow_id = flow_node_id(relative_path, flow_name)
        _ensure_contract_node(
            artifact,
            kind="playwright_flow",
            value=flow_name,
            relative_path=relative_path,
            line_no=test_scope["start_line"],
            extractor="playwright_scan",
            confidence_reason="playwright test name",
            node_id=flow_id,
        )
        flow_scope = {
            **test_scope,
            "node_id": flow_id,
            "kind": "playwright_flow",
            "name": flow_name,
        }
        for pattern in (PLAYWRIGHT_GOTO_RE, PLAYWRIGHT_URL_RE):
            for match in pattern.finditer(playwright_text):
                route_name = match.group(1)
                if not route_name.startswith("/"):
                    continue
                route_id = _ensure_contract_node(
                    artifact,
                    kind="route",
                    value=route_name,
                    relative_path=relative_path,
                    line_no=test_scope["start_line"] + playwright_text[: match.start()].count("\n"),
                    extractor="playwright_scan",
                    confidence_reason="playwright route literal",
                )
                _add_edge(
                    artifact,
                    src_id=flow_id,
                    edge_type="ROUTES_TO",
                    dst_id=route_id,
                    relative_path=relative_path,
                    start_line=test_scope["start_line"] + playwright_text[: match.start()].count("\n"),
                    end_line=test_scope["start_line"] + playwright_text[: match.start()].count("\n"),
                    confidence=0.9,
                    attrs={
                        "dependency_kind": "playwright_route",
                        "extractor": "playwright_scan",
                        "confidence_reason": "page URL literal",
                    },
                )
        for pattern, reason in CLIENT_ENDPOINT_PATTERNS:
            for match in pattern.finditer(playwright_text):
                endpoint = match.group(1)
                if not endpoint.startswith("/"):
                    continue
                _record_literal_contract(
                    artifact,
                    scope=flow_scope,
                    kind="endpoint",
                    value=endpoint,
                    edge_type="USES_ENDPOINT",
                    extractor="playwright_scan",
                    line_no=test_scope["start_line"] + playwright_text[: match.start()].count("\n"),
                    confidence_reason=reason,
                    dependency_kind="playwright_endpoint",
                )
    return artifact


def build_contract_artifacts(
    *,
    relative_path: str,
    source_text: str,
    function_records: list[dict],
    test_records: list[dict],
) -> dict:
    scopes = _scopes_for_source(
        relative_path=relative_path,
        source_text=source_text,
        function_records=function_records,
        test_records=test_records,
    )
    return link_contracts(
        extract_env_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_config_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_endpoint_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_route_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_component_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_event_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_ipc_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_sql_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_obsidian_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
        extract_playwright_contracts(relative_path=relative_path, source_text=source_text, scopes=scopes),
    )
