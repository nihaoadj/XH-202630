"""SQL/Memory equivalence for the Claim evidence retrieval side tables."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.audit.base import PersistenceConflict
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.claim.supplement import (
    MemoryClaimSupplementRepository,
    SQLClaimSupplementRepository,
    SupplementBudgetExceeded,
    SupplementSessionClosed,
)
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimReviewEvidenceSetV1,
    ClaimSupplementJudgementV1,
)
from app.models.reviews.claims import ClaimJudgementStatus, ClaimVerdict
from app.models.shared.persistence import (
    CreateRunCommand,
    PersistedEvidenceSnapshot,
    canonical_hash,
)
from tests.fakes.persistence import (
    create_command,
    memory_repository,
    sqlite_repository,
)

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)


def policy() -> ClaimEvidenceRetrievalPolicyV1:
    return ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_estimated_tokens=100_000,
    )


def _locator():
    from app.models.knowledge.knowledge import SourceLocator, SourceType

    return SourceLocator(
        knowledge_base_id="kb-001", document_id="doc-1", document_version="v1",
        chunk_id="chunk-1", source_type=SourceType.MARKDOWN,
        source_path="docs/a.md", title="a.md", section="1",
    )


def _snapshot(evidence_id: str, *, step_id: str = "step-1", rank: int = 1) -> PersistedEvidenceSnapshot:
    from app.core.retrieval.knowledge_ids import sha256_hex
    from app.models.knowledge.knowledge import EvidenceItem, ScoreKind

    excerpt = "excerpt"
    item = EvidenceItem(
        evidence_id=evidence_id,
        knowledge_base_id="kb-001",
        document_id="doc-1",
        document_version="v1",
        chunk_id="chunk-1",
        query="q",
        query_hash="1" * 64,
        query_rank=1,
        rank=rank,
        raw_score=0.9,
        score_kind=ScoreKind.SIMILARITY,
        normalized_score=0.8,
        excerpt=excerpt,
        excerpt_hash=sha256_hex(excerpt),
        locator=_locator(),
        config_hash="3" * 64,
        retrieved_at=NOW,
    )
    return PersistedEvidenceSnapshot.from_evidence(
        item, run_id="run-001", retrieval_step_id=step_id,
    )


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        audit = memory_repository()
        claim_repo = MemoryClaimRepository()
        audit.create_run(create_command())
        audit.start_run("run-001", occurred_at=NOW)
        audit.begin_step(_begin_step_command())
        # The activation rewrites the persisted review summary, exactly like the
        # SQL fixture's ResourceReviewORM row.
        audit.save_review(
            "res-1",
            {
                "resource_id": "res-1", "run_id": "run-001",
                "review_id": "rev-1", "review_ids": {"res-1": "rev-1"},
                "status": "approve", "claim_total": 1, "claim_supported": 0,
                "claim_unsupported": 1, "claim_hallucination_rate": 1.0,
                "claim_metric_status": "complete",
            },
            "run-001",
        )
        repository = MemoryClaimSupplementRepository(
            claim_repository=claim_repo, audit_repository=audit,
        )
        yield repository, audit, claim_repo
        return
    audit, engine = sqlite_repository(tmp_path)
    with audit.session_factory() as db:
        db.add(_run_orm())
        db.add(_step_orm())
        db.add(_resource_orm())
        db.add(_review_orm())
        db.commit()
    claim_repo = SQLClaimRepository(audit.session_factory)
    repository = SQLClaimSupplementRepository(
        claim_repository=claim_repo, audit_repository=audit,
        session_factory=audit.session_factory,
    )
    try:
        yield repository, audit, claim_repo
    finally:
        engine.dispose()


def _begin_step_command():
    from app.models.shared.persistence import BeginStepCommand

    return BeginStepCommand(
        run_id="run-001", step_id="step-1", step_sequence=1,
        node_name="claim_evidence_retrieve", agent_name="claim_evidence_retrieval",
        action="Claim 缺证补检", generation_attempt=1, started_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=600),
    )


def _run_orm():
    from app.db.shared.models import AgentRunORM

    return AgentRunORM(
        run_id="run-001", learner_id=None, knowledge_base_id="kb-001",
        topic="RAG", status="running",
    )


def _step_orm():
    from app.db.shared.models import AgentStepORM

    return AgentStepORM(
        step_id="step-1", run_id="run-001", step_no=1,
        agent_name="claim_evidence_retrieval", node_name="claim_evidence_retrieve",
        action="Claim 缺证补检", status="running",
    )


def _resource_orm():
    from app.db.shared.models import GeneratedResourceORM

    return GeneratedResourceORM(
        resource_id="res-1", run_id="run-001", learner_id="learner-001",
        topic="RAG", resource_type="讲义", difficulty="初级", storage_type="text",
    )


def _review_orm():
    from app.db.shared.models import ResourceReviewORM

    return ResourceReviewORM(
        review_id="rev-1", resource_id="res-1", run_id="run-001", status="approve",
    )


def _session(session_id: str = "cers_" + "1" * 32) -> ClaimEvidenceRetrievalSessionV1:
    return ClaimEvidenceRetrievalSessionV1(
        session_id=session_id,
        run_id="run-001", resource_id="res-1", resource_version=1, review_id="rev-1",
        content_hash="a" * 64, policy_hash=policy().policy_hash,
        base_evidence_set_hash="b" * 64, initial_judgement_hash="c" * 64,
        target_claim_ids=["clm_" + "1" * 32],
        created_at=NOW, updated_at=NOW,
    )


def _batch(session_id: str, *, kind: ClaimEvidenceBatchKind, ordinal: int = 0) -> ClaimEvidenceRetrievalBatchV1:
    input_hash = canonical_hash({"kind": kind.value, "ordinal": ordinal})
    from app.models.reviews.claim_evidence_retrieval import batch_id_for

    return ClaimEvidenceRetrievalBatchV1(
        batch_id=batch_id_for(
            session_id=session_id, kind=kind.value, ordinal=ordinal, input_hash=input_hash,
        ),
        session_id=session_id,
        kind=kind,
        ordinal=ordinal,
        input_hash=input_hash,
        expected_claim_ids=["clm_" + "1" * 32],
        created_at=NOW,
        updated_at=NOW,
    )


def _scope(session_id: str, evidence_id: str = "ev-new") -> ClaimReviewEvidenceSetV1:
    from app.models.reviews.claim_evidence_retrieval import build_evidence_set

    return build_evidence_set(
        run_id="run-001", resource_id="res-1", resource_version=1, review_id="rev-1",
        purpose="audit", session_id=session_id,
        base_evidence_ids=[], added_evidence_ids=[evidence_id],
        snapshot_hashes={evidence_id: "d" * 64},
        manifest=[{"evidence_id": evidence_id, "order": 0}],
        created_at=NOW,
    )


def _supplement(session_id: str, *, evidence_id: str = "ev-new") -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + "9" * 32,
        session_id=session_id,
        claim_id="clm_" + "1" * 32,
        run_id="run-001", resource_id="res-1", resource_version=1, review_id="rev-1",
        scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED,
        verdict=ClaimVerdict.SUPPORTED,
        evidence_ids=[evidence_id],
        reason="补证支持",
        judge_prompt_version="claim-evidence-rejudge-v1",
        confidence=0.8,
        payload_hash="e" * 64,
        created_at=NOW,
    )


def test_open_run_is_idempotent_and_policy_locked(storage):
    repository, _audit, _claim_repo = storage
    first = repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    second = repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )

    assert first.policy_hash == second.policy_hash
    assert second.revision == 0
    other = ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_queries=95,
    )
    with pytest.raises(PersistenceConflict):
        repository.open_run(
            run_id="run-001", policy=other, started_at=NOW,
            deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
        )


def test_attempt_reservation_is_idempotent_and_bounded(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    batch = _batch("cers_" + "1" * 32, kind=ClaimEvidenceBatchKind.QUERY)
    repository.save_batch(batch)
    ledger = repository.reserve_attempt(
        run_id="run-001", owner="owner", epoch=1, reserved_tokens=100,
        attempt_id="cera_" + "1" * 32, batch_id=batch.batch_id,
        logical_call_id="call-1", attempt_no=1, output_cap=50, now=NOW,
    )
    assert ledger.reserved_tokens == 100
    again = repository.reserve_attempt(
        run_id="run-001", owner="owner", epoch=1, reserved_tokens=100,
        attempt_id="cera_" + "1" * 32, batch_id=batch.batch_id,
        logical_call_id="call-1", attempt_no=1, output_cap=50, now=NOW,
    )
    assert again.attempts == 1

    settled = repository.settle_attempt(
        run_id="run-001", attempt_id="cera_" + "1" * 32, owner="owner", epoch=1,
        status=__import__(
            "app.models.reviews.claim_evidence_retrieval",
            fromlist=["ClaimEvidenceAttemptStatus"],
        ).ClaimEvidenceAttemptStatus.USAGE_UNKNOWN,
        known_tokens=None, now=NOW,
    )
    assert settled.reserved_tokens == 0
    assert settled.unknown_tokens == 100
    assert settled.known_tokens == 0


def test_dispatch_intent_and_not_sent_settlement_are_persisted(storage):
    """The send boundary is a durable state, not an in-memory flag."""
    repository, _audit, _claim_repo = storage
    from app.models.reviews.claim_evidence_retrieval import (
        ClaimEvidenceAttemptStatus,
        attempt_id_for,
    )

    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    repository.create_session(_session())
    batch = _batch("cers_" + "1" * 32, kind=ClaimEvidenceBatchKind.QUERY)
    repository.save_batch(batch)
    first = attempt_id_for(batch_id=batch.batch_id, logical_call_id="call-1", attempt_no=1)
    repository.reserve_attempt(
        run_id="run-001", owner="owner", epoch=1, reserved_tokens=100,
        attempt_id=first, batch_id=batch.batch_id, logical_call_id="call-1",
        attempt_no=1, output_cap=50, now=NOW,
    )
    repository.mark_dispatched(
        run_id="run-001", attempt_id=first, owner="owner", epoch=1, now=NOW,
    )
    assert repository.list_attempts("run-001")[-1].status is ClaimEvidenceAttemptStatus.DISPATCHING

    # A dispatched attempt that fails keeps the reserve as unknown usage.
    ledger = repository.settle_attempt(
        run_id="run-001", attempt_id=first, owner="owner", epoch=1,
        status=ClaimEvidenceAttemptStatus.FAILED, known_tokens=None, now=NOW,
    )
    assert (ledger.reserved_tokens, ledger.known_tokens, ledger.unknown_tokens) == (0, 0, 100)

    # The next physical attempt of the same logical call is still allowed.
    second = attempt_id_for(batch_id=batch.batch_id, logical_call_id="call-1", attempt_no=2)
    ledger = repository.reserve_attempt(
        run_id="run-001", owner="owner", epoch=1, reserved_tokens=40,
        attempt_id=second, batch_id=batch.batch_id, logical_call_id="call-1",
        attempt_no=2, output_cap=20, now=NOW,
    )
    assert ledger.reserved_tokens == 40
    ledger = repository.settle_attempt(
        run_id="run-001", attempt_id=second, owner="owner", epoch=1,
        status=ClaimEvidenceAttemptStatus.NOT_SENT, known_tokens=None, now=NOW,
    )
    # Only a definitively unsent attempt releases its token reservation.
    assert (ledger.reserved_tokens, ledger.known_tokens, ledger.unknown_tokens) == (0, 0, 100)
    assert ledger.attempts == 2
    attempts = {item.attempt_id: item for item in repository.list_attempts("run-001")}
    assert attempts[second].status is ClaimEvidenceAttemptStatus.NOT_SENT
    assert attempts[second].unknown_usage is False

    # A dispatched attempt can never be reclassified as not sent.
    third = attempt_id_for(batch_id=batch.batch_id, logical_call_id="call-1", attempt_no=3)
    repository.reserve_attempt(
        run_id="run-001", owner="owner", epoch=1, reserved_tokens=10,
        attempt_id=third, batch_id=batch.batch_id, logical_call_id="call-1",
        attempt_no=3, output_cap=5, now=NOW,
    )
    repository.mark_dispatched(
        run_id="run-001", attempt_id=third, owner="owner", epoch=1, now=NOW,
    )
    with pytest.raises(PersistenceConflict):
        repository.settle_attempt(
            run_id="run-001", attempt_id=third, owner="owner", epoch=1,
            status=ClaimEvidenceAttemptStatus.NOT_SENT, known_tokens=None, now=NOW,
        )


def test_session_uniqueness_and_terminal_immutability(storage):
    repository, _audit, _claim_repo = storage
    repository.create_session(_session())
    repository.create_session(_session())
    with pytest.raises(PersistenceConflict):
        repository.create_session(_session().model_copy(update={"session_id": "cers_" + "2" * 32}))

    closed = repository.update_session(
        "cers_" + "1" * 32,
        expected_status=ClaimEvidenceRetrievalStatus.PENDING,
        status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
        reason_code="no_new_evidence",
        now=NOW,
    )
    assert closed.completed_at is not None
    with pytest.raises(SupplementSessionClosed):
        repository.update_session(
            "cers_" + "1" * 32,
            expected_status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
            status=ClaimEvidenceRetrievalStatus.BLOCKED,
            now=NOW,
        )


def test_retrieval_batch_persists_snapshots_and_batch_atomically(storage):
    repository, audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = repository.create_session(_session())
    repository.update_session(
        session.session_id,
        expected_status=ClaimEvidenceRetrievalStatus.PENDING,
        status=ClaimEvidenceRetrievalStatus.QUERYING,
        now=NOW,
    )
    repository.update_session(
        session.session_id,
        expected_status=ClaimEvidenceRetrievalStatus.QUERYING,
        status=ClaimEvidenceRetrievalStatus.RETRIEVING,
        now=NOW,
    )
    batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.RETRIEVE)
    repository.save_batch(batch)
    repository.complete_retrieval_batch(
        batch_id=batch.batch_id, run_id="run-001", step_id="step-1",
        owner="owner", epoch=1, output_hash="f" * 64,
        payload={"selected_count": 1},
        evidence=[_snapshot("ev-new")],
        now=NOW,
    )
    stored = repository.get_batch(batch.batch_id)
    assert stored.status is ClaimEvidenceBatchStatus.COMPLETED
    assert [item.evidence_id for item in audit.list_evidence("run-001")] == ["ev-new"]

    # Replay is idempotent; a different payload conflicts.
    repository.complete_retrieval_batch(
        batch_id=batch.batch_id, run_id="run-001", step_id="step-1",
        owner="owner", epoch=1, output_hash="f" * 64,
        payload={"selected_count": 1}, evidence=[_snapshot("ev-new")], now=NOW,
    )
    with pytest.raises(PersistenceConflict):
        repository.complete_retrieval_batch(
            batch_id=batch.batch_id, run_id="run-001", step_id="step-1",
            owner="owner", epoch=1, output_hash="1" * 64,
            payload={"selected_count": 2}, evidence=[], now=NOW,
        )


def test_rejudge_batch_commits_hard_block_with_the_judgement(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = repository.create_session(_session())
    batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.REJUDGE)
    repository.save_batch(batch)
    retrieval_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.RETRIEVE)
    repository.save_batch(retrieval_batch)
    repository.complete_retrieval_batch(
        batch_id=retrieval_batch.batch_id,
        run_id="run-001", step_id="step-1", owner="owner", epoch=1,
        output_hash="a" * 64, payload={}, evidence=[_snapshot("ev-new")], now=NOW,
    )

    repository.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="b" * 64,
        payload={"hard_block": "contradicted"},
        supplements=[_supplement(session.session_id)],
        hard_block_reason="contradicted",
        now=NOW,
    )
    stored = repository.get_session(session.session_id)
    assert stored.hard_block is True
    assert stored.hard_block_reason == "contradicted"
    assert [item.claim_id for item in repository.list_supplements(["run-001"])] == ["clm_" + "1" * 32]


def _round_one(repository, run_id: str = "run-001") -> str:
    from app.models.reviews.claim_evidence_retrieval import round_one_identity

    return round_one_identity(repository.list_supplements([run_id]))


def test_activation_is_single_round_and_scope_is_idempotent(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = repository.create_session(_session())
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        repository.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    retrieval_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.RETRIEVE)
    repository.save_batch(retrieval_batch)
    repository.complete_retrieval_batch(
        batch_id=retrieval_batch.batch_id,
        run_id="run-001", step_id="step-1", owner="owner", epoch=1,
        output_hash="a" * 64, payload={}, evidence=[_snapshot("ev-new")], now=NOW,
    )
    rejudge_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.REJUDGE)
    repository.save_batch(rejudge_batch)
    repository.save_rejudge_batch(
        batch_id=rejudge_batch.batch_id,
        output_hash="b" * 64, payload={}, supplements=[_supplement(session.session_id)],
        hard_block_reason=None, now=NOW,
    )

    # The production node persists the audit scope before activating it; the
    # activation must reuse that row instead of inserting the same identity.
    scope = _scope(session.session_id)
    repository.save_evidence_set(scope)
    round_one = _round_one(repository)
    active = repository.activate_session(
        session_id=session.session_id, scope=scope, round_one_hash=round_one,
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )
    assert active.active is True
    assert active.status is ClaimEvidenceRetrievalStatus.COMPLETED
    assert len(repository.list_evidence_sets(["run-001"])) == 1

    again = repository.activate_session(
        session_id=session.session_id, scope=scope, round_one_hash=round_one,
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )
    assert again.session_id == active.session_id
    assert len(repository.list_evidence_sets(["run-001"])) == 1


def test_activation_rejects_a_different_scope_for_the_same_binding(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = repository.create_session(_session())
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        repository.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    retrieval_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.RETRIEVE)
    repository.save_batch(retrieval_batch)
    repository.complete_retrieval_batch(
        batch_id=retrieval_batch.batch_id,
        run_id="run-001", step_id="step-1", owner="owner", epoch=1,
        output_hash="a" * 64, payload={}, evidence=[_snapshot("ev-new")], now=NOW,
    )
    rejudge_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.REJUDGE)
    repository.save_batch(rejudge_batch)
    repository.save_rejudge_batch(
        batch_id=rejudge_batch.batch_id,
        output_hash="b" * 64, payload={}, supplements=[_supplement(session.session_id)],
        hard_block_reason=None, now=NOW,
    )
    scope = _scope(session.session_id)
    repository.save_evidence_set(scope)
    other = _scope(session.session_id, evidence_id="ev-other")
    assert other.scope_id != scope.scope_id
    with pytest.raises(PersistenceConflict):
        repository.save_evidence_set(other)
    with pytest.raises(PersistenceConflict):
        repository.activate_session(
            session_id=session.session_id, scope=other,
            round_one_hash=_round_one(repository),
            supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
        )
    assert repository.get_session(session.session_id).active is False


def test_activation_rejects_a_metric_set_that_differs_from_the_persisted_round(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    session = repository.create_session(_session())
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        repository.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    retrieval_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.RETRIEVE)
    repository.save_batch(retrieval_batch)
    repository.complete_retrieval_batch(
        batch_id=retrieval_batch.batch_id,
        run_id="run-001", step_id="step-1", owner="owner", epoch=1,
        output_hash="a" * 64, payload={}, evidence=[_snapshot("ev-new")], now=NOW,
    )
    rejudge_batch = _batch(session.session_id, kind=ClaimEvidenceBatchKind.REJUDGE)
    repository.save_batch(rejudge_batch)
    repository.save_rejudge_batch(
        batch_id=rejudge_batch.batch_id,
        output_hash="b" * 64, payload={}, supplements=[_supplement(session.session_id)],
        hard_block_reason=None, now=NOW,
    )
    with pytest.raises(PersistenceConflict):
        repository.activate_session(
            session_id=session.session_id, scope=_scope(session.session_id),
            round_one_hash="0" * 64,
            supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
        )
    assert repository.get_session(session.session_id).active is False
    assert repository.list_evidence_sets(["run-001"]) == []


def test_query_budget_is_enforced_by_the_ledger(storage):
    repository, _audit, _claim_repo = storage
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    repository.record_query_count(run_id="run-001", count=90)
    with pytest.raises(SupplementBudgetExceeded):
        repository.record_query_count(run_id="run-001", count=10)
