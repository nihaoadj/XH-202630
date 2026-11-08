"""T50 additive side tables for optional Claim evidence retrieval.

The first-round Claim audit stays in ``resource_claims`` / ``claim_judgements``.
These tables only hold the supplement ledger, the controlled evidence scopes and
the round-1 judgements, so no existing row, unique constraint or ID material is
rewritten.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.db.shared.models import Base


class ClaimEvidenceRetrievalRunORM(Base):
    __tablename__ = "claim_evidence_retrieval_runs"

    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    policy_hash = Column(String(64), nullable=False)
    policy_json = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    reserved_tokens = Column(Integer, nullable=False, default=0)
    known_tokens = Column(Integer, nullable=False, default=0)
    unknown_tokens = Column(Integer, nullable=False, default=0)
    logical_calls = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    query_count = Column(Integer, nullable=False, default=0)
    owner = Column(String(256), nullable=True)
    epoch = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False)
    deadline_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClaimEvidenceRetrievalSessionORM(Base):
    __tablename__ = "claim_evidence_retrieval_sessions"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "resource_id", "resource_version", "review_id",
            name="uq_claim_evidence_session_binding",
        ),
        Index("ix_claim_evidence_session_status", "run_id", "status"),
    )

    session_id = Column(String(128), primary_key=True)
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    resource_id = Column(
        String(64), ForeignKey("generated_resources.resource_id"), nullable=False, index=True,
    )
    resource_version = Column(Integer, nullable=False)
    review_id = Column(String(128), ForeignKey("resource_reviews.review_id"), nullable=False)
    content_hash = Column(String(64), nullable=False)
    policy_hash = Column(String(64), nullable=False)
    base_evidence_set_hash = Column(String(64), nullable=False)
    initial_judgement_hash = Column(String(64), nullable=False)
    target_claim_ids = Column(JSON, nullable=False, default=list)
    query_count = Column(Integer, nullable=False, default=0)
    evidence_scope_ids = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="pending")
    reason_code = Column(String(64), nullable=True)
    active = Column(Boolean, nullable=False, default=False)
    hard_block = Column(Boolean, nullable=False, default=False)
    hard_block_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ClaimEvidenceRetrievalBatchORM(Base):
    __tablename__ = "claim_evidence_retrieval_batches"
    __table_args__ = (
        UniqueConstraint("session_id", "kind", "ordinal", name="uq_claim_evidence_batch_ordinal"),
    )

    batch_id = Column(String(128), primary_key=True)
    session_id = Column(
        String(128),
        ForeignKey("claim_evidence_retrieval_sessions.session_id"),
        nullable=False,
        index=True,
    )
    kind = Column(String(16), nullable=False)
    ordinal = Column(Integer, nullable=False)
    input_hash = Column(String(64), nullable=False)
    output_hash = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="planned")
    payload = Column(JSON, nullable=False, default=dict)
    expected_claim_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClaimEvidenceRetrievalAttemptORM(Base):
    __tablename__ = "claim_evidence_retrieval_attempts"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "logical_call_id", "attempt_no",
            name="uq_claim_evidence_attempt_identity",
        ),
    )

    attempt_id = Column(String(128), primary_key=True)
    batch_id = Column(
        String(128),
        ForeignKey("claim_evidence_retrieval_batches.batch_id"),
        nullable=False,
        index=True,
    )
    logical_call_id = Column(String(128), nullable=False)
    attempt_no = Column(Integer, nullable=False)
    owner = Column(String(256), nullable=False)
    epoch = Column(Integer, nullable=False)
    reserved_tokens = Column(Integer, nullable=False)
    output_cap = Column(Integer, nullable=False)
    known_tokens = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="reserved")
    unknown_usage = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)


class ClaimReviewEvidenceSetORM(Base):
    __tablename__ = "claim_review_evidence_sets"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "resource_id", "resource_version", "purpose", "session_id",
            name="uq_claim_review_evidence_set_scope",
        ),
    )

    scope_id = Column(String(128), primary_key=True)
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    resource_id = Column(
        String(64), ForeignKey("generated_resources.resource_id"), nullable=False, index=True,
    )
    resource_version = Column(Integer, nullable=False)
    review_id = Column(String(128), ForeignKey("resource_reviews.review_id"), nullable=False)
    purpose = Column(String(16), nullable=False)
    session_id = Column(String(128), nullable=True)
    base_evidence_ids = Column(JSON, nullable=False, default=list)
    added_evidence_ids = Column(JSON, nullable=False, default=list)
    snapshot_hashes = Column(JSON, nullable=False, default=dict)
    manifest = Column(JSON, nullable=False, default=list)
    manifest_hash = Column(String(64), nullable=False)
    parent_scope_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClaimSupplementJudgementORM(Base):
    __tablename__ = "claim_supplement_judgements"
    __table_args__ = (
        UniqueConstraint("session_id", "claim_id", name="uq_claim_supplement_judgement"),
    )

    judgement_id = Column(String(128), primary_key=True)
    session_id = Column(
        String(128),
        ForeignKey("claim_evidence_retrieval_sessions.session_id"),
        nullable=False,
        index=True,
    )
    claim_id = Column(
        String(128), ForeignKey("resource_claims.claim_id"), nullable=False, index=True,
    )
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    resource_id = Column(
        String(64), ForeignKey("generated_resources.resource_id"), nullable=False, index=True,
    )
    resource_version = Column(Integer, nullable=False)
    review_id = Column(String(128), ForeignKey("resource_reviews.review_id"), nullable=False)
    round_no = Column(Integer, nullable=False, default=1)
    scope_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    verdict = Column(String(32), nullable=True)
    reason = Column(Text, nullable=False)
    judge_model = Column(String(256), nullable=True)
    judge_prompt_version = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=True)
    evidence_conflict = Column(Boolean, nullable=False, default=False)
    conflicting_evidence_ids = Column(JSON, nullable=False, default=list)
    payload_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ClaimSupplementEvidenceORM(Base):
    __tablename__ = "claim_supplement_evidence"
    __table_args__ = (
        UniqueConstraint("judgement_id", "evidence_id", name="uq_claim_supplement_evidence"),
    )

    binding_id = Column(String(128), primary_key=True)
    judgement_id = Column(
        String(128), ForeignKey("claim_supplement_judgements.judgement_id"),
        nullable=False, index=True,
    )
    evidence_id = Column(
        String(128),
        ForeignKey("retrieval_evidence_snapshots.evidence_id"),
        nullable=False,
        index=True,
    )
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


SUPPLEMENT_MODELS = (
    ClaimEvidenceRetrievalRunORM,
    ClaimEvidenceRetrievalSessionORM,
    ClaimEvidenceRetrievalBatchORM,
    ClaimEvidenceRetrievalAttemptORM,
    ClaimReviewEvidenceSetORM,
    ClaimSupplementJudgementORM,
    ClaimSupplementEvidenceORM,
)

SUPPLEMENT_TABLES = tuple(model.__tablename__ for model in SUPPLEMENT_MODELS)

__all__ = [
    "ClaimEvidenceRetrievalAttemptORM",
    "ClaimEvidenceRetrievalBatchORM",
    "ClaimEvidenceRetrievalRunORM",
    "ClaimEvidenceRetrievalSessionORM",
    "ClaimReviewEvidenceSetORM",
    "ClaimSupplementEvidenceORM",
    "ClaimSupplementJudgementORM",
    "SUPPLEMENT_MODELS",
    "SUPPLEMENT_TABLES",
]
