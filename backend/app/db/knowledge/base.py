"""Read contract used by the EvidenceRetriever provenance validator."""

from typing import Protocol

from app.models.knowledge.knowledge import KnowledgeChunk, SourceLocator


class KnowledgeChunkRepository(Protocol):
    def get_chunk(
        self,
        chunk_id: str,
        *,
        knowledge_base_id: str | None = None,
        document_version: str | None = None,
    ) -> KnowledgeChunk | None: ...

    def is_chunk_active(self, knowledge_base_id: str, chunk_id: str) -> bool: ...

    def resolve_chunk_locator(
        self,
        knowledge_base_id: str,
        document_version: str,
        chunk_id: str,
    ) -> SourceLocator | None: ...

    def get_active_chunk_ids_for_skill_nodes(
        self,
        knowledge_base_id: str,
        skill_node_ids: list[str],
    ) -> list[str]: ...
