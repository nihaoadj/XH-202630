"""Create-API guard for the optional Claim evidence retrieval switch (H06).

The invalid-combination rule belongs to the public request contract.  A DTO
test alone cannot prove the API has no side effect, so each rejection below is
sent through the real generation router and everything observable that could
have moved is counted: job rows, supplement sessions/attempts (the only
persisted budget reservations of this feature), LLM sends, retrieval sends and
real workflow invocations.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.generation import generation as generate
from app.core.llm.gateway import LLMGateway
from app.core.retrieval.retriever import EvidenceRetriever
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.supplement import MemoryClaimSupplementRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.main import (
    application_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.models.learning_documents.schemas import (
    GenerateRequest,
    LearnerProfile,
    LearningResource,
)
from app.services.generation import generation as generation_module
from app.services.generation.generation import GenerationService
from app.services.generation.jobs import GenerationJobService
from app.services.learners.profiles import ProfileService

LEARNER_ID = "job-switch"
USER_ID = "user-switch"


class _CountingWorkflow:
    def __init__(self, calls: dict[str, int]):
        self.calls = calls

    def invoke(self, state):
        self.calls["workflow"] += 1
        return {
            **state,
            "generated_resources": [LearningResource(
                resource_id="switch-resource",
                resource_type="讲义",
                difficulty="中级",
                content_text="生成完成",
                knowledge_points=["测试"],
                source_refs=[],
                review_status="unreviewed_draft",
            )],
            "review_result": {"decision": "not_requested", "status": "not_requested"},
            "workflow_status": "completed",
            "final_decision": "未审核草稿",
            "trace": [],
        }


class _RecordingContainer:
    """Records handler access; a rejected request must never touch it."""

    def __init__(self, **services):
        object.__setattr__(self, "_services", services)
        object.__setattr__(self, "accesses", [])

    def __getattr__(self, name: str):
        self.accesses.append(name)
        try:
            return self._services[name]
        except KeyError as error:  # pragma: no cover - explicit failure signal
            raise AttributeError(name) from error


class _User:
    def __init__(self, user_id: str):
        self.user_id = user_id


def _app(monkeypatch, *, current_user: _User | None = None):
    monkeypatch.setattr(
        generation_module, "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )
    monkeypatch.setattr(
        generate, "build_health_report",
        lambda settings: SimpleNamespace(status="ready", error_codes=[]),
    )
    monkeypatch.setattr(generate, "get_settings", lambda: object())

    calls = {"workflow": 0, "llm": 0, "retrieval": 0}
    monkeypatch.setattr(
        LLMGateway, "invoke_structured",
        lambda self, **kwargs: calls.__setitem__("llm", calls["llm"] + 1),
    )
    monkeypatch.setattr(
        EvidenceRetriever, "retrieve",
        lambda self, request: calls.__setitem__("retrieval", calls["retrieval"] + 1),
    )

    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id=LEARNER_ID, user_id=USER_ID, learner_type="测试",
        education="本科", major="软件工程", learning_goal="验证创建开关",
    ))
    resources = MemoryResourceRepository()
    audit = MemoryAuditRepository()
    generation_service = GenerationService(
        resources, _CountingWorkflow(calls), audit,
    )
    job_repo = MemoryGenerationJobRepository()
    job_service = GenerationJobService(job_repo, generation_service)
    claims = MemoryClaimRepository()
    supplement = MemoryClaimSupplementRepository(
        claim_repository=claims, audit_repository=audit,
    )
    container = _RecordingContainer(
        profile_service=lambda: ProfileService(learners),
        generation_job_service=lambda: job_service,
        generation_service=lambda: generation_service,
        runtime_settings=lambda: SimpleNamespace(
            learning_round_creation_enabled=True,
        ),
        round_learning_service=lambda: (_ for _ in ()).throw(
            AssertionError("an invalid round request must not reach the service")
        ),
        claim_repository=lambda: claims,
        supplement_repository=lambda: supplement,
    )
    app = FastAPI()
    app.container = container
    app.add_exception_handler(ApplicationError, application_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    from fastapi.exceptions import StarletteHTTPException

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    def _set_user(request: Request):
        if current_user is not None:
            request.state.current_user = current_user

    app.include_router(
        generate.router, prefix="/api/generate", dependencies=[Depends(_set_user)],
    )
    return TestClient(app), SimpleNamespace(
        container=container, jobs=job_repo, supplement=supplement, calls=calls,
    )


def _jobs_payload(**overrides):
    payload = {
        "learner_id": LEARNER_ID,
        "topic": "验证补检开关",
        "resource_types": ["讲义"],
        "include_review": True,
        "include_claim_check": True,
    }
    payload.update(overrides)
    # ``None`` models an omitted field, which is its own invalid case.
    return {key: value for key, value in payload.items() if value is not None}


def _snapshot(probe) -> dict:
    return {
        "jobs": len(probe.jobs.list_by_learner(LEARNER_ID)),
        "sessions": probe.supplement.list_sessions([]),
        "attempts": probe.supplement.list_attempts("run-switch"),
        "calls": dict(probe.calls),
        "accesses": list(probe.container.accesses),
    }


INVALID_JOBS = {
    "retrieval_without_claim_field": {
        "topic": "缺少 Claim 审核字段",
        "include_claim_evidence_retrieval": True,
        # ``None`` removes the key: the field itself was omitted.
        "include_claim_check": None,
    },
    "retrieval_with_claim_off": {
        "include_claim_evidence_retrieval": True,
        "include_claim_check": False,
    },
    "retrieval_with_review_off": {
        "include_claim_evidence_retrieval": True,
        "include_review": False,
    },
    "retrieval_with_two_types": {
        "include_claim_evidence_retrieval": True,
        "resource_types": ["讲义", "实操指南"],
    },
    "claim_audit_without_review": {
        "include_claim_check": True,
        "include_review": False,
    },
}


@pytest.mark.parametrize("case", sorted(INVALID_JOBS))
def test_invalid_switch_combination_is_422_without_any_side_effect(monkeypatch, case):
    client, probe = _app(monkeypatch)
    before = _snapshot(probe)

    response = client.post(
        "/api/generate/jobs", json=_jobs_payload(**INVALID_JOBS[case]),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["code"] == ErrorCode.REQUEST_VALIDATION_ERROR.value
    assert body["message"] == "请求参数校验失败"
    assert "include_claim" in response.text

    after = _snapshot(probe)
    assert after["jobs"] == before["jobs"] == 0
    assert after["sessions"] == [] and after["attempts"] == []
    assert after["calls"] == {"workflow": 0, "llm": 0, "retrieval": 0}
    # The handler never ran, so not even the container was resolved.
    assert after["accesses"] == []


@pytest.mark.parametrize("case", ["retrieval_with_review_off", "retrieval_with_two_types"])
def test_round_creation_rejects_the_same_switch_on_the_public_contract(monkeypatch, case):
    client, probe = _app(monkeypatch)
    before = _snapshot(probe)
    payload = {
        "schema_version": "1.0",
        "learner_id": LEARNER_ID,
        "topic": "轮次补检开关",
        "selection_key": "switch-round-key",
        "resource_types": ["讲义"],
        "include_review": True,
        "include_claim_check": True,
        "include_claim_evidence_retrieval": True,
        **INVALID_JOBS[case],
    }

    response = client.post("/api/generate/rounds", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.REQUEST_VALIDATION_ERROR.value
    after = _snapshot(probe)
    assert after["jobs"] == before["jobs"] == 0
    assert after["sessions"] == [] and after["attempts"] == []
    assert after["calls"] == {"workflow": 0, "llm": 0, "retrieval": 0}
    assert after["accesses"] == []


def test_server_controlled_constraints_are_rejected_before_job_creation(monkeypatch):
    client, probe = _app(monkeypatch)
    before = _snapshot(probe)

    response = client.post(
        "/api/generate/jobs",
        json=_jobs_payload(
            include_claim_check=False,
            constraints={"learner_focus_snapshot": {"targets": []}},
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.GENERATION_TARGET_INVALID.value
    after = _snapshot(probe)
    assert after["jobs"] == before["jobs"] == 0
    assert after["sessions"] == [] and after["attempts"] == []
    assert after["calls"] == {"workflow": 0, "llm": 0, "retrieval": 0}
    # The constraint guard runs before the container is resolved as well.
    assert after["accesses"] == []


def test_unknown_publication_field_is_forbidden(monkeypatch):
    client, probe = _app(monkeypatch)

    response = client.post(
        "/api/generate/jobs",
        json=_jobs_payload(include_claim_check=False, publication_status="published"),
    )

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.REQUEST_VALIDATION_ERROR.value
    assert "publication_status" in response.text
    assert probe.jobs.list_by_learner(LEARNER_ID) == []
    assert probe.calls == {"workflow": 0, "llm": 0, "retrieval": 0}


def test_closed_branch_creates_exactly_one_job_and_no_supplement_work(monkeypatch):
    """Flag off: five resource types keep the original multi-type behaviour."""

    client, probe = _app(monkeypatch)

    response = client.post("/api/generate/jobs", json=_jobs_payload(
        include_claim_check=False,
        resource_types=["讲义", "实操指南", "分阶测试题", "复习清单", "案例分析"],
    ))

    assert response.status_code == 200
    body = response.json()
    assert probe.calls["workflow"] == 1
    assert len(probe.jobs.list_by_learner(LEARNER_ID)) == 1
    status = client.get(f"/api/generate/jobs/{body['run_id']}")
    assert status.status_code == 200
    payload = status.json()["request_payload"]
    assert payload["include_claim_evidence_retrieval"] is False
    assert payload["include_claim_check"] is False
    assert probe.supplement.list_sessions([body["run_id"]]) == []
    assert probe.supplement.list_attempts(body["run_id"]) == []


def test_legacy_request_without_the_field_stays_closed():
    legacy = GenerateRequest.model_validate({
        "learner_id": LEARNER_ID,
        "topic": "旧请求",
        "resource_types": ["讲义", "实操指南"],
        "include_review": True,
    })
    assert legacy.include_claim_evidence_retrieval is False
    assert "include_claim_evidence_retrieval" not in legacy.model_fields_set


def test_another_users_learner_is_a_404_and_creates_nothing(monkeypatch):
    client, probe = _app(monkeypatch, current_user=_User("someone-else"))

    response = client.post(
        "/api/generate/jobs",
        json=_jobs_payload(include_claim_check=False),
    )

    assert response.status_code == 404
    assert response.json()["message"] == "学习者画像不存在"
    assert probe.jobs.list_by_learner(LEARNER_ID) == []
    assert probe.supplement.list_sessions([LEARNER_ID]) == []
    assert probe.calls == {"workflow": 0, "llm": 0, "retrieval": 0}
