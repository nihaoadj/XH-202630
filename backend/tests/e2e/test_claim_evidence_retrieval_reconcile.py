"""The real reconciliation entry turns an in-flight supplement session into a
durable interruption, without resending any request.

A fresh SQLite engine and a fresh set of repositories are built over the same
file, then ``GenerationReconciler.run_once`` (the startup/worker reconcile path)
is executed exactly as production does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.claim.publication import INTERRUPTED_REASON, PublicationBarrier
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceAttemptStatus,
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalStatus,
    attempt_id_for,
)

from tests.e2e.test_claim_evidence_retrieval_recovery import (
    NOW,
    RESOURCE,
    RUN,
    _Harness,
    _batch,
    _seed_retrieval,
)


@pytest.fixture()
def harness(tmp_path):
    item = _Harness(tmp_path / "t50_reconcile.db")
    item.bootstrap()
    try:
        yield item
    finally:
        item.close()


def _bootstrap_job(harness, *, lease_expired=True):
    from app.db.shared.models import (
        AgentRunORM,
        GenerationJobORM,
        LearnerProfileORM,
        UserProfileORM,
    )

    now = datetime.now(timezone.utc)
    lease = now - timedelta(seconds=30) if lease_expired else now + timedelta(seconds=600)
    with harness.factory() as db:
        db.add(UserProfileORM(user_id="owner-1", display_name="synthetic", identity="test",
                              education="本科", major="软件"))
        db.add(LearnerProfileORM(learner_id="learner-001", user_id="owner-1", learner_type="test",
                                 education="本科", major="软件", learning_goal="test"))
        db.commit()
        db.add(GenerationJobORM(
            run_id=RUN, batch_id="batch-1", learner_id="learner-001",
            knowledge_base_id="kb-001", topic="RAG", status="running",
            request_payload={}, dispatch_mode="worker", claim_owner="worker-1",
            claim_count=1, lease_expires_at=lease,
        ))
        run = db.get(AgentRunORM, RUN)
        run.status = "running"
        run.execution_status = "running"
        run.lease_expires_at = lease
        db.commit()
    return lease


def _inflight_attempt(harness):
    _audit, _claim, supplement, _resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.QUERY)
    supplement.save_batch(batch)
    attempt_id = attempt_id_for(
        batch_id=batch.batch_id, logical_call_id=f"{batch.batch_id}:query", attempt_no=1)
    supplement.reserve_attempt(
        run_id=RUN, owner="owner", epoch=1, reserved_tokens=120,
        attempt_id=attempt_id, batch_id=batch.batch_id,
        logical_call_id=f"{batch.batch_id}:query", attempt_no=1,
        output_cap=50, now=NOW,
    )
    # The process died after committing the send boundary.
    supplement.mark_dispatched(run_id=RUN, attempt_id=attempt_id, owner="owner", epoch=1, now=NOW)
    return supplement, batch.batch_id, attempt_id


def test_reconciler_interrupts_the_inflight_round_and_keeps_the_version_blocked(harness):
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.reconciliation import GenerationReconciler

    _bootstrap_job(harness)
    _supplement, batch_id, attempt_id = _inflight_attempt(harness)

    # A restarted process: fresh engine, fresh repositories.
    audit, _claim, supplement, resources = harness.repositories()
    jobs = SQLGenerationJobRepository(harness.factory)
    reconciler = GenerationReconciler(
        jobs, SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
        supplement_repository=supplement,
    )
    result = reconciler.run_once()

    assert RUN in result["failed_run_ids"]
    assert result["claim_evidence_interrupted"] == 1
    assert audit.get_run(RUN).status.value == "interrupted"
    session = supplement.get_session("cers_" + "1" * 32)
    assert session.status is ClaimEvidenceRetrievalStatus.INTERRUPTED
    assert session.reason_code == "run_interrupted"
    assert session.active is False
    attempt = supplement.list_attempts(RUN)[0]
    assert attempt.attempt_id == attempt_id
    assert attempt.status is ClaimEvidenceAttemptStatus.USAGE_UNKNOWN
    assert attempt.unknown_usage is True
    ledger = supplement.get_run(RUN)
    # The dispatched send keeps its reservation as unknown usage, never zero.
    assert ledger.reserved_tokens == 0
    assert ledger.unknown_tokens == 120
    assert ledger.known_tokens == 0
    assert supplement.get_batch(batch_id).status is ClaimEvidenceBatchStatus.INTERRUPTED
    # The version stays unpublished and the user cannot confirm it.
    with pytest.raises(PublicationBarrier) as caught:
        resources.update_publication_decision(RESOURCE, publish=True)
    assert caught.value.reason_code == INTERRUPTED_REASON

    # The same recovery pass is idempotent and sends nothing.
    again = reconciler.run_once()
    assert again.get("claim_evidence_interrupted", 0) == 0
    assert supplement.get_run(RUN).unknown_tokens == 120


def test_reconciler_releases_only_the_pre_dispatch_reservation(harness):
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.reconciliation import GenerationReconciler

    _bootstrap_job(harness)
    _audit, _claim, supplement, _resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.QUERY)
    supplement.save_batch(batch)
    attempt_id = attempt_id_for(
        batch_id=batch.batch_id, logical_call_id="call-1", attempt_no=1)
    supplement.reserve_attempt(
        run_id=RUN, owner="owner", epoch=1, reserved_tokens=90,
        attempt_id=attempt_id, batch_id=batch.batch_id,
        logical_call_id="call-1", attempt_no=1, output_cap=40, now=NOW,
    )
    # No dispatch intent: this reservation is provably unsent.

    _audit2, _claim2, supplement2, _resources2 = harness.repositories()
    reconciler = GenerationReconciler(
        SQLGenerationJobRepository(harness.factory),
        SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
        supplement_repository=supplement2,
    )
    reconciler.run_once()

    attempt = supplement2.list_attempts(RUN)[0]
    assert attempt.status is ClaimEvidenceAttemptStatus.NOT_SENT
    assert attempt.unknown_usage is False
    ledger = supplement2.get_run(RUN)
    assert (ledger.reserved_tokens, ledger.known_tokens, ledger.unknown_tokens) == (0, 0, 0)
    assert supplement2.get_session("cers_" + "1" * 32).status is (
        ClaimEvidenceRetrievalStatus.INTERRUPTED
    )


def test_a_completed_round_is_never_rewritten_by_reconciliation(harness):
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.reconciliation import GenerationReconciler

    _bootstrap_job(harness)
    _audit, _claim, supplement, _resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    from tests.e2e.test_claim_evidence_retrieval_recovery import _supplement as supplement_row
    from app.models.reviews.claims import ClaimVerdict

    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="c" * 64, payload={"round": 1},
        supplements=[supplement_row(ClaimVerdict.SUPPORTED)],
        hard_block_reason=None, now=NOW,
    )
    from app.models.reviews.claim_evidence_retrieval import build_evidence_set, round_one_identity

    scope = build_evidence_set(
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id="rev-recovery",
        purpose="audit", session_id="cers_" + "1" * 32,
        base_evidence_ids=[], added_evidence_ids=["ev-new"],
        snapshot_hashes={"ev-new": "d" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
    )
    supplement.save_evidence_set(scope)
    supplement.activate_session(
        session_id="cers_" + "1" * 32, scope=scope,
        round_one_hash=round_one_identity(supplement.list_supplements([RUN])),
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )

    reconciler = GenerationReconciler(
        SQLGenerationJobRepository(harness.factory),
        SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
        supplement_repository=supplement,
    )
    result = reconciler.run_once()
    assert result.get("claim_evidence_interrupted", 0) == 0
    session = supplement.get_session("cers_" + "1" * 32)
    assert session.status is ClaimEvidenceRetrievalStatus.COMPLETED and session.active is True


def test_all_batches_succeeded_before_activation_cannot_be_activated_later(harness):
    """A crash before activation leaves an inactive round, not a half-active one."""
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.reconciliation import GenerationReconciler
    from app.models.reviews.claims import ClaimVerdict
    from app.models.reviews.claim_evidence_retrieval import build_evidence_set, round_one_identity
    from tests.e2e.test_claim_evidence_retrieval_recovery import _supplement as supplement_row

    _bootstrap_job(harness)
    audit, _claim, supplement, resources = harness.repositories()
    _seed_retrieval(supplement)
    batch = _batch(ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="c" * 64, payload={"round": 1},
        supplements=[supplement_row(ClaimVerdict.SUPPORTED)],
        hard_block_reason=None, now=NOW,
    )
    before = audit.get_review_by_resource(RESOURCE)

    reconciler = GenerationReconciler(
        SQLGenerationJobRepository(harness.factory),
        SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
        supplement_repository=supplement,
    )
    assert reconciler.run_once()["claim_evidence_interrupted"] == 1
    audit2, _claim2, supplement2, resources2 = harness.repositories()
    session = supplement2.get_session("cers_" + "1" * 32)
    assert session.status is ClaimEvidenceRetrievalStatus.INTERRUPTED and session.active is False
    after = audit2.get_review_by_resource(RESOURCE)
    assert (after.claim_total, after.claim_supported, after.claim_unsupported) == (
        before.claim_total, before.claim_supported, before.claim_unsupported)
    # A late activation cannot resurrect an interrupted round.
    scope = build_evidence_set(
        run_id=RUN, resource_id=RESOURCE, resource_version=1, review_id="rev-recovery",
        purpose="audit", session_id="cers_" + "1" * 32,
        base_evidence_ids=[], added_evidence_ids=["ev-new"],
        snapshot_hashes={"ev-new": "d" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
    )
    from app.db.audit.base import PersistenceConflict

    with pytest.raises(PersistenceConflict):
        supplement2.activate_session(
            session_id="cers_" + "1" * 32, scope=scope,
            round_one_hash=round_one_identity(supplement2.list_supplements([RUN])),
            supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
        )
    assert supplement2.get_session("cers_" + "1" * 32).active is False
    with pytest.raises(PublicationBarrier):
        resources2.update_publication_decision(RESOURCE, publish=True)
