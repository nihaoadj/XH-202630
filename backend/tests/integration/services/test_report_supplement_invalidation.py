"""Report cache/ETag and quality facts follow supplement activation (H07).

Real file SQLite with the real watermark triggers: the report is read through
the actual ``ReportService``, the supplement facts are written through the real
supplement repositories, and every invalidation is measured on the persisted
watermark epoch — not on a mocked cache.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.scripts.report_benchmark import LEARNER, NOW as BENCH_NOW, make_service, seed_database
from app.config import get_settings
from app.db.audit.memory import MemoryAuditRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.publication import HARD_BLOCK_REASON, PublicationBarrier
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.claim.supplement import (
    MemoryClaimSupplementRepository,
    PersistenceConflict,
    SQLClaimSupplementRepository,
)
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import (
    AgentRunORM,
    AgentStepORM,
    ClaimJudgementORM,
    GeneratedResourceORM,
    ResourceClaimORM,
    ResourceReviewORM,
)
from app.api.reports import report as report_routes
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceBatchKind,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
    batch_id_for,
    build_evidence_set,
    round_one_identity,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimJudgeType,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.shared.persistence import CreateRunCommand, PersistedEvidenceSnapshot, canonical_hash
from app.services.learners.profiles import ProfileService
from app.services.reviews.quality_query import ResourceQualityQueryService
from app.services.runs.queries import RunQueryService

RUN = "run-h07"
STEP = "step-h07"
RES = "res-h07-a"
RES_BLOCKED = "res-h07-b"
REV = "rev-h07-a"
REV_BLOCKED = "rev-h07-b"
CLAIM_SUPPORTED = "clm_" + "a" * 32
CLAIM_GAP = "clm_" + "b" * 32
CLAIM_COUNTER = "clm_" + "c" * 32
SESSION_A = "cers_" + "a" * 32
SESSION_B = "cers_" + "b" * 32
NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)


def _policy() -> ClaimEvidenceRetrievalPolicyV1:
    return ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_estimated_tokens=100_000,
    )


def _session(session_id: str, resource_id: str, review_id: str, target: str) -> ClaimEvidenceRetrievalSessionV1:
    return ClaimEvidenceRetrievalSessionV1(
        session_id=session_id,
        run_id=RUN, resource_id=resource_id, resource_version=1, review_id=review_id,
        content_hash="a" * 64, policy_hash=_policy().policy_hash,
        base_evidence_set_hash="b" * 64, initial_judgement_hash="c" * 64,
        target_claim_ids=[target], created_at=NOW, updated_at=NOW,
    )


def _batch(session_id: str, kind: ClaimEvidenceBatchKind, ordinal: int = 0) -> ClaimEvidenceRetrievalBatchV1:
    input_hash = canonical_hash({"kind": kind.value, "ordinal": ordinal})
    return ClaimEvidenceRetrievalBatchV1(
        batch_id=batch_id_for(
            session_id=session_id, kind=kind.value, ordinal=ordinal, input_hash=input_hash,
        ),
        session_id=session_id, kind=kind, ordinal=ordinal, input_hash=input_hash,
        expected_claim_ids=[CLAIM_GAP if session_id == SESSION_A else CLAIM_COUNTER],
        created_at=NOW, updated_at=NOW,
    )


def _supplement(
    session_id: str, claim_id: str, verdict: ClaimVerdict, index: int,
    *, evidence_ids: list[str] | None = None,
) -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + f"{index:032x}", session_id=session_id,
        claim_id=claim_id, run_id=RUN, resource_id=RES if session_id == SESSION_A else RES_BLOCKED,
        resource_version=1, review_id=REV if session_id == SESSION_A else REV_BLOCKED,
        scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-new"] if evidence_ids is None else list(evidence_ids),
        reason="round1",
        judge_prompt_version="claim-evidence-rejudge-v1", confidence=0.8,
        payload_hash="e" * 64, created_at=NOW,
    )


def _snapshot() -> PersistedEvidenceSnapshot:
    from app.core.retrieval.knowledge_ids import sha256_hex
    from app.models.knowledge.knowledge import EvidenceItem, ScoreKind, SourceLocator, SourceType

    excerpt = "补充摘录"
    item = EvidenceItem(
        evidence_id="ev-new", knowledge_base_id="benchmark",
        document_id="doc-h07", document_version="v1", chunk_id="chunk-h07",
        query="q", query_hash="1" * 64, query_rank=1, rank=1,
        raw_score=0.9, score_kind=ScoreKind.SIMILARITY, normalized_score=0.8,
        excerpt=excerpt, excerpt_hash=sha256_hex(excerpt),
        locator=SourceLocator(
            knowledge_base_id="benchmark", document_id="doc-h07", document_version="v1",
            chunk_id="chunk-h07", source_type=SourceType.MARKDOWN,
            source_path="docs/h07.md", title="h07.md", section="1",
        ),
        config_hash="3" * 64, retrieved_at=NOW,
    )
    return PersistedEvidenceSnapshot.from_evidence(item, run_id=RUN, retrieval_step_id=STEP)


def _retrieve_to_rejudging(supplement, session_id: str, target: str) -> ClaimEvidenceRetrievalBatchV1:
    """Real lifecycle: PENDING → QUERYING → RETRIEVING → committed batch → REJUDGING."""

    supplement.create_session(_session(session_id, RES if session_id == SESSION_A else RES_BLOCKED,
                                       REV if session_id == SESSION_A else REV_BLOCKED, target))
    for expected, status in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
    ):
        supplement.update_session(session_id, expected_status=expected, status=status, now=NOW)
    batch = _batch(session_id, ClaimEvidenceBatchKind.RETRIEVE)
    supplement.save_batch(batch)
    supplement.complete_retrieval_batch(
        batch_id=batch.batch_id, run_id=RUN, step_id=STEP, owner="owner", epoch=1,
        output_hash="a" * 64, payload={"selected_count": 1},
        evidence=[_snapshot()], now=NOW,
    )
    supplement.update_session(
        session_id,
        expected_status=ClaimEvidenceRetrievalStatus.RETRIEVING,
        status=ClaimEvidenceRetrievalStatus.REJUDGING,
        evidence_scope_ids=["ev-new"], now=NOW,
    )
    return batch


def _open_rejudging_session(supplement, session_id: str, target: str) -> None:
    """Session lifecycle up to REJUDGING without touching retrieval batches."""

    supplement.create_session(_session(
        session_id, RES if session_id == SESSION_A else RES_BLOCKED,
        REV if session_id == SESSION_A else REV_BLOCKED, target,
    ))
    for expected, status in (
        (ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING),
        (ClaimEvidenceRetrievalStatus.QUERYING, ClaimEvidenceRetrievalStatus.RETRIEVING),
        (ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING),
    ):
        supplement.update_session(session_id, expected_status=expected, status=status, now=NOW)


def _epoch(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(
            "SELECT epoch FROM report_read_watermarks WHERE source = 'global'"
        )).scalar_one())


@pytest.fixture()
def store(tmp_path):
    engine = configure_sqlite_foreign_keys(create_engine(
        f"sqlite:///{tmp_path / 'h07_report.db'}", connect_args={"check_same_thread": False},
    ))
    seed_database(engine, 2)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        db.add(AgentRunORM(
            run_id=RUN, learner_id=LEARNER, knowledge_base_id="benchmark",
            topic="RAG", status="completed", started_at=BENCH_NOW - timedelta(days=1),
            input_payload={"include_claim_check": True, "include_review": True},
        ))
        db.add(AgentStepORM(
            step_id=STEP, run_id=RUN, step_no=1,
            agent_name="claim_evidence_retrieval",
            node_name="claim_evidence_retrieve", action="Claim 缺证补检",
            status="running",
        ))
        db.add(_job_row())
        # Bare ORM rows have no relationship(): flush per dependency level
        # so the unit of work cannot reorder foreign-key parents away.
        db.flush()
        db.add(GeneratedResourceORM(
            resource_id=RES, run_id=RUN, learner_id=LEARNER, topic="RAG",
            resource_type="讲义", difficulty="初级", storage_type="text",
            version=1, review_id=REV, publication_status="unpublished",
        ))
        db.add(ResourceReviewORM(review_id=REV, resource_id=RES, run_id=RUN, status="approve"))
        db.flush()
        db.add(_claim_row(CLAIM_SUPPORTED, supported=True))
        db.add(_claim_row(CLAIM_GAP, supported=False))
        db.flush()
        db.add(ClaimJudgementORM(
            judgement_id="jdg_" + "a" * 32, claim_id=CLAIM_SUPPORTED, run_id=RUN,
            resource_id=RES, resource_version=1, review_id=REV, status="completed",
            verdict="supported", reason="round0", judge_type="llm",
            judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
        ))
        db.add(ClaimJudgementORM(
            judgement_id="jdg_" + "b" * 32, claim_id=CLAIM_GAP, run_id=RUN,
            resource_id=RES, resource_version=1, review_id=REV, status="completed",
            verdict="not_in_evidence", reason="round0", judge_type="llm",
            judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
        ))
        db.commit()

    report_service = make_service(factory)
    report_service.profile_repo = SQLLearnerRepository(factory)
    report_service._clock = lambda: BENCH_NOW
    profiles = ProfileService(report_service.profile_repo)
    app = FastAPI()
    app.container = SimpleNamespaceContainer(profiles, report_service)
    app.include_router(report_routes.router, prefix="/api/report")

    audit = SQLAuditRepository(factory)
    claim = SQLClaimRepository(factory)
    supplement = SQLClaimSupplementRepository(
        claim_repository=claim, audit_repository=audit, session_factory=factory,
    )
    resources = SQLResourceRepository(factory)
    quality = ResourceQualityQueryService(
        audit_repository=audit, resource_repository=resources,
        claim_repository=claim, supplement_repository=supplement,
    )
    # The report attaches the shared versioned quality projection.
    report_service.quality_service = quality
    runs = RunQueryService(
        repository=audit, resource_repository=resources, claim_repository=claim,
        feedback_loop_repository=None, supplement_repository=supplement,
    )
    supplement.open_run(
        run_id=RUN, policy=_policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    yield SimpleNamespace(
        engine=engine, factory=factory, client=TestClient(app),
        audit=audit, claim=claim, supplement=supplement, resources=resources,
        quality=quality, runs=runs, report_service=report_service,
    )
    engine.dispose()


def _job_row():
    from app.db.shared.models import GenerationJobORM

    return GenerationJobORM(
        run_id=RUN, batch_id="batch-h07", learner_id=LEARNER,
        knowledge_base_id="benchmark", topic="RAG", status="completed",
        request_payload={"include_claim_check": True, "include_review": True},
        created_at=BENCH_NOW - timedelta(days=1),
    )


def _claim_row(claim_id: str, *, supported: bool):
    return ResourceClaimORM(
        claim_id=claim_id, review_id=REV, resource_id=RES, run_id=RUN,
        resource_version=1, schema_version="2.0", claim_index=0, claim_type="factual",
        claim_text="claim", source_text="claim", source_start=0, source_end=5,
        source_text_hash="a" * 64, extraction_method="llm",
        extractor_prompt_version="p0-06-extract-v3",
        claim_hash="b" * 64, supported=supported,
    )


def _claim_quality(store, resource_id: str):
    response = store.quality.get_run_quality(RUN, resource_id=resource_id)
    assert len(response.items) == 1
    return response.items[0].claim


class SimpleNamespaceContainer:
    def __init__(self, profiles, report_service):
        self._profiles = profiles
        self._report_service = report_service

    def profile_service(self):
        return self._profiles

    def report_service(self):
        return self._report_service


def test_activation_invalidates_the_report_cache_and_switches_to_the_effective_round(store, monkeypatch):
    # The resource must be visible for the report to carry its quality metric.
    store.resources.update_publication_decision(RES, publish=True)
    assert store.resources.get(RES).publication_status == "published"

    builds = []
    original_build = store.report_service._build_report_once

    def counted(*args, **kwargs):
        builds.append(kwargs.get("now"))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(store.report_service, "_build_report_once", counted)

    first = store.client.get(f"/api/report/{LEARNER}")
    assert first.status_code == 200
    etag0 = first.headers["etag"]
    revision0 = first.json()["report_revision"]
    builds_after_first = len(builds)
    warm = store.client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": etag0})
    assert warm.status_code == 304
    assert len(builds) == builds_after_first  # served from the metadata cache

    baseline = _claim_quality(store, RES)
    assert baseline.counts.factual_claim_total == 2
    assert baseline.counts.supported_claim_total == 1
    assert baseline.counts.not_in_evidence_claim_total == 1
    assert baseline.hallucination.value == 0.5

    epoch_before = _epoch(store.engine)
    batch = _retrieve_to_rejudging(store.supplement, SESSION_A, CLAIM_GAP)
    assert store.supplement.get_session(SESSION_A).status is ClaimEvidenceRetrievalStatus.REJUDGING

    store.supplement.save_batch(_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE))
    store.supplement.save_rejudge_batch(
        batch_id=_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE).batch_id,
        output_hash="c" * 64, payload={"round": 1},
        supplements=[_supplement(SESSION_A, CLAIM_GAP, ClaimVerdict.SUPPORTED, 0xC)],
        hard_block_reason=None, now=NOW,
    )
    scope = build_evidence_set(
        run_id=RUN, resource_id=RES, resource_version=1, review_id=REV,
        purpose="audit", session_id=SESSION_A,
        base_evidence_ids=[], added_evidence_ids=["ev-new"],
        snapshot_hashes={"ev-new": "d" * 64},
        manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
    )
    store.supplement.save_evidence_set(scope)
    store.supplement.activate_session(
        session_id=SESSION_A, scope=scope,
        round_one_hash=round_one_identity(store.supplement.list_supplements([RUN])),
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )

    # The persisted watermark moved because the real triggers fired.
    assert _epoch(store.engine) > epoch_before
    stale = store.client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": etag0})
    # The cache was invalidated and rebuilt (one more build), and because the
    # visible quality facts changed, the old conditional request gets a body.
    assert stale.status_code == 200
    assert len(builds) == builds_after_first + 1
    assert stale.json()["report_revision"] != revision0
    etag1 = stale.headers["etag"]
    warm2 = store.client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": etag1})
    assert warm2.status_code == 304
    assert len(builds) == builds_after_first + 1  # no second rebuild

    # One effective round, one denominator: the substituted gap counts once.
    effective = _claim_quality(store, RES)
    assert effective.counts.factual_claim_total == 2
    assert effective.counts.supported_claim_total == 2
    assert effective.counts.not_in_evidence_claim_total == 0
    assert effective.hallucination.value == 0.0
    # No false conflict between the historical round-0 row and the effective verdict.
    assert "CLAIM_JUDGEMENT_CONFLICT" not in (effective.reason_codes or ())

    claims = store.runs.get_claims(RUN)
    # Run Claims reads the effective round: the activated supplement
    # substitutes the round-0 not-in-evidence verdict.
    verdicts = sorted(item.verdict.value for item in claims.judgements)
    assert verdicts == ["supported", "supported"]

    # The same committed batch rejects a different payload for the same round.
    with pytest.raises(PersistenceConflict):
        store.supplement.complete_retrieval_batch(
            batch_id=batch.batch_id, run_id=RUN, step_id=STEP, owner="owner", epoch=1,
            output_hash="f" * 64, payload={"selected_count": 2},
            evidence=[], now=NOW,
        )


def test_counter_evidence_hard_block_changes_the_watermark_and_blocks_publication(store):
    with store.factory() as db:
        db.add(GeneratedResourceORM(
            resource_id=RES_BLOCKED, run_id=RUN, learner_id=LEARNER, topic="RAG",
            resource_type="实操指南", difficulty="初级", storage_type="text",
            version=1, review_id=REV_BLOCKED, publication_status="unpublished",
        ))
        db.flush()
        db.add(ResourceReviewORM(
            review_id=REV_BLOCKED, resource_id=RES_BLOCKED, run_id=RUN, status="approve",
        ))
        db.flush()
        db.add(ResourceClaimORM(
            claim_id=CLAIM_COUNTER, review_id=REV_BLOCKED, resource_id=RES_BLOCKED,
            run_id=RUN, resource_version=1, schema_version="2.0", claim_index=0,
            claim_type="factual", claim_text="counter claim", source_text="counter",
            source_start=0, source_end=7, source_text_hash="a" * 64,
            extraction_method="llm", extractor_prompt_version="p0-06-extract-v3",
            claim_hash="b" * 64, supported=False,
        ))
        db.flush()
        db.add(ClaimJudgementORM(
            judgement_id="jdg_" + "c" * 32, claim_id=CLAIM_COUNTER, run_id=RUN,
            resource_id=RES_BLOCKED, resource_version=1, review_id=REV_BLOCKED,
            status="completed", verdict="not_in_evidence", reason="round0",
            judge_type="llm", judge_prompt_version="p0-06-judge-v1",
            confidence=0.8, created_at=NOW,
        ))
        db.commit()

    # Publish the second version so the report carries its quality facts.
    store.resources.update_publication_decision(RES_BLOCKED, publish=True)
    fresh = store.client.get(f"/api/report/{LEARNER}")
    assert fresh.status_code == 200
    etag0 = fresh.headers["etag"]
    revision0 = fresh.json()["report_revision"]
    assert store.client.get(
        f"/api/report/{LEARNER}", headers={"If-None-Match": etag0},
    ).status_code == 304
    epoch_before = _epoch(store.engine)

    _retrieve_to_rejudging(store.supplement, SESSION_B, CLAIM_COUNTER)
    store.supplement.save_batch(_batch(SESSION_B, ClaimEvidenceBatchKind.REJUDGE))
    store.supplement.save_rejudge_batch(
        batch_id=_batch(SESSION_B, ClaimEvidenceBatchKind.REJUDGE).batch_id,
        output_hash="b" * 64, payload={"hard_block": "contradicted"},
        supplements=[_supplement(SESSION_B, CLAIM_COUNTER, ClaimVerdict.CONTRADICTED, 0xD)],
        hard_block_reason="contradicted", now=NOW,
    )

    blocked = store.supplement.get_session(SESSION_B)
    assert blocked.hard_block is True and blocked.hard_block_reason == "contradicted"

    # The counter evidence withdrew the published version; the conditional
    # request taken before the block must not be served from the stale cache.
    assert store.resources.get(RES_BLOCKED).publication_status == "unpublished"
    assert _epoch(store.engine) > epoch_before
    stale = store.client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": etag0})
    assert stale.status_code == 200
    assert stale.json()["report_revision"] != revision0
    assert store.client.get(
        f"/api/report/{LEARNER}", headers={"If-None-Match": stale.headers["etag"]},
    ).status_code == 304

    # The inactive session keeps round zero; the counter verdict is not applied.
    item = _claim_quality(store, RES_BLOCKED)
    assert item.counts.not_in_evidence_claim_total == 1
    assert item.counts.contradicted_claim_total == 0

    with pytest.raises(PublicationBarrier) as caught:
        store.resources.update_publication_decision(RES_BLOCKED, publish=True)
    assert caught.value.reason_code == HARD_BLOCK_REASON
    assert store.resources.get(RES_BLOCKED).publication_status == "unpublished"


def test_sql_and_memory_reach_the_same_projection_and_publication_decision(tmp_path):
    """Same facts on both backends produce the same session, metrics and gate."""

    # ---- SQL stack ----------------------------------------------------
    engine = configure_sqlite_foreign_keys(create_engine(
        f"sqlite:///{tmp_path / 'h07_parity.db'}", connect_args={"check_same_thread": False},
    ))
    try:
        from app.db.shared.models import Base
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            from app.db.shared.models import KnowledgeBaseORM, LearnerProfileORM

            db.add(KnowledgeBaseORM(knowledge_base_id="kb-001", name="Parity", version="1"))
            db.add(LearnerProfileORM(
                learner_id="learner-001", learner_type="test", education="本科",
                major="软件", learning_goal="parity", knowledge_base_id="kb-001",
                created_at=NOW, updated_at=NOW,
            ))
            db.flush()
            db.add(AgentRunORM(
                run_id=RUN, learner_id="learner-001", knowledge_base_id="kb-001",
                topic="RAG", status="completed", started_at=NOW,
            ))
            db.flush()
            db.add(GeneratedResourceORM(
                resource_id=RES, run_id=RUN, learner_id="learner-001", topic="RAG",
                resource_type="讲义", difficulty="初级", storage_type="text",
                version=1, review_id=REV, publication_status="unpublished",
            ))
            db.add(ResourceReviewORM(review_id=REV, resource_id=RES, run_id=RUN, status="approve"))
            db.flush()
            db.add(_claim_row(CLAIM_GAP, supported=False))
            db.flush()
            db.add(ClaimJudgementORM(
                judgement_id="jdg_" + "b" * 32, claim_id=CLAIM_GAP, run_id=RUN,
                resource_id=RES, resource_version=1, review_id=REV, status="completed",
                verdict="not_in_evidence", reason="round0", judge_type="llm",
                judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
            ))
            db.commit()
        sql_audit = SQLAuditRepository(factory)
        sql_claim = SQLClaimRepository(factory)
        sql_supplement = SQLClaimSupplementRepository(
            claim_repository=sql_claim, audit_repository=sql_audit, session_factory=factory,
        )
        sql_supplement.open_run(
            run_id=RUN, policy=_policy(), started_at=NOW,
            deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
        )
        _open_rejudging_session(sql_supplement, SESSION_A, CLAIM_GAP)
        sql_supplement.save_batch(_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE))
        sql_supplement.save_rejudge_batch(
            batch_id=_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE).batch_id,
            output_hash="c" * 64, payload={"round": 1},
            supplements=[_supplement(SESSION_A, CLAIM_GAP, ClaimVerdict.SUPPORTED, 0xC, evidence_ids=[])],
            hard_block_reason=None, now=NOW,
        )
        scope = build_evidence_set(
            run_id=RUN, resource_id=RES, resource_version=1, review_id=REV,
            purpose="audit", session_id=SESSION_A,
            base_evidence_ids=[], added_evidence_ids=["ev-new"],
            snapshot_hashes={"ev-new": "d" * 64},
            manifest=[{"evidence_id": "ev-new", "order": 0}], created_at=NOW,
        )
        sql_supplement.save_evidence_set(scope)
        sql_supplement.activate_session(
            session_id=SESSION_A, scope=scope,
            round_one_hash=round_one_identity(sql_supplement.list_supplements([RUN])),
            supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
        )
        sql_session = sql_supplement.get_session(SESSION_A)
        sql_review = sql_audit.get_review_by_resource(RES)
        sql_resource = SQLResourceRepository(factory)
    finally:
        engine.dispose()

    # ---- Memory stack -------------------------------------------------
    memory_audit = MemoryAuditRepository()
    run_snapshot = {"topic": "RAG", "include_claim_check": True, "include_review": True}
    memory_audit.create_run(CreateRunCommand(
        run_id=RUN, learner_id="learner-001", knowledge_base_id="kb-001",
        topic="RAG", request_snapshot=run_snapshot,
        request_hash=canonical_hash(run_snapshot),
        owner_instance_id="test", lease_expires_at=NOW + timedelta(seconds=60),
        occurred_at=NOW,
    ))
    memory_resources = MemoryResourceRepository()
    memory_resources.save(
        LearningResource(
            resource_id=RES, resource_type="讲义", difficulty="初级",
            content_text="正文", knowledge_points=[], source_refs=[],
            version=1, review_id=REV,
        ),
        "learner-001", "RAG", run_id=RUN,
    )
    memory_audit.save_review(
        RES,
        {"decision": "approve", "status": "approve", "review_id": REV},
        RUN,
    )
    memory_claim = MemoryClaimRepository()

    gap = ClaimRecord(
        claim_id=CLAIM_GAP, run_id=RUN, resource_id=RES, resource_version=1,
        review_id=REV, claim_index=0, claim_text="claim", claim_type=ClaimType.FACTUAL,
        source_text="claim", source_start=0, source_end=5,
        source_text_hash="a" * 64, extractor_prompt_version="p",
        claim_hash="b" * 64, created_at=NOW,
    )
    round0 = ClaimJudgement(
        judgement_id="jdg_" + "b" * 32, claim_id=CLAIM_GAP, run_id=RUN,
        resource_id=RES, resource_version=1, review_id=REV,
        status=ClaimJudgementStatus.COMPLETED, verdict=ClaimVerdict.NOT_IN_EVIDENCE,
        evidence_ids=[], reason="round0", judge_type=ClaimJudgeType.LLM,
        judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
    )
    memory_claim.save_audit([gap], [round0])
    memory_supplement = MemoryClaimSupplementRepository(
        claim_repository=memory_claim, audit_repository=memory_audit,
    )
    memory_supplement.open_run(
        run_id=RUN, policy=_policy(), started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner", epoch=1,
    )
    _open_rejudging_session(memory_supplement, SESSION_A, CLAIM_GAP)
    memory_supplement.save_batch(_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE))
    memory_supplement.save_rejudge_batch(
        batch_id=_batch(SESSION_A, ClaimEvidenceBatchKind.REJUDGE).batch_id,
        output_hash="c" * 64, payload={"round": 1},
        supplements=[_supplement(SESSION_A, CLAIM_GAP, ClaimVerdict.SUPPORTED, 0xC, evidence_ids=[])],
        hard_block_reason=None, now=NOW,
    )
    memory_supplement.save_evidence_set(scope)
    memory_supplement.activate_session(
        session_id=SESSION_A, scope=scope,
        round_one_hash=round_one_identity(memory_supplement.list_supplements([RUN])),
        supported=1, contradicted=0, absent=0, factual=1, claim_total=1, now=NOW,
    )
    memory_session = memory_supplement.get_session(SESSION_A)
    memory_review = memory_audit.get_review_by_resource(RES)

    # Same facts → same activation projection.
    for field in ("status", "active", "hard_block", "hard_block_reason"):
        assert getattr(memory_session, field) == getattr(sql_session, field)
    assert memory_session.status is ClaimEvidenceRetrievalStatus.COMPLETED
    assert memory_session.active is True
    # Same facts → same persisted claim metrics.
    assert (memory_review.claim_total, memory_review.claim_supported, memory_review.claim_unsupported) == (
        sql_review.claim_total, sql_review.claim_supported, sql_review.claim_unsupported,
    ) == (1, 1, 0)
    # Same facts → the same publication decision is available again.
    sql_resource.update_publication_decision(RES, publish=True)
    memory_resources.update_publication_decision(RES, publish=True)
    assert sql_resource.get(RES).publication_status == "published"
    assert memory_resources.get(RES).publication_status == "published"
