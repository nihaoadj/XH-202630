from app.db.audit.base import PersistenceConflict
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.shared.models import (
    AgentRunORM,
    AgentStepORM,
    Base,
    GeneratedResourceORM,
    ResourceReviewORM,
    RetrievalEvidenceSnapshotORM,
)
from app.models.reviews.claims import (
    ClaimCandidate,
    ClaimJudgementCandidate,
    ClaimType,
    ClaimVerdict,
    materialize_claims,
    materialize_judgements,
)
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _audit():
    claim = materialize_claims(
        candidates=[ClaimCandidate(
            claim_text="事实",
            claim_type=ClaimType.FACTUAL,
            source_text="事实",
            source_start=0,
            source_end=2,
            source_evidence_ids=["ev"],
        )],
        resource_content="事实",
        resource_id="res",
        resource_version=1,
        review_id="rev",
        run_id="run",
        allowed_evidence_ids={"ev"},
        allowed_knowledge_point_ids=set(),
        extractor_prompt_version="extract-v1",
        extractor_model="fake",
    )
    judgement = materialize_judgements(
        claims=claim,
        candidates=[ClaimJudgementCandidate(
            claim_id=claim[0].claim_id,
            verdict=ClaimVerdict.SUPPORTED,
            evidence_ids=["ev"],
            reason="支持",
            confidence=1.0,
        )],
        allowed_evidence_ids={"ev"},
        judge_prompt_version="judge-v1",
        judge_model="fake",
    )
    return claim, judgement


def test_memory_claim_repository_is_idempotent_and_queryable():
    repository = MemoryClaimRepository()
    claims, judgements = _audit()
    repository.save_audit(claims, judgements)
    repository.save_audit(claims, judgements)
    stored_claims = repository.list_claims_by_run("run")
    assert [item.model_dump(exclude={"created_at"}) for item in stored_claims] == [
        item.model_dump(exclude={"created_at"}) for item in claims
    ]
    assert repository.list_judgements_by_run("run") == judgements


def test_memory_claim_repository_rejects_immutable_conflict():
    repository = MemoryClaimRepository()
    claims, judgements = _audit()
    repository.save_audit(claims, judgements)
    changed = claims[0].model_copy(update={"claim_text": "被修改"})
    with pytest.raises(PersistenceConflict, match="immutable"):
        repository.save_audit([changed], judgements)


def test_sql_claim_repository_persists_judgement_and_frozen_evidence_binding():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(AgentRunORM(run_id="run", status="running"))
        db.add(AgentStepORM(
            step_id="step-retrieve",
            run_id="run",
            step_no=1,
            agent_name="retriever",
            action="retrieve",
        ))
        db.add(GeneratedResourceORM(
            resource_id="res",
            run_id="run",
            learner_id="learner",
            topic="topic",
            resource_type="讲义",
            difficulty="初级",
            storage_type="text",
        ))
        db.add(ResourceReviewORM(review_id="rev", resource_id="res", run_id="run", status="approve"))
        db.add(RetrievalEvidenceSnapshotORM(
            evidence_id="ev",
            run_id="run",
            retrieval_step_id="step-retrieve",
            knowledge_base_id="kb",
            document_id="doc",
            document_version="v1",
            chunk_id="chunk",
            query_hash="1" * 64,
            query_rank=1,
            rank=1,
            raw_score=0.1,
            score_kind="distance",
            normalized_score=0.9,
            excerpt="事实",
            excerpt_hash="2" * 64,
            locator={},
            config_hash="3" * 64,
            snapshot_hash="4" * 64,
            retrieved_at=now,
        ))
        db.commit()
    claims, judgements = _audit()
    repository = SQLClaimRepository(factory)
    repository.save_audit(claims, judgements)

    stored_claims = repository.list_claims_by_run("run")
    assert [item.model_dump(exclude={"created_at"}) for item in stored_claims] == [
        item.model_dump(exclude={"created_at"}) for item in claims
    ]
    loaded = repository.list_judgements_by_run("run")
    assert len(loaded) == 1
    assert loaded[0].evidence_ids == ["ev"]
    with factory() as db:
        review = db.get(ResourceReviewORM, "rev")
        assert review.claim_metric_status == "complete"
        assert review.claim_hallucination_rate == 0.0
