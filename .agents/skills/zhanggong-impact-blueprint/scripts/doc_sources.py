#!/usr/bin/env python3
import json
import pathlib

from parser_backends import matches_any


LOCAL_MARKDOWN_DOC_SOURCE = "local_markdown"
OPTIONAL_EXTERNAL_DOC_SOURCE = "external_placeholder"


def configured_doc_source_adapter(config: dict) -> str:
    return config.get("doc_source_adapter", LOCAL_MARKDOWN_DOC_SOURCE)


def local_markdown_documents(project_root: pathlib.Path, config: dict) -> list[dict]:
    rule_globs = config.get("rules", {}).get("globs", [])
    documents: list[dict] = []
    for rule_file in sorted(project_root.rglob("*.md")):
        relative = rule_file.relative_to(project_root).as_posix()
        if not matches_any(relative, rule_globs):
            continue
        documents.append(
            {
                "relative_path": relative,
                "text": rule_file.read_text(encoding="utf-8"),
                "source_adapter": LOCAL_MARKDOWN_DOC_SOURCE,
            }
        )
    return documents


def optional_external_documents(project_root: pathlib.Path, config: dict) -> list[dict]:
    documents: list[dict] = []
    external_docs = config.get("external_docs", [])
    if not external_docs:
        return documents
    project_root_value = pathlib.PurePosixPath(config.get("project_root", "."))
    workspace_root = project_root
    for _ in project_root_value.parts:
        workspace_root = workspace_root.parent
    cache_dir = workspace_root / config.get("doc_cache", {}).get("dir", ".ai/codegraph/doc-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(external_docs, start=1):
        doc_id = item.get("id", f"external-doc-{index}")
        text = item.get("text", "").strip()
        if not text:
            continue
        snapshot_path = cache_dir / f"{doc_id}.json"
        snapshot_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        documents.append(
            {
                "relative_path": pathlib.PurePosixPath(".ai/codegraph/doc-cache", snapshot_path.name).as_posix(),
                "text": text,
                "source_adapter": OPTIONAL_EXTERNAL_DOC_SOURCE,
            }
        )
    return documents


def collect_rule_documents_from_sources(project_root: pathlib.Path, config: dict) -> list[dict]:
    adapter_name = configured_doc_source_adapter(config)
    documents = local_markdown_documents(project_root, config)
    if adapter_name == OPTIONAL_EXTERNAL_DOC_SOURCE:
        documents.extend(optional_external_documents(project_root, config))
    return documents


def doc_source_doctor_status(project_root: pathlib.Path, config: dict) -> tuple[str, str]:
    adapter_name = configured_doc_source_adapter(config)
    if adapter_name == OPTIONAL_EXTERNAL_DOC_SOURCE:
        if config.get("external_docs"):
            return ("PASS", f"doc_source external_placeholder loaded {len(config.get('external_docs', []))} cached external document(s)")
        return ("WARN", "doc_source external_placeholder configured but no external documents were supplied")
    documents = local_markdown_documents(project_root, config)
    if documents:
        return ("PASS", f"doc_source local_markdown found {len(documents)} local markdown document(s)")
    return ("WARN", "doc_source local_markdown found no matching markdown rule files")
