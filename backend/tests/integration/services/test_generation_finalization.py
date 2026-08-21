from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.audit.base import PersistenceConflict
from app.core.errors import ApplicationError, ErrorCode
from app.db.database import configure_sqlite_foreign_keys
from app.db.audit.memory import MemoryAuditRepository
from app.db.models import Base, KnowledgeBaseORM, LearnerProfileORM
from app.db.resource.memory import MemoryResourceRepository
from app.db.resource.models import ResourceSpecRecord
from app.db.resource.sql_repository import SQLResourceRepository
from app.models.persistence import BeginStepCommand, CreateRunCommand, RunStatus, canonical_hash
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
    event_types = [item.event_type.value for item in audit.list_events(run_id, limit=100)]
    assert event_types.count("review_persisted") == 1
    assert event_types.count("resource_published") == 1
    assert event_types.count("resource_persisted") == 1


def test_reconcile_allows_unpublished_degraded_resource_without_review_record():
    """A per-resource LLM failure remains human-reviewable, not a run failure."""
    audit = MemoryAuditRepository()
    resource = _resource(
        resource_id="degraded-resource",
        review_status="human_review",
        publication_status="unpublished",
    )
    _reconcile_reviews(
        [resource],
        {"decision": "human_review", "review_ids": {}},
        run_id="run-degraded-no-review",
        audit_repo=audit,
    )


def test_sql_recorder_persists_degraded_resource_before_execution_foreign_key(tmp_path):
    """A degraded worker result remains reviewable instead of failing the run.

    This specifically protects the resource-execution FK ordering used by
    SQLite in production: the fallback resource must exist before its execution
    projection references it.
    """

    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{tmp_path / 'degraded-execution.db'}")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    resources = SQLResourceRepository(factory)
    recorder = WorkflowArtifactRecorder(resources, audit)
    # Keep foreign-key validation enabled end-to-end.  Agent runs reference
    # both a learner profile and a knowledge base before workflow artifacts
    # can be recorded.
    with factory() as db:
        db.add_all([
            KnowledgeBaseORM(knowledge_base_id="kb", name="Test knowledge base"),
            LearnerProfileORM(
                learner_id="learner",
                learner_type="test",
                education="本科",
                major="软件工程",
                learning_goal="verify degraded resource persistence",
                knowledge_base_id="kb",
            ),
        ])
        db.commit()
    run_id = "run-degraded-execution"
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
    audit.begin_step(BeginStepCommand(
        run_id=run_id,
        step_id="step-degraded-generator",
        step_sequence=1,
        node_name="generator",
        agent_name="generator",
        action="generate degraded fallback",
        started_at=NOW,
    ))

    spec_id = "spec-degraded"
    resource = _resource(
        resource_id="resource-degraded",
        learner_id="learner",
        topic="RAG",
        resource_spec_id=spec_id,
        resource_family_id="family-degraded",
        representation="text",
        review_status="human_review",
        publication_status="unpublished",
        content_text="# 待人工审核的降级资源",
    )
    state = {
        "run_id": run_id,
        "learner_id": "learner",
        "topic": "RAG",
        "resource_specs": [{
            "resource_spec_id": spec_id,
            "resource_family_id": "family-degraded",
            "resource_type": "讲义",
            "learning_objective": "验证降级资源持久化",
            "difficulty": "中级",
            "representations": [{"representation": "text"}],
            "display_order": 1,
        }],
        "generated_resources": [resource],
        "resource_executions": [{
            "resource_spec_id": spec_id,
            "resource_type": "讲义",
            "representation": "text",
            "resource_execution_state": "human_review",
            "attempt": 1,
            "resource_id": resource.resource_id,
            "error_code": "LLM_OUTPUT_EMPTY",
            "agent_name": "TextResourceAgent",
            "prompt_version": "v1",
            "artifact_format": "markdown",
            "validation_status": "failed",
        }],
    }

    trace = {
        # Reproduce the production ordering: the generator step is durable
        # before its resource (which references that step).
        "step_id": "step-degraded-generator",
        "sequence": 1,
        "node_name": "generator",
        "agent_name": "generator",
        "resource_ids": [resource.resource_id],
    }
    execution = state["resource_executions"][0]
    recorder.record_resource_queued(
        state,
        spec=ResourceSpecRecord.model_validate({**state["resource_specs"][0], "run_id": run_id}),
        execution=execution,
        trace_item=trace,
    )
    # This is the worker-completion boundary used by production: the fallback
    # resource must be stored before its execution projection and SSE event.
    recorder.record_resource_generated(
        state, resource=resource, execution=execution, trace_item=trace,
    )
    # The aggregate generator merge remains idempotent and must not send a
    # duplicate resource-generated notification.
    recorder.record(state, trace)

    assert resources.get(resource.resource_id) is not None
    execution = resources.get_execution(run_id, spec_id, "text")
    assert execution is not None
    assert execution.resource_id == resource.resource_id
    assert execution.state == "human_review"
    event_types = [item.event_type.value for item in audit.list_events(run_id, limit=100)]
    assert event_types.count("resource_execution_queued") == 1
    assert event_types.count("resource_human_review_requested") == 1
    assert "resource_version_created" not in event_types
    completion_event = next(
        item for item in audit.list_events(run_id, limit=100)
        if item.event_type.value == "resource_human_review_requested"
    )
    assert completion_event.payload["representation"] == "text"
    assert completion_event.payload["attempt"] == 1
    assert completion_event.payload["agent_name"] == "TextResourceAgent"
    assert completion_event.payload["validation_status"] == "failed"


def test_sql_reconcile_preserves_recorder_owned_resource_review_id(tmp_path):
    """A human-review fallback must finalize without rewriting its review ID."""

    engine = create_engine(f"sqlite:///{tmp_path / 'resource-review-id.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    resources = SQLResourceRepository(factory)
    recorder = WorkflowArtifactRecorder(resources, audit)
    run_id = "run-resource-review-id"
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

    resource = _resource(resource_id="resource-human-review")
    base_state = {
        "run_id": run_id,
        "learner_id": "learner",
        "topic": "RAG",
        "generated_resources": [resource],
    }
    recorder.record(base_state, _trace("generator", 1))
    review_id = "review-human-review"
    review = {
        "decision": "human_review",
        "status": "human_review",
        "review_ids": {resource.resource_id: review_id},
        "issues": [],
        "revision_instructions": [],
        "revision_count": 0,
    }
    reviewed = resource.model_copy(update={
        "review_id": review_id,
        "review_status": "human_review",
    })
    recorder.record(
        {
            **base_state,
            "generated_resources": [reviewed],
            "review_result": review,
            "resource_review_results": {
                resource.resource_id: {
                    **review,
                    "review_id": review_id,
                    "resource_id": resource.resource_id,
                },
            },
        },
        _trace("review", 2),
    )

    persisted = resources.get(resource.resource_id)
    assert persisted is not None
    assert persisted.review_id == review_id
    assert audit.list_reviews_by_run(run_id)[0]["review_id"] == review_id
    _reconcile_reviews([persisted], review, run_id=run_id, audit_repo=audit)


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
