#!/usr/bin/env python3
import ast
import hashlib
import pathlib
import re
from dataclasses import dataclass, field


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


def iter_matching_files(project_root: pathlib.Path, patterns: list[str]) -> list[pathlib.Path]:
    if not patterns:
        return []
    results: dict[str, pathlib.Path] = {}
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root).as_posix()
        if matches_any(relative, patterns):
            results[relative] = path
    return [results[key] for key in sorted(results)]


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


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


def parse_python_backend(project_root: pathlib.Path, config: dict) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    python_config = config["python"]
    patterns = python_config["source_globs"] + python_config["test_globs"]

    file_records: dict[str, dict] = {}
    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns):
        relative = path.relative_to(project_root).as_posix()
        source_text = path.read_text(encoding="utf-8")
        module = ast.parse(source_text, filename=str(path))
        is_test_file = matches_any(relative, python_config["test_globs"])
        file_records[relative] = {
            "path": relative,
            "is_test_file": is_test_file,
            "content_hash": sha1_text(source_text),
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
            function_contexts.append(
                {
                    "file_path": relative,
                    "local_function_ids": local_function_ids,
                    "imported_function_map": imported_function_map,
                    "imported_module_map": imported_module_map,
                    "node": function_node,
                }
            )
            function_text = python_node_text(source_text, function_node)
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


JS_FUNCTION_RE = re.compile(r"^\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_ARROW_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>\s*\{")
JS_TEST_RE = re.compile(r"^\s*(?:test|it)\(\s*['\"]([^'\"]+)['\"]\s*,")
JS_IMPORT_RE = re.compile(r"^\s*import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]\s*;?\s*$")
JS_IMPORT_STAR_RE = re.compile(r"^\s*import\s+\*\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s*['\"]([^'\"]+)['\"]\s*;?\s*$")
JS_REQUIRE_OBJECT_RE = re.compile(r"^\s*const\s*\{([^}]+)\}\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
JS_REQUIRE_MODULE_RE = re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)\s*;?\s*$")
JS_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
JS_MEMBER_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
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
}


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
                base / "index.js",
                base / "index.ts",
            ]
        )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.relative_to(project_root).as_posix()
    return None


def block_end_line(lines: list[str], start_index: int) -> int:
    depth = 0
    started = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        opens = line.count("{")
        closes = line.count("}")
        if opens:
            started = True
        depth += opens
        depth -= closes
        if started and depth <= 0:
            return index + 1
    return start_index + 1


def extract_js_targets(
    *,
    body_text: str,
    local_function_ids: dict[str, str],
    imported_function_map: dict[str, str],
    imported_module_map: dict[str, str],
    base_line: int,
) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for alias, member in JS_MEMBER_CALL_RE.findall(body_text):
        if alias not in imported_module_map:
            continue
        target = function_node_id(imported_module_map[alias], member)
        item = (target, base_line)
        if item not in seen:
            seen.add(item)
            targets.append(item)
    for name in JS_CALL_RE.findall(body_text):
        if name in JS_KEYWORDS:
            continue
        target: str | None = None
        if name in local_function_ids:
            target = local_function_ids[name]
        elif name in imported_function_map:
            target = imported_function_map[name]
        if target:
            item = (target, base_line)
            if item not in seen:
                seen.add(item)
                targets.append(item)
    return targets


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


def parse_tsjs_backend(project_root: pathlib.Path, config: dict) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    tsjs_config = config["tsjs"]
    patterns = tsjs_config["source_globs"] + tsjs_config["test_globs"]
    file_records: dict[str, dict] = {}
    known_function_ids: set[str] = set()

    function_contexts: list[dict] = []
    test_contexts: list[dict] = []

    for path in iter_matching_files(project_root, patterns):
        relative = path.relative_to(project_root).as_posix()
        is_test_file = matches_any(relative, tsjs_config["test_globs"])
        text = path.read_text(encoding="utf-8")
        file_records[relative] = {"path": relative, "is_test_file": is_test_file, "content_hash": sha1_text(text)}
        lines = text.splitlines()
        imported_function_map: dict[str, str] = {}
        imported_module_map: dict[str, str] = {}
        local_function_ids: dict[str, str] = {}

        for line_index, line in enumerate(lines, start=1):
            import_match = JS_IMPORT_RE.match(line)
            if import_match:
                target_file = resolve_tsjs_module(relative, import_match.group(2), project_root)
                if target_file:
                    imported_function_map.update(parse_named_imports(import_match.group(1), target_file))
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
            import_star_match = JS_IMPORT_STAR_RE.match(line)
            if import_star_match:
                target_file = resolve_tsjs_module(relative, import_star_match.group(2), project_root)
                if target_file:
                    imported_module_map[import_star_match.group(1)] = target_file
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

        index = 0
        while index < len(lines):
            line = lines[index]
            function_match = JS_FUNCTION_RE.match(line) or JS_ARROW_RE.match(line)
            if function_match:
                name = function_match.group(1)
                local_function_ids[name] = function_node_id(relative, name)
                end_line = block_end_line(lines, index)
                body_text = "\n".join(lines[index:end_line])
                function_contexts.append(
                    {
                        "node_id": function_node_id(relative, name),
                        "relative_path": relative,
                        "name": name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "body_text": body_text,
                        "local_function_ids": local_function_ids,
                        "imported_function_map": imported_function_map,
                        "imported_module_map": imported_module_map,
                    }
                )
                known_function_ids.add(function_node_id(relative, name))
                adapter_graph.functions.append(
                    {
                        "node_id": function_node_id(relative, name),
                        "path": relative,
                        "name": name,
                        "symbol": name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "language": "tsjs",
                        "body_hash": sha1_text(body_text),
                    }
                )
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
                        "test_name": test_name,
                        "start_line": index + 1,
                        "end_line": end_line,
                        "body_text": body_text,
                        "local_function_ids": local_function_ids,
                        "imported_function_map": imported_function_map,
                        "imported_module_map": imported_module_map,
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
                    }
                )
                index = end_line
                continue
            index += 1

        adapter_graph.files.append(file_records[relative])

    for context in function_contexts:
        for target_id, line_no in extract_js_targets(
            body_text=context["body_text"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            base_line=context["start_line"],
        ):
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
        for target_id, line_no in extract_js_targets(
            body_text=context["body_text"],
            local_function_ids=context["local_function_ids"],
            imported_function_map=context["imported_function_map"],
            imported_module_map=context["imported_module_map"],
            base_line=context["start_line"],
        ):
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


def parse_generic_backend(project_root: pathlib.Path, config: dict) -> AdapterGraph:
    adapter_graph = AdapterGraph()
    generic_config = config["generic"]
    source_globs = generic_config.get("source_globs", ["src/*", "src/**/*"])
    matched_files = iter_matching_files(project_root, source_globs)
    for path in matched_files:
        relative = path.relative_to(project_root).as_posix()
        adapter_graph.files.append(
            {
                "path": relative,
                "is_test_file": False,
                "content_hash": sha1_text(path.read_text(encoding="utf-8")),
            }
        )
    return adapter_graph


BACKENDS = {
    "python": parse_python_backend,
    "tsjs": parse_tsjs_backend,
    "generic": parse_generic_backend,
}


def parse_with_backend(adapter_name: str, project_root: pathlib.Path, config: dict) -> AdapterGraph:
    return BACKENDS[adapter_name](project_root, config)
