from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.audit.base import PersistenceConflict
from app.core.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.models import Base
from app.db.resource.memory import MemoryResourceRepository
from app.db.resource.sql_repository import SQLResourceRepository
from app.models.persistence import CreateRunCommand, RunStatus, canonical_hash
from app.models.schemas import LearningResource
from app.models.schemas import GenerateRequest, LearnerProfile
from app.services import generation_service as generation_module
from app.services.generation_service import GenerationService
from app.services.generation_service import _materialize_resources, _reconcile_reviews
from app.services.workflow_artifact_recorder import WorkflowArtifactRecorder


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _resource(**updates):
    resource = LearningResource(
        resource_id="resource-one",
        resource_type="讲义",
        difficulty="中级",
        content_text=None,
        knowledge_points=[],
        source_refs=[],
        review_status="pending_review",
        publication_status="unpublished",
        version=1,
    )
    return resource.model_copy(update=updates)


def _trace(node_name, sequence):
    return {
        "step_id": f"step-{sequence}",
        "sequence": sequence,
        "node_name": node_name,
        "agent_name": node_name,
    }


def test_sql_finalization_uses_recorder_owned_review_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'finalization.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    resources = SQLResourceRepository(factory)
    recorder = WorkflowArtifactRecorder(resources, audit)
    run_id = "run-finalization"
    audit.create_run(CreateRunCommand(
        run_id=run_id,
        learner_id="learner",
        knowledge_base_id="kb",
        topic="RAG",
        request_snapshot={},
        request_hash=canonical_hash({}),
        owner_instance_id="test",
        lease_expires_at=None,
        occurred_at=NOW,
    ))
    audit.start_run(run_id, occurred_at=NOW)

    generated = _resource()
    base_state = {
        "run_id": run_id,
        "learner_id": "learner",
        "topic": "RAG",
        "generated_resources": [generated],
    }
    recorder.record(base_state, _trace("generator", 1))
    review_id = "review-one"
    reviewer_review = {
        "decision": "approve",
        "status": "approve",
        "review_ids": {generated.resource_id: review_id},
        "issues": [],
        "revision_instructions": [],
        "revision_count": 0,
    }
    approved = generated.model_copy(update={"review_id": review_id, "review_status": "approved"})
    recorder.record(
        {**base_state, "generated_resources": [approved], "review_result": reviewer_review},
        _trace("reviewer", 2),
    )
    finalized_review = {**reviewer_review, "claim_check_status": "not_requested"}
    # This is the exact historical root cause: finalize enriches the same
    # review_id, so the legacy second authoritative write conflicts by hash.
    with pytest.raises(PersistenceConflict, match="review payload conflict"):
        audit.save_review(generated.resource_id, finalized_review, run_id)
    published = approved.model_copy(update={"publication_status": "published", "published_at": NOW})
    recorder.record(
        {**base_state, "generated_resources": [published], "review_result": finalized_review},
        _trace("supervisor", 3),
    )

    audit.mark_finalizing(
        run_id,
        workflow_status="completed",
        current_node="supervisor",
        generation_attempt=1,
        revision_count=0,
        retrieval_status="available",
        final_decision="审核通过",
        occurred_at=NOW,
    )
    for _ in range(2):
        materialized = _materialize_resources(
            [published],
            "learner",
            "RAG",
            resources,
            run_id=run_id,
            generation_steps={},
            audit_repo=audit,
        )
        _reconcile_reviews(materialized, finalized_review, run_id=run_id, audit_repo=audit)
        audit.complete_run(
            run_id,
            status=RunStatus.COMPLETED,
            workflow_status="completed",
            execution_status="success",
            final_decision="审核通过",
            occurred_at=NOW,
        )

    assert audit.get_run(run_id).status == RunStatus.COMPLETED
    assert len(audit.list_reviews_by_run(run_id)) == 1
    assert len(resources.list_by_run(run_id)) == 1
    assert resources.list_by_run(run_id)[0].batch_id == run_id
    event_types = [item.event_type.value for item in audit.list_events(run_id, limit=100)]
    assert event_types.count("review_persisted") == 1
    assert event_types.count("resource_published") == 1
    assert event_types.count("resource_persisted") == 1


class _FinalizationWorkflow:
    def invoke(self, state):
        review_id = "review-finalization-failure"
        resource = _resource(
            review_id=review_id,
            review_status="approved",
            publication_status="published",
            published_at=NOW,
        )
        review = {
            "decision": "approve",
            "status": "approve",
            "claim_check_status": "not_requested",
            "review_ids": {resource.resource_id: review_id},
            "issues": [],
            "revision_instructions": [],
        }
        trace = [
            {**_trace("generator", 1), "resource_ids": [resource.resource_id], "status": "success"},
            {**_trace("reviewer", 2), "review_ids": [review_id], "status": "success"},
            {**_trace("supervisor", 3), "resource_ids": [resource.resource_id], "status": "success"},
        ]
        return {
            **state,
            "generated_resources": [resource],
            "review_result": review,
            "workflow_status": "completed",
            "current_node": "supervisor",
            "final_decision": "审核通过",
            "trace": trace,
        }


def test_finalization_failure_records_safe_stage_and_stable_public_error(monkeypatch, caplog):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: type("Ready", (), {"status": "ready", "error_codes": []})(),
    )

    class FailingReconcileAudit(MemoryAuditRepository):
        def list_reviews_by_run(self, run_id):
            raise RuntimeError("private database detail")

    audit = FailingReconcileAudit()
    service = GenerationService(MemoryResourceRepository(), _FinalizationWorkflow(), audit)
    learner = LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="计算机",
        learning_goal="RAG",
    )
    request = GenerateRequest(
        learner_id="learner",
        topic="RAG",
        include_review=True,
        resource_types=["讲义"],
    )

    with pytest.raises(ApplicationError) as caught:
        service.generate(learner, request)

    assert caught.value.code == ErrorCode.WORKFLOW_FINALIZATION_FAILED
    assert audit.get_run(next(iter(audit.runs))).status == RunStatus.FAILED
    failure_events = [
        item for item in audit.list_events(next(iter(audit.runs)), limit=100)
        if item.event_type.value == "workflow_finalization_failed"
    ]
    assert failure_events[0].payload == {
        "finalization_stage": "reconcile_review",
        "exception_type": "RuntimeError",
        "safe_message": "finalization_stage_failed",
    }
    assert "finalization_stage=reconcile_review" in caplog.text
    assert "private database detail" not in caplog.text
