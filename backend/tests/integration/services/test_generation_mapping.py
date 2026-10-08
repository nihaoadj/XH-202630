from types import SimpleNamespace

import pytest

from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation import generation as generation_module
from app.services.generation.generation import GenerationService, build_workflow_state


def _learner(learner_id="mapping-001"):
    return LearnerProfile(
        learner_id=learner_id,
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="验证映射",
    )


def test_generation_mapping_rejects_mismatched_learner_identity():
    request = GenerateRequest(learner_id="request-user", topic="测试")
    with pytest.raises(ApplicationError) as caught:
        build_workflow_state(_learner("profile-user"), request)
    assert caught.value.code == ErrorCode.WORKFLOW_CONTRACT_INVALID


class _RecordingWorkflow:
    def __init__(self):
        self.state = None

    def invoke(self, state):
        self.state = state
        resource = LearningResource(
            resource_id="resource-stable",
            resource_type="讲义",
            difficulty="中级",
            content_text=None,
            knowledge_points=["测试"],
            source_refs=[],
            review_status="unreviewed_draft",
        )
        return {
            **state,
            "generated_resources": [resource],
            "review_result": {"decision": "not_requested", "status": "not_requested"},
            "workflow_status": "completed",
            "final_decision": "未审核草稿",
            "trace": [{
                "schema_version": "1.0",
                "run_id": state["run_id"],
                "step_id": "step-stable",
                "sequence": 1,
                "attempt": 1,
                "agent_name": "generator",
                "node_name": "generator",
                "action": "生成",
                "output_summary": "完成",
                "status": "success",
            }],
        }


def test_service_reuses_run_id_in_state_response_trace_and_audit(monkeypatch):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )
    workflow = _RecordingWorkflow()
    repo = MemoryResourceRepository()
    repo.save(
        LearningResource(
            resource_id="resource-stable", learner_id="mapping-001", topic="测试",
            resource_type="讲义", difficulty="中级", knowledge_points=["测试"], source_refs=[],
        ),
        "mapping-001", "测试",
    )
    audit = MemoryAuditRepository()
    service = GenerationService(repo, workflow, audit)

    response = service.generate(
        _learner(),
        GenerateRequest(
            learner_id="mapping-001",
            topic="测试",
            include_review=False,
            resource_types=["讲义"],
        ),
    )

    assert workflow.state is not None
    assert response.run_id == workflow.state["run_id"]
    assert response.trace[0].run_id == response.run_id
    assert response.run_id in audit.runs
    assert response.resources[0].run_id == response.run_id
    assert response.schema_version == "1.0"
    assert response.workflow_status == "completed"


class _ReviewedWorkflow:
    def __init__(self, audit):
        self.audit = audit

    def invoke(self, state):
        self.audit.save_review(
            "reviewed-resource",
            {"review_id": "review-stable", "status": "approved", "passed": True},
            state["run_id"],
        )
        resource = LearningResource(
            resource_id="reviewed-resource",
            resource_type="讲义",
            difficulty="中级",
            content_text=None,
            knowledge_points=["测试"],
            source_refs=[],
            review_status="approved",
        )
        return {
            **state,
            "generated_resources": [resource],
            "review_result": {
                "decision": "approve",
                "status": "approve",
                "passed": True,
                "review_ids": {"reviewed-resource": "review-stable"},
            },
            "workflow_status": "completed",
            "trace": [{
                "schema_version": "1.0",
                "run_id": state["run_id"],
                "step_id": "review-step",
                "sequence": 1,
                "attempt": 1,
                "agent_name": "reviewer",
                "action": "审核",
                "output_summary": "通过",
                "status": "success",
                "review_ids": ["review-stable"],
            }],
        }


def test_service_persists_preallocated_review_id(monkeypatch):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )
    audit = MemoryAuditRepository()
    repo = MemoryResourceRepository()
    repo.save(
        LearningResource(
            resource_id="reviewed-resource", learner_id="mapping-001", topic="测试",
            resource_type="讲义", difficulty="中级", knowledge_points=["测试"], source_refs=[],
        ),
        "mapping-001", "测试",
    )
    service = GenerationService(repo, _ReviewedWorkflow(audit), audit)

    response = service.generate(
        _learner(),
        GenerateRequest(
            learner_id="mapping-001",
            topic="测试",
            include_review=True,
            resource_types=["讲义"],
        ),
    )

    assert response.resources[0].review_id == "review-stable"
    assert audit.reviews["review-stable"]["run_id"] == response.run_id
