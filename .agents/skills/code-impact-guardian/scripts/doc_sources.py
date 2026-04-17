#!/usr/bin/env python3
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
    _ = project_root
    _ = config
    return []


def collect_rule_documents_from_sources(project_root: pathlib.Path, config: dict) -> list[dict]:
    adapter_name = configured_doc_source_adapter(config)
    documents = local_markdown_documents(project_root, config)
    if adapter_name == OPTIONAL_EXTERNAL_DOC_SOURCE:
        documents.extend(optional_external_documents(project_root, config))
    return documents


def doc_source_doctor_status(project_root: pathlib.Path, config: dict) -> tuple[str, str]:
    adapter_name = configured_doc_source_adapter(config)
    if adapter_name == OPTIONAL_EXTERNAL_DOC_SOURCE:
        return ("WARN", "doc_source external_placeholder configured but no external provider is installed")
    documents = local_markdown_documents(project_root, config)
    if documents:
        return ("PASS", f"doc_source local_markdown found {len(documents)} local markdown document(s)")
    return ("WARN", "doc_source local_markdown found no matching markdown rule files")
