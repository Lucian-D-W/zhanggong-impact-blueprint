#!/usr/bin/env python3
import ast
import hashlib
import os
import pathlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.request import url2pathname


@dataclass
class AdapterGraph:
    files: list[dict] = field(default_factory=list)
    functions: list[dict] = field(default_factory=list)
    tests: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    covers: list[dict] = field(default_factory=list)
    extra_nodes: list[dict] = field(default_factory=list)
    extra_edges: list[dict] = field(default_factory=list)


def file_node_id(relative_path: str) -> str:
    return f"file:{relative_path}"


def function_node_id(relative_path: str, function_name: str) -> str:
    return f"fn:{relative_path}:{function_name}"


def test_node_id(relative_path: str, test_name: str) -> str:
    return f"test:{relative_path}:{test_name}"


DEFAULT_EXCLUDE_DIRS = [
    ".git",
    ".ai",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".playwright",
    "test-results",
]


def normalize_glob_pattern(pattern: str) -> str:
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def glob_static_prefix(pattern: str) -> str:
    normalized = normalize_glob_pattern(pattern)
    prefix_chars: list[str] = []
    for char in normalized:
        if char in "*?[":
            break
        prefix_chars.append(char)
    return "".join(prefix_chars)


def matches_any(relative_path: str, patterns: list[str]) -> bool:
    normalized = normalize_repo_relative_path(relative_path)
    pure = pathlib.PurePosixPath(normalized)
    for pattern in patterns:
        if not pattern:
            continue
        normalized_pattern = normalize_glob_pattern(pattern)
        prefix = glob_static_prefix(normalized_pattern)
        if prefix and not normalized.startswith(prefix):
            continue
        if pure.match(normalized_pattern):
            return True
    return False


def normalize_repo_relative_path(value: str) -> str:
    normalized = str(value).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def configured_exclude_dirs(config: dict) -> list[str]:
    graph_config = config.get("graph", {}) or {}
    exclude_dirs = graph_config.get("exclude_dirs")
    if isinstance(exclude_dirs, list):
        return [str(item) for item in exclude_dirs if str(item).strip()]
    return list(DEFAULT_EXCLUDE_DIRS)


def normalized_exclude_dir_set(exclude_dirs: list[str] | None) -> set[str]:
    values = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
    normalized: set[str] = set()
    for item in values:
        cleaned = normalize_repo_relative_path(item)
        if cleaned:
            normalized.add(cleaned)
    return normalized


def include_dir_prefixes(include_files: list[str] | None) -> set[str]:
    prefixes: set[str] = set()
    for item in include_files or []:
        normalized = normalize_repo_relative_path(item)
        if not normalized:
            continue
        parent = pathlib.PurePosixPath(normalized).parent
        if str(parent) == ".":
            continue
        current = ""
        for part in parent.parts:
            current = f"{current}/{part}" if current else part
            prefixes.add(current)
    return prefixes


def is_path_under_excluded_dir(path: str, excluded_dirs: set[str]) -> bool:
    return any(path == excluded or path.startswith(f"{excluded}/") for excluded in excluded_dirs)


def should_prune_dir(relative_root: str, dir_name: str, excluded_dirs: set[str], allowed_include_dirs: set[str]) -> bool:
    current_path = normalize_repo_relative_path(f"{relative_root}/{dir_name}" if relative_root else dir_name)
    if current_path in allowed_include_dirs:
        return False
    if normalize_repo_relative_path(dir_name) in excluded_dirs:
        return True
    return is_path_under_excluded_dir(current_path, excluded_dirs)


def iter_matching_files(
    project_root: pathlib.Path,
    patterns: list[str],
    include_files: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[pathlib.Path]:
    if not patterns:
        return []
    include_set = {normalize_repo_relative_path(item) for item in (include_files or []) if normalize_repo_relative_path(item)}
    excluded_dirs = normalized_exclude_dir_set(exclude_dirs)
    allowed_include_dirs = include_dir_prefixes(include_files)
    results: dict[str, pathlib.Path] = {}
    for current_root, dirs, files in os.walk(project_root, topdown=True):
        current_root_path = pathlib.Path(current_root)
        relative_root = ""
        if current_root_path != project_root:
            relative_root = normalize_repo_relative_path(current_root_path.relative_to(project_root).as_posix())
        dirs[:] = sorted(
            dir_name
            for dir_name in dirs
            if not should_prune_dir(relative_root, dir_name, excluded_dirs, allowed_include_dirs)
        )
        for file_name in sorted(files):
            path = current_root_path / file_name
            relative = normalize_repo_relative_path(path.relative_to(project_root).as_posix())
            if include_set and relative not in include_set:
                continue
            if matches_any(relative, patterns):
                results[relative] = path
    return [results[key] for key in sorted(results)]


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


SQL_QUERY_HINT_RE = re.compile(r"(?is)\b(?:select|perform|call)\s+([a-z_][a-z0-9_\.]*)\s*\(")
SQL_EXECUTE_FUNCTION_RE = re.compile(r"(?is)\bexecute\s+function\s+([a-z_][a-z0-9_\.]*)\s*\(")


def extract_sql_query_hints(text: str) -> list[str]:
    hints = {match.group(1) for match in SQL_QUERY_HINT_RE.finditer(text)}
    hints.update(match.group(1) for match in SQL_EXECUTE_FUNCTION_RE.finditer(text))
    return sorted(hints)


CONTRACT_ENV_RE = re.compile(r"\bprocess\.env\.([A-Z0-9_]+)\b")
CONTRACT_CONFIG_GET_RE = re.compile(r"""\bconfig\.get\(\s*['"]([^'"]+)['"]\s*\)""")
CONTRACT_SETTINGS_RE = re.compile(r"\bsettings\.([A-Za-z0-9_\.]+)\b")
CONTRACT_FETCH_RE = re.compile(r"""\bfetch\(\s*['"]([^'"]+)['"]\s*[\),]""")
CONTRACT_IPC_SEND_RE = re.compile(r"""\bipcRenderer\.send\(\s*['"]([^'"]+)['"]""")
CONTRACT_IPC_HANDLE_RE = re.compile(r"""\bipcMain\.(?:handle|on)\(\s*['"]([^'"]+)['"]""")
CONTRACT_OBSIDIAN_COMMAND_RE = re.compile(r"""addCommand\(\s*\{[\s\S]{0,200}?id\s*:\s*['"]([^'"]+)['"]""")
CONTRACT_PLAYWRIGHT_RE = re.compile(r"""\b(?:test|it)\(\s*['"]([^'"]+)['"]""")
SQL_SELECT_TABLE_RE = re.compile(r"(?is)\bselect\b[\s\S]{0,120}?\bfrom\s+([a-z_][a-z0-9_\.]*)")
SQL_DELETE_TABLE_RE = re.compile(r"(?is)\bdelete\s+from\s+([a-z_][a-z0-9_\.]*)")
SQL_INSERT_TABLE_RE = re.compile(r"(?is)\binsert\s+into\s+([a-z_][a-z0-9_\.]*)")
SQL_UPDATE_TABLE_RE = re.compile(r"(?is)\bupdate\s+([a-z_][a-z0-9_\.]*)")


def contract_node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def append_contract_artifacts(
    adapter_graph: AdapterGraph,
    *,
    relative_path: str,
    source_text: str,
    language: str,
) -> None:
    file_id = file_node_id(relative_path)
    seen_nodes: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def add_contract(kind: str, value: str, edge_type: str, *, extractor: str, confidence: float = 0.8) -> None:
        if not value:
            return
        node_key = (kind, value)
        node_id = contract_node_id(kind, value)
        if node_key not in seen_nodes:
            seen_nodes.add(node_key)
            adapter_graph.extra_nodes.append(
                {
                    "node_id": node_id,
                    "kind": kind,
                    "name": value,
                    "path": relative_path,
                    "symbol": value,
                    "start_line": 1,
                    "end_line": 1,
                    "attrs": {
                        "language": language,
                        "contract_value": value,
                        "definition_kind": "runtime_contract",
                    },
                }
            )
        edge_key = (file_id, edge_type, node_id)
        if edge_key in seen_edges:
            return
        seen_edges.add(edge_key)
        adapter_graph.extra_edges.append(
            {
                "src_id": file_id,
                "dst_id": node_id,
                "edge_type": edge_type,
                "relative_path": relative_path,
                "start_line": 1,
                "end_line": 1,
                "extractor": extractor,
                "confidence": confidence,
            }
        )

    for env_name in sorted(set(CONTRACT_ENV_RE.findall(source_text))):
        add_contract("env_var", env_name, "READS_ENV", extractor="contract_env_scan")
    for config_key in sorted(set(CONTRACT_CONFIG_GET_RE.findall(source_text)) | set(CONTRACT_SETTINGS_RE.findall(source_text))):
        add_contract("config_key", config_key, "READS_CONFIG", extractor="contract_config_scan")
    for endpoint in sorted(set(CONTRACT_FETCH_RE.findall(source_text))):
        add_contract("endpoint", endpoint, "ROUTES_TO", extractor="contract_endpoint_scan")
    for channel in sorted(set(CONTRACT_IPC_SEND_RE.findall(source_text))):
        add_contract("ipc_channel", channel, "IPC_SENDS", extractor="contract_ipc_send_scan")
    for channel in sorted(set(CONTRACT_IPC_HANDLE_RE.findall(source_text))):
        add_contract("ipc_channel", channel, "IPC_HANDLES", extractor="contract_ipc_handle_scan")
    for command_id in sorted(set(CONTRACT_OBSIDIAN_COMMAND_RE.findall(source_text))):
        add_contract("obsidian_command", command_id, "REGISTER_COMMAND", extractor="contract_obsidian_command_scan")
    for flow_name in sorted(set(CONTRACT_PLAYWRIGHT_RE.findall(source_text))):
        add_contract("playwright_flow", flow_name, "ROUTES_TO", extractor="contract_playwright_flow_scan", confidence=0.7)

    query_tables = sorted(set(SQL_SELECT_TABLE_RE.findall(source_text)) | set(SQL_DELETE_TABLE_RE.findall(source_text)))
    mutation_tables = sorted(set(SQL_INSERT_TABLE_RE.findall(source_text)) | set(SQL_UPDATE_TABLE_RE.findall(source_text)))
    for table_name in query_tables:
        add_contract("sql_table", table_name.split(".")[-1], "QUERIES_TABLE", extractor="contract_sql_query_scan")
    for table_name in mutation_tables:
        add_contract("sql_table", table_name.split(".")[-1], "MUTATES_TABLE", extractor="contract_sql_mutation_scan")


def resolve_python_module(module_name: str, project_root: pathlib.Path) -> str | None:
    module_path = project_root / pathlib.Path(*module_name.split("."))
    file_candidate = module_path.with_suffix(".py")
    if file_candidate.exists():
        return file_candidate.relative_to(project_root).as_posix()
    package_candidate = module_path / "__init__.py"
    if package_candidate.exists():
        return package_candidate.relative_to(project_root).as_posix()
    return None


def python_node_text(source_text: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(source_text, node)
    if segment:
        return segment
    return ""


def python_method_symbol(class_name: str, method_name: str) -> str:
    return f"{class_name}.{method_name}"


def infer_python_instance_types(node: ast.AST) -> dict[str, str]:
    instance_type_map: dict[str, str] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
            target_name = child.targets[0].id
            if isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name):
                instance_type_map[target_name] = child.value.func.id
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            target_name = child.target.id
            annotation = child.annotation.id if isinstance(child.annotation, ast.Name) else None
            if annotation and isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name) and child.value.func.id == annotation:
                instance_type_map[target_name] = annotation
    return instance_type_map


def extract_python_called_targets(
    *,
    node: ast.AST,
    local_function_ids: dict[str, str],
    imported_function_map: dict[str, str],
    imported_module_map: dict[str, str],
    imported_symbol_map: dict[str, tuple[str, str]] | None = None,
    instance_type_map: dict[str, str] | None = None,
    class_method_ids: dict[str, str] | None = None,
    all_class_method_ids: dict[str, dict[str, str]] | None = None,
) -> list[tuple[str, int]]:
    class_method_ids = class_method_ids or {}
    all_class_method_ids = all_class_method_ids or {}
    imported_symbol_map = imported_symbol_map or {}
    instance_type_map = instance_type_map or {}
    targets: list[tuple[str, int]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target_id: str | None = None
        func = child.func
        if isinstance(func, ast.Name):
            if func.id in local_function_ids:
                target_id = local_function_ids[func.id]
            elif func.id in imported_function_map:
                target_id = imported_function_map[func.id]
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            alias = func.value.id
            if alias in imported_module_map:
                target_id = function_node_id(imported_module_map[alias], func.attr)
            elif alias in imported_symbol_map:
                target_file, symbol_name = imported_symbol_map[alias]
                target_id = function_node_id(target_file, python_method_symbol(symbol_name, func.attr))
            elif alias in {"self", "cls"} and func.attr in class_method_ids:
                target_id = class_method_ids[func.attr]
            elif alias in instance_type_map:
                class_name = instance_type_map[alias]
                target_id = all_class_method_ids.get(class_name, {}).get(func.attr)
                if target_id is None and class_name in imported_symbol_map:
                    target_file, symbol_name = imported_symbol_map[class_name]
                    target_id = function_node_id(target_file, python_method_symbol(symbol_name, func.attr))
            elif alias in all_class_method_ids and func.attr in all_class_method_ids[alias]:
                target_id = all_class_method_ids[alias][func.attr]
        if target_id:
            targets.append((target_id, getattr(child, "lineno", 1)))
    return targets


def parse_python_backend(project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    python_config = config["python"]
    patterns = python_config["source_globs"] + python_config["test_globs"]
    exclude_dirs = configured_exclude_dirs(config)

    file_records: dict[str, dict] = {}
    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files, exclude_dirs=exclude_dirs):
        relative = path.relative_to(project_root).as_posix()
        source_text = path.read_text(encoding="utf-8")
        module = ast.parse(source_text, filename=str(path))
        is_test_file = matches_any(relative, python_config["test_globs"])
        file_records[relative] = {
            "path": relative,
            "is_test_file": is_test_file,
            "content_hash": sha1_text(source_text),
            "attrs": {
                "extension": path.suffix,
                "parser_backend": "python_ast",
            },
        }
        append_contract_artifacts(
            adapter_graph,
            relative_path=relative,
            source_text=source_text,
            language="python",
        )
        import_file_targets: list[tuple[str, int]] = []
        imported_function_map: dict[str, str] = {}
        imported_module_map: dict[str, str] = {}
        imported_symbol_map: dict[str, tuple[str, str]] = {}
        local_function_ids: dict[str, str] = {}
        all_class_method_ids: dict[str, dict[str, str]] = {}
        function_nodes: list[ast.FunctionDef] = []
        class_method_nodes: list[tuple[str, ast.FunctionDef]] = []
        test_nodes: list[tuple[str, ast.AST, dict[str, str]]] = []

        for child in module.body:
            if isinstance(child, ast.Import):
                for alias in child.names:
                    target_file = resolve_python_module(alias.name, project_root)
                    if target_file:
                        import_file_targets.append((target_file, getattr(child, "lineno", 1)))
                        imported_module_map[alias.asname or alias.name.split(".")[-1]] = target_file
            elif isinstance(child, ast.ImportFrom) and child.module:
                target_file = resolve_python_module(child.module, project_root)
                if target_file:
                    import_file_targets.append((target_file, getattr(child, "lineno", 1)))
                    for alias in child.names:
                        alias_name = alias.asname or alias.name
                        imported_function_map[alias_name] = function_node_id(target_file, alias.name)
                        imported_symbol_map[alias_name] = (target_file, alias.name)
            elif isinstance(child, ast.FunctionDef):
                if is_test_file and child.name.startswith("test_"):
                    test_nodes.append((child.name, child, {}))
                else:
                    local_function_ids[child.name] = function_node_id(relative, child.name)
                    function_nodes.append(child)
            elif isinstance(child, ast.ClassDef):
                class_method_map: dict[str, str] = {}
                for member in child.body:
                    if not isinstance(member, ast.FunctionDef):
                        continue
                    if is_test_file and member.name.startswith("test_"):
                        test_nodes.append((f"{child.name}.{member.name}", member, class_method_map))
                        continue
                    symbol = python_method_symbol(child.name, member.name)
                    node_id = function_node_id(relative, symbol)
                    class_method_map[member.name] = node_id
                    class_method_nodes.append((child.name, member))
                if class_method_map:
                    all_class_method_ids[child.name] = class_method_map

        for function_node in function_nodes:
            function_text = python_node_text(source_text, function_node)
            function_contexts.append(
                {
                    "node_id": function_node_id(relative, function_node.name),
                    "file_path": relative,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
                    "imported_symbol_map": imported_symbol_map,
                    "instance_type_map": infer_python_instance_types(function_node),
                    "class_method_ids": {},
                    "all_class_method_ids": all_class_method_ids,
                    "node": function_node,
                }
            )
            adapter_graph.functions.append(
                {
                    "node_id": function_node_id(relative, function_node.name),
                    "path": relative,
                    "name": function_node.name,
                    "symbol": function_node.name,
                    "start_line": function_node.lineno,
                    "end_line": function_node.end_lineno or function_node.lineno,
                    "language": "python",
                    "body_hash": sha1_text(function_text),
                    "attrs": {
                        "definition_kind": "function_definition",
                        "exported": False,
                        "sql_query_hints": extract_sql_query_hints(function_text),
                        "reference_hints": {
                            "imports": sorted(imported_function_map.keys()) + sorted(imported_module_map.keys()),
                            "exports": [],
                        },
                    },
                }
            )

        for class_name, function_node in class_method_nodes:
            symbol = python_method_symbol(class_name, function_node.name)
            function_text = python_node_text(source_text, function_node)
            function_contexts.append(
                {
                    "node_id": function_node_id(relative, symbol),
                    "file_path": relative,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
                    "imported_symbol_map": imported_symbol_map,
                    "instance_type_map": infer_python_instance_types(function_node),
                    "class_method_ids": all_class_method_ids.get(class_name, {}),
                    "all_class_method_ids": all_class_method_ids,
                    "node": function_node,
                }
            )
            adapter_graph.functions.append(
                {
                    "node_id": function_node_id(relative, symbol),
                    "path": relative,
                    "name": symbol,
                    "symbol": symbol,
                    "start_line": function_node.lineno,
                    "end_line": function_node.end_lineno or function_node.lineno,
                    "language": "python",
                    "body_hash": sha1_text(function_text),
                    "attrs": {
                        "definition_kind": "class_method",
                        "class_name": class_name,
                        "exported": False,
                        "sql_query_hints": extract_sql_query_hints(function_text),
                        "reference_hints": {
                            "imports": sorted(imported_function_map.keys()) + sorted(imported_module_map.keys()),
                            "exports": [],
                        },
                    },
                }
            )

        for test_name, test_node, class_method_map in test_nodes:
            test_contexts.append(
                {
                    "node_id": test_node_id(relative, test_name),
                    "file_path": relative,
                    "test_name": test_name,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
                    "imported_symbol_map": imported_symbol_map,
                    "instance_type_map": infer_python_instance_types(test_node),
                    "class_method_ids": class_method_map,
                    "all_class_method_ids": all_class_method_ids,
                    "node": test_node,
                }
            )
            adapter_graph.tests.append(
                {
                    "node_id": test_node_id(relative, test_name),
                    "path": relative,
                    "name": test_name,
                    "symbol": test_name,
                    "start_line": getattr(test_node, "lineno", None),
                    "end_line": getattr(test_node, "end_lineno", None),
                    "language": "python",
                    "body_hash": sha1_text(python_node_text(source_text, test_node)),
                    "attrs": {
                        "definition_kind": "test_case",
                        "test_style": "python_unittest",
                        "sql_query_hints": extract_sql_query_hints(python_node_text(source_text, test_node)),
                    },
                }
            )

        for target_file, line_no in import_file_targets:
            adapter_graph.imports.append(
                {
                    "src_id": file_node_id(relative),
                    "dst_id": file_node_id(target_file),
                    "relative_path": relative,
                    "start_line": line_no,
                    "end_line": line_no,
                    "extractor": "python_import_ast",
                }
            )

    adapter_graph.files.extend(file_records.values())

    known_function_ids = {item["node_id"] for item in adapter_graph.functions}
    for context in function_contexts:
        source_id = context.get("node_id") or function_node_id(context["file_path"], context["node"].name)
        for target_id, line_no in extract_python_called_targets(
            node=context["node"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            imported_symbol_map=context.get("imported_symbol_map"),
            instance_type_map=context.get("instance_type_map"),
            class_method_ids=context.get("class_method_ids"),
            all_class_method_ids=context.get("all_class_method_ids"),
        ):
            if target_id not in known_function_ids:
                continue
            adapter_graph.calls.append(
                {
                    "src_id": source_id,
                    "dst_id": target_id,
                    "relative_path": context["file_path"],
                    "start_line": line_no,
                    "end_line": line_no,
                    "extractor": "python_call_ast",
                }
            )

    for context in test_contexts:
        source_id = context.get("node_id") or test_node_id(context["file_path"], context["test_name"])
        for target_id, line_no in extract_python_called_targets(
            node=context["node"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            imported_symbol_map=context.get("imported_symbol_map"),
            instance_type_map=context.get("instance_type_map"),
            class_method_ids=context.get("class_method_ids"),
            all_class_method_ids=context.get("all_class_method_ids"),
        ):
            if target_id not in known_function_ids:
                continue
            adapter_graph.covers.append(
                {
                    "src_id": source_id,
                    "dst_id": target_id,
                    "relative_path": context["file_path"],
                    "start_line": line_no,
                    "end_line": line_no,
                    "extractor": "python_test_ast",
                }
            )
    return adapter_graph


JS_FUNCTION_RE = re.compile(r"^\s*(?:export\s+default\s+|export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_ARROW_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s+)?(?:<[^>]+>\s*)?(?:\([^=]*\)|[A-Za-z_][A-Za-z0-9_]*)\s*=>")
JS_ARROW_START_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")
JS_ARROW_MULTILINE_RE = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s+)?(?:<[^>]+>\s*)?(?:\(.+?\)|[A-Za-z_][A-Za-z0-9_]*)\s*=>",
    re.DOTALL,
)
JS_CLASS_RE = re.compile(r"^\s*(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
JS_METHOD_RE = re.compile(r"^\s*(?:(?:public|private|protected|static|readonly|async|get|set)\s+)*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_TEST_RE = re.compile(r"^\s*(?:test(?:\.only)?|it(?:\.only)?|describe|test\.describe)\s*\(\s*['\"]([^'\"]+)['\"]")
JS_IMPORT_FROM_RE = re.compile(r"^\s*import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]\s*;?\s*$")
JS_EXPORT_FROM_RE = re.compile(r"^\s*export\s+(?:\{([^}]*)\}|\*)\s+from\s+['\"]([^'\"]+)['\"]\s*;?\s*$")
JS_REQUIRE_OBJECT_RE = re.compile(r"^\s*const\s*\{([^}]+)\}\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
JS_REQUIRE_MODULE_RE = re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
JS_EXPORT_ASSIGN_RE = re.compile(r"^\s*exports\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;?\s*$")
JS_MODULE_EXPORT_ASSIGN_RE = re.compile(r"^\s*module\.exports\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;?\s*$")
JS_MODULE_EXPORT_OBJECT_RE = re.compile(r"module\.exports\s*=\s*\{([^}]*)\}")
JS_MODULE_EXPORT_REQUIRE_RE = re.compile(r"^\s*module\.exports\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
JS_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_MEMBER_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_THIS_CALL_RE = re.compile(r"\bthis\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_REFERENCE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
JS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "function",
    "require",
    "test",
    "it",
    "describe",
    "class",
    "new",
}


def parse_named_imports(import_block: str, target_file: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw_part in import_block.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if " as " in part:
            source_name, alias_name = [item.strip() for item in part.split(" as ", 1)]
        elif ":" in part:
            source_name, alias_name = [item.strip() for item in part.split(":", 1)]
        else:
            source_name = part
            alias_name = part
        mapping[alias_name] = function_node_id(target_file, source_name)
    return mapping


def resolve_tsjs_module(source_relative: str, spec: str, project_root: pathlib.Path) -> str | None:
    if not spec.startswith("."):
        return None
    source_path = project_root / pathlib.PurePosixPath(source_relative)
    base = (source_path.parent / spec).resolve()
    candidates: list[pathlib.Path] = []
    if base.suffix:
        candidates.append(base)
    else:
        candidates.extend(
            [
                base.with_suffix(".js"),
                base.with_suffix(".ts"),
                base.with_suffix(".jsx"),
                base.with_suffix(".tsx"),
                base / "index.js",
                base / "index.ts",
                base / "index.jsx",
                base / "index.tsx",
            ]
        )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.relative_to(project_root).as_posix()
    return None


def block_end_line(lines: list[str], start_index: int, limit: int | None = None) -> int:
    return scan_js_block(lines, start_index, limit)["end_line"]


def arrow_end_line(lines: list[str], start_index: int) -> int:
    body_open = find_js_body_open_brace(lines, start_index, kind="arrow")
    if body_open:
        return scan_js_block(lines, start_index, kind="arrow")["end_line"]
    return start_index + 1


def match_js_arrow_name(lines: list[str], start_index: int, limit: int | None = None) -> str | None:
    line = lines[start_index]
    arrow_match = JS_ARROW_RE.match(line)
    if arrow_match:
        return arrow_match.group(1)

    if not JS_ARROW_START_RE.match(line):
        return None

    last_index = min(limit if limit is not None else len(lines), start_index + 8)
    header_text = "\n".join(lines[start_index:last_index])
    multiline_match = JS_ARROW_MULTILINE_RE.match(header_text)
    if multiline_match:
        return multiline_match.group(1)
    return None


def previous_js_word(line: str, char_index: int) -> str:
    index = char_index - 1
    while index >= 0 and line[index].isspace():
        index -= 1
    end_index = index + 1
    while index >= 0 and (line[index].isalnum() or line[index] in {"_", "$"}):
        index -= 1
    return line[index + 1:end_index]


def should_start_js_regex(line: str, char_index: int, prev_significant_char: str | None) -> bool:
    next_char = line[char_index + 1] if char_index + 1 < len(line) else ""
    if next_char in {"/", "*"}:
        return False
    if prev_significant_char is None:
        return True
    if prev_significant_char in "([{:;,=!&|?+-*%^~<>":
        return True
    return previous_js_word(line, char_index) in {
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }


def find_js_body_open_brace(
    lines: list[str],
    start_index: int,
    *,
    kind: str | None = None,
    limit: int | None = None,
) -> tuple[int, int] | None:
    last_index = limit if limit is not None else len(lines)
    in_single = False
    in_double = False
    in_template = False
    in_block_comment = False
    in_regex = False
    regex_char_class = False
    template_expr_depth = 0
    prev_significant_char: str | None = None
    paren_depth = 0
    saw_params = kind in {"class", None}
    arrow_seen = kind not in {"arrow"}
    in_return_type = False
    return_type_seen_token = False
    type_object_depth = 0
    type_angle_depth = 0
    type_paren_depth = 0
    type_bracket_depth = 0

    for index in range(start_index, last_index):
        line = lines[index]
        in_line_comment = False
        char_index = 0
        while char_index < len(line):
            char = line[char_index]
            next_char = line[char_index + 1] if char_index + 1 < len(line) else ""

            if in_line_comment:
                break

            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    char_index += 2
                    continue
                char_index += 1
                continue

            if in_single:
                if char == "\\":
                    char_index += 2
                    continue
                if char == "'":
                    in_single = False
                char_index += 1
                continue

            if in_double:
                if char == "\\":
                    char_index += 2
                    continue
                if char == '"':
                    in_double = False
                char_index += 1
                continue

            if in_regex:
                if char == "\\":
                    char_index += 2
                    continue
                if char == "[":
                    regex_char_class = True
                    char_index += 1
                    continue
                if char == "]" and regex_char_class:
                    regex_char_class = False
                    char_index += 1
                    continue
                if char == "/" and not regex_char_class:
                    in_regex = False
                    char_index += 1
                    while char_index < len(line) and line[char_index].isalpha():
                        char_index += 1
                    prev_significant_char = "/"
                    continue
                char_index += 1
                continue

            if in_template:
                if template_expr_depth == 0:
                    if char == "\\":
                        char_index += 2
                        continue
                    if char == "`":
                        in_template = False
                        char_index += 1
                        continue
                    if char == "$" and next_char == "{":
                        template_expr_depth = 1
                        char_index += 2
                        continue
                    char_index += 1
                    continue
                if char == "'" and not in_single:
                    in_single = True
                    char_index += 1
                    continue
                if char == '"' and not in_double:
                    in_double = True
                    char_index += 1
                    continue
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    char_index += 2
                    continue
                if char == "/" and next_char == "/":
                    in_line_comment = True
                    break
                if char == "{":
                    template_expr_depth += 1
                elif char == "}":
                    template_expr_depth -= 1
                    if template_expr_depth == 0:
                        char_index += 1
                        continue
                char_index += 1
                continue

            if char == "/" and next_char == "/":
                in_line_comment = True
                break
            if char == "/" and next_char == "*":
                in_block_comment = True
                char_index += 2
                continue
            if char == "/" and should_start_js_regex(line, char_index, prev_significant_char):
                in_regex = True
                regex_char_class = False
                char_index += 1
                continue
            if char == "'":
                in_single = True
                char_index += 1
                continue
            if char == '"':
                in_double = True
                char_index += 1
                continue
            if char == "`":
                in_template = True
                char_index += 1
                continue

            if kind == "arrow" and not arrow_seen:
                if char == "=" and next_char == ">":
                    arrow_seen = True
                    prev_significant_char = ">"
                    char_index += 2
                    continue
                if not char.isspace():
                    prev_significant_char = char
                char_index += 1
                continue

            if kind not in {"class", "arrow", None} and not saw_params:
                if char == "(":
                    saw_params = True
                    paren_depth = 1
                if not char.isspace():
                    prev_significant_char = char
                char_index += 1
                continue

            if saw_params and paren_depth > 0:
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                if not char.isspace():
                    prev_significant_char = char
                char_index += 1
                continue

            if kind in {"class", None}:
                if char == "{":
                    return index, char_index
                if not char.isspace():
                    prev_significant_char = char
                char_index += 1
                continue

            if kind == "arrow":
                if char == "{":
                    return index, char_index
                if not char.isspace():
                    return None
                char_index += 1
                continue

            if char.isspace():
                char_index += 1
                continue

            if not in_return_type and char == ":":
                in_return_type = True
                return_type_seen_token = False
                prev_significant_char = char
                char_index += 1
                continue

            if not in_return_type and char == "{":
                return index, char_index

            if in_return_type:
                if char == "{":
                    if not return_type_seen_token:
                        type_object_depth += 1
                        return_type_seen_token = True
                    elif type_object_depth == 0 and type_angle_depth == 0 and type_paren_depth == 0 and type_bracket_depth == 0:
                        return index, char_index
                    else:
                        type_object_depth += 1
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == "}":
                    if type_object_depth > 0:
                        type_object_depth -= 1
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == "<":
                    type_angle_depth += 1
                    return_type_seen_token = True
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == ">" and type_angle_depth > 0:
                    type_angle_depth -= 1
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == "[":
                    type_bracket_depth += 1
                    return_type_seen_token = True
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == "]" and type_bracket_depth > 0:
                    type_bracket_depth -= 1
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == "(":
                    type_paren_depth += 1
                    return_type_seen_token = True
                    prev_significant_char = char
                    char_index += 1
                    continue
                if char == ")" and type_paren_depth > 0:
                    type_paren_depth -= 1
                    prev_significant_char = char
                    char_index += 1
                    continue
                return_type_seen_token = True
                prev_significant_char = char
                char_index += 1
                continue

            prev_significant_char = char
            char_index += 1
    return None


def js_body_text(lines: list[str], scan: dict) -> str:
    body_start = scan.get("body_start")
    body_end = scan.get("body_end")
    if not body_start or not body_end:
        return ""
    start_line, start_col = body_start
    end_line, end_col = body_end
    if start_line == end_line:
        return lines[start_line][start_col + 1:end_col]
    parts = [lines[start_line][start_col + 1:]]
    parts.extend(lines[start_line + 1:end_line])
    parts.append(lines[end_line][:end_col])
    return "\n".join(parts)


def scan_js_block(lines: list[str], start_index: int, limit: int | None = None, *, kind: str | None = None) -> dict:
    last_index = limit if limit is not None else len(lines)
    body_open = find_js_body_open_brace(lines, start_index, kind=kind, limit=last_index)
    if body_open is None:
        return {
            "end_line": min(last_index, start_index + 1),
            "parser_warning": "parser_warning: unstable function boundary scan",
            "parser_confidence": 0.35,
            "body_start": None,
            "body_end": None,
        }

    depth = 0
    in_single = False
    in_double = False
    in_template = False
    in_block_comment = False
    in_regex = False
    regex_char_class = False
    template_expr_depth = 0
    parser_warning: str | None = None
    prev_significant_char: str | None = None

    for index in range(body_open[0], last_index):
        line = lines[index]
        in_line_comment = False
        char_index = body_open[1] if index == body_open[0] else 0
        while char_index < len(line):
            char = line[char_index]
            next_char = line[char_index + 1] if char_index + 1 < len(line) else ""

            if in_line_comment:
                break

            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    char_index += 2
                    continue
                char_index += 1
                continue

            if in_single:
                if char == "\\":
                    char_index += 2
                    continue
                if char == "'":
                    in_single = False
                char_index += 1
                continue

            if in_double:
                if char == "\\":
                    char_index += 2
                    continue
                if char == '"':
                    in_double = False
                char_index += 1
                continue

            if in_regex:
                if char == "\\":
                    char_index += 2
                    continue
                if char == "[":
                    regex_char_class = True
                    char_index += 1
                    continue
                if char == "]" and regex_char_class:
                    regex_char_class = False
                    char_index += 1
                    continue
                if char == "/" and not regex_char_class:
                    in_regex = False
                    char_index += 1
                    while char_index < len(line) and line[char_index].isalpha():
                        char_index += 1
                    prev_significant_char = "/"
                    continue
                char_index += 1
                continue

            if in_template:
                if template_expr_depth == 0:
                    if char == "\\":
                        char_index += 2
                        continue
                    if char == "`":
                        in_template = False
                        char_index += 1
                        continue
                    if char == "$" and next_char == "{":
                        template_expr_depth = 1
                        char_index += 2
                        continue
                    char_index += 1
                    continue
                if char == "'" and not in_single:
                    in_single = True
                    char_index += 1
                    continue
                if char == '"' and not in_double:
                    in_double = True
                    char_index += 1
                    continue
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    char_index += 2
                    continue
                if char == "/" and next_char == "/":
                    in_line_comment = True
                    break
                if char == "{":
                    template_expr_depth += 1
                elif char == "}":
                    template_expr_depth -= 1
                    if template_expr_depth == 0:
                        char_index += 1
                        continue
                char_index += 1
                continue

            if char == "/" and next_char == "/":
                in_line_comment = True
                break
            if char == "/" and next_char == "*":
                in_block_comment = True
                char_index += 2
                continue
            if char == "/" and should_start_js_regex(line, char_index, prev_significant_char):
                in_regex = True
                regex_char_class = False
                char_index += 1
                continue
            if char == "'":
                in_single = True
                char_index += 1
                continue
            if char == '"':
                in_double = True
                char_index += 1
                continue
            if char == "`":
                in_template = True
                char_index += 1
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth <= 0:
                    warning = parser_warning
                    if in_template or in_block_comment or in_regex:
                        warning = warning or "parser_warning: unterminated template/comment recovered"
                    return {
                        "end_line": index + 1,
                        "parser_warning": warning,
                        "parser_confidence": 0.6 if warning else 0.92,
                        "body_start": body_open,
                        "body_end": (index, char_index),
                    }
            if not char.isspace():
                prev_significant_char = char
            char_index += 1

    if in_template or in_block_comment or in_single or in_double or in_regex:
        parser_warning = "parser_warning: unstable function boundary scan"
    return {
        "end_line": min(last_index, start_index + 1),
        "parser_warning": parser_warning or "parser_warning: unterminated block scan",
        "parser_confidence": 0.35,
        "body_start": body_open,
        "body_end": None,
    }


def normalize_export_items(export_block: str) -> list[str]:
    items: list[str] = []
    for raw_part in export_block.split(","):
        part = raw_part.strip()
        if not part:
            continue
        cleaned = part.replace("...", "").strip()
        if " as " in cleaned:
            source_name, alias_name = [item.strip() for item in cleaned.split(" as ", 1)]
            items.append(alias_name or source_name)
        else:
            items.append(cleaned)
    return items


def import_clause_to_mappings(import_clause: str, target_file: str) -> tuple[dict[str, str], dict[str, str]]:
    function_map: dict[str, str] = {}
    module_map: dict[str, str] = {}
    clause = import_clause.strip()
    if clause.startswith("* as "):
        module_map[clause.split("* as ", 1)[1].strip()] = target_file
        return function_map, module_map
    named_block = None
    default_part = None
    if "{" in clause and "}" in clause:
        before, rest = clause.split("{", 1)
        named_block, _ = rest.split("}", 1)
        default_part = before.rstrip(", ").strip() or None
    else:
        default_part = clause
    if default_part:
        function_map[default_part] = function_node_id(target_file, "default")
    if named_block:
        function_map.update(parse_named_imports(named_block, target_file))
    return function_map, module_map


def extract_js_targets(
    *,
    body_text: str,
    local_function_ids: dict[str, str],
    imported_function_map: dict[str, str],
    imported_module_map: dict[str, str],
    class_method_map: dict[str, str] | None,
    base_line: int,
) -> tuple[list[tuple[str, int]], list[str]]:
    class_method_map = class_method_map or {}
    targets: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    raw_references: list[str] = []

    for alias, member in JS_MEMBER_CALL_RE.findall(body_text):
        raw_references.append(f"{alias}.{member}")
        if alias not in imported_module_map:
            continue
        target = function_node_id(imported_module_map[alias], member)
        item = (target, base_line)
        if item not in seen:
            seen.add(item)
            targets.append(item)

    for member in JS_THIS_CALL_RE.findall(body_text):
        raw_references.append(f"this.{member}")
        if member in class_method_map:
            item = (class_method_map[member], base_line)
            if item not in seen:
                seen.add(item)
                targets.append(item)

    for name in JS_CALL_RE.findall(body_text):
        if name in JS_KEYWORDS:
            continue
        raw_references.append(name)
        target: str | None = None
        if name in local_function_ids:
            target = local_function_ids[name]
        elif name in imported_function_map:
            target = imported_function_map[name]
        elif name in class_method_map:
            target = class_method_map[name]
        if target:
            item = (target, base_line)
            if item not in seen:
                seen.add(item)
                targets.append(item)
    return targets, sorted(set(raw_references))


def tsjs_test_style(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("test.describe("):
        return "playwright_test"
    if stripped.startswith("describe("):
        return "describe_block"
    if stripped.startswith("test("):
        return "node_or_vitest_test"
    if stripped.startswith("it("):
        return "jest_or_vitest_it"
    return "tsjs_test"


def tsjs_definition_kind(name: str, file_path: str, exported: bool, class_name: str | None = None) -> tuple[str, bool, bool]:
    suffix = pathlib.PurePosixPath(file_path).suffix
    is_hook = name.startswith("use") and len(name) > 3 and name[3:4].isupper()
    is_component = name[:1].isupper() and suffix in {".jsx", ".tsx"}
    if class_name:
        return "class_method", False, False
    if is_hook:
        return "custom_hook", is_component, True
    if is_component:
        return "react_component", True, False
    if exported:
        return "exported_const_arrow", False, False
    return "function_declaration", False, False


def parse_tsjs_backend(project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    tsjs_config = config["tsjs"]
    patterns = tsjs_config["source_globs"] + tsjs_config["test_globs"]
    exclude_dirs = configured_exclude_dirs(config)

    known_function_ids: set[str] = set()
    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files, exclude_dirs=exclude_dirs):
        relative = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        is_test_file = matches_any(relative, tsjs_config["test_globs"])
        file_attrs = {
            "extension": path.suffix,
            "parser_backend": "tsjs_family",
            "file_role": "test-file" if is_test_file else "source-file",
            "exports": [],
            "reexports": [],
        }
        adapter_graph.files.append(
            {
                "path": relative,
                "is_test_file": is_test_file,
                "content_hash": sha1_text(text),
                "attrs": file_attrs,
            }
        )
        append_contract_artifacts(
            adapter_graph,
            relative_path=relative,
            source_text=text,
            language="tsjs",
        )

        imported_function_map: dict[str, str] = {}
        imported_module_map: dict[str, str] = {}
        local_function_ids: dict[str, str] = {}
        export_names_by_symbol: dict[str, list[str]] = {}

        for line_index, line in enumerate(lines, start=1):
            import_match = JS_IMPORT_FROM_RE.match(line)
            if import_match:
                target_file = resolve_tsjs_module(relative, import_match.group(2), project_root)
                if target_file:
                    function_map, module_map = import_clause_to_mappings(import_match.group(1), target_file)
                    imported_function_map.update(function_map)
                    imported_module_map.update(module_map)
                    adapter_graph.imports.append(
                        {
                            "src_id": file_node_id(relative),
                            "dst_id": file_node_id(target_file),
                            "relative_path": relative,
                            "start_line": line_index,
                            "end_line": line_index,
                            "extractor": "tsjs_import_scan",
                        }
                    )
                continue

            export_from_match = JS_EXPORT_FROM_RE.match(line)
            if export_from_match:
                target_file = resolve_tsjs_module(relative, export_from_match.group(2), project_root)
                if target_file:
                    adapter_graph.imports.append(
                        {
                            "src_id": file_node_id(relative),
                            "dst_id": file_node_id(target_file),
                            "relative_path": relative,
                            "start_line": line_index,
                            "end_line": line_index,
                            "extractor": "tsjs_reexport_scan",
                        }
                    )
                    file_attrs["reexports"].append(target_file)
                continue

            require_object_match = JS_REQUIRE_OBJECT_RE.match(line)
            if require_object_match:
                target_file = resolve_tsjs_module(relative, require_object_match.group(2), project_root)
                if target_file:
                    imported_function_map.update(parse_named_imports(require_object_match.group(1), target_file))
                    adapter_graph.imports.append(
                        {
                            "src_id": file_node_id(relative),
                            "dst_id": file_node_id(target_file),
                            "relative_path": relative,
                            "start_line": line_index,
                            "end_line": line_index,
                            "extractor": "tsjs_require_scan",
                        }
                    )
                continue

            require_module_match = JS_REQUIRE_MODULE_RE.match(line)
            if require_module_match:
                target_file = resolve_tsjs_module(relative, require_module_match.group(2), project_root)
                if target_file:
                    imported_module_map[require_module_match.group(1)] = target_file
                    adapter_graph.imports.append(
                        {
                            "src_id": file_node_id(relative),
                            "dst_id": file_node_id(target_file),
                            "relative_path": relative,
                            "start_line": line_index,
                            "end_line": line_index,
                            "extractor": "tsjs_require_scan",
                        }
                    )
                continue

            module_export_require_match = JS_MODULE_EXPORT_REQUIRE_RE.match(line)
            if module_export_require_match:
                target_file = resolve_tsjs_module(relative, module_export_require_match.group(1), project_root)
                if target_file:
                    adapter_graph.imports.append(
                        {
                            "src_id": file_node_id(relative),
                            "dst_id": file_node_id(target_file),
                            "relative_path": relative,
                            "start_line": line_index,
                            "end_line": line_index,
                            "extractor": "tsjs_module_export_scan",
                        }
                    )
                    file_attrs["reexports"].append(target_file)
                continue

            export_assign_match = JS_EXPORT_ASSIGN_RE.match(line) or JS_MODULE_EXPORT_ASSIGN_RE.match(line)
            if export_assign_match:
                export_name, source_name = export_assign_match.groups()
                export_names_by_symbol.setdefault(source_name, []).append(export_name)
                file_attrs["exports"].append(export_name)
                continue

            module_export_object_match = JS_MODULE_EXPORT_OBJECT_RE.search(line)
            if module_export_object_match:
                for export_name in normalize_export_items(module_export_object_match.group(1)):
                    source_name = export_name.split(":", 1)[0].strip()
                    export_names_by_symbol.setdefault(source_name, []).append(export_name)
                    file_attrs["exports"].append(export_name)

        index = 0
        while index < len(lines):
            line = lines[index]

            class_match = JS_CLASS_RE.match(line)
            if class_match:
                class_name = class_match.group(1)
                class_scan = scan_js_block(lines, index, kind="class")
                class_end = class_scan["end_line"]
                class_methods: dict[str, str] = {}
                inner_index = index + 1
                while inner_index < class_end - 1:
                    inner_line = lines[inner_index]
                    method_match = JS_METHOD_RE.match(inner_line)
                    if method_match and method_match.group(1) != "constructor":
                        method_name = method_match.group(1)
                        method_scan = scan_js_block(lines, inner_index, class_end, kind="method")
                        end_line = method_scan["end_line"]
                        symbol = f"{class_name}.{method_name}"
                        node_id = function_node_id(relative, symbol)
                        class_methods[method_name] = node_id
                        local_function_ids[symbol] = node_id
                        known_function_ids.add(node_id)
                        full_text = "\n".join(lines[inner_index:end_line])
                        body_text = js_body_text(lines, method_scan)
                        export_names = export_names_by_symbol.get(class_name, [])
                        adapter_graph.functions.append(
                            {
                                "node_id": node_id,
                                "path": relative,
                                "name": symbol,
                                "symbol": symbol,
                                "start_line": inner_index + 1,
                                "end_line": end_line,
                                "language": "tsjs",
                                "body_hash": sha1_text(full_text),
                        "attrs": {
                            "definition_kind": "class_method",
                            "class_name": class_name,
                            "exported": bool(export_names),
                            "is_component": False,
                            "is_hook": False,
                            "parser_confidence": method_scan["parser_confidence"],
                            "parser_warning": method_scan["parser_warning"],
                            "sql_query_hints": extract_sql_query_hints(body_text),
                            "reference_hints": {
                                        "imports": sorted(list(imported_function_map.keys()) + list(imported_module_map.keys())),
                                        "exports": sorted(export_names),
                                        "references": [],
                                        "resolved_call_targets": [],
                                    },
                                },
                            }
                        )
                        function_contexts.append(
                            {
                                "node_id": node_id,
                                "relative_path": relative,
                                "start_line": inner_index + 1,
                                "body_text": body_text,
                                "local_function_ids": local_function_ids,
                                "imported_function_map": imported_function_map,
                                "imported_module_map": imported_module_map,
                                "class_method_map": class_methods,
                            }
                        )
                        inner_index = end_line
                        continue
                    inner_index += 1
                index = class_end
                continue

            function_match = JS_FUNCTION_RE.match(line)
            if function_match:
                name = function_match.group(1)
                node_id = function_node_id(relative, name)
                local_function_ids[name] = node_id
                known_function_ids.add(node_id)
                function_scan = scan_js_block(lines, index, kind="function")
                end_line = function_scan["end_line"]
                full_text = "\n".join(lines[index:end_line])
                body_text = js_body_text(lines, function_scan)
                export_names = export_names_by_symbol.get(name, [])
                exported = line.strip().startswith("export ") or bool(export_names)
                definition_kind, is_component, is_hook = tsjs_definition_kind(name, relative, exported)
                adapter_graph.functions.append(
                    {
                        "node_id": node_id,
                        "path": relative,
                        "name": name,
                        "symbol": name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "language": "tsjs",
                        "body_hash": sha1_text(full_text),
                        "attrs": {
                            "definition_kind": definition_kind,
                            "exported": exported,
                            "is_component": is_component,
                            "is_hook": is_hook,
                            "parser_confidence": function_scan["parser_confidence"],
                            "parser_warning": function_scan["parser_warning"],
                            "sql_query_hints": extract_sql_query_hints(body_text),
                            "reference_hints": {
                                "imports": sorted(list(imported_function_map.keys()) + list(imported_module_map.keys())),
                                "exports": sorted(export_names),
                                "references": [],
                                "resolved_call_targets": [],
                            },
                        },
                    }
                )
                function_contexts.append(
                    {
                        "node_id": node_id,
                        "relative_path": relative,
                        "start_line": index + 1,
                        "body_text": body_text,
                        "local_function_ids": local_function_ids,
                        "imported_function_map": imported_function_map,
                        "imported_module_map": imported_module_map,
                        "class_method_map": {},
                    }
                )
                if exported:
                    file_attrs["exports"].extend(export_names or [name])
                index = end_line
                continue

            arrow_name = match_js_arrow_name(lines, index)
            if arrow_name:
                name = arrow_name
                node_id = function_node_id(relative, name)
                local_function_ids[name] = node_id
                known_function_ids.add(node_id)
                arrow_body_open = find_js_body_open_brace(lines, index, kind="arrow")
                arrow_scan = (
                    scan_js_block(lines, index, kind="arrow")
                    if arrow_body_open
                    else {"end_line": index + 1, "parser_warning": None, "parser_confidence": 0.92, "body_start": None, "body_end": None}
                )
                end_line = arrow_scan["end_line"]
                full_text = "\n".join(lines[index:end_line])
                body_text = js_body_text(lines, arrow_scan)
                if not body_text and "=>" in full_text:
                    body_text = full_text.split("=>", 1)[1].strip()
                export_names = export_names_by_symbol.get(name, [])
                exported = line.strip().startswith("export ") or bool(export_names)
                _, is_component, is_hook = tsjs_definition_kind(name, relative, exported)
                definition_kind = "custom_hook" if is_hook else ("react_component" if is_component else ("exported_const_arrow" if exported else "const_arrow_function"))
                adapter_graph.functions.append(
                    {
                        "node_id": node_id,
                        "path": relative,
                        "name": name,
                        "symbol": name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "language": "tsjs",
                        "body_hash": sha1_text(full_text),
                        "attrs": {
                            "definition_kind": definition_kind,
                            "exported": exported,
                            "is_component": is_component,
                            "is_hook": is_hook,
                            "parser_confidence": arrow_scan["parser_confidence"],
                            "parser_warning": arrow_scan["parser_warning"],
                            "sql_query_hints": extract_sql_query_hints(body_text),
                            "reference_hints": {
                                "imports": sorted(list(imported_function_map.keys()) + list(imported_module_map.keys())),
                                "exports": sorted(export_names),
                                "references": [],
                                "resolved_call_targets": [],
                            },
                        },
                    }
                )
                function_contexts.append(
                    {
                        "node_id": node_id,
                        "relative_path": relative,
                        "start_line": index + 1,
                        "body_text": body_text,
                        "local_function_ids": local_function_ids,
                        "imported_function_map": imported_function_map,
                        "imported_module_map": imported_module_map,
                        "class_method_map": {},
                    }
                )
                if exported:
                    file_attrs["exports"].extend(export_names or [name])
                index = end_line
                continue

            test_match = JS_TEST_RE.match(line)
            if test_match:
                test_name = test_match.group(1)
                test_scan = scan_js_block(lines, index)
                end_line = test_scan["end_line"]
                body_text = "\n".join(lines[index:end_line])
                test_contexts.append(
                    {
                        "node_id": test_node_id(relative, test_name),
                        "relative_path": relative,
                        "start_line": index + 1,
                        "body_text": body_text,
                        "local_function_ids": local_function_ids,
                        "imported_function_map": imported_function_map,
                        "imported_module_map": imported_module_map,
                        "class_method_map": {},
                    }
                )
                adapter_graph.tests.append(
                    {
                        "node_id": test_node_id(relative, test_name),
                        "path": relative,
                        "name": test_name,
                        "symbol": test_name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "language": "tsjs",
                        "body_hash": sha1_text(body_text),
                        "attrs": {
                            "definition_kind": "test_case",
                            "test_style": tsjs_test_style(line),
                            "parser_confidence": test_scan["parser_confidence"],
                            "parser_warning": test_scan["parser_warning"],
                            "sql_query_hints": extract_sql_query_hints(body_text),
                        },
                    }
                )
                index = end_line
                continue

            index += 1

        file_attrs["exports"] = sorted(set(file_attrs["exports"]))
        file_attrs["reexports"] = sorted(set(file_attrs["reexports"]))

    function_attrs_by_id = {item["node_id"]: item["attrs"] for item in adapter_graph.functions}
    for context in function_contexts:
        targets, raw_refs = extract_js_targets(
            body_text=context["body_text"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            class_method_map=context["class_method_map"],
            base_line=context["start_line"],
        )
        function_attrs_by_id[context["node_id"]]["reference_hints"]["references"] = raw_refs
        function_attrs_by_id[context["node_id"]]["reference_hints"]["resolved_call_targets"] = sorted({target for target, _ in targets})
        for target_id, line_no in targets:
            if target_id not in known_function_ids:
                continue
            adapter_graph.calls.append(
                {
                    "src_id": context["node_id"],
                    "dst_id": target_id,
                    "relative_path": context["relative_path"],
                    "start_line": line_no,
                    "end_line": line_no,
                    "extractor": "tsjs_call_scan",
                }
            )

    for context in test_contexts:
        targets, raw_refs = extract_js_targets(
            body_text=context["body_text"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            class_method_map=context["class_method_map"],
            base_line=context["start_line"],
        )
        for test_record in adapter_graph.tests:
            if test_record["node_id"] == context["node_id"]:
                test_record["attrs"]["reference_hints"] = {
                    "references": raw_refs,
                    "resolved_call_targets": sorted({target for target, _ in targets}),
                }
                break
        for target_id, line_no in targets:
            if target_id not in known_function_ids:
                continue
            adapter_graph.covers.append(
                {
                    "src_id": context["node_id"],
                    "dst_id": target_id,
                    "relative_path": context["relative_path"],
                    "start_line": line_no,
                    "end_line": line_no,
                    "extractor": "tsjs_test_scan",
                }
            )
    return adapter_graph


def parse_generic_backend(project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    generic_config = config["generic"]
    source_globs = generic_config.get("source_globs", ["src/*", "src/**/*"])
    matched_files = iter_matching_files(
        project_root,
        source_globs,
        include_files,
        exclude_dirs=configured_exclude_dirs(config),
    )
    for path in matched_files:
        relative = path.relative_to(project_root).as_posix()
        adapter_graph.files.append(
            {
                "path": relative,
                "is_test_file": False,
                "content_hash": sha1_text(path.read_text(encoding="utf-8")),
                "attrs": {
                    "extension": path.suffix,
                    "file_level_only": True,
                    "parser_backend": "generic_fallback",
                },
            }
        )
        append_contract_artifacts(
            adapter_graph,
            relative_path=relative,
            source_text=path.read_text(encoding="utf-8"),
            language="generic",
        )
    return adapter_graph


SQL_ROUTINE_RE = re.compile(
    r"(?is)create\s+(?:or\s+replace\s+)?(function|procedure)\s+([a-z_][a-z0-9_\.]*)\s*\((.*?)\)\s*(returns\s+trigger|returns\s+[^$;]+)?\s+(?:language\s+[a-z_]+\s+)?as\s+\$\$(.*?)\$\$(?:\s+language\s+[a-z_]+)?\s*;",
)
SQL_TRIGGER_BINDING_RE = re.compile(r"(?is)create\s+trigger\s+([a-z_][a-z0-9_]*)[\s\S]*?execute\s+function\s+([a-z_][a-z0-9_\.]*)\s*\(")
SQL_VIEW_RE = re.compile(r"(?is)create\s+(materialized\s+)?view\s+([a-z_][a-z0-9_\.]*)")


def sql_basename(name: str) -> str:
    return name.split(".")[-1]


def unique_sql_target(hint: str, sql_targets: dict[str, list[str]]) -> str | None:
    exact = sql_targets.get(hint, [])
    if len(exact) == 1:
        return exact[0]
    base = sql_targets.get(sql_basename(hint), [])
    if len(base) == 1:
        return base[0]
    return None


def parse_sql_postgres_backend(project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    sql_config = config["sql_postgres"]
    source_globs = sql_config.get("source_globs", [])
    test_globs = sql_config.get("test_globs", [])
    patterns = source_globs + test_globs
    exclude_dirs = configured_exclude_dirs(config)

    sql_targets: dict[str, list[str]] = {}
    routine_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files, exclude_dirs=exclude_dirs):
        relative = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        is_test_file = matches_any(relative, test_globs)
        trigger_bindings = [
            {"trigger_name": match.group(1), "target": match.group(2)}
            for match in SQL_TRIGGER_BINDING_RE.finditer(text)
        ]
        adapter_graph.files.append(
            {
                "path": relative,
                "is_test_file": is_test_file,
                "content_hash": sha1_text(text),
                "attrs": {
                    "extension": path.suffix,
                    "parser_backend": "sql_postgres_lite",
                    "file_role": "test-file" if is_test_file else "sql-file",
                    "trigger_bindings": trigger_bindings,
                    "sql_view_hints": [
                        {
                            "view_name": match.group(2),
                            "materialized": bool(match.group(1)),
                        }
                        for match in SQL_VIEW_RE.finditer(text)
                    ],
                },
            }
        )
        append_contract_artifacts(
            adapter_graph,
            relative_path=relative,
            source_text=text,
            language="sql_postgres",
        )

        if is_test_file:
            test_name = pathlib.PurePosixPath(relative).stem
            test_contexts.append(
                {
                    "node_id": test_node_id(relative, test_name),
                    "relative_path": relative,
                    "text": text,
                }
            )
            adapter_graph.tests.append(
                {
                    "node_id": test_node_id(relative, test_name),
                    "path": relative,
                    "name": test_name,
                    "symbol": test_name,
                    "start_line": 1,
                    "end_line": len(text.splitlines()),
                    "language": "sql_postgres",
                    "body_hash": sha1_text(text),
                    "attrs": {
                        "definition_kind": "sql_test_file",
                        "test_style": "sql_file",
                        "sql_query_hints": extract_sql_query_hints(text),
                    },
                }
            )
            continue

        for match in SQL_ROUTINE_RE.finditer(text):
            routine_type = match.group(1).lower()
            qualified_name = match.group(2)
            returns_clause = (match.group(4) or "").lower()
            body_text = match.group(5)
            sql_kind = "trigger" if "returns trigger" in returns_clause else routine_type
            node_id = function_node_id(relative, qualified_name)
            start_line = text[: match.start()].count("\n") + 1
            end_line = text[: match.end()].count("\n") + 1
            query_hints = extract_sql_query_hints(body_text)
            adapter_graph.functions.append(
                {
                    "node_id": node_id,
                    "path": relative,
                    "name": qualified_name,
                    "symbol": qualified_name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "language": "sql_postgres",
                    "body_hash": sha1_text(body_text),
                    "attrs": {
                        "definition_kind": "sql_routine",
                        "sql_kind": sql_kind,
                        "qualified_name": qualified_name,
                        "sql_query_hints": query_hints,
                        "reference_hints": {
                            "imports": [],
                            "exports": [],
                            "references": query_hints,
                            "resolved_call_targets": [],
                        },
                    },
                }
            )
            routine_contexts.append(
                {
                    "node_id": node_id,
                    "relative_path": relative,
                    "qualified_name": qualified_name,
                    "body_text": body_text,
                    "start_line": start_line,
                    "query_hints": query_hints,
                }
            )
            for key in {qualified_name, sql_basename(qualified_name)}:
                sql_targets.setdefault(key, []).append(node_id)

    function_attrs = {item["node_id"]: item["attrs"] for item in adapter_graph.functions}
    for context in routine_contexts:
        resolved_targets: list[str] = []
        unresolved_hints: list[str] = []
        for hint in context["query_hints"]:
            target = unique_sql_target(hint, sql_targets)
            if target and target != context["node_id"]:
                resolved_targets.append(target)
                adapter_graph.calls.append(
                    {
                        "src_id": context["node_id"],
                        "dst_id": target,
                        "relative_path": context["relative_path"],
                        "start_line": context["start_line"],
                        "end_line": context["start_line"],
                        "extractor": "sql_postgres_call_scan",
                    }
                )
            else:
                unresolved_hints.append(hint)
        function_attrs[context["node_id"]]["reference_hints"]["resolved_call_targets"] = sorted(set(resolved_targets))
        function_attrs[context["node_id"]]["reference_hints"]["unresolved_sql_hints"] = sorted(set(unresolved_hints))

    for context in test_contexts:
        resolved_targets: list[str] = []
        unresolved_hints: list[str] = []
        for hint in extract_sql_query_hints(context["text"]):
            target = unique_sql_target(hint, sql_targets)
            if target:
                resolved_targets.append(target)
                adapter_graph.covers.append(
                    {
                        "src_id": context["node_id"],
                        "dst_id": target,
                        "relative_path": context["relative_path"],
                        "start_line": 1,
                        "end_line": 1,
                        "extractor": "sql_postgres_test_scan",
                    }
                )
            else:
                unresolved_hints.append(hint)
        for test_record in adapter_graph.tests:
            if test_record["node_id"] == context["node_id"]:
                test_record["attrs"]["reference_hints"] = {
                    "references": extract_sql_query_hints(context["text"]),
                    "resolved_call_targets": sorted(set(resolved_targets)),
                    "unresolved_sql_hints": sorted(set(unresolved_hints)),
                }
                break

    return adapter_graph


def v8_relative_path(url: str, project_root: pathlib.Path) -> str | None:
    if not url:
        return None
    if url.startswith("file:"):
        parsed = urlparse(url)
        file_path = pathlib.Path(url2pathname(parsed.path))
    else:
        file_path = pathlib.Path(url)
    try:
        return file_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return None


BACKENDS = {
    "python": parse_python_backend,
    "tsjs": parse_tsjs_backend,
    "generic": parse_generic_backend,
    "sql_postgres": parse_sql_postgres_backend,
}


def parse_with_backend(adapter_name: str, project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    return BACKENDS[adapter_name](project_root, config, include_files)
