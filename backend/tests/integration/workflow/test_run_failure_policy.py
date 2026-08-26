from types import SimpleNamespace

import pytest

from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation import generation as generation_module
from app.services.generation.generation import GenerationService


def _learner():
    return LearnerProfile(
        learner_id="failure-learner",
        learner_type="测试",
        education="本科",
        major="计算机",
        learning_goal="验证持久化失败策略",
    )


def _request():
    return GenerateRequest(
        learner_id="failure-learner",
        topic="RAG",
        include_review=False,
        resource_types=["讲义"],
    )


class _Workflow:
    def __init__(self):
        self.calls = 0

    def invoke(self, state):
        self.calls += 1
        resource = LearningResource(
            resource_id="resource-failure",
            resource_type="讲义",
            difficulty="初级",
            content_text=None,
            knowledge_points=[],
            source_refs=[],
            review_status="unreviewed_draft",
        )
        return {
            **state,
            "generated_resources": [resource],
            "review_result": {"decision": "not_requested"},
            "workflow_status": "completed",
            "final_decision": "草稿",
            "trace": [
                {
                    "run_id": state["run_id"],
                    "step_id": "step-failure",
                    "sequence": 1,
                    "attempt": 1,
                    "agent_name": "generator",
                    "node_name": "generator",
                    "action": "生成",
                    "status": "success",
                    "resource_ids": ["resource-failure"],
                }
            ],
        }


def test_create_run_failure_prevents_workflow_invocation(monkeypatch):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )

    class FailingRepository(MemoryAuditRepository):
        def create_run(self, command):
            raise RuntimeError("database unavailable")

    workflow = _Workflow()
    service = GenerationService(MemoryResourceRepository(), workflow, FailingRepository())
    with pytest.raises(ApplicationError) as caught:
        service.generate(_learner(), _request())
    assert caught.value.code == ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
    assert workflow.calls == 0


def test_recorder_resource_failure_cannot_leave_completed_run(monkeypatch):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )

    class FailingResourceRepository(MemoryResourceRepository):
        def save(self, *args, **kwargs):
            raise RuntimeError("disk error")

    audit = MemoryAuditRepository()
    service = GenerationService(FailingResourceRepository(), _Workflow(), audit)
    with pytest.raises(ApplicationError) as caught:
        service.generate(_learner(), _request())
    assert caught.value.code == ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
    run = next(iter(audit.runs.values()))
    assert run["status"] == "failed"
