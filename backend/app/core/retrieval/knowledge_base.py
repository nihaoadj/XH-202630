"""知识库加载、元数据规范化与稳定切片。

知识库目录是可替换的领域数据源。本模块确保所有进入向量库的片段都带有
知识库、文档和片段三级标识，供检索溯源、Claim 审核和后续关系库同步使用。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config import PROJECT_ROOT, get_settings, resolve_backend_path
from app.core.retrieval.knowledge_ids import (
    chunk_id,
    chunking_config_hash,
    document_id as build_document_id,
    document_version_id,
    normalize_source_path,
    normalize_text,
    sha256_hex,
)
from app.core.retrieval.markdown_structure import (
    MAX_ATOMIC_CHARS,
    STRUCTURE_STRATEGY,
    structural_chunks,
)
from app.core.retrieval.evidence_chunking import EVIDENCE_STRATEGY, evidence_chunks
from app.core.retrieval.knowledge_paths import (
    LAYOUT_VERSION, resolve_knowledge_file,
)


TEXT_EXTENSIONS = {".md", ".txt"}
DEFAULT_CHUNKING_STRATEGY = "recursive-v1"
_DOCUMENT_IDENTITY_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"知识库元数据必须为 JSON 对象：{path}")
    return data


def resolve_knowledge_base_dir(kb_dir: Optional[str] = None) -> Path:
    """解析知识库目录；相对路径统一以 backend 目录为基准。"""
    target = resolve_backend_path(kb_dir or get_settings().knowledge_base_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"知识库目录不存在：{target}")
    return target


def list_knowledge_base_dirs() -> List[Path]:
    """列出项目内所有可作为学习方向的数据目录。"""
    root = PROJECT_ROOT / "knowledge_base"
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def resolve_knowledge_base_dir_by_id(knowledge_base_id: Optional[str] = None) -> Path:
    """按知识库 ID 解析目录；ID 是学习方向在后端的稳定绑定。"""
    if not knowledge_base_id:
        return resolve_knowledge_base_dir()
    for path in list_knowledge_base_dirs():
        raw = _read_json(path / "metadata.json")
        kb_id = str(raw.get("knowledge_base_id") or raw.get("knowledge_base_name") or path.name)
        if kb_id == knowledge_base_id:
            return path
    raise FileNotFoundError(f"知识库目录不存在：{knowledge_base_id}")


def load_metadata(kb_dir: Optional[str] = None) -> Dict[str, Any]:
    """加载原始知识库元数据，不存在时返回空字典以兼容旧知识库。"""
    return _read_json(resolve_knowledge_base_dir(kb_dir) / "metadata.json")


def load_knowledge_base_manifest(kb_dir: Optional[str] = None) -> Dict[str, Any]:
    """返回兼容新旧目录结构的标准化知识库清单。

    最低要求是目录名；推荐在 metadata.json 中显式提供 knowledge_base_id、
    version、documents 和 skill_nodes。旧格式会被补全，而不会阻塞现有示例运行。
    """
    kb_path = resolve_knowledge_base_dir(kb_dir)
    raw = load_metadata(str(kb_path))
    kb_id = str(raw.get("knowledge_base_id") or raw.get("knowledge_base_name") or kb_path.name)

    identity_revision = raw.get("document_identity_revision")
    if identity_revision is not None and (
        not isinstance(identity_revision, str)
        or not _DOCUMENT_IDENTITY_REVISION.fullmatch(identity_revision)
    ):
        raise ValueError("document_identity_revision must be a stable token of at most 128 characters")

    raw_documents = raw.get("documents", [])
    layout = raw.get("storage_layout", {})
    if layout and (not isinstance(layout, dict) or layout.get("version") != LAYOUT_VERSION or layout.get("loading") != "manifest_only"):
        raise ValueError("unsupported knowledge storage layout")
    document_specs: Dict[str, Dict[str, Any]] = {}
    seen_ids: set[str] = set()
    seen_physical: set[Path] = set()
    if layout and not isinstance(raw_documents, list):
        raise ValueError("manifest-only documents must be a list")
    if isinstance(raw_documents, list):
        for item in raw_documents:
            if not isinstance(item, dict) or not item.get("file"):
                if layout:
                    raise ValueError("manifest-only document requires a file")
                continue
            relative_file = str(item["file"]).replace("\\", "/")
            if layout:
                physical = resolve_knowledge_file(kb_path, relative_file)
                if physical.suffix.lower() not in TEXT_EXTENSIONS:
                    raise ValueError("manifest-only body must be Markdown or text")
                ident = str(item.get("id") or build_document_id(kb_id, relative_file))
                if relative_file in document_specs or ident in seen_ids or physical in seen_physical:
                    raise ValueError("duplicate manifest-only document identity or target")
                seen_ids.add(ident)
                seen_physical.add(physical)
            document_specs[relative_file] = dict(item)

    return {
        "knowledge_base_id": kb_id,
        "name": str(raw.get("name") or raw.get("knowledge_base_name") or kb_id),
        "version": str(raw.get("version") or "0.1.0"),
        "domain": raw.get("domain"),
        "description": raw.get("description"),
        "skill_nodes": raw.get("skill_nodes", []),
        "learner_levels": raw.get("learner_levels", []),
        "document_specs": document_specs,
        "index_schema_version": str(raw.get("index_schema_version") or "1.0"),
        "document_identity_revision": identity_revision,
        "chunking": raw.get("chunking", {}),
        "smoke_queries": raw.get("smoke_queries", []),
        "raw_metadata": raw,
        "storage_layout": layout,
    }


def _document_metadata(
    path: Path,
    kb_path: Path,
    manifest: Dict[str, Any],
    content: str,
    logical_path: str | None = None,
) -> Dict[str, Any]:
    relative_path = logical_path or normalize_source_path(path.relative_to(kb_path).as_posix())
    # 支持 metadata.json 中写 "01_x.md" 和 "raw/01_x.md" 两种格式。
    spec = manifest["document_specs"].get(relative_path)
    if spec is None:
        spec = manifest["document_specs"].get(path.name, {})
    if spec.get("document_type") == "authoritative_original":
        snapshot = resolve_knowledge_file(kb_path, str(spec.get("source_snapshot", "")))
        if not snapshot.is_relative_to(kb_path.resolve()) or not snapshot.is_file():
            raise ValueError("Authoritative source snapshot must be a local KB file")
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != spec.get("source_hash"):
            raise ValueError("Authoritative source snapshot hash mismatch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec.get("normalized_hash"):
            raise ValueError("Authoritative normalized document hash mismatch")
    document_id = str(
        spec.get("id")
        or build_document_id(manifest["knowledge_base_id"], relative_path)
    )
    content_hash = sha256_hex(content)
    document_version = document_version_id(
        manifest["knowledge_base_id"],
        document_id,
        content_hash,
        identity_revision=manifest.get("document_identity_revision"),
    )
    first_heading = next(
        (line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")),
        path.stem,
    )
    metadata = {
        "knowledge_base_id": manifest["knowledge_base_id"],
        "document_id": document_id,
        "title": str(spec.get("title") or first_heading),
        "source_path": relative_path,
        "knowledge_points": spec.get("knowledge_points", []),
        "learner_levels": spec.get("learner_levels", manifest["learner_levels"]),
        "document_version": document_version,
        "source_version": str(spec.get("version") or manifest["version"]),
        "document_content_hash": content_hash,
        "source_type": str(
            spec.get("source_type")
            or ("markdown" if path.suffix.lower() == ".md" else "text")
        ),
        "enabled": bool(spec.get("enabled", True)),
        "source_urls": spec.get("source_urls", []),
    }
    # Do not add defaults to legacy metadata: immutable SQL versions compare
    # the complete metadata payload, not just the document content hash.
    for key in (
        "chunking_strategy", "section_knowledge_points", "document_type",
        "authority", "source_snapshot", "source_hash", "normalized_hash", "parser_version", "license",
        "page_spans",
    ):
        if key in spec and (
            "chunking_strategy" in spec or spec.get("document_type") == "authoritative_original"
        ):
            metadata[key] = spec[key]
    if manifest.get("document_identity_revision") is not None:
        metadata["document_identity_revision"] = manifest["document_identity_revision"]
    return metadata


def load_documents(kb_dir: Optional[str] = None) -> List[Document]:
    """加载 Markdown/TXT 文档，并为每篇文档填充标准溯源元数据。"""
    kb_path = resolve_knowledge_base_dir(kb_dir)
    manifest = load_knowledge_base_manifest(str(kb_path))
    documents: List[Document] = []
    if manifest["storage_layout"]:
        entries = [(logical, resolve_knowledge_file(kb_path, logical))
                   for logical, spec in sorted(manifest["document_specs"].items()) if spec.get("enabled", True)]
    else:
        entries = [(None, path) for path in sorted(kb_path.rglob("*"))]
    for logical, path in entries:
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        with path.open("r", encoding="utf-8") as file:
            text = normalize_text(file.read())
        if not text and manifest["storage_layout"]:
            raise ValueError("manifest-only body must not be empty")
        if text:
            metadata = _document_metadata(path, kb_path, manifest, text, logical)
            if metadata["enabled"]:
                documents.append(Document(page_content=text, metadata=metadata))
    return documents


def _section_at(text: str, start_index: int) -> Optional[str]:
    """Return the nearest Markdown heading path before one character offset."""

    headings: Dict[int, str] = {}
    consumed = 0
    for line in text.splitlines(keepends=True):
        if consumed > start_index:
            break
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= level <= 6 and stripped[level:].strip():
                headings = {key: value for key, value in headings.items() if key < level}
                headings[level] = stripped[level:].strip()
        consumed += len(line)
    if not headings:
        return None
    return " / ".join(headings[level] for level in sorted(headings))


def chunk_documents(
    documents: List[Document], chunk_size: int = 500, chunk_overlap: int = 100
) -> List[Document]:
    """按默认 500/100 切片并生成稳定 ID、序号和内容校验值。"""
    if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_size 必须大于 0，且 chunk_overlap 必须满足 0 <= overlap < size")
    config = {
        "strategy": DEFAULT_CHUNKING_STRATEGY,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "separators_version": "zh-text-v1",
        "normalization_version": "nfc-lines-v1",
    }
    config_hash = chunking_config_hash(config)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""],
        add_start_index=True,
    )
    chunks: List[Document] = []
    for document in documents:
        strategy = document.metadata.get("chunking_strategy", DEFAULT_CHUNKING_STRATEGY)
        if strategy in {STRUCTURE_STRATEGY, EVIDENCE_STRATEGY}:
            chunker = evidence_chunks if strategy == EVIDENCE_STRATEGY else structural_chunks
            source_chunks = chunker(
                document, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
            )
            structure_config = {
                **config, "strategy": strategy,
                "atomic_limit": MAX_ATOMIC_CHARS,
                "mapping": document.metadata.get("section_knowledge_points", {}),
            }
            if strategy == EVIDENCE_STRATEGY:
                structure_config.update(soft_max_chars=max(1200, chunk_size), min_chars=200,
                                        unit_rules="teaching-units-v2")
            if "page_spans" in document.metadata:
                structure_config["page_spans"] = document.metadata["page_spans"]
            document_config_hash = chunking_config_hash(structure_config)
        elif strategy in {DEFAULT_CHUNKING_STRATEGY, "recursive_v1"}:
            source_chunks = splitter.split_documents([document])
            document_config_hash = config_hash
        else:
            raise ValueError(f"Unsupported document chunking strategy: {strategy}")
        kb_id = document.metadata.get("knowledge_base_id")
        document_id = document.metadata.get("document_id")
        document_version = document.metadata.get("document_version")
        if not kb_id or not document_id or not document_version:
            raise ValueError(
                "文档缺少 knowledge_base_id、document_id 或 document_version，无法进行可追溯切片"
            )
        for index, chunk in enumerate(source_chunks):
            normalized_chunk = normalize_text(chunk.page_content)
            text_hash = sha256_hex(normalized_chunk)
            start_index = int(chunk.metadata.pop("start_index", 0))
            line_start = document.page_content.count("\n", 0, start_index) + 1
            line_end = line_start + normalized_chunk.count("\n")
            stable_chunk_id = chunk_id(
                knowledge_base_id=str(kb_id),
                logical_document_id=str(document_id),
                document_version=str(document_version),
                chunking_hash=document_config_hash,
                ordinal=index,
                text_hash=text_hash,
            )
            piece_metadata = dict(chunk.metadata)
            chunk.page_content = normalized_chunk
            chunk.metadata.update(document.metadata)
            if strategy in {STRUCTURE_STRATEGY, EVIDENCE_STRATEGY}:
                chunk.metadata.update(piece_metadata)
            chunk.metadata.update(
                {
                    "chunk_id": stable_chunk_id,
                    "chunk_index": index,
                    "chunk_ordinal": index,
                    "content_hash": text_hash,
                    "text_hash": text_hash,
                    "chunking_config_hash": document_config_hash,
                    "section": (
                        piece_metadata.get("section") if strategy in {STRUCTURE_STRATEGY, EVIDENCE_STRATEGY}
                        else _section_at(document.page_content, start_index)
                    ),
                    "line_start": line_start,
                    "line_end": line_end,
                }
            )
            chunks.append(chunk)
    return chunks
