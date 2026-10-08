import pytest

from app.agents.resource_workflows.learning_documents import reviewer_agent as reviewer_module
from app.config import Settings
from app.core.security import errors as errors_module
from app.core.security.errors import ApplicationError, ErrorCode, require_degraded_generation
from app.core.health import ComponentHealth, HealthReport
from app.core.llm.gateway import LLMGateway
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation import generation as generation_module
from app.services.generation.generation import GenerationService
from tests.fakes.llm import ScriptedLLMTransport


def make_settings(**overrides):
    values = {"_env_file": None}
    values.update(overrides)
    return Settings(**values)


def learner():
    return LearnerProfile(
        learner_id="policy_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="测试失败语义",
    )


def test_fallback_is_blocked_by_default(monkeypatch):
    monkeypatch.setattr(errors_module, "get_settings", lambda: make_settings())
    with pytest.raises(ApplicationError) as caught:
        require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE)
    assert caught.value.code == ErrorCode.LLM_UPSTREAM_UNAVAILABLE


def test_fallback_requires_explicit_non_production_opt_in(monkeypatch):
    settings = make_settings(app_mode="demo", allow_degraded_generation=True)
    monkeypatch.setattr(errors_module, "get_settings", lambda: settings)
    assert require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE) == "LLM_UPSTREAM_UNAVAILABLE"


def test_reviewer_failure_is_degraded_and_not_approved(monkeypatch):
    settings = make_settings(app_mode="demo", allow_degraded_generation=True)
    monkeypatch.setattr(errors_module, "get_settings", lambda: settings)
    gateway = LLMGateway(ScriptedLLMTransport([RuntimeError("secret")]))

    result = reviewer_module.review_node({
        "generated_resources": [],
        "retrieved_chunks": [],
    }, llm_gateway=gateway)

    assert result["review_result"]["passed"] is False
    assert result["trace"][0]["status"] == "degraded"
    assert result["trace"][0]["error_code"] == "LLM_UPSTREAM_UNAVAILABLE"
    assert "secret" not in str(result)


class RecordingWorkflow:
    def __init__(self, result=None):
        self.called = False
        self.result = result or {}

    def invoke(self, state):
        self.called = True
        return self.result


def test_not_ready_blocks_workflow_and_persistence(monkeypatch):
    workflow = RecordingWorkflow()
    repo = MemoryResourceRepository()
    service = GenerationService(repo, workflow)
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: (_ for _ in ()).throw(
            ApplicationError(ErrorCode.GENERATION_DEPENDENCY_UNAVAILABLE)
        ),
    )

    request = GenerateRequest(learner_id="policy_001", topic="测试")
    with pytest.raises(ApplicationError):
        service.generate(learner(), request)

    assert workflow.called is False
    assert repo.list_by_learner("policy_001") == []


def test_degraded_workflow_response_is_not_normal_success(monkeypatch):
    resource = LearningResource(
        resource_id="resource_001",
        resource_type="讲义",
        difficulty="初级",
        content_text=None,
        knowledge_points=["测试"],
        source_refs=[],
    )
    workflow = RecordingWorkflow({
        "generated_resources": [resource],
        "trace": [{
            "agent_name": "generator",
            "action": "生成",
            "output_summary": "fallback",
            "status": "degraded",
            "error_code": "LLM_UPSTREAM_UNAVAILABLE",
        }],
        "diagnosis": {},
        "review_result": {},
        "learning_plan": {},
    })
    report = HealthReport(
        status="degraded",
        app_mode="demo",
        degraded_generation_allowed=True,
        python=ComponentHealth(status="ready"),
        storage=ComponentHealth(
            status="degraded",
            code="STORAGE_MEMORY_EPHEMERAL",
            mode="memory",
            ephemeral=True,
        ),
        llm=ComponentHealth(status="not_ready", code="CFG_LLM_API_KEY_MISSING"),
        embedding=ComponentHealth(status="ready"),
        vector_store=ComponentHealth(status="ready"),
        resources=ComponentHealth(status="ready"),
        error_codes=["STORAGE_MEMORY_EPHEMERAL", "CFG_LLM_API_KEY_MISSING"],
    )
    monkeypatch.setattr(generation_module, "ensure_generation_ready", lambda: report)
    repo = MemoryResourceRepository()
    repo.save(resource, "policy_001", "测试")
    service = GenerationService(repo, workflow)

    response = service.generate(
        learner(),
        GenerateRequest(learner_id="policy_001", topic="测试", resource_types=["讲义"]),
    )

    assert response.execution_status == "degraded"
    assert "LLM_UPSTREAM_UNAVAILABLE" in response.error_codes
    assert "CFG_LLM_API_KEY_MISSING" in response.error_codes
