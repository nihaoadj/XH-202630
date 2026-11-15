"""Publication facts refresh after a user decision on a finished run."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.generation.progress import PublishCompleteness
from app.models.learning_documents.schemas import GenerateRequest, LearningResource
from app.models.reviews.claims import ClaimJudgement, ClaimRecord
from app.models.shared.persistence import CreateRunCommand, WorkflowEventType, canonical_hash
from app.services.generation.jobs import GenerationJobService
from app.services.learning_documents.publication import ResourcePublicationConflict
from app.services.learning_documents.resources import ResourceService
from app.services.runs.queries import RunQueryService

RUN_ID = "run-refresh"
LEARNER_ID = "learner-refresh"
PENDING_RESOURCE_ID = "res-assessment"
REQUEST_TYPES = ["讲义", "实操指南", "分阶测试题"]


class _Fixture:
    def __init__(self):
        self.audit = MemoryAuditRepository()
        self.claims = MemoryClaimRepository()
        self.jobs = MemoryGenerationJobRepository()
        self.resources = MemoryResourceRepository()
        self.service = ResourceService(self.resources)
        self._seed()

    def _seed(self) -> None:
        snapshot = {"learner_id": LEARNER_ID, "topic": "T47", "resource_types": REQUEST_TYPES}
        self.audit.create_run(CreateRunCommand(
            run_id=RUN_ID,
            learner_id=LEARNER_ID,
            knowledge_base_id=None,
            topic="T47",
            request_snapshot=snapshot,
            request_hash=canonical_hash(snapshot),
        ))
        self.jobs.create(
            run_id=RUN_ID,
            learner_id=LEARNER_ID,
            topic="T47",
            knowledge_base_id=None,
            request_payload=GenerateRequest(
                learner_id=LEARNER_ID, topic="T47", resource_types=REQUEST_TYPES
            ).model_dump(mode="json"),
        )
        for order, (spec_id, resource_type) in enumerate(
            (("spec-video", "讲义"), ("spec-practice", "实操指南"), ("spec-assessment", "分阶测试题"))
        ):
            self.resources.save_spec(ResourceSpecRecord(
                resource_spec_id=spec_id,
                run_id=RUN_ID,
                resource_type=resource_type,
                learning_objective=f"覆盖 {resource_type}",
                difficulty="初级",
                representations=[{"representation": "text"}],
                display_order=order,
            ))
        for spec_id, resource_type, resource_id, state in (
            ("spec-video", "讲义", "res-video", "approved"),
            ("spec-practice", "实操指南", "res-practice", "approved"),
            ("spec-assessment", "分阶测试题", PENDING_RESOURCE_ID, "human_review"),
        ):
            self.resources.upsert_execution(ResourceExecutionRecord(
                run_id=RUN_ID,
                resource_spec_id=spec_id,
                resource_type=resource_type,
                state=state,
                resource_id=resource_id,
                attempt=1,
                agent_name="TextResourceAgent",
                prompt_version="v1",
                artifact_format="markdown",
            ))
        for resource_id, resource_type, spec_id in (
            ("res-video", "讲义", "spec-video"),
            ("res-practice", "实操指南", "spec-practice"),
        ):
            self.resources.save(
                LearningResource(
                    resource_id=resource_id,
                    resource_type=resource_type,
                    difficulty="初级",
                    knowledge_points=["kp-1"],
                    source_refs=[],
                    run_id=RUN_ID,
                    resource_spec_id=spec_id,
                    publication_status="published",
                ),
                learner_id=LEARNER_ID,
                topic="T47",
            )
        self.resources.save(
            LearningResource(
                resource_id=PENDING_RESOURCE_ID,
                resource_type="分阶测试题",
                difficulty="初级",
                knowledge_points=["kp-1"],
                source_refs=[],
                run_id=RUN_ID,
                resource_spec_id="spec-assessment",
                review_id="review-assessment",
                publication_status="unpublished",
                claim_metric_status="complete",
                claim_factual_pass_rate=0.8,
                claim_publish_decision="pending",
                claim_publish_decision_pending=True,
            ),
            learner_id=LEARNER_ID,
            topic="T47",
        )
        record = ClaimRecord(
            claim_id="clm_" + "a" * 32,
            run_id=RUN_ID,
            resource_id=PENDING_RESOURCE_ID,
            resource_version=1,
            review_id="review-assessment",
            claim_index=0,
            claim_text="事实",
            claim_type="factual",
            source_text="事实",
            source_start=0,
            source_end=2,
            source_text_hash="b" * 64,
            source_evidence_ids=["evidence"],
            extractor_prompt_version="v1",
            claim_hash="c" * 64,
        )
        judgement = ClaimJudgement(
            judgement_id="jdg_" + "d" * 32,
            claim_id=record.claim_id,
            run_id=RUN_ID,
            resource_id=PENDING_RESOURCE_ID,
            resource_version=1,
            review_id="review-assessment",
            status="completed",
            verdict="supported",
            evidence_ids=["evidence"],
            reason="supported",
            judge_type="deterministic",
            judge_prompt_version="v1",
        )
        self.claims.save_audit([record], [judgement])

    def run_service(self) -> RunQueryService:
        return RunQueryService(
            self.audit,
            self.resources,
            claim_repository=self.claims,
            generation_job_repository=self.jobs,
        )

    def job_service(self) -> GenerationJobService:
        return GenerationJobService(
            self.jobs, SimpleNamespace(resource_repo=self.resources)
        )

    def decide(self, publish: bool, *, audit_factory=None):
        resource = self.resources.get(PENDING_RESOURCE_ID)
        assert resource is not None
        return self.service.decide_claim_publication(
            resource,
            resource_id=PENDING_RESOURCE_ID,
            publish=publish,
            settings_factory=lambda: SimpleNamespace(claim_user_review_min_factual_pass_rate=0.6),
            run_query_factory=self.run_service,
            audit_factory=audit_factory or (lambda: self.audit),
        )

    def publication_events(self) -> list:
        return [
            event
            for event in self.audit.list_events(RUN_ID, after_sequence=0, limit=100)
            if event.event_type == WorkflowEventType.RESOURCE_PUBLICATION_DECIDED
        ]


def test_publish_decision_refreshes_job_and_run_to_three_of_three():
    fixture = _Fixture()
    before = fixture.job_service().get_job(RUN_ID).publish_summary
    assert (before.total, before.published, before.pending_review) == (3, 2, 1)
    assert before.completeness is PublishCompleteness.COMPLETE
    run_before = fixture.run_service().get_summary(RUN_ID)
    assert run_before.publish_summary.model_dump() == before.model_dump()
    status_before = run_before.status

    fixture.decide(True)

    after = fixture.job_service().get_job(RUN_ID).publish_summary
    assert (after.total, after.published, after.unpublished, after.pending_review) == (3, 3, 0, 0)
    run_after = fixture.run_service().get_summary(RUN_ID)
    assert run_after.publish_summary.model_dump() == after.model_dump()
    assert run_after.status == status_before
    timeline = fixture.run_service().get_timeline(RUN_ID, limit=1)
    assert timeline.run.publish_summary.model_dump() == after.model_dump()


def test_rejection_keeps_the_confirmed_two_of_three():
    fixture = _Fixture()
    fixture.decide(False)
    summary = fixture.job_service().get_job(RUN_ID).publish_summary
    assert (summary.total, summary.published, summary.pending_review) == (3, 2, 0)
    assert summary.completeness is PublishCompleteness.COMPLETE
    resource = fixture.resources.get(PENDING_RESOURCE_ID)
    assert resource.publication_status == "unpublished"
    assert resource.claim_publish_decision == "rejected_by_user"


def test_repeating_the_same_decision_does_not_duplicate_events():
    fixture = _Fixture()
    fixture.decide(True)
    assert len(fixture.publication_events()) == 1
    fixture.decide(True)
    assert len(fixture.publication_events()) == 1
    assert fixture.job_service().get_job(RUN_ID).publish_summary.published == 3


def test_non_pending_resource_rejects_a_new_decision():
    fixture = _Fixture()
    resource = fixture.resources.get("res-video")
    assert resource is not None
    with pytest.raises(ResourcePublicationConflict):
        fixture.service.decide_claim_publication(
            resource,
            resource_id="res-video",
            publish=True,
            settings_factory=lambda: SimpleNamespace(claim_user_review_min_factual_pass_rate=0.6),
            run_query_factory=fixture.run_service,
            audit_factory=lambda: fixture.audit,
        )


def test_failed_event_append_is_recovered_without_a_second_publication():
    fixture = _Fixture()

    class _BrokenAudit:
        def append_event(self, *args, **kwargs):
            raise RuntimeError("audit append failed")

        def list_events(self, *args, **kwargs):
            return []

    with pytest.raises(RuntimeError, match="audit append failed"):
        fixture.decide(True, audit_factory=lambda: _BrokenAudit())
    # The resource commit already happened, so the publication is durable even
    # though its audit event is not.
    assert fixture.resources.get(PENDING_RESOURCE_ID).publication_status == "published"
    assert fixture.publication_events() == []

    fixture.decide(True)
    assert len(fixture.publication_events()) == 1
    assert fixture.job_service().get_job(RUN_ID).publish_summary.published == 3


def test_job_summary_follows_a_rebound_resource_repository():
    fixture = _Fixture()
    job_service = fixture.job_service()
    assert job_service.get_job(RUN_ID).publish_summary.published == 2

    # Continuation rebinds the service copy instead of carrying scheduler state;
    # the aggregate must read whatever repository the current call is bound to.
    job_service.generation_service.resource_repo = MemoryResourceRepository()
    rebound = job_service.get_job(RUN_ID).publish_summary
    assert rebound.total == 3
    assert rebound.published == 0
    assert rebound.pending_review == 0
    assert rebound.completeness is PublishCompleteness.PARTIAL
    assert [reason.value for reason in rebound.incomplete_reasons] == ["spec_request_mismatch"]
