from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.agents.tutor import TutorAgent, TutorContextBuilder
from app.api import tutor
from app.config import Settings
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.db.tutor.memory import MemoryTutorRepository
from app.models.persistence import PersistedEvidenceSnapshot
from app.models.schemas import DiagnosticQuestion, LearnerProfile, LearningResource
from app.services.profile_service import ProfileService
from app.services.tutor_service import TutorService
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


class _Audit:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def list_evidence(self, run_id):
        return [self.snapshot] if run_id == "run-owner" else []


class _Knowledge:
    def load_diagnostic_questions(self, knowledge_base_id):
        return [
            DiagnosticQuestion(
                question_id="question-owner",
                knowledge_base_id=knowledge_base_id,
                skill_node_id="skill-owner",
                knowledge_point="rerank",
                question_type="single_choice",
                question="Rerank 在哪里？",
                options=["召回前", "召回后"],
                answer="召回后",
            )
        ]


def _client(current_user_id="user-owner"):
    learner_repo = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner-owner",
        user_id="user-owner",
        learner_type="student",
        education="undergraduate",
        major="software",
        knowledge_base_id="kb-fixture",
        learning_goal="RAG",
    )
    learner_repo.save(profile)
    resource_repo = MemoryResourceRepository()
    resource_repo.save(
        LearningResource(
            resource_id="resource-owner",
            learner_id="learner-owner",
            run_id="run-owner",
            topic="Rerank",
            resource_type="讲义",
            difficulty="初级",
            content_text="Rerank 在召回后细排候选。",
            knowledge_points=["rerank"],
            source_refs=[],
            publication_status="published",
        ),
        "learner-owner",
        "Rerank",
    )
    snapshot = PersistedEvidenceSnapshot.from_evidence(
        make_evidence(evidence_id="ev-owner"),
        run_id="run-owner",
        retrieval_step_id="step-owner",
    )
    settings = Settings(_env_file=None, rerank_enabled=False)
    gateway = ScriptedLLMGateway(
        [
            {
                "pedagogy_action": "hint",
                "answer_text": "先看召回后候选的排序问题。",
                "follow_up_question": "候选很多时怎么办？",
                "target_knowledge_points": ["rerank"],
                "cited_evidence_ids": ["ev-owner"],
            }
        ]
    )
    context_builder = TutorContextBuilder(
        audit_repository=_Audit(snapshot),
        evidence_retriever=None,
        knowledge_index=None,
        settings=settings,
    )
    service = TutorService(
        tutor_repo=MemoryTutorRepository(),
        learner_repo=learner_repo,
        resource_repo=resource_repo,
        knowledge_service=_Knowledge(),
        context_builder=context_builder,
        tutor_agent=TutorAgent(llm_gateway=gateway, settings=settings),
        settings=settings,
    )
    app = FastAPI()
    app.state.current_user_id = current_user_id
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        tutor_service=lambda: service,
    )

    @app.middleware("http")
    async def attach_user(request: Request, call_next):
        request.state.current_user = SimpleNamespace(
            user_id=request.app.state.current_user_id
        )
        return await call_next(request)

    app.include_router(tutor.router, prefix="/api/tutor")
    return TestClient(app)


def test_tutor_api_session_turn_restore_list_and_close():
    client = _client()
    created = client.post(
        "/api/tutor/sessions",
        json={
            "learner_id": "learner-owner",
            "source_type": "run",
            "run_id": "run-owner",
            "context_type": "question_help",
            "question_id": "question-owner",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    turn = client.post(
        f"/api/tutor/sessions/{session_id}/turns",
        json={"client_message_id": "api-message-0001", "message": "给我一个提示"},
    )
    assert turn.status_code == 200
    assert turn.json()["hint_level"] == 1
    assert turn.json()["source_refs"][0]["evidence_id"] == "ev-owner"
    assert "raw_prompt" not in turn.text

    restored = client.get(f"/api/tutor/sessions/{session_id}")
    assert restored.status_code == 200
    assert len(restored.json()["turns"]) == 1
    listed = client.get(
        "/api/tutor/sessions",
        params={"learner_id": "learner-owner", "run_id": "run-owner"},
    )
    assert listed.json()["total"] == 1
    assert client.post(f"/api/tutor/sessions/{session_id}/close").json()["status"] == "closed"


def test_tutor_api_hides_cross_user_profile_resource_and_session():
    client = _client(current_user_id="user-other")
    response = client.post(
        "/api/tutor/sessions",
        json={
            "learner_id": "learner-owner",
            "source_type": "resource",
            "resource_id": "resource-owner",
            "context_type": "resource_help",
        },
    )
    assert response.status_code == 404


def test_tutor_api_hides_existing_session_after_cross_user_switch():
    client = _client()
    created = client.post(
        "/api/tutor/sessions",
        json={
            "learner_id": "learner-owner",
            "source_type": "resource",
            "resource_id": "resource-owner",
            "context_type": "resource_help",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    client.app.state.current_user_id = "user-other"
    assert client.get(f"/api/tutor/sessions/{session_id}").status_code == 404
    assert client.post(f"/api/tutor/sessions/{session_id}/close").status_code == 404
    assert client.post(
        f"/api/tutor/sessions/{session_id}/turns",
        json={"client_message_id": "cross-user-message", "message": "提示"},
    ).status_code == 404
