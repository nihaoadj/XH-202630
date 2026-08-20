from datetime import datetime, timezone

import pytest

from app.agents.tutor import TutorAgent, TutorContextBuilder
from app.config import Settings
from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGatewayError
from app.db.learner.memory import MemoryLearnerRepository
from app.db.feedback_loop.memory import MemoryFeedbackLoopRepository
from app.db.resource.memory import MemoryResourceRepository
from app.db.tutor.memory import MemoryTutorRepository
from app.models.common import ErrorInfo
from app.models.persistence import PersistedEvidenceSnapshot
from app.models.schemas import DiagnosticQuestion, LearnerProfile, LearningResource
from app.models.tutor import TutorSessionCreateRequest, TutorTurnSubmitRequest
from app.services.tutor_service import TutorService
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


class _Audit:
    def __init__(self, evidence):
        self.evidence = evidence

    def list_evidence(self, run_id):
        return list(self.evidence)


class _KnowledgeService:
    def load_diagnostic_questions(self, knowledge_base_id):
        return [
            DiagnosticQuestion(
                question_id="q-rerank",
                knowledge_base_id=knowledge_base_id,
                skill_node_id="skill-rerank",
                knowledge_point="rerank",
                question_type="single_choice",
                difficulty="初级",
                question="Rerank 应放在哪个阶段？",
                options=["召回前", "召回后"],
                answer="召回后",
                explanation="服务端秘密答案，不得进入 Tutor context",
            )
        ]


def _profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="learner-tutor",
        user_id="user-a",
        learner_type="student",
        education="undergraduate",
        major="software",
        knowledge_base_id="kb-fixture",
        skill_level="初级",
        weak_points=["rerank"],
        learning_goal="理解 RAG",
    )


def _resource() -> LearningResource:
    return LearningResource(
        resource_id="resource-tutor",
        learner_id="learner-tutor",
        run_id="run-tutor",
        batch_id="batch-tutor",
        topic="RAG rerank",
        resource_type="讲义",
        difficulty="初级",
        content_text="召回得到候选。Rerank 在召回后对候选重新排序。",
        knowledge_points=["rerank"],
        source_refs=[],
        learning_path_node="skill-rerank",
        publication_status="published",
    )


def _gateway_outcomes():
    return [
        {
            "pedagogy_action": "hint",
            "answer_text": "先思考召回结果很多时，下一步要解决什么。",
            "follow_up_question": "Prompt 能容纳全部候选吗？",
            "target_knowledge_points": ["rerank"],
            "cited_evidence_ids": ["ev-tutor"],
        },
        {
            "pedagogy_action": "scaffold",
            "answer_text": "召回候选 → 相关性细排 → 选择少量上下文。",
            "follow_up_question": "中间的细排步骤对应什么？",
            "target_knowledge_points": ["rerank"],
            "cited_evidence_ids": ["ev-tutor"],
        },
        {
            "pedagogy_action": "explanation",
            "answer_text": "Rerank 在召回后对候选进行更精细的相关性排序。",
            "follow_up_question": "候选只有 3 条时收益会一样吗？",
            "target_knowledge_points": ["rerank"],
            "cited_evidence_ids": ["ev-tutor"],
        },
    ]


def _service(*, evidence=True, gateway=None):
    settings = Settings(_env_file=None, rerank_enabled=False)
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(_profile())
    resource_repo = MemoryResourceRepository()
    resource_repo.save(_resource(), "learner-tutor", "RAG rerank")
    snapshots = []
    if evidence:
        snapshots = [
            PersistedEvidenceSnapshot.from_evidence(
                make_evidence(
                    evidence_id="ev-tutor",
                    excerpt="Rerank 在召回后对候选结果重新排序。",
                ),
                run_id="run-tutor",
                retrieval_step_id="step-retrieve",
            )
        ]
    tutor_repo = MemoryTutorRepository()
    llm = gateway or ScriptedLLMGateway(_gateway_outcomes())
    context_builder = TutorContextBuilder(
        audit_repository=_Audit(snapshots),
        evidence_retriever=None,
        knowledge_index=None,
        settings=settings,
    )
    service = TutorService(
        tutor_repo=tutor_repo,
        learner_repo=learner_repo,
        resource_repo=resource_repo,
        knowledge_service=_KnowledgeService(),
        context_builder=context_builder,
        tutor_agent=TutorAgent(llm_gateway=llm, settings=settings),
        settings=settings,
    )
    return service, learner_repo, tutor_repo, llm


def _create(service):
    profile = service.learner_repo.get("learner-tutor")
    return service.create_session(
        profile,
        TutorSessionCreateRequest(
            learner_id="learner-tutor",
            source_type="run",
            run_id="run-tutor",
            context_type="question_help",
            question_id="q-rerank",
        ),
    )


def test_service_progresses_three_turns_restores_and_has_no_formal_side_effects():
    service, learner_repo, tutor_repo, _ = _service()
    before = learner_repo.get("learner-tutor")
    before_resource = service.resource_repo.get("resource-tutor")
    feedback_loop = MemoryFeedbackLoopRepository(learner_repo)
    before_path = feedback_loop.get_current_path("learner-tutor")
    session = _create(service)
    first = service.submit_turn(
        before,
        session.session_id,
        TutorTurnSubmitRequest(
            client_message_id="client-turn-0001",
            message="为什么需要 rerank？",
        ),
    )
    second = service.submit_turn(
        before,
        session.session_id,
        TutorTurnSubmitRequest(
            client_message_id="client-turn-0002",
            message="前面提示我还是不懂，请再解释",
        ),
    )
    third = service.submit_turn(
        before,
        session.session_id,
        TutorTurnSubmitRequest(
            client_message_id="client-turn-0003",
            message="请结合证据说明",
        ),
    )
    assert [first.hint_level, second.hint_level, third.hint_level] == [1, 2, 3]
    assert [first.pedagogy_action, second.pedagogy_action, third.pedagogy_action] == [
        "hint",
        "scaffold",
        "explanation",
    ]
    assert all(item.source_refs[0].evidence_id == "ev-tutor" for item in (first, second, third))
    detail = service.get_session_detail(session.session_id)
    assert len(detail.turns) == 3
    assert tutor_repo.count_turns(
        "learner-tutor",
        source_run_id="run-tutor",
        context_type="question_help",
    ) == 3
    assert learner_repo.get("learner-tutor") == before
    assert service.resource_repo.get("resource-tutor") == before_resource
    assert feedback_loop.get_current_path("learner-tutor") == before_path


def test_service_creates_and_restores_batch_scoped_question_session():
    service, learner_repo, tutor_repo, _ = _service()
    profile = learner_repo.get("learner-tutor")
    payload = TutorSessionCreateRequest(
        learner_id="learner-tutor",
        source_type="batch",
        batch_id="batch-tutor",
        context_type="question_help",
        question_id="q-rerank",
    )

    first = service.create_session(profile, payload)
    restored = service.create_session(profile, payload)

    assert restored.session_id == first.session_id
    assert first.source_batch_id == "batch-tutor"
    assert first.source_run_id == "run-tutor"
    assert first.source_resource_id == "resource-tutor"
    assert tutor_repo.list_sessions(
        "learner-tutor",
        source_batch_id="batch-tutor",
        context_type="question_help",
    )[0].session_id == first.session_id


def test_service_idempotent_replay_and_conflict():
    service, learner_repo, _, _ = _service()
    profile = learner_repo.get("learner-tutor")
    session = _create(service)
    payload = TutorTurnSubmitRequest(
        client_message_id="client-turn-replay",
        message="给我提示",
    )
    first = service.submit_turn(profile, session.session_id, payload)
    replay = service.submit_turn(profile, session.session_id, payload)
    assert replay.turn_id == first.turn_id
    assert replay.idempotent_replay is True

    with pytest.raises(ApplicationError) as caught:
        service.submit_turn(
            profile,
            session.session_id,
            TutorTurnSubmitRequest(
                client_message_id="client-turn-replay",
                message="换一个不同请求",
            ),
        )
    assert caught.value.code == ErrorCode.TUTOR_IDEMPOTENCY_CONFLICT


def test_service_fails_closed_without_evidence_and_does_not_call_llm():
    gateway = ScriptedLLMGateway([])
    service, learner_repo, tutor_repo, _ = _service(evidence=False, gateway=gateway)
    profile = learner_repo.get("learner-tutor")
    session = _create(service)
    response = service.submit_turn(
        profile,
        session.session_id,
        TutorTurnSubmitRequest(
            client_message_id="client-no-evidence",
            message="直接告诉我答案",
        ),
    )
    assert response.grounding_status == "evidence_insufficient"
    assert response.source_refs == []
    assert response.error_code == ErrorCode.EVIDENCE_INSUFFICIENT.value
    assert gateway.calls == []
    assert tutor_repo.list_turns(session.session_id)[0].model_name is None


def test_service_rejects_invalid_citation_without_persisting_false_success():
    gateway = ScriptedLLMGateway(
        [
            {
                "pedagogy_action": "hint",
                "answer_text": "不安全引用",
                "follow_up_question": "继续吗？",
                "target_knowledge_points": ["rerank"],
                "cited_evidence_ids": ["invented"],
            }
        ]
    )
    service, learner_repo, tutor_repo, _ = _service(gateway=gateway)
    profile = learner_repo.get("learner-tutor")
    session = _create(service)
    with pytest.raises(ApplicationError) as caught:
        service.submit_turn(
            profile,
            session.session_id,
            TutorTurnSubmitRequest(
                client_message_id="client-bad-citation",
                message="提示",
            ),
        )
    assert caught.value.code == ErrorCode.TUTOR_GROUNDING_INVALID
    assert tutor_repo.list_turns(session.session_id) == []


class _FailingAgent:
    def __init__(self, code):
        self.code = code

    def invoke(self, agent_input):
        raise LLMGatewayError(
            error=ErrorInfo(
                code=self.code.value,
                category="upstream",
                message="sanitized",
                retryable=False,
                source="tutor",
            ),
            call_id="call-failure",
            retry_count=0,
            latency_ms=1,
            attempts=[],
        )


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.LLM_TIMEOUT,
        ErrorCode.LLM_AUTH_FAILED,
        ErrorCode.LLM_BAD_REQUEST,
        ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
    ],
)
def test_service_preserves_sanitized_llm_failure_semantics(code):
    service, learner_repo, tutor_repo, _ = _service()
    service.tutor_agent = _FailingAgent(code)
    profile = learner_repo.get("learner-tutor")
    session = _create(service)
    with pytest.raises(ApplicationError) as caught:
        service.submit_turn(
            profile,
            session.session_id,
            TutorTurnSubmitRequest(
                client_message_id=f"client-{code.value}",
                message="提示",
            ),
        )
    assert caught.value.code == code
    assert caught.value.status_code == 503
    assert tutor_repo.list_turns(session.session_id) == []
