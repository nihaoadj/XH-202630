"""按知识库隔离的 Chroma 向量存储访问层。"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable, Optional

from langchain_community.vectorstores import Chroma
from langchain.schema import Document

from app.config import get_settings, resolve_backend_path
from app.core.embeddings import get_embeddings
from app.core.knowledge_base import load_knowledge_base_manifest


def _collection_name(knowledge_base_id: str) -> str:
    """避免中文、空格等 ID 直接作为 Chroma collection 名称带来的兼容问题。"""
    digest = hashlib.sha256(knowledge_base_id.encode("utf-8")).hexdigest()[:16]
    return f"kb_{digest}"


def _resolve_knowledge_base_id(knowledge_base_id: Optional[str]) -> str:
    if knowledge_base_id:
        return knowledge_base_id
    return str(load_knowledge_base_manifest()["knowledge_base_id"])


# Chroma metadata accepts scalar values only.  The source document metadata also
# deliberately carries lists (knowledge points, learner levels and source URLs),
# so encode those values at the storage boundary instead of throwing away
# provenance needed by retrieval and audit features.
_JSON_METADATA_FIELDS = {"knowledge_points", "learner_levels", "source_urls"}


def _to_chroma_document(document: Document) -> Document:
    metadata = {}
    for key, value in document.metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        else:
            metadata[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return Document(page_content=document.page_content, metadata=metadata)


def _restore_retrieved_metadata(document: Document) -> Document:
    """Restore JSON-encoded provenance lists before returning search results."""
    for key in _JSON_METADATA_FIELDS:
        value = document.metadata.get(key)
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list):
                document.metadata[key] = decoded
    return document


def get_vector_store(knowledge_base_id: Optional[str] = None) -> Chroma:
    """获取指定知识库独立的持久化向量集合。"""
    settings = get_settings()
    vector_store_dir = resolve_backend_path(settings.vector_store_dir)
    os.makedirs(vector_store_dir, exist_ok=True)
    kb_id = _resolve_knowledge_base_id(knowledge_base_id)
    return Chroma(
        collection_name=_collection_name(kb_id),
        persist_directory=str(vector_store_dir),
        embedding_function=get_embeddings(),
        collection_metadata={"knowledge_base_id": kb_id},
    )


def add_documents(documents: Iterable, ids: Optional[list[str]] = None, knowledge_base_id: Optional[str] = None):
    """以稳定 ID 上插入文档；重复执行同一批入库操作不会新增重复片段。"""
    documents = list(documents)
    if not documents:
        return []
    inferred_ids = {document.metadata.get("knowledge_base_id") for document in documents}
    if None in inferred_ids or len(inferred_ids) != 1:
        raise ValueError("一次入库只能包含同一 knowledge_base_id 的完整溯源片段")
    kb_id = _resolve_knowledge_base_id(knowledge_base_id or next(iter(inferred_ids)))
    if kb_id not in inferred_ids:
        raise ValueError("传入的 knowledge_base_id 与片段元数据不一致")
    stable_ids = ids or [document.metadata.get("chunk_id") for document in documents]
    if not all(stable_ids) or len(stable_ids) != len(documents):
        raise ValueError("每个片段必须具备唯一的 chunk_id")
    chroma_documents = [_to_chroma_document(document) for document in documents]
    return get_vector_store(kb_id).add_documents(chroma_documents, ids=stable_ids)


def reset_vector_store(knowledge_base_id: Optional[str] = None) -> None:
    """删除指定知识库的向量集合，用于显式全量重建。"""
    get_vector_store(knowledge_base_id).delete_collection()


def similarity_search(query: str, top_k: int = 5, knowledge_base_id: Optional[str] = None):
    """在指定知识库的独立集合中执行语义检索。"""
    if not query or not query.strip():
        raise ValueError("检索查询不能为空")
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    results = get_vector_store(knowledge_base_id).similarity_search_with_score(query, k=top_k)
    return [(_restore_retrieved_metadata(document), score) for document, score in results]
