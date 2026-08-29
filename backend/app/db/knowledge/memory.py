"""In-memory immutable Chunk catalog for offline evidence tests."""

from typing import Iterable

from app.models.knowledge.knowledge import KnowledgeChunk, SourceLocator


class MemoryKnowledgeChunkRepository:
    def __init__(self, chunks: Iterable[KnowledgeChunk] = ()):
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def save_all(self, chunks: Iterable[KnowledgeChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def get_chunk(
        self,
        chunk_id: str,
        *,
        knowledge_base_id: str | None = None,
        document_version: str | None = None,
    ) -> KnowledgeChunk | None:
        chunk = self._chunks.get(chunk_id)
        if chunk is None:
            return None
        if knowledge_base_id is not None and chunk.knowledge_base_id != knowledge_base_id:
            return None
        if document_version is not None and chunk.document_version != document_version:
            return None
        return chunk

    def is_chunk_active(self, knowledge_base_id: str, chunk_id: str) -> bool:
        chunk = self.get_chunk(chunk_id, knowledge_base_id=knowledge_base_id)
        return bool(chunk and chunk.enabled)

    def resolve_chunk_locator(
        self,
        knowledge_base_id: str,
        document_version: str,
        chunk_id: str,
    ) -> SourceLocator | None:
        chunk = self.get_chunk(
            chunk_id,
            knowledge_base_id=knowledge_base_id,
            document_version=document_version,
        )
        return chunk.locator if chunk else None

    def get_active_chunk_ids_for_skill_nodes(
        self,
        knowledge_base_id: str,
        skill_node_ids: list[str],
    ) -> list[str]:
        # Offline evidence tests do not model persistent node mappings.
        return []
