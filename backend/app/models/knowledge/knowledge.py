"""Strict provenance and retrieval contracts for the P0-03 evidence pipeline."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.retrieval.knowledge_ids import normalize_source_path, normalize_text
from app.models.shared.common import ErrorInfo


Scalar = Union[str, int, float, bool]


class StrictKnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class SourceType(str, Enum):
    MARKDOWN = "markdown"
    TEXT = "text"
    PDF = "pdf"
    WEB = "web"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class ScoreKind(str, Enum):
    DISTANCE = "distance"
    SIMILARITY = "similarity"


class RetrievalStatus(str, Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    NO_HIT = "no_hit"
    RETRIEVAL_ERROR = "retrieval_error"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


class SourceLocator(StrictKnowledgeModel):
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)
    source_type: SourceType
    source_path: str = Field(min_length=1, max_length=1024)
    title: str = Field(min_length=1, max_length=512)
    section: Optional[str] = Field(default=None, max_length=512)
    page: Optional[int] = Field(default=None, ge=1)
    line_start: Optional[int] = Field(default=None, ge=1)
    line_end: Optional[int] = Field(default=None, ge=1)
    timestamp_start_ms: Optional[int] = Field(default=None, ge=0)
    timestamp_end_ms: Optional[int] = Field(default=None, ge=0)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return normalize_source_path(value)

    @model_validator(mode="after")
    def validate_locator_range(self) -> "SourceLocator":
        if self.line_start is not None and self.line_end is not None:
            if self.line_end < self.line_start:
                raise ValueError("line_end must be greater than or equal to line_start")
        if self.timestamp_start_ms is not None and self.timestamp_end_ms is not None:
            if self.timestamp_end_ms < self.timestamp_start_ms:
                raise ValueError("timestamp_end_ms must be >= timestamp_start_ms")
        if self.source_type in {SourceType.MARKDOWN, SourceType.TEXT} and not (
            self.section or self.line_start is not None
        ):
            raise ValueError("text sources require a section or line range")
        return self


class KnowledgeDocumentVersion(StrictKnowledgeModel):
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    source_version: Optional[str] = Field(default=None, max_length=64)
    source_type: SourceType
    source_path: str = Field(min_length=1, max_length=1024)
    title: str = Field(min_length=1, max_length=512)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return normalize_source_path(value)


class KnowledgeChunk(StrictKnowledgeModel):
    schema_version: Literal["1.0"] = "1.0"
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=100000)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunking_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: SourceLocator
    knowledge_points: List[str] = Field(default_factory=list, max_length=100)
    learner_levels: List[str] = Field(default_factory=list, max_length=50)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_locator_identity(self) -> "KnowledgeChunk":
        expected = (
            self.knowledge_base_id,
            self.document_id,
            self.document_version,
            self.chunk_id,
        )
        actual = (
            self.locator.knowledge_base_id,
            self.locator.document_id,
            self.locator.document_version,
            self.locator.chunk_id,
        )
        if actual != expected:
            raise ValueError("locator identity must match chunk identity")
        return self


class RetrievalPolicy(StrictKnowledgeModel):
    top_k_per_query: int = Field(default=3, ge=1, le=10)
    max_query_count: int = Field(default=6, ge=1, le=10)
    min_normalized_score: float = Field(default=0.35, ge=0.0, le=1.0)
    min_evidence_count: int = Field(default=1, ge=1, le=20)
    max_evidence_count: int = Field(default=8, ge=1, le=20)
    max_excerpt_chars: int = Field(default=1200, ge=100, le=10000)
    distance_metric: Literal["cosine"] = "cosine"
    query_strategy_version: str = "deterministic-v1"
    ranking_strategy_version: str = "normalized-score-v1"

    @model_validator(mode="after")
    def validate_counts(self) -> "RetrievalPolicy":
        if self.min_evidence_count > self.max_evidence_count:
            raise ValueError("min_evidence_count cannot exceed max_evidence_count")
        return self


class RetrievalRequest(StrictKnowledgeModel):
    run_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    queries: List[str] = Field(min_length=1, max_length=10)
    # Query text is retained only for the retrieval call.  This optional map
    # records which node-scoped query produced a hit so the result can expose
    # a safe, many-to-many node -> evidence projection after global dedupe.
    query_node_ids: Dict[str, str] = Field(default_factory=dict)
    policy: RetrievalPolicy = Field(default_factory=RetrievalPolicy)

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, values: List[str]) -> List[str]:
        normalized = list(dict.fromkeys(
            normalize_text(value) for value in values if value.strip()
        ))
        if not normalized:
            raise ValueError("queries cannot be empty")
        if any(len(value) > 2000 for value in normalized):
            raise ValueError("retrieval query exceeds maximum length")
        return normalized

    @model_validator(mode="after")
    def validate_query_node_ids(self) -> "RetrievalRequest":
        unknown = set(self.query_node_ids) - set(self.queries)
        if unknown or any(not str(node_id).strip() for node_id in self.query_node_ids.values()):
            raise ValueError("query_node_ids must reference non-empty request queries")
        return self


class VectorCandidate(StrictKnowledgeModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=100000)
    metadata: Dict[str, Scalar]
    raw_score: float
    score_kind: ScoreKind
    metric: str = Field(min_length=1, max_length=32)
    query: str = Field(min_length=1, max_length=2000)
    query_rank: int = Field(ge=1)

    @field_validator("raw_score")
    @classmethod
    def validate_finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("raw_score must be finite")
        return value


class EvidenceItem(StrictKnowledgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2000)
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_rank: int = Field(ge=1)
    rank: int = Field(ge=1)
    raw_score: float
    score_kind: ScoreKind
    normalized_score: float = Field(ge=0.0, le=1.0)
    excerpt: str = Field(min_length=1, max_length=10000)
    excerpt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: SourceLocator
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime

    @model_validator(mode="after")
    def validate_locator_identity(self) -> "EvidenceItem":
        expected = (
            self.knowledge_base_id,
            self.document_id,
            self.document_version,
            self.chunk_id,
        )
        actual = (
            self.locator.knowledge_base_id,
            self.locator.document_id,
            self.locator.document_version,
            self.locator.chunk_id,
        )
        if actual != expected:
            raise ValueError("locator identity must match evidence identity")
        return self


class EvidenceBatch(StrictKnowledgeModel):
    status: RetrievalStatus
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    # This is a classification of the one immutable evidence snapshot, not a
    # second evidence store.  One evidence ID may appear under multiple nodes.
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)
    query_hashes: List[str] = Field(default_factory=list)
    query_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    dropped_candidate_count: int = Field(ge=0)
    partial_failure_count: int = Field(default=0, ge=0)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Safe timing/count metadata only; query and evidence bodies are forbidden.
    retrieval_profile: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[ErrorInfo] = None

    @model_validator(mode="after")
    def validate_status(self) -> "EvidenceBatch":
        if self.status == RetrievalStatus.AVAILABLE:
            if not self.evidence or self.error is not None:
                raise ValueError("available requires evidence and forbids an error")
        elif self.status == RetrievalStatus.NO_HIT:
            if self.evidence or self.candidate_count != 0 or self.error is not None:
                raise ValueError("no_hit requires no candidates, evidence, or error")
        elif self.status in {
            RetrievalStatus.RETRIEVAL_ERROR,
            RetrievalStatus.EVIDENCE_INSUFFICIENT,
        }:
            if self.evidence or self.error is None:
                raise ValueError("failed evidence batches require an error and no evidence")
        evidence_ids = {item.evidence_id for item in self.evidence}
        for node_id, ids in self.node_evidence_map.items():
            if not str(node_id).strip() or not ids or len(ids) != len(set(ids)):
                raise ValueError("node evidence bindings must be non-empty and unique")
            if not set(ids) <= evidence_ids:
                raise ValueError("node evidence bindings must belong to the batch")
        return self


class IngestionSmokeResult(StrictKnowledgeModel):
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_document_ids: List[str] = Field(default_factory=list)
    expected_chunk_ids: List[str] = Field(default_factory=list)
    hit_document_ids: List[str] = Field(default_factory=list)
    hit_chunk_ids: List[str] = Field(default_factory=list)
    passed: bool


class IngestionReport(StrictKnowledgeModel):
    schema_version: Literal["1.0"] = "1.0"
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    status: Literal["ready", "not_ready"]
    index_schema_version: str = Field(min_length=1, max_length=32)
    active_snapshot_hash: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    document_count: int = Field(default=0, ge=0)
    expected_active_chunk_count: int = Field(default=0, ge=0)
    sql_active_chunk_count: int = Field(default=0, ge=0)
    vector_chunk_count: int = Field(default=0, ge=0)
    smoke_status: Literal["passed", "failed", "not_configured", "not_run"]
    smoke_results: List[IngestionSmokeResult] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None

    @model_validator(mode="after")
    def validate_ingestion_result(self) -> "IngestionReport":
        if self.status == "ready":
            if self.error is not None:
                raise ValueError("ready ingestion forbids error")
            if not (
                self.expected_active_chunk_count
                == self.sql_active_chunk_count
                == self.vector_chunk_count
            ):
                raise ValueError("ready ingestion requires reconciled counts")
            if self.smoke_status == "failed":
                raise ValueError("ready ingestion cannot have failed smoke queries")
        elif self.error is None:
            raise ValueError("not_ready ingestion requires error")
        return self
