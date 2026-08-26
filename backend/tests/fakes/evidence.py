from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.core.retrieval.knowledge_ids import query_hash, sha256_hex
from app.models.knowledge.knowledge import (
    EvidenceBatch,
    EvidenceItem,
    KnowledgeChunk,
    RetrievalRequest,
    RetrievalStatus,
    ScoreKind,
    SourceLocator,
    SourceType,
    VectorCandidate,
)


def make_knowledge_chunk(
    *,
    knowledge_base_id: str = "kb-fixture",
    document_id: str = "doc-fixture",
    document_version: str = "docv-fixture",
    chunk_id: str = "chunk-fixture",
    text: str = "可信知识片段",
    source_path: str = "source.md",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        document_version=document_version,
        chunk_id=chunk_id,
        ordinal=0,
        text=text,
        text_hash=sha256_hex(text),
        chunking_config_hash="1" * 64,
        locator=SourceLocator(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            document_version=document_version,
            chunk_id=chunk_id,
            source_type=SourceType.MARKDOWN,
            source_path=source_path,
            title="Fixture",
            section="Fixture",
            line_start=1,
            line_end=1,
        ),
    )


def make_evidence(
    *,
    knowledge_base_id: str = "kb-fixture",
    document_id: str = "doc-fixture",
    document_version: str = "docv-fixture",
    chunk_id: str = "chunk-fixture",
    evidence_id: str = "evidence-fixture",
    excerpt: str = "可信知识片段",
    query: str = "测试查询",
    rank: int = 1,
    normalized_score: float = 0.9,
    source_path: str = "source.md",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        document_version=document_version,
        chunk_id=chunk_id,
        query=query,
        query_hash=query_hash(query),
        query_rank=rank,
        rank=rank,
        raw_score=0.2,
        score_kind=ScoreKind.DISTANCE,
        normalized_score=normalized_score,
        excerpt=excerpt,
        excerpt_hash=sha256_hex(excerpt),
        locator=SourceLocator(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            document_version=document_version,
            chunk_id=chunk_id,
            source_type=SourceType.MARKDOWN,
            source_path=source_path,
            title="Fixture",
            section="Fixture",
            line_start=1,
            line_end=1,
        ),
        config_hash="2" * 64,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_available_batch(
    evidence: list[EvidenceItem],
    *,
    candidate_count: int | None = None,
) -> EvidenceBatch:
    kb_id = evidence[0].knowledge_base_id
    return EvidenceBatch(
        status=RetrievalStatus.AVAILABLE,
        knowledge_base_id=kb_id,
        evidence=evidence,
        query_hashes=list(dict.fromkeys(item.query_hash for item in evidence)),
        query_count=len({item.query_hash for item in evidence}),
        candidate_count=candidate_count or len(evidence),
        dropped_candidate_count=max(0, (candidate_count or len(evidence)) - len(evidence)),
        config_hash=evidence[0].config_hash,
    )


def make_vector_candidate(
    chunk: KnowledgeChunk,
    *,
    query: str,
    raw_score: float = 0.2,
) -> VectorCandidate:
    return VectorCandidate(
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        metadata={
            "knowledge_base_id": chunk.knowledge_base_id,
            "document_id": chunk.document_id,
            "document_version": chunk.document_version,
            "chunk_id": chunk.chunk_id,
            "text_hash": chunk.text_hash,
        },
        raw_score=raw_score,
        score_kind=ScoreKind.DISTANCE,
        metric="cosine",
        query=query,
        query_rank=1,
    )


class ScriptedVectorSearchBackend:
    def __init__(self, outcomes: dict[str, Any]):
        self.outcomes = dict(outcomes)
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs) -> list[VectorCandidate]:
        self.calls.append(kwargs)
        outcome = self.outcomes.get(kwargs["query"], [])
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Callable):
            outcome = outcome(kwargs)
        return list(outcome)


class ScriptedEvidenceRetriever:
    def __init__(
        self,
        batches: list[EvidenceBatch],
        settings: Settings | None = None,
    ):
        self.batches = list(batches)
        self.settings = settings or Settings(_env_file=None)
        self.calls: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest) -> EvidenceBatch:
        self.calls.append(request)
        if not self.batches:
            raise AssertionError("No scripted EvidenceBatch remains")
        return self.batches.pop(0)
