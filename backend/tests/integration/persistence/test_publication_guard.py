"""F03: one durable publication guard shared by every release path."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.db.claim.publication import (
    HARD_BLOCK_REASON,
    IN_FLIGHT_REASON,
    INTERRUPTED_REASON,
    PublicationBarrier,
    bind_memory_publication_guard,
    publication_barrier_reason,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceBatchKind,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
    batch_id_for,
)
from app.models.reviews.claims import ClaimJudgementStatus, ClaimVerdict
from app.models.shared.persistence import (
    BeginStepCommand,
    CreateRunCommand,
    PersistedEvidenceSnapshot,
    canonical_hash,
)

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)


def policy() -> ClaimEvidenceRetrievalPolicyV1:
    return ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_estimated_tokens=100_000,
    )


def _resource(*, version: int = 1, status: str = "unpublished", parent: str | None = None) -> LearningResource:
    return LearningResource(
        resource_id=f"res-v{version}", run_id="run-001", learner_id="learner-001",
        topic="RAG", resource_type="讲义", difficulty="初级", storage_type="text",
        content_text="正文", knowledge_points=[], source_refs=[], version=version,
        parent_resource_id=parent, publication_status=status,
        claim_metric_status="complete", claim_factual_pass_rate=1.0,
        claim_publish_decision_pending=True, review_id=f"rev-v{version}",
    )


def _session(
    *, version: int = 1, status: ClaimEvidenceRetrievalStatus = ClaimEvidenceRetrievalStatus.REJUDGING,
) -> ClaimEvidenceRetrievalSessionV1:
    session_id = "cers_" + f"{version:032x}"
    return ClaimEvidenceRetrievalSessionV1(
        session_id=session_id,
        run_id="run-001", resource_id=f"res-v{version}", resource_version=version,
        review_id=f"rev-v{version}",
        content_hash="a" * 64, policy_hash=policy().policy_hash,
        base_evidence_set_hash="b" * 64, initial_judgement_hash="c" * 64,
        target_claim_ids=["clm_" + "1" * 32],
        status=status, created_at=NOW, updated_at=NOW,
        completed_at=NOW if status in {
            ClaimEvidenceRetrievalStatus.INTERRUPTED,
            ClaimEvidenceRetrievalStatus.BLOCKED,
            ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
        } else None,
    )


def _batch(session_id: str, kind: ClaimEvidenceBatchKind) -> ClaimEvidenceRetrievalBatchV1:
    input_hash = canonical_hash({"kind": kind.value})
    return ClaimEvidenceRetrievalBatchV1(
        batch_id=batch_id_for(
            session_id=session_id, kind=kind.value, ordinal=0, input_hash=input_hash,
        ),
        session_id=session_id, kind=kind, ordinal=0, input_hash=input_hash,
        expected_claim_ids=["clm_" + "1" * 32], created_at=NOW, updated_at=NOW,
    )


def _supplement(session: ClaimEvidenceRetrievalSessionV1, verdict: ClaimVerdict) -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + "9" * 32, session_id=session.session_id,
        claim_id="clm_" + "1" * 32, run_id=session.run_id,
        resource_id=session.resource_id, resource_version=session.resource_version,
        review_id=session.review_id, scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-new"], reason="round1",
        judge_prompt_version="claim-evidence-rejudge-v1", confidence=0.8,
        payload_hash="e" * 64, created_at=NOW,
    )


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    from app.db.claim.memory import MemoryClaimRepository
    from app.db.claim.sql_repository import SQLClaimRepository
    from app.db.claim.supplement import (
        MemoryClaimSupplementRepository,
        SQLClaimSupplementRepository,
    )
    from app.db.audit.memory import MemoryAuditRepository
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.learning_documents.sql_repository import SQLResourceRepository
    from app.db.shared.models import (
        AgentRunORM,
        AgentStepORM,
        Base,
        GeneratedResourceORM,
        ResourceClaimORM,
        ResourceReviewORM,
    )
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    if request.param == "memory":
        audit = MemoryAuditRepository()
        claim_repo = MemoryClaimRepository()
        resource_repo = MemoryResourceRepository()
        supplement = MemoryClaimSupplementRepository(
            claim_repository=claim_repo, audit_repository=audit,
        )
        bind_memory_publication_guard(resource_repo, supplement)
        audit.create_run(CreateRunCommand(
            run_id="run-001", learner_id="learner-001", knowledge_base_id="kb-001",
            topic="RAG", request_snapshot={"topic": "RAG"},
            request_hash=canonical_hash({"topic": "RAG"}), occurred_at=NOW,
        ))
        audit.start_run("run-001", occurred_at=NOW)
        audit.begin_step(BeginStepCommand(
            run_id="run-001", step_id=STEP_ID, step_sequence=1,
            node_name="claim_evidence_retrieve",
            agent_name="claim_evidence_retrieval",
            action="Claim 缺证补检", generation_attempt=1, started_at=NOW,
            lease_expires_at=NOW + timedelta(seconds=600),
        ))
        audit.append_step_evidence(
            run_id="run-001", step_id=STEP_ID, evidence=[_snapshot()], now=NOW,
        )
        resource_repo.save(_resource(), "learner-001", "RAG")
        yield resource_repo, supplement, None
        return

    engine = create_engine(f"sqlite:///{tmp_path / 't50_publication.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(AgentRunORM(
            run_id="run-001", learner_id="learner-001", knowledge_base_id="kb-001",
            topic="RAG", status="running",
        ))
        db.add(GeneratedResourceORM(
            resource_id="res-v1", run_id="run-001", learner_id="learner-001",
            topic="RAG", resource_type="讲义", difficulty="初级", storage_type="text",
            version=1, review_id="rev-v1", publication_status="unpublished",
        ))
        db.add(ResourceReviewORM(
            review_id="rev-v1", resource_id="res-v1", run_id="run-001", status="approve",
        ))
        db.add(ResourceClaimORM(
            claim_id="clm_" + "1" * 32, review_id="rev-v1", resource_id="res-v1",
            claim_text="claim", supported=False,
        ))
        db.add(AgentStepORM(
            step_id=STEP_ID, run_id="run-001", step_no=1,
            agent_name="claim_evidence_retrieval",
            node_name="claim_evidence_retrieve",
            action="Claim 缺证补检", status="running",
        ))
        db.commit()
    from app.db.audit.sql_repository import SQLAuditRepository

    audit = SQLAuditRepository(factory)
    audit.append_step_evidence(
        run_id="run-001", step_id=STEP_ID, evidence=[_snapshot()], now=NOW,
    )
    claim_repo = SQLClaimRepository(factory)
    supplement = SQLClaimSupplementRepository(
        claim_repository=claim_repo, audit_repository=audit, session_factory=factory,
    )
    resource_repo = SQLResourceRepository(factory)
    try:
        yield resource_repo, supplement, factory
    finally:
        engine.dispose()


def _open(repository) -> None:
    repository.open_run(
        run_id="run-001", policy=policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )


def _publish_resource(resource_repo, resource: LearningResource) -> None:
    resource_repo.update_publication_decision(resource.resource_id, publish=True)


def _legacy_publish(resource_repo, factory, *, publication: str = "published") -> None:
    """Simulate a version published before the durable guard existed."""

    if factory is None:
        guard = resource_repo.publication_guard
        resource_repo.publication_guard = None
        try:
            resource_repo.update_publication_decision("res-v1", publish=True)
        finally:
            resource_repo.publication_guard = guard
        return
    from app.db.shared.models import GeneratedResourceORM

    with factory() as db:
        row = db.get(GeneratedResourceORM, "res-v1")
        row.publication_status = publication
        db.commit()


STEP_ID = "step-1"


def _snapshot() -> PersistedEvidenceSnapshot:
    from app.core.retrieval.knowledge_ids import sha256_hex
    from app.models.knowledge.knowledge import (
        EvidenceItem,
        ScoreKind,
        SourceLocator,
        SourceType,
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
        item, run_id="run-001", retrieval_step_id=STEP_ID,
    )


def test_barrier_reason_precedence():
    assert publication_barrier_reason(
        status=ClaimEvidenceRetrievalStatus.REJUDGING, hard_block=False,
    ) == IN_FLIGHT_REASON
    assert publication_barrier_reason(
        status=ClaimEvidenceRetrievalStatus.INTERRUPTED, hard_block=False,
    ) == INTERRUPTED_REASON
    assert publication_barrier_reason(
        status=ClaimEvidenceRetrievalStatus.BLOCKED, hard_block=True,
    ) == HARD_BLOCK_REASON
    assert publication_barrier_reason(
        status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE, hard_block=False,
    ) is None
    assert publication_barrier_reason(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, hard_block=False,
    ) is None


def test_creating_pending_session_revokes_prior_publication(storage):
    resources, supplement, _ = storage
    _open(supplement)
    resources.update_publication_decision("res-v1", publish=True)
    supplement.create_session(_session(status=ClaimEvidenceRetrievalStatus.PENDING))
    assert resources.get("res-v1").publication_status == "unpublished"


def test_initial_published_save_uses_the_publication_guard(storage):
    resources, _, _ = storage
    resources.publication_guard = lambda *args, **kwargs: IN_FLIGHT_REASON
    child = _resource(version=2, parent="res-v1", status="published")
    with pytest.raises(PublicationBarrier):
        resources.save(child, "learner-001", "RAG")
    assert resources.get(child.resource_id) is None


def test_session_creation_serializes_with_in_progress_publication(storage):
    resources, supplement, _ = storage
    _open(supplement)
    checked, release, creating = threading.Event(), threading.Event(), threading.Event()
    original = resources.publication_guard
    errors = []

    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        checked.set()
        assert release.wait(10)
        return result

    resources.publication_guard = paused

    def publish():
        try:
            resources.update_publication_decision("res-v1", publish=True)
        except Exception as exc:
            errors.append(exc)

    def create():
        creating.set()
        try:
            supplement.create_session(_session(status=ClaimEvidenceRetrievalStatus.PENDING))
        except Exception as exc:
            errors.append(exc)

    publisher = threading.Thread(target=publish)
    creator = threading.Thread(target=create)
    publisher.start()
    try:
        assert checked.wait(10)
        creator.start()
        assert creating.wait(10)
    finally:
        release.set()
        publisher.join(15)
        if creator.ident:
            creator.join(15)
    assert not publisher.is_alive() and not creator.is_alive()
    assert not errors
    assert supplement.get_session(_session().session_id).status is ClaimEvidenceRetrievalStatus.PENDING
    assert resources.get("res-v1").publication_status == "unpublished"


@pytest.mark.parametrize("mismatch", ["owner", "expired", "run"])
@pytest.mark.parametrize("operation", ["create", "rejudge", "activate"])
def test_execution_context_cannot_commit_supplement_after_lease_loss(storage, mismatch, operation):
    from app.core.execution import ExecutionFence, execution_fence
    from app.db.generation.fencing import ExecutionLeaseLost
    from app.db.shared.models import AgentRunORM

    _, supplement, factory = storage
    _open(supplement)
    session = _session(status=ClaimEvidenceRetrievalStatus.PENDING)
    batch = _batch(session.session_id, ClaimEvidenceBatchKind.REJUDGE)
    if operation != "create":
        supplement.create_session(session)
        supplement.save_batch(batch)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    if factory is None:
        run = supplement.audit_repository.runs["run-001"]
        run.update(owner_instance_id="current", lease_expires_at=deadline)
        if mismatch == "expired":
            run["lease_expires_at"] = deadline - timedelta(minutes=10)
    else:
        with factory() as db:
            run = db.get(AgentRunORM, "run-001")
            run.owner_instance_id = "current"
            run.lease_expires_at = deadline if mismatch != "expired" else deadline - timedelta(minutes=10)
            db.commit()
    with execution_fence(ExecutionFence(
        "foreign-run" if mismatch == "run" else "run-001",
        "stale" if mismatch == "owner" else "current",
    )):
        with pytest.raises(ExecutionLeaseLost):
            if operation == "create":
                supplement.create_session(session)
            elif operation == "rejudge":
                supplement.save_rejudge_batch(
                    batch_id=batch.batch_id, output_hash="d" * 64, payload={},
                    supplements=[], hard_block_reason=None, now=NOW,
                )
            else:
                supplement.activate_session(
                    session_id=session.session_id, scope=None, round_one_hash="d" * 64,
                    supported=0, contradicted=0, absent=0, factual=0, claim_total=0, now=NOW,
                )
    stored = supplement.get_session(session.session_id)
    if operation == "create":
        assert stored is None
    else:
        assert stored.status is ClaimEvidenceRetrievalStatus.PENDING and not stored.active
        assert supplement.get_batch(batch.batch_id).output_hash is None


@pytest.mark.parametrize("status,reason", [
    (ClaimEvidenceRetrievalStatus.REJUDGING, IN_FLIGHT_REASON),
    (ClaimEvidenceRetrievalStatus.INTERRUPTED, INTERRUPTED_REASON),
])
def test_in_flight_and_interrupted_rounds_block_the_user_publish(storage, status, reason):
    resource_repo, supplement, _factory = storage
    _open(supplement)
    supplement.create_session(_session(status=status))

    with pytest.raises(PublicationBarrier) as caught:
        _publish_resource(resource_repo, _resource())
    assert caught.value.reason_code == reason
    assert resource_repo.get("res-v1").publication_status == "unpublished"


def test_counter_evidence_withdraws_an_already_published_version(storage):
    resource_repo, supplement, _factory = storage
    _open(supplement)
    session = supplement.create_session(
        _session(status=ClaimEvidenceRetrievalStatus.PENDING)
    )
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        supplement.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    # The version was published before any round-1 result existed (a legacy
    # write, or another process that predates the barrier).
    _legacy_publish(resource_repo, _factory)
    assert resource_repo.get("res-v1").publication_status == "published"

    batch = _batch(session.session_id, ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="b" * 64,
        payload={"hard_block": "contradicted"},
        supplements=[_supplement(session, ClaimVerdict.CONTRADICTED)],
        hard_block_reason="contradicted", now=NOW,
    )

    stored = resource_repo.get("res-v1")
    # Version-level safety stamp committed together with the block.
    assert stored.publication_status == "unpublished"
    assert stored.published_at is None
    assert stored.claim_publish_decision_pending is False
    assert stored.claim_publish_decision is None
    with pytest.raises(PublicationBarrier) as caught:
        _publish_resource(resource_repo, _resource())
    assert caught.value.reason_code == HARD_BLOCK_REASON


def test_a_child_version_cannot_clear_the_parent_block(storage):
    resource_repo, supplement, factory = storage
    _open(supplement)
    session = supplement.create_session(
        _session(status=ClaimEvidenceRetrievalStatus.PENDING)
    )
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        supplement.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    batch = _batch(session.session_id, ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    supplement.save_rejudge_batch(
        batch_id=batch.batch_id, output_hash="c" * 64,
        payload={"hard_block": "evidence_conflict"},
        supplements=[_supplement(session, ClaimVerdict.CONTRADICTED)],
        hard_block_reason="evidence_conflict", now=NOW,
    )

    child = _resource(version=2, parent="res-v1").model_copy(
        update={"resource_id": "res-v2", "review_id": "rev-v2"},
    )
    resource_repo.save(child, "learner-001", "RAG")
    _publish_resource(resource_repo, child)

    assert resource_repo.get("res-v2").publication_status == "published"
    # The parent version keeps its own permanent block.
    with pytest.raises(PublicationBarrier):
        _publish_resource(resource_repo, _resource())
    assert resource_repo.get("res-v1").publication_status == "unpublished"
    assert supplement.get_session(session.session_id).hard_block is True


def test_concurrent_publish_and_block_never_end_published_with_a_block(storage):
    resource_repo, supplement, factory = storage
    if factory is not None:
        pytest.skip("the concurrent CAS check runs on the memory transaction")
    _open(supplement)
    session = supplement.create_session(
        _session(status=ClaimEvidenceRetrievalStatus.PENDING)
    )
    for expected, target in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        supplement.update_session(
            session.session_id, expected_status=expected, status=target, now=NOW,
        )
    batch = _batch(session.session_id, ClaimEvidenceBatchKind.REJUDGE)
    supplement.save_batch(batch)
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def publish():
        barrier.wait()
        try:
            _publish_resource(resource_repo, _resource())
        except PublicationBarrier as exc:  # expected when the block wins
            errors.append(exc)

    def block():
        barrier.wait()
        supplement.save_rejudge_batch(
            batch_id=batch.batch_id, output_hash="d" * 64,
            payload={"hard_block": "contradicted"},
            supplements=[_supplement(session, ClaimVerdict.CONTRADICTED)],
            hard_block_reason="contradicted", now=NOW,
        )

    first = threading.Thread(target=publish)
    second = threading.Thread(target=block)
    first.start()
    second.start()
    first.join()
    second.join()

    stored = resource_repo.get("res-v1")
    assert stored.publication_status == "unpublished"
    assert supplement.get_session(session.session_id).hard_block is True
    assert all(isinstance(item, PublicationBarrier) for item in errors)


def test_replay_of_a_publication_event_uses_the_same_guard(storage):
    """A replay path re-reads the guard instead of trusting its own payload."""

    from app.services.learning_documents.publication import (
        ResourcePublicationConflict,
        decide_claim_publication,
    )
    from app.config import get_settings

    resource_repo, supplement, _factory = storage
    _open(supplement)
    supplement.create_session(_session(status=ClaimEvidenceRetrievalStatus.INTERRUPTED))

    service = _Service(resource_repo)
    with pytest.raises(ResourcePublicationConflict):
        decide_claim_publication(
            service, _resource(status="published"),
            resource_id="res-v1", publish=True,
            settings_factory=get_settings,
            run_query_factory=_ClaimsStub,
            audit_factory=_AuditStub,
        )


class _Service:
    def __init__(self, repository):
        self.repository = repository

    def update_publication_decision(self, resource_id: str, *, publish: bool):
        return self.repository.update_publication_decision(resource_id, publish=publish)


class _ClaimsStub:
    def __init__(self):
        from app.models.reviews.claims import ClaimMetricStatus, ClaimMetricSummary

        self.resource_metrics = {
            "res-v1": ClaimMetricSummary(
                metric_status=ClaimMetricStatus.COMPLETE, claim_total=1,
                factual_claim_total=1, supported_claim_total=1,
                contradicted_claim_total=0, not_in_evidence_claim_total=0,
                non_factual_claim_total=0, incomplete_claim_total=0,
            )
        }

    def get_claims(self, run_id: str):
        return self


class _AuditStub:
    def append_event(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("a blocked publication must not append an event")

    def list_events(self, *args, **kwargs):
        return []
