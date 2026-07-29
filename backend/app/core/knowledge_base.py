"""知识库加载、元数据规范化与稳定切片。

知识库目录是可替换的领域数据源。本模块确保所有进入向量库的片段都带有
知识库、文档和片段三级标识，供检索溯源、Claim 审核和后续关系库同步使用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config import PROJECT_ROOT, get_settings, resolve_backend_path
from app.core.knowledge_ids import (
    chunk_id,
    chunking_config_hash,
    document_id as build_document_id,
    document_version_id,
    normalize_source_path,
    normalize_text,
    sha256_hex,
)


TEXT_EXTENSIONS = {".md", ".txt"}
DEFAULT_CHUNKING_STRATEGY = "recursive-v1"


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

    raw_documents = raw.get("documents", [])
    document_specs: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_documents, list):
        for item in raw_documents:
            if not isinstance(item, dict) or not item.get("file"):
                continue
            relative_file = str(item["file"]).replace("\\", "/")
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
        "chunking": raw.get("chunking", {}),
        "smoke_queries": raw.get("smoke_queries", []),
        "raw_metadata": raw,
    }


def _document_metadata(
    path: Path,
    kb_path: Path,
    manifest: Dict[str, Any],
    content: str,
) -> Dict[str, Any]:
    relative_path = normalize_source_path(path.relative_to(kb_path).as_posix())
    # 支持 metadata.json 中写 "01_x.md" 和 "raw/01_x.md" 两种格式。
    spec = manifest["document_specs"].get(relative_path)
    if spec is None:
        spec = manifest["document_specs"].get(path.name, {})
    document_id = str(
        spec.get("id")
        or build_document_id(manifest["knowledge_base_id"], relative_path)
    )
    content_hash = sha256_hex(content)
    document_version = document_version_id(
        manifest["knowledge_base_id"],
        document_id,
        content_hash,
    )
    first_heading = next(
        (line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")),
        path.stem,
    )
    return {
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


def load_documents(kb_dir: Optional[str] = None) -> List[Document]:
    """加载 Markdown/TXT 文档，并为每篇文档填充标准溯源元数据。"""
    kb_path = resolve_knowledge_base_dir(kb_dir)
    manifest = load_knowledge_base_manifest(str(kb_path))
    documents: List[Document] = []
    for path in sorted(kb_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        with path.open("r", encoding="utf-8") as file:
            text = normalize_text(file.read())
        if text:
            metadata = _document_metadata(path, kb_path, manifest, text)
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
    documents: List[Document], chunk_size: int = 500, chunk_overlap: int = 50
) -> List[Document]:
    """切片并为每个片段生成稳定 ID、序号和内容校验值。"""
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
        source_chunks = splitter.split_documents([document])
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
                chunking_hash=config_hash,
                ordinal=index,
                text_hash=text_hash,
            )
            chunk.page_content = normalized_chunk
            chunk.metadata.update(document.metadata)
            chunk.metadata.update(
                {
                    "chunk_id": stable_chunk_id,
                    "chunk_index": index,
                    "chunk_ordinal": index,
                    "content_hash": text_hash,
                    "text_hash": text_hash,
                    "chunking_config_hash": config_hash,
                    "section": _section_at(document.page_content, start_index),
                    "line_start": line_start,
                    "line_end": line_end,
                }
            )
            chunks.append(chunk)
    return chunks
