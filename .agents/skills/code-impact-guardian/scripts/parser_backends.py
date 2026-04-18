#!/usr/bin/env python3
import ast
import hashlib
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


def file_node_id(relative_path: str) -> str:
    return f"file:{relative_path}"


def function_node_id(relative_path: str, function_name: str) -> str:
    return f"fn:{relative_path}:{function_name}"


def test_node_id(relative_path: str, test_name: str) -> str:
    return f"test:{relative_path}:{test_name}"


def matches_any(relative_path: str, patterns: list[str]) -> bool:
    pure = pathlib.PurePosixPath(relative_path)
    return any(pure.match(pattern) for pattern in patterns)


def iter_matching_files(project_root: pathlib.Path, patterns: list[str], include_files: list[str] | None = None) -> list[pathlib.Path]:
    if not patterns:
        return []
    include_set = {item.replace("\\", "/") for item in (include_files or [])}
    results: dict[str, pathlib.Path] = {}
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root).as_posix()
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


def extract_python_called_targets(
    *,
    node: ast.AST,
    local_function_ids: dict[str, str],
    imported_function_map: dict[str, str],
    imported_module_map: dict[str, str],
) -> list[tuple[str, int]]:
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
        if target_id:
            targets.append((target_id, getattr(child, "lineno", 1)))
    return targets


def parse_python_backend(project_root: pathlib.Path, config: dict, include_files: list[str] | None = None) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    python_config = config["python"]
    patterns = python_config["source_globs"] + python_config["test_globs"]

    file_records: dict[str, dict] = {}
    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files):
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
        import_file_targets: list[tuple[str, int]] = []
        imported_function_map: dict[str, str] = {}
        imported_module_map: dict[str, str] = {}
        local_function_ids: dict[str, str] = {}
        function_nodes: list[ast.FunctionDef] = []
        test_nodes: list[tuple[str, ast.AST]] = []

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
                        imported_function_map[alias.asname or alias.name] = function_node_id(target_file, alias.name)
            elif isinstance(child, ast.FunctionDef):
                if is_test_file and child.name.startswith("test_"):
                    test_nodes.append((child.name, child))
                else:
                    local_function_ids[child.name] = function_node_id(relative, child.name)
                    function_nodes.append(child)
            elif isinstance(child, ast.ClassDef) and is_test_file:
                for member in child.body:
                    if isinstance(member, ast.FunctionDef) and member.name.startswith("test_"):
                        test_nodes.append((f"{child.name}.{member.name}", member))

        for function_node in function_nodes:
            function_text = python_node_text(source_text, function_node)
            function_contexts.append(
                {
                    "file_path": relative,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
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

        for test_name, test_node in test_nodes:
            test_contexts.append(
                {
                    "file_path": relative,
                    "test_name": test_name,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
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
        source_id = function_node_id(context["file_path"], context["node"].name)
        for target_id, line_no in extract_python_called_targets(
            node=context["node"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
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
        source_id = test_node_id(context["file_path"], context["test_name"])
        for target_id, line_no in extract_python_called_targets(
            node=context["node"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
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
JS_CLASS_RE = re.compile(r"^\s*(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
JS_METHOD_RE = re.compile(r"^\s*(?:async\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*\{")
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
    depth = 0
    started = False
    last_index = limit if limit is not None else len(lines)
    for index in range(start_index, last_index):
        line = lines[index]
        opens = line.count("{")
        closes = line.count("}")
        if opens:
            started = True
        depth += opens
        depth -= closes
        if started and depth <= 0:
            return index + 1
    return min(last_index, start_index + 1)


def arrow_end_line(lines: list[str], start_index: int) -> int:
    line = lines[start_index]
    if "{" in line:
        return block_end_line(lines, start_index)
    return start_index + 1


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

    known_function_ids: set[str] = set()
    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files):
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
                class_end = block_end_line(lines, index)
                class_methods: dict[str, str] = {}
                inner_index = index + 1
                while inner_index < class_end - 1:
                    inner_line = lines[inner_index]
                    method_match = JS_METHOD_RE.match(inner_line)
                    if method_match and method_match.group(1) != "constructor":
                        method_name = method_match.group(1)
                        end_line = block_end_line(lines, inner_index, class_end)
                        symbol = f"{class_name}.{method_name}"
                        node_id = function_node_id(relative, symbol)
                        class_methods[method_name] = node_id
                        local_function_ids[symbol] = node_id
                        known_function_ids.add(node_id)
                        body_text = "\n".join(lines[inner_index:end_line])
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
                                "body_hash": sha1_text(body_text),
                        "attrs": {
                            "definition_kind": "class_method",
                            "class_name": class_name,
                            "exported": bool(export_names),
                            "is_component": False,
                            "is_hook": False,
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
                end_line = block_end_line(lines, index)
                body_text = "\n".join(lines[index:end_line])
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
                        "body_hash": sha1_text(body_text),
                        "attrs": {
                            "definition_kind": definition_kind,
                            "exported": exported,
                            "is_component": is_component,
                            "is_hook": is_hook,
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

            arrow_match = JS_ARROW_RE.match(line)
            if arrow_match:
                name = arrow_match.group(1)
                node_id = function_node_id(relative, name)
                local_function_ids[name] = node_id
                known_function_ids.add(node_id)
                end_line = arrow_end_line(lines, index)
                body_text = "\n".join(lines[index:end_line])
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
                        "body_hash": sha1_text(body_text),
                        "attrs": {
                            "definition_kind": definition_kind,
                            "exported": exported,
                            "is_component": is_component,
                            "is_hook": is_hook,
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
                end_line = block_end_line(lines, index)
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
    matched_files = iter_matching_files(project_root, source_globs, include_files)
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

    sql_targets: dict[str, list[str]] = {}
    routine_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns, include_files):
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
