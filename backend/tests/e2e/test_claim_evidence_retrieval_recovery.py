"""F06/T50 offline recovery boundaries for the Claim evidence retrieval feature.

No Worker, server or model is started: the "restart" is a fresh engine and fresh
repository objects over the same SQLite file, which is exactly the boundary the
durable rows have to survive.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.audit.base import PersistenceConflict
from app.db.claim.publication import HARD_BLOCK_REASON, IN_FLIGHT_REASON, PublicationBarrier
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
    batch_id_for,
    round_one_identity,
)
from app.models.reviews.claims import ClaimJudgementStatus, ClaimVerdict
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)
RUN = "run-recovery"
RESOURCE = "res-recovery"
REVIEW = "rev-recovery"
CLAIM = "clm_" + "1" * 32
STEP = "step-recovery"


def _policy() -> ClaimEvidenceRetrievalPolicyV1:
    return ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_estimated_tokens=100_000,
    )


def _snapshot() -> PersistedEvidenceSnapshot:
    from app.core.retrieval.knowledge_ids import sha256_hex
    from app.models.knowledge.knowledge import (
        EvidenceItem, ScoreKind, SourceLocator, SourceType,
    )

    excerpt = "补充摘录"
    item = EvidenceItem(
        evidence_id="ev-new", knowledge_base_id="kb-001",
        document_id="doc-1", document_version="v1", chunk_id="chunk-1",
        query="q", query_hash="1" * 64, query_rank=1, rank=1,
        raw_score=0.9, score_kind=ScoreKind.SIMILARITY, normalized_score=0.8,
        excerpt=excerpt, excerpt_hash=sha256_hex(excerpt),
        locator=SourceLocator(
            knowledge_base_id="kb-001", document_id="doc-1", document_version="v1",
            chunk_id="chunk-1", source_type=SourceType.MARKDOWN,
            source_path="docs/a.md", title="a.md", section="1",
        ),
        config_hash="3" * 64, retrieved_at=NOW,
    )
    return PersistedEvidenceSnapshot.from_evidence(
        item, run_id=RUN, retrieval_step_id=STEP,
    )


def _session() -> ClaimEvidenceRetrievalSessionV1:
    return ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32,
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id=REVIEW,
        content_hash="a" * 64, policy_hash=_policy().policy_hash,
        base_evidence_set_hash="b" * 64, initial_judgement_hash="c" * 64,
        target_claim_ids=[CLAIM], created_at=NOW, updated_at=NOW,
    )


def _batch(kind: ClaimEvidenceBatchKind) -> ClaimEvidenceRetrievalBatchV1:
    input_hash = canonical_hash({"kind": kind.value})
    return ClaimEvidenceRetrievalBatchV1(
        batch_id=batch_id_for(
            session_id="cers_" + "1" * 32, kind=kind.value, ordinal=0, input_hash=input_hash,
        ),
        session_id="cers_" + "1" * 32, kind=kind, ordinal=0, input_hash=input_hash,
        expected_claim_ids=[CLAIM], created_at=NOW, updated_at=NOW,
    )


def _supplement(verdict: ClaimVerdict) -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + "9" * 32, session_id="cers_" + "1" * 32,
        claim_id=CLAIM, run_id=RUN, resource_id=RESOURCE, resource_version=1,
        review_id=REVIEW, scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-new"], reason="round1",
        judge_prompt_version="claim-evidence-rejudge-v1", confidence=0.8,
        payload_hash="e" * 64, created_at=NOW,
    )


class _Harness:
    """One process generation; ``restart`` builds a fresh one over the same file."""

    def __init__(self, path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(f"sqlite:///{path}")
        self.factory = sessionmaker(bind=self.engine)

    def bootstrap(self):
        from app.db.shared.models import (
            AgentRunORM, AgentStepORM, Base, GeneratedResourceORM,
            ResourceClaimORM, ResourceReviewORM,
        )

        Base.metadata.create_all(self.engine)
        with self.factory() as db:
            db.add(AgentRunORM(
                run_id=RUN, learner_id="learner-001", knowledge_base_id="kb-001",
                topic="RAG", status="running",
            ))
            db.add(AgentStepORM(
                step_id=STEP, run_id=RUN, step_no=1,
                agent_name="claim_evidence_retrieval",
                node_name="claim_evidence_retrieve", action="Claim 缺证补检",
                status="running",
            ))
            db.add(GeneratedResourceORM(
                resource_id=RESOURCE, run_id=RUN, learner_id="learner-001",
                topic="RAG", resource_type="讲义", difficulty="初级",
                storage_type="text", version=1, review_id=REVIEW,
                publication_status="unpublished",
            ))
            db.add(ResourceReviewORM(
                review_id=REVIEW, resource_id=RESOURCE, run_id=RUN, status="approve",
            ))
            db.add(ResourceClaimORM(
                claim_id=CLAIM, review_id=REVIEW, resource_id=RESOURCE,
                claim_text="claim", supported=False,
            ))
            db.commit()

    def repositories(self):
        from app.db.audit.sql_repository import SQLAuditRepository
        from app.db.claim.sql_repository import SQLClaimRepository
        from app.db.claim.supplement import SQLClaimSupplementRepository
        from app.db.learning_documents.sql_repository import SQLResourceRepository

        audit = SQLAuditRepository(self.factory)
        claim = SQLClaimRepository(self.factory)
        supplement = SQLClaimSupplementRepository(
            claim_repository=claim, audit_repository=audit,
            session_factory=self.factory,
        )
        resources = SQLResourceRepository(self.factory)
        return audit, claim, supplement, resources

    def close(self):
        self.engine.dispose()


@pytest.fixture()
def harness(tmp_path):
    item = _Harness(tmp_path / "t50_recovery.db")
    item.bootstrap()
    try:
        yield item
    finally:
        item.close()


def _seed_retrieval(supplement) -> None:
    supplement.open_run(
        run_id=RUN, policy=_policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = supplement.create_session(_session())
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
    ):
        supplement.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    batch = _batch(ClaimEvidenceBatchKind.RETRIEVE)
    supplement.save_batch(batch)
    supplement.complete_retrieval_batch(
        batch_id=batch.batch_id, run_id=RUN, step_id=STEP, owner="owner", epoch=1,
        output_hash="a" * 64, payload={"selected_count": 1},
        evidence=[_snapshot()], now=NOW,
    )
    supplement.update_session(
        session.session_id,
        expected_status=ClaimEvidenceRetrievalStatus.RETRIEVING,
        status=ClaimEvidenceRetrievalStatus.REJUDGING,
        evidence_scope_ids=["ev-new"],
        now=NOW,
    )


def test_a_crash_between_retrieval_and_rejudge_keeps_the_version_unpublished(harness):
    audit, _claim, supplement, resources = harness.repositories()
    _seed_retrieval(supplement)

    # Fresh process over the same file.
    audit2, _claim2, supplement2, resources2 = harness.repositories()
    session = supplement2.get_session("cers_" + "1" * 32)
    assert session.status is ClaimEvidenceRetrievalStatus.REJUDGING
    assert session.active is False
    # The persisted snapshot belongs to its retrieval step and is not lost.
    assert [item.evidence_id for item in audit2.list_evidence(RUN)] == ["ev-new"]
    batch = supplement2.get_batch(_batch(ClaimEvidenceBatchKind.RETRIEVE).batch_id)
    assert batch.status is ClaimEvidenceBatchStatus.COMPLETED
    # A replayed completion is idempotent; a different payload conflicts.
    supplement2.complete_retrieval_batch(
        batch_id=batch.batch_id, run_id=RUN, step_id=STEP, owner="owner", epoch=1,
        output_hash="a" * 64, payload={"selected_count": 1},
        evidence=[_snapshot()], now=NOW,
    )
    with pytest.raises(PersistenceConflict):
        supplement2.complete_retrieval_batch(
            batch_id=batch.batch_id, run_id=RUN, step_id=STEP, owner="owner", epoch=1,
            output_hash="f" * 64, payload={"selected_count": 2},
            evidence=[], now=NOW,
        )
    # The interrupted round is a temporary barrier: the version stays unpublished
    # and the user cannot confirm it while the round is unfinished.
    with pytest.raises(PublicationBarrier) as caught:
        resources2.update_publication_decision(RESOURCE, publish=True)
    assert caught.value.reason_code == IN_FLIGHT_REASON
    assert resources2.get(RESOURCE).publication_status == "unpublished"
    # An explicit interruption keeps the barrier but no automatic resend happens.
    supplement2.update_session(
        "cers_" + "1" * 32,
        expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
        status=ClaimEvidenceRetrievalStatus.INTERRUPTED,
        reason_code="process_interrupted",
        now=NOW,
    )
    with pytest.raises(PublicationBarrier):
        resources2.update_publication_decision(RESOURCE, publish=True)
    assert supplement2.list_batches("cers_" + "1" * 32)[0].status is (
        ClaimEvidenceBatchStatus.COMPLETED
    )


def test_a_committed_counter_evidence_batch_survives_the_restart(harness):
    audit, _claim, supplement, resources = harness.repositories()
    _seed_retrieval(supplement)
    # A legacy publication exists before the new contradiction is committed.
    with harness.factory() as db:
        from app.db.shared.models import GeneratedResourceORM

        row = db.get(GeneratedResourceORM, RESOURCE)
        row.publication_status = "published"
        db.commit()
    assert resources.get(RESOURCE).publication_status == "published"

    batch = _batch(ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="b" * 64,
        payload={"hard_block": "contradicted"},
        supplements=[_supplement(ClaimVerdict.CONTRADICTED)],
        hard_block_reason="contradicted", now=NOW,
    )

    # Restart: the block, the judgement and the withdrawal are all durable.
    _audit2, _claim2, supplement2, resources2 = harness.repositories()
    session = supplement2.get_session("cers_" + "1" * 32)
    assert session.hard_block is True
    assert session.hard_block_reason == "contradicted"
    assert [item.claim_id for item in supplement2.list_supplements([RUN])] == [CLAIM]
    assert resources2.get(RESOURCE).publication_status == "unpublished"
    with pytest.raises(PublicationBarrier) as caught:
        resources2.update_publication_decision(RESOURCE, publish=True)
    assert caught.value.reason_code == HARD_BLOCK_REASON



def test_an_activated_round_replays_with_the_same_metric_after_restart(harness):
    audit, _claim, supplement, resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="c" * 64, payload={"round": 1},
        supplements=[_supplement(ClaimVerdict.SUPPORTED)],
        hard_block_reason=None, now=NOW,
    )
    from app.models.reviews.claim_evidence_retrieval import build_evidence_set

    scope = build_evidence_set(
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id=REVIEW,
        purpose="audit", session_id="cers_" + "1" * 32,
        base_evidence_ids=[], added_evidence_ids=["ev-new"],
        snapshot_hashes={"ev-new": "d" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
    )
    supplement.save_evidence_set(scope)
    round_one = round_one_identity(supplement.list_supplements([RUN]))
    supplement.activate_session(
        session_id="cers_" + "1" * 32, scope=scope, round_one_hash=round_one,
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )

    _audit2, _claim2, supplement2, resources2 = harness.repositories()
    session = supplement2.get_session("cers_" + "1" * 32)
    assert session.active is True
    assert session.status is ClaimEvidenceRetrievalStatus.COMPLETED
    review = _audit2.get_review_by_resource(RESOURCE)
    assert (review.claim_total, review.claim_supported, review.claim_unsupported) == (1, 1, 0)
    # A completed round does not keep a temporary barrier; the version may be
    # published by the existing rules again.
    resources2.update_publication_decision(RESOURCE, publish=True)
    assert resources2.get(RESOURCE).publication_status == "published"
    # The activation replay is idempotent and keeps a single scope row.
    again = supplement2.activate_session(
        session_id="cers_" + "1" * 32, scope=scope, round_one_hash=round_one,
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )
    assert again.active is True
    assert len(supplement2.list_evidence_sets([RUN])) == 1


def test_activation_transaction_rolls_back_on_a_mid_transaction_conflict(harness):
    """A failing activation never leaves a half-applied session, scope or metric."""
    audit, _claim, supplement, resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="c" * 64, payload={"round": 1},
        supplements=[_supplement(ClaimVerdict.SUPPORTED)],
        hard_block_reason=None, now=NOW,
    )
    from app.models.reviews.claim_evidence_retrieval import build_evidence_set

    scope = build_evidence_set(
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id=REVIEW,
        purpose="audit", session_id="cers_" + "1" * 32,
        base_evidence_ids=[], added_evidence_ids=["ev-new"],
        snapshot_hashes={"ev-new": "d" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
    )
    # A different manifest already occupies the same deterministic scope id.
    conflicting = build_evidence_set(
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id=REVIEW,
        purpose="audit", session_id="cers_" + "1" * 32,
        base_evidence_ids=[], added_evidence_ids=["ev-new", "ev-other"],
        snapshot_hashes={"ev-new": "d" * 64, "ev-other": "e" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}, {"evidence_id": "ev-other", "order": 1}],
        created_at=NOW,
    )
    supplement.save_evidence_set(conflicting)
    before_review = audit.get_review_by_resource(RESOURCE)
    before_status = supplement.get_session("cers_" + "1" * 32).status

    with pytest.raises(PersistenceConflict):
        supplement.activate_session(
            session_id="cers_" + "1" * 32, scope=scope,
            round_one_hash=round_one_identity(supplement.list_supplements([RUN])),
            supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
        )

    _audit2, _claim2, supplement2, resources2 = harness.repositories()
    session = supplement2.get_session("cers_" + "1" * 32)
    assert session.active is False and session.status is before_status
    review = _audit2.get_review_by_resource(RESOURCE)
    assert (review.claim_total, review.claim_supported, review.claim_unsupported) == (
        before_review.claim_total, before_review.claim_supported, before_review.claim_unsupported)
    scopes = supplement2.list_evidence_sets([RUN])
    assert len(scopes) == 1 and scopes[0].manifest_hash == conflicting.manifest_hash
    with pytest.raises(PublicationBarrier):
        resources2.update_publication_decision(RESOURCE, publish=True)
