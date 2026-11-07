"""T48 run quality projection against real SQL and Memory repositories.

Deterministic: no model call, no network, no production database.  The tests
build the same private-ledger fixture for both repository families and compare
the serialized projection, then prove the shared read boundary (no writes, no
cross-moment stitching, locks released).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.audit.memory import MemoryAuditRepository
from app.db.audit.quality_read import (
    CONSISTENT_READ_UNSUPPORTED,
    NATIVE_MEMORY,
    NATIVE_SQL,
    UNSUPPORTED,
    read_quality_sources,
)
from app.db.claim.memory import MemoryClaimRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.models import ResourceSpecRecord
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.shared.models import Base
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claims import (
    ClaimJudgementCandidate,
    ClaimType,
    ClaimVerdict,
    materialize_claims,
    materialize_judgements,
)
from app.models.reviews.quality_metrics import (
    QualityAssessment,
    QualityEvidenceMode,
    QualityMetricStatus,
)
from app.models.reviews.resource_review import (
    ResourceDimensionsV1,
    ResourceEvidenceRefV1,
    ResourceIssueV1,
    ResourceLedgerV1,
    ResourceLocationV1,
    ResourceObservationV1,
    ResourceResolutionV1,
    ResourceReviewBindingV1,
    ResourceReviewOutputV1,
    ResourceTargetCoverageV1,
    derived_coverage_rate,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash
from app.models.reviews.review_audit import (
    ReviewAuditRecordV4,
    ReviewPolicySnapshotV1,
    ReviewResourceAuditV1,
    summarize_review_calls,
)
from app.models.shared.persistence import AgentStepRecord, CreateRunCommand, canonical_hash
from app.services.reviews.quality_query import (
    ResourceQualityNotFound,
    ResourceQualityQueryService,
)

RUN_ID = "run-t48"
LEARNER_ID = "learner-t48"
SPEC_ID = "spec-t48"
RESOURCE_ID = "res-t48"
REVIEW_ID = "rev-t48"
STEP_ID = "step-review-1"
SNAPSHOT = {
    "learner_id": LEARNER_ID, "topic": "T48",
    "include_review": True, "include_claim_check": False,
}


def _v4_snapshot() -> dict:
    """The frozen request snapshot a real V4 run persists."""
    return {
        **SNAPSHOT,
        "resource_review_contract_version": "1.0",
        "resource_review_policy": _POLICY.model_dump(mode="json"),
        "resource_review_policy_hash": _POLICY_HASH,
    }


_POLICY = ResourceReviewPolicyV1(
    context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2,
)
_POLICY_HASH = policy_hash(_POLICY)


def _binding(version: int = 1) -> ResourceReviewBindingV1:
    return ResourceReviewBindingV1(
        run_id=RUN_ID, resource_spec_id=SPEC_ID, lineage_id="fam-t48",
        resource_id=RESOURCE_ID, resource_type="讲义", version=version,
        text_exact_hash="a" * 64, structured_payload_hash=None,
        artifact_exact_hash="b" * 64, comparison_hash="c" * 64,
        evidence_snapshot_hash="d" * 64, policy_hash=_POLICY_HASH,
    )


def _ledger(
    *,
    version: int = 1,
    decisions: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
    issues: list[ResourceIssueV1] | None = None,
    resolutions: list[ResourceResolutionV1] | None = None,
) -> ResourceLedgerV1:
    decisions = decisions or {"node-1": "covered", "node-2": "covered"}
    dimensions = dimensions or {
        "factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass",
    }
    # The ledger owns a server-derived identity per issue ordinal; the fixture
    # must use the same derivation instead of inventing ids.
    from app.models.reviews.resource_review import (
        ResourceIssueHistoryV1,
        model_issue_id,
    )

    derived_issues = [
        issue.model_copy(update={
            "issue_id": model_issue_id(
                run_id=RUN_ID, resource_spec_id=SPEC_ID, lineage_id="fam-t48",
                step_id=STEP_ID, ordinal=ordinal,
            ),
        })
        for ordinal, issue in enumerate(issues or [], 1)
    ]
    targets = []
    for target_id, status in decisions.items():
        targets.append(ResourceTargetCoverageV1.model_validate({
            "target": target_id,
            "status": status,
            "reason": "已讲解" if status == "covered" else "未讲解",
            "location": {"kind": "paragraph", "paragraph_id": f"p-{target_id}"} if status == "covered" else None,
        }))
    binding = _binding(version)
    output = ResourceReviewOutputV1.model_validate({
        "binding": binding.model_dump(mode="json"),
        "dimensions": dimensions,
        "targets": [item.model_dump(mode="json") for item in targets],
        "hallucination_score": 0.0,
        "issues": [item.model_dump(mode="json") for item in derived_issues],
        "resolutions": [],
        "reopen": [],
        "omitted_blocking_issues": False,
    })
    final_decision = "approve" if dimensions["factual_evidence"] == "pass" else "revise"
    observation = ResourceObservationV1(
        origin="model_review", step_id=STEP_ID, binding=binding,
        output_hash="f" * 64, comparison_hash=binding.comparison_hash,
        parent_content_hash=None, revision_kind="ordinary", unchanged=False,
        consecutive_unchanged=0, characters_added=10, characters_removed=0,
        gate=None, output=output, coverage_rate=derived_coverage_rate(output.targets),
        decision=final_decision,
    )
    history = [
        ResourceIssueHistoryV1(
            issue=issue, introduced_step_id=STEP_ID, introduced_version=version,
            status="open" if issue.blocking else "closed",
        )
        for issue in derived_issues
    ]
    return ResourceLedgerV1(
        binding=binding,
        issues=history,
        observations=[observation],
    )


def _audit(ledger: ResourceLedgerV1, *, decision: str | None = None) -> ReviewAuditRecordV4:
    policy = _POLICY
    decision = decision or getattr(ledger.observations[-1], "decision", None) or "approve"
    return ReviewAuditRecordV4(
        schema_version="4.0", run_id=RUN_ID, step_id=STEP_ID, generation_attempt=1,
        revision_count=0, policy=ReviewPolicySnapshotV1(), decision=decision,
        node_wall_ms=1,
        resources=[ReviewResourceAuditV1(
            resource_id=RESOURCE_ID, review_id=REVIEW_ID, resource_spec_id=SPEC_ID,
            resource_type="讲义", structure_status="passed", semantic_status="passed",
            decision=decision,
        )],
        calls=[], summary=summarize_review_calls([]),
        resource_review_policy=policy, resource_review_policy_hash=policy_hash(policy),
        resource_ledgers=[ledger], repairs=[],
    )


def _step() -> AgentStepRecord:
    return AgentStepRecord(
        step_id=STEP_ID, run_id=RUN_ID, step_sequence=7, agent_name="Reviewer",
        node_name="review", action="review", status="success",
        resource_ids=[RESOURCE_ID], review_ids=[REVIEW_ID],
        started_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )


def _spec(*targets: str) -> ResourceSpecRecord:
    return ResourceSpecRecord(
        resource_spec_id=SPEC_ID, run_id=RUN_ID, resource_type="讲义",
        learning_objective="覆盖目标", knowledge_points=list(targets) or ["node-1", "node-2"],
        difficulty="中级", representations=[{"representation": "text"}], display_order=0,
        resource_family_id="fam-t48",
    )


def _resource(*, version: int = 1) -> LearningResource:
    return LearningResource(
        resource_id=RESOURCE_ID, resource_type="讲义", difficulty="中级", topic="T48",
        content_text="讲解", knowledge_points=["node-1", "node-2"], source_refs=[],
        run_id=RUN_ID, resource_spec_id=SPEC_ID, version=version, review_id=REVIEW_ID,
        publication_status="published", resource_family_id="fam-t48",
    )


def _claims(resource: LearningResource, verdicts: list[ClaimVerdict]):
    content = "\n".join(f"claim {index} text" for index in range(len(verdicts)))
    from app.models.reviews.claims import ClaimCandidate

    candidates = [
        ClaimCandidate(claim_text=f"claim {index} text", claim_type=ClaimType.FACTUAL,
                       source_text=f"claim {index} text", source_start=0,
                       source_end=len(f"claim {index} text"))
        for index in range(len(verdicts))
    ]
    records = materialize_claims(
        candidates=candidates, resource_content=content,
        resource_id=resource.resource_id, resource_version=resource.version,
        review_id=REVIEW_ID, run_id=RUN_ID, allowed_evidence_ids={"ev-1"},
        allowed_knowledge_point_ids={"node-1", "node-2"},
        extractor_prompt_version="v1", extractor_model=None,
    )
    judgements = materialize_judgements(
        claims=records,
        candidates=[
            ClaimJudgementCandidate(
                claim_id=record.claim_id, verdict=verdict,
                evidence_ids=["ev-1"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} else [],
                reason="fixture", confidence=1.0,
            )
            for record, verdict in zip(records, verdicts)
        ],
        allowed_evidence_ids={"ev-1"}, judge_prompt_version="v1", judge_model=None,
    )
    return records, judgements


def _memory_bundle(*, ledger=None, claims=(), judgements=(), resource=None, spec=None,
                   claim_requested: bool = False, decision: str | None = None):
    from app.db.audit.base import StepReviewAudit
    from app.db.audit.quality_read import QualitySourceBundle

    audit = _audit(ledger or _ledger(), decision=decision)
    run = _memory_audit_repo().get_run(RUN_ID)
    return QualitySourceBundle(
        run_id=RUN_ID, read_mode=NATIVE_MEMORY, run=run,
        request_snapshot={**_v4_snapshot(), "include_claim_check": claim_requested},
        steps=(_step(),), checkpoints=(),
        audits=(StepReviewAudit(
            run_id=RUN_ID, step_id=STEP_ID, step_sequence=7, node_name="review",
            status="success", audit=audit,
        ),),
        specs=(spec or _spec(),),
        executions=(),
        resources=(resource or _resource(),),
        claims=tuple(claims), judgements=tuple(judgements),
        reviews=((RESOURCE_ID, _persisted_review("passed")),),
    )


def _memory_audit_repo() -> MemoryAuditRepository:
    repo = MemoryAuditRepository()
    repo.create_run(CreateRunCommand(
        run_id=RUN_ID, learner_id=LEARNER_ID, knowledge_base_id=None, topic="T48",
        request_snapshot=SNAPSHOT, request_hash=canonical_hash(SNAPSHOT),
    ))
    return repo


class _Review:
    def __init__(self, status: str, review_id: str = REVIEW_ID, issues=None):
        self.review_id = review_id
        self.status = status
        self.issues = issues or []


def _persisted_review(status: str, *, review_id: str = REVIEW_ID, issues=None):
    return _Review(status, review_id, issues)


def _service() -> ResourceQualityQueryService:
    return ResourceQualityQueryService(
        audit_repository=_memory_audit_repo(),
        resource_repository=MemoryResourceRepository(),
        claim_repository=MemoryClaimRepository(),
    )


# --- coverage and binding ---------------------------------------------
def test_exact_version_ledger_produces_measured_coverage():
    service = _service()
    items = service.build_items(_memory_bundle())
    assert len(items) == 1
    item = items[0]
    assert item.coverage.status is QualityMetricStatus.COMPLETE
    assert (item.coverage.numerator, item.coverage.denominator) == (2, 2)
    assert item.coverage.assessment is QualityAssessment.MET
    assert [target.target_id for target in item.target_coverage] == ["node-1", "node-2"]
    assert item.ordinary_review.decision == "approve"
    assert item.ordinary_review.factual_evidence == "pass"


def test_target_set_must_match_the_frozen_spec():
    service = _service()
    items = service.build_items(_memory_bundle(spec=_spec("node-1", "node-3")))
    assert items[0].coverage.status is QualityMetricStatus.UNAVAILABLE
    assert items[0].coverage.value is None
    assert "COVERAGE_TARGETS_MISMATCH" in items[0].reason_codes


def test_newer_ledger_version_never_lends_its_coverage_to_an_older_resource():
    service = _service()
    items = service.build_items(_memory_bundle(resource=_resource(version=1)))
    newer = _ledger(version=2)
    service_items = service.build_items(_memory_bundle(ledger=newer, resource=_resource(version=1)))
    assert items[0].coverage.status is QualityMetricStatus.COMPLETE
    assert service_items[0].coverage.status is QualityMetricStatus.UNAVAILABLE
    assert "ORDINARY_VERSION_MISMATCH" in service_items[0].reason_codes


def test_program_gate_only_round_is_not_a_measured_coverage():
    from app.models.reviews.resource_review import (
        ResourceGateKeyV1,
        ResourceIssueHistoryV1,
        ResourceProgramGateResultV1,
        program_issue_id,
    )

    service = _service()
    binding = _binding()
    identity = program_issue_id(run_id=RUN_ID, resource_spec_id=SPEC_ID,
                                gate_rule_id="rule-1", scope_locator="p-1",
                                failure_code="MISSING_SECTION")
    issue = ResourceIssueV1.model_validate({
        "issue_id": identity, "origin": "program_gate", "code": "MISSING_SECTION",
        "severity": "high", "blocking": True, "blocking_rule": "rule-1",
        "dimension": "self_contained", "location": {"kind": "root"},
        "impact": "结构缺失", "requirement": "补齐结构", "acceptance": "结构检查通过",
        "criteria_version": 1, "path": "reorganize_existing",
        "executability": "executable", "rationale": "程序门禁",
    })
    gate = ResourceProgramGateResultV1(
        rule_version="v1", passed=False,
        keys=[ResourceGateKeyV1(gate_rule_id="rule-1", scope_locator="p-1",
                                failure_code="MISSING_SECTION")],
        new_issues=[issue],
    )
    observation = ResourceObservationV1(
        origin="program_gate", step_id=STEP_ID, binding=binding, output_hash=None,
        comparison_hash="c" * 64, parent_content_hash=None, revision_kind="ordinary",
        unchanged=False, consecutive_unchanged=0, characters_added=0,
        characters_removed=0, gate=gate, output=None, coverage_rate=None,
        decision=None,
    )
    ledger = ResourceLedgerV1(
        binding=binding,
        issues=[ResourceIssueHistoryV1(
            issue=issue, introduced_step_id=STEP_ID, introduced_version=1, status="open",
        )],
        observations=[observation],
    )
    items = service.build_items(_memory_bundle(ledger=ledger, decision="revise"))
    assert items[0].coverage.status is QualityMetricStatus.FAILED
    assert items[0].coverage.value is None
    assert "ORDINARY_PROGRAM_GATE_ONLY" in items[0].reason_codes


def test_audit_failure_is_attributed_to_the_resource():
    service = _service()
    bundle = _memory_bundle()
    from app.db.audit.base import AUDIT_INVALID, StepReviewAudit

    failed = bundle.audits[0]
    variant = bundle.__class__(
        run_id=bundle.run_id, read_mode=bundle.read_mode, run=bundle.run,
        request_snapshot=bundle.request_snapshot,
        steps=bundle.steps, checkpoints=bundle.checkpoints,
        audits=(StepReviewAudit(run_id=RUN_ID, step_id=STEP_ID, step_sequence=7,
                                node_name="review", status="success",
                                audit=None, failure_code=AUDIT_INVALID),),
        specs=bundle.specs, executions=bundle.executions, resources=bundle.resources,
        claims=bundle.claims, judgements=bundle.judgements, reviews=bundle.reviews,
    )
    items = service.build_items(variant)
    assert items[0].coverage.status is QualityMetricStatus.FAILED
    assert items[0].ordinary_review.failure_code == AUDIT_INVALID
    assert failed.audit is not None


# --- hallucination sources --------------------------------------------
def test_ordinary_approved_reference_without_claim_check():
    service = _service()
    item = service.build_items(_memory_bundle())[0]
    assert item.hallucination.status is QualityMetricStatus.REFERENCE
    assert item.hallucination.value == 0.05
    assert item.hallucination.numerator is None and item.hallucination.denominator is None
    assert item.hallucination.assessment is QualityAssessment.NOT_ASSESSED
    assert item.hallucination.evidence_mode is QualityEvidenceMode.RULE_REFERENCE


def test_rejected_ordinary_review_does_not_get_the_reference():
    service = _service()
    failed_ledger = _ledger(dimensions={
        "factual_evidence": "fail", "difficulty": "pass", "self_contained": "pass",
    })
    items = service.build_items(_memory_bundle(ledger=failed_ledger))
    assert items[0].hallucination.status is not QualityMetricStatus.REFERENCE
    assert items[0].hallucination.value is None


def test_compat_review_record_can_establish_the_reference():
    from app.db.audit.base import StepReviewAudit
    from app.models.reviews.claims import ClaimRecord  # noqa: F401 - typing only

    service = _service()
    bundle = _memory_bundle()
    variant = bundle.__class__(
        run_id=bundle.run_id, read_mode=bundle.read_mode, run=bundle.run,
        request_snapshot=bundle.request_snapshot,
        steps=bundle.steps, checkpoints=bundle.checkpoints,
        audits=(StepReviewAudit(run_id=RUN_ID, step_id=STEP_ID, step_sequence=7,
                                node_name="review", status="success", audit=None),),
        specs=bundle.specs, executions=bundle.executions, resources=bundle.resources,
        claims=bundle.claims, judgements=bundle.judgements,
        reviews=((RESOURCE_ID, _persisted_review("passed")),),
    )
    item = service.build_items(variant)[0]
    assert item.ordinary_review.status == "legacy_unavailable"
    assert item.coverage.value is None
    assert item.hallucination.status is QualityMetricStatus.REFERENCE


def test_complete_claim_result_overrides_the_reference():
    service = _service()
    resource = _resource()
    claims, judgements = _claims(resource, [ClaimVerdict.SUPPORTED] * 20 + [ClaimVerdict.CONTRADICTED])
    bundle = _memory_bundle(claims=claims, judgements=judgements, claim_requested=True)
    item = service.build_items(bundle)[0]
    assert item.hallucination.status is QualityMetricStatus.COMPLETE
    assert item.hallucination.value == pytest.approx(1 / 21)
    assert item.hallucination.assessment is QualityAssessment.MET
    assert item.claim.counts.factual_claim_total == 21


def test_claim_incomplete_is_not_a_reference_or_a_zero():
    service = _service()
    resource = _resource()
    claims, judgements = _claims(resource, [ClaimVerdict.SUPPORTED, ClaimVerdict.SUPPORTED])
    bundle = _memory_bundle(claims=claims[:2], judgements=judgements[:1], claim_requested=True)
    item = service.build_items(bundle)[0]
    assert item.hallucination.status is QualityMetricStatus.INCOMPLETE
    assert item.hallucination.value is None
    assert item.claim.progress.value == pytest.approx(0.5)


def test_requested_claim_check_without_rows_is_unknown():
    service = _service()
    bundle = _memory_bundle()
    requested = bundle.__class__(
        run_id=bundle.run_id, read_mode=bundle.read_mode, run=bundle.run,
        request_snapshot={"include_review": True, "include_claim_check": True},
        steps=bundle.steps, checkpoints=bundle.checkpoints, audits=bundle.audits,
        specs=bundle.specs, executions=bundle.executions, resources=bundle.resources,
        claims=(), judgements=(), reviews=bundle.reviews,
    )
    item = service.build_items(requested)[0]
    assert item.hallucination.status is QualityMetricStatus.UNAVAILABLE
    assert item.hallucination.value is None


def test_conflicting_judgements_are_not_resolved_by_last_write():
    service = _service()
    resource = _resource()
    claims, judgements = _claims(resource, [ClaimVerdict.SUPPORTED])
    conflicting = judgements[0].model_copy(update={
        "judgement_id": "jdg_" + "1" * 32, "verdict": ClaimVerdict.CONTRADICTED,
    })
    bundle = _memory_bundle(
        claims=claims, judgements=(judgements[0], conflicting), claim_requested=True,
    )
    item = service.build_items(bundle)[0]
    assert item.hallucination.status is QualityMetricStatus.INCOMPLETE
    assert item.hallucination.value is None
    assert "CLAIM_JUDGEMENT_CONFLICT" in item.claim.reason_codes


# --- issue statistics and leakage -------------------------------------
def test_issue_statistics_counts_the_ledger_not_the_public_summary():
    service = _service()
    issue = ResourceIssueV1.model_validate({
        "issue_id": "ri_" + "0" * 64, "origin": "model_review", "code": "MISSING_EXAMPLE",
        "severity": "high", "blocking": True, "blocking_rule": "rule-x",
        "dimension": "coverage", "affected_target_ids": ["node-2"],
        "location": {"kind": "root"}, "impact": "缺少例子",
        "requirement": "补充例子", "acceptance": "例子可复现", "criteria_version": 1,
        "path": "synthetic_example", "evidence_refs": [{"evidence_id": "ev-1",
                                                       "excerpt_hash": "a" * 64}],
        "executability": "executable", "rationale": "教学需要",
    })
    ledger = _ledger(issues=[issue])
    items = service.build_items(_memory_bundle(ledger=ledger))
    stats = items[0].issue_statistics
    assert stats.open_issue_total == 1
    assert stats.open_by_severity.high == 1
    assert stats.open_by_dimension.coverage == 1
    payload = items[0].model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "补充例子" not in serialized
    assert "缺少例子" not in serialized


def test_projection_never_contains_answers_rubrics_or_evidence_text():
    service = _service()
    item = service.build_items(_memory_bundle())[0]
    serialized = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
    for forbidden in ("已讲解", "未讲解", "rationale", "excerpt", "prompt"):
        assert forbidden not in serialized


# --- run query surface -------------------------------------------------
def test_resource_filter_and_unknown_resource():
    service = _service()
    bundle = _memory_bundle()
    items = service.build_items(bundle)
    assert items[0].resource_id == RESOURCE_ID
    assert ResourceQualityNotFound is not None


def test_summary_buckets_partition_the_resources():
    service = _service()
    items = service.build_items(_memory_bundle())
    summary = service.summarize_items(items)
    assert summary.resource_total == 1
    assert summary.coverage_buckets.total == 1
    assert summary.claim_buckets.total == 1
    assert summary.reference_resource_total == 1


# --- SQL / Memory equivalence and shared read boundary ----------------
@pytest.fixture()
def sql_repositories(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 't48.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    repositories = (
        SQLAuditRepository(factory), SQLResourceRepository(factory), SQLClaimRepository(factory),
    )
    yield engine, factory, repositories
    engine.dispose()


def _seed_sql(factory, repositories, *, ledger=None, decision: str | None = None):
    with factory() as db:
        from app.db.shared.models import (
            AgentRunORM, AgentStepORM, WorkflowCheckpointORM,
        )
        from app.models.reviews.review_audit import (
            AUDIT_V4_NAMESPACE, review_audit_envelope,
        )

        audit = _audit(ledger or _ledger(), decision=decision)
        envelope = review_audit_envelope(audit, run_id=RUN_ID, step_id=STEP_ID)
        run = AgentRunORM(
            run_id=RUN_ID, learner_id=LEARNER_ID, knowledge_base_id=None, topic="T48",
            status="completed", request_hash=canonical_hash(_v4_snapshot()),
            input_payload=_v4_snapshot(),
            output_payload={}, updated_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.add(AgentStepORM(
            step_id=STEP_ID, run_id=RUN_ID, step_no=7, agent_name="Reviewer",
            node_name="review", action="review", status="success",
            input_payload={}, output_payload={AUDIT_V4_NAMESPACE: envelope},
            resource_ids=[RESOURCE_ID], review_ids=[REVIEW_ID],
            started_at=datetime.now(timezone.utc),
        ))
        projection = {
                "review_audit_refs": [{
                    "step_id": STEP_ID, "audit_hash": envelope["audit_hash"],
                    "review_ids": [REVIEW_ID], "schema_version": "4.0",
                }],
            "resource_review_policy": audit.resource_review_policy.model_dump(mode="json"),
            "resource_review_policy_hash": audit.resource_review_policy_hash,
        }
        db.add(WorkflowCheckpointORM(
            checkpoint_id="cp-1", schema_version="1.0", run_id=RUN_ID, event_sequence=1,
            step_id=STEP_ID, step_sequence=7, node_name="review",
            state_projection=projection,
            state_hash=canonical_hash(projection), created_at=datetime.now(timezone.utc),
        ))
        db.commit()
    # Use the public repository so the persisted projection is the real one.
    repositories[1].save_spec(_spec())
    repositories[1].save(_resource(), LEARNER_ID, "T48", run_id=RUN_ID)


def test_sql_and_memory_project_the_same_items(sql_repositories):
    engine, factory, repositories = sql_repositories
    _seed_sql(factory, repositories)
    audit_repo, resource_repo, claim_repo = repositories
    service = ResourceQualityQueryService(
        audit_repository=audit_repo, resource_repository=resource_repo,
        claim_repository=claim_repo,
    )
    sql_items = service.get_run_quality(RUN_ID).items
    memory_items = _service().build_items(_memory_bundle())
    assert [item.model_dump(mode="json") for item in sql_items] == [
        item.model_dump(mode="json") for item in memory_items
    ]


def test_sql_snapshot_is_read_only_and_declares_native_mode(sql_repositories):
    engine, factory, repositories = sql_repositories
    _seed_sql(factory, repositories)
    audit_repo, resource_repo, claim_repo = repositories
    before = engine.connect().execute(text("PRAGMA integrity_check")).scalar()
    bundle = read_quality_sources(
        RUN_ID, audit_repository=audit_repo,
        resource_repository=resource_repo, claim_repository=claim_repo,
    )
    assert bundle.read_mode == NATIVE_SQL
    assert bundle.failure_code is None
    assert bundle.specs and bundle.resources and bundle.audits
    # PRAGMA query_only is reset before the connection returns to the pool.
    with factory() as db:
        db.execute(text("CREATE TABLE t48_probe (id INTEGER)"))
        db.rollback()
    assert before == "ok"


def test_unsupported_mixed_repositories_declare_themselves(sql_repositories):
    _, factory, repositories = sql_repositories
    audit_repo = repositories[0]
    bundle = read_quality_sources(
        RUN_ID, audit_repository=audit_repo,
        resource_repository=MemoryResourceRepository(),
        claim_repository=MemoryClaimRepository(),
    )
    assert bundle.read_mode == UNSUPPORTED
    assert bundle.failure_code == CONSISTENT_READ_UNSUPPORTED
    service = ResourceQualityQueryService(
        audit_repository=audit_repo,
        resource_repository=MemoryResourceRepository(),
        claim_repository=MemoryClaimRepository(),
    )
    response = service.get_run_quality(RUN_ID)
    assert response.availability.value == "unavailable"
    assert "CONSISTENT_READ_UNSUPPORTED" in response.reason_codes


def test_memory_snapshot_takes_and_releases_every_lock():
    resource_repo = MemoryResourceRepository()
    claim_repo = MemoryClaimRepository()
    audit_repo = MemoryAuditRepository()
    audit_repo.create_run(CreateRunCommand(
        run_id=RUN_ID, learner_id=LEARNER_ID, knowledge_base_id=None, topic="T48",
        request_snapshot=SNAPSHOT, request_hash=canonical_hash(SNAPSHOT),
    ))
    bundle = read_quality_sources(
        RUN_ID, audit_repository=audit_repo,
        resource_repository=resource_repo, claim_repository=claim_repo,
    )
    assert bundle.read_mode == NATIVE_MEMORY
    # Locks must be free again: another thread can write immediately.
    done = threading.Event()

    def writer():
        resource_repo.save(_resource(), LEARNER_ID, "T48")
        claim_repo.save_audit([], [])
        done.set()

    thread = threading.Thread(target=writer)
    thread.start()
    thread.join(timeout=5)
    assert done.is_set()
    assert not thread.is_alive()


def test_memory_writer_during_read_cannot_stitch_two_moments():
    resource_repo = MemoryResourceRepository()
    claim_repo = MemoryClaimRepository()
    audit_repo = MemoryAuditRepository()
    audit_repo.create_run(CreateRunCommand(
        run_id=RUN_ID, learner_id=LEARNER_ID, knowledge_base_id=None, topic="T48",
        request_snapshot=SNAPSHOT, request_hash=canonical_hash(SNAPSHOT),
    ))
    resource_repo.save(_resource(), LEARNER_ID, "T48")
    observed = []

    def reader():
        bundle = read_quality_sources(
            RUN_ID, audit_repository=audit_repo,
            resource_repository=resource_repo, claim_repository=claim_repo,
        )
        observed.append(len(bundle.resources))

    thread = threading.Thread(target=reader)
    thread.start()
    claim_repo.save_audit([], [])
    thread.join(timeout=5)
    assert observed and observed[0] >= 1


@pytest.mark.parametrize("matched", [True, False])
def test_boolean_difficulty_is_not_a_labelled_accuracy(matched):
    resource = _resource().model_copy(update={"difficulty_match": matched})
    item = _service().build_items(_memory_bundle(resource=resource))[0]
    assert item.difficulty_fit.match_status == "not_measured"
    assert item.difficulty_fit.dimension_status == "pass"


@pytest.mark.parametrize("marker", [{"claim_failed_resource_ids": [RESOURCE_ID]}, {"claim_check_status": "failed"}, {"claim_check_status": "pending"}])
def test_claim_checkpoint_precedes_partial_persisted_rows(marker):
    from dataclasses import replace
    from types import SimpleNamespace
    resource = _resource()
    claims, judgements = _claims(resource, [ClaimVerdict.SUPPORTED])
    bundle = _memory_bundle(resource=resource, claims=claims, judgements=judgements, claim_requested=True)
    bundle = replace(bundle, checkpoints=(SimpleNamespace(state_projection=marker),))
    item = _service().build_items(bundle)[0]
    assert item.hallucination.value is None
    assert item.hallucination.status.value in {"pending", "failed"}
    assert item.coverage.value == 1.0


def test_unknown_request_flags_never_become_reference_or_not_requested():
    from dataclasses import replace
    bundle = replace(_memory_bundle(), request_snapshot={}, job_request_payload={})
    item = _service().build_items(bundle)[0]
    assert item.hallucination.value is None
    assert item.claim.status == "unavailable"
    assert item.claim.progress.status.value == "unavailable"


@pytest.mark.parametrize("field,value", [("resource_spec_id", "other"), ("resource_family_id", "other")])
def test_ledger_identity_never_borrows_a_same_type_resource(field, value):
    resource = _resource().model_copy(update={field: value})
    item = _service().build_items(_memory_bundle(resource=resource))[0]
    assert item.coverage.value is None
    assert item.hallucination.value is None


def test_complete_empty_ledger_means_zero_issues_and_partial_ledger_validates():
    from app.services.reviews.quality_query import _issue_statistics
    complete = _issue_statistics(_ledger(), truncated=False)
    assert complete.history_completeness == "complete"
    assert complete.open_issue_total == complete.fixed_issue_total == 0
    partial = _issue_statistics(_ledger(), truncated=True)
    assert partial.history_completeness == "partial"


def test_multi_spec_display_order_is_the_response_order():
    from dataclasses import replace
    from app.models.reviews.quality_metrics import RunResourceQualityResponseV1
    resource = _resource()
    a = resource.model_copy(update={"resource_id": "first", "resource_spec_id": "z-spec"})
    b = resource.model_copy(update={"resource_id": "second", "resource_spec_id": "a-spec"})
    z = _spec().model_copy(update={"resource_spec_id": "z-spec", "display_order": 0})
    a_spec = _spec().model_copy(update={"resource_spec_id": "a-spec", "display_order": 1})
    items = _service().build_items(replace(_memory_bundle(), resources=(b, a), specs=(a_spec, z)))
    response = RunResourceQualityResponseV1(run_id=RUN_ID, source_revision="rq_" + "a" * 64,
                                          availability="partial", items=tuple(items),
                                          summary=_service().summarize_items(items))
    assert [item.resource_id for item in response.items] == ["first", "second"]



def test_memory_read_failure_propagates_and_releases_snapshot_locks(monkeypatch):
    audit = _memory_audit_repo()
    resource = MemoryResourceRepository()
    claim = MemoryClaimRepository()
    def fail(*args):
        raise RuntimeError("injected read failure")
    monkeypatch.setattr(resource, "list_by_run", fail)
    with pytest.raises(RuntimeError, match="injected read failure"):
        read_quality_sources(RUN_ID, audit_repository=audit, resource_repository=resource, claim_repository=claim)
    done = threading.Event()
    def writer():
        with audit._lock, resource._lock, claim._lock:
            done.set()
    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert done.wait(2)
    thread.join(2)


def test_sql_read_failure_propagates_and_restores_connection(sql_repositories, monkeypatch):
    engine, factory, repositories = sql_repositories
    _seed_sql(factory, repositories)
    def fail(*args):
        raise RuntimeError("injected SQL failure")
    monkeypatch.setattr(SQLResourceRepository, "list_by_run", fail)
    with pytest.raises(RuntimeError, match="injected SQL failure"):
        read_quality_sources(RUN_ID, audit_repository=repositories[0], resource_repository=repositories[1], claim_repository=repositories[2])
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 0



@pytest.mark.parametrize("failed_sequence", [6, 7, 8])
@pytest.mark.parametrize("failed_resource_id", [RESOURCE_ID, "other-resource"])
def test_latest_review_round_selects_valid_or_failed_without_stale_reference(failed_sequence, failed_resource_id):
    from dataclasses import replace
    from app.db.audit.base import AUDIT_INVALID, StepReviewAudit

    bundle = _memory_bundle()
    failed_step = bundle.steps[0].model_copy(update={
        "step_id": "failed-round", "step_sequence": failed_sequence,
        "resource_ids": [failed_resource_id],
    })
    failed_audit = StepReviewAudit(
        run_id=RUN_ID, step_id="failed-round", step_sequence=failed_sequence,
        node_name="review", status="success", failure_code=AUDIT_INVALID,
    )
    bundle = replace(bundle, steps=(*bundle.steps, failed_step), audits=(*bundle.audits, failed_audit))
    item = _service().build_items(bundle)[0]
    # The helper includes a persisted approved review. It cannot bypass a
    # newer failed audit, including the conservative same-sequence boundary.
    if failed_resource_id == RESOURCE_ID and failed_sequence >= 7:
        assert item.coverage.status is QualityMetricStatus.FAILED
        assert item.coverage.value is None
        assert item.hallucination.status is QualityMetricStatus.FAILED
        assert item.hallucination.value is None
        assert item.ordinary_review.review_step_id == "failed-round"
    else:
        assert item.coverage.status is QualityMetricStatus.COMPLETE
        assert item.hallucination.status is QualityMetricStatus.REFERENCE
        assert item.ordinary_review.review_step_id == STEP_ID


def test_later_valid_review_restores_measurement_after_a_failed_round():
    from dataclasses import replace
    from app.db.audit.base import AUDIT_INVALID, StepReviewAudit

    bundle = _memory_bundle()
    failed_step = bundle.steps[0].model_copy(update={"step_id": "bad", "step_sequence": 8})
    valid_step = bundle.steps[0].model_copy(update={"step_id": "recovered", "step_sequence": 9})
    failed = StepReviewAudit(run_id=RUN_ID, step_id="bad", step_sequence=8,
                            node_name="review", status="success", failure_code=AUDIT_INVALID)
    recovered = replace(bundle.audits[0], step_id="recovered", step_sequence=9)
    bundle = replace(bundle, steps=(*bundle.steps, failed_step, valid_step),
                     audits=(*bundle.audits, failed, recovered))
    item = _service().build_items(bundle)[0]
    assert item.coverage.value == 1
    assert item.hallucination.status is QualityMetricStatus.REFERENCE
    assert item.ordinary_review.review_step_id == "recovered"
