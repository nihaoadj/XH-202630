from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents.learning_agents.tutor_agent import (
    TutorAgent,
    TutorContextBuilder,
    TutorGroundingValidationError,
)
from app.config import Settings
from app.models.shared.persistence import PersistedEvidenceSnapshot
from app.models.learning_documents.schemas import LearnerProfile, LearningResource, SourceRef
from app.models.tutor.tutor import TutorQuestionContext, TutorSession
from backend.tests.fakes.evidence import (
    ScriptedEvidenceRetriever,
    make_available_batch,
    make_evidence,
)
from backend.tests.fakes.llm import ScriptedLLMGateway


class _Audit:
    def __init__(self, evidence):
        self.evidence = evidence

    def list_evidence(self, run_id):
        return list(self.evidence)


class _FailingAudit:
    def list_evidence(self, run_id):
        raise RuntimeError("audit unavailable")


class _Index:
    def __init__(self, status="ready"):
        self.status = status

    def get_index_status(self, knowledge_base_id):
        return {"status": self.status}


def _settings(**overrides):
    return Settings(_env_file=None, rerank_enabled=False, **overrides)


def _session() -> TutorSession:
    return TutorSession(
        session_id="tus-agent-1",
        learner_id="learner-1",
        source_type="resource",
        source_resource_id="resource-1",
        source_run_id="run-1",
        knowledge_base_id="kb-fixture",
        context_type="question_help",
        question_id="question-1",
        skill_node_id="skill-rerank",
        knowledge_point="rerank",
    )


def _profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="learner-1",
        learner_type="student",
        education="undergraduate",
        major="software",
        target_domain="RAG",
        knowledge_base_id="kb-fixture",
        skill_level="初级",
        weak_points=["rerank"],
        strong_points=["retrieval"],
        learning_goal="掌握可信 RAG",
    )


def _resource(source_refs=None) -> LearningResource:
    return LearningResource(
        resource_id="resource-1",
        learner_id="learner-1",
        run_id="run-1",
        topic="RAG rerank",
        resource_type="讲义",
        difficulty="初级",
        content_text="召回会得到多个候选。\n\nRerank 会对候选结果做更精细的相关性排序。",
        knowledge_points=["rerank"],
        source_refs=source_refs or [],
        publication_status="published",
    )


def _question() -> TutorQuestionContext:
    return TutorQuestionContext(
        question_id="question-1",
        question="Rerank 应位于哪个阶段？",
        question_type="single_choice",
        options=["召回前", "召回后"],
        skill_node_id="skill-rerank",
        knowledge_point="rerank",
        difficulty="初级",
    )


def test_context_builder_prefers_frozen_evidence_and_projects_profile():
    evidence = make_evidence(evidence_id="ev-frozen")
    snapshot = PersistedEvidenceSnapshot.from_evidence(
        evidence,
        run_id="run-1",
        retrieval_step_id="step-1",
    )
    builder = TutorContextBuilder(
        audit_repository=_Audit([snapshot]),
        evidence_retriever=None,
        knowledge_index=None,
        settings=_settings(),
    )
    grounding = builder.resolve_grounding(
        session=_session(),
        resource=_resource(
            [SourceRef(doc_id="legacy", title="Legacy", snippet="legacy", score=0.5)]
        ),
        message="为什么需要 rerank",
        turn_id="turn-1",
        question_context=_question(),
    )
    assert grounding.source == "frozen_evidence"
    assert grounding.evidence[0].evidence_id == "ev-frozen"

    agent_input = builder.build_input(
        session=_session(),
        turn_id="turn-1",
        profile=_profile(),
        resource=_resource(),
        question_context=_question(),
        recent_turns=[],
        message="为什么需要 rerank",
        hint_level=1,
        allowed_actions=("hint", "guided_question"),
        grounding=grounding,
    )
    assert agent_input.learner_context.skill_level == "初级"
    assert agent_input.learner_context.weak_points == ["rerank"]
    assert "Rerank" in agent_input.resource_context.relevant_excerpt


def test_context_builder_source_ref_then_fresh_retrieval_then_fail_closed():
    builder = TutorContextBuilder(
        audit_repository=_Audit([]),
        evidence_retriever=None,
        knowledge_index=None,
        settings=_settings(),
    )
    source = builder.resolve_grounding(
        session=_session(),
        resource=_resource(
            [SourceRef(doc_id="doc", title="Doc", snippet="可信片段", score=0.8)]
        ),
        message="rerank",
        turn_id="turn-1",
        question_context=_question(),
    )
    assert source.source == "source_refs"

    fresh_evidence = make_evidence(evidence_id="ev-fresh")
    retriever = ScriptedEvidenceRetriever([make_available_batch([fresh_evidence])])
    fresh_builder = TutorContextBuilder(
        audit_repository=_Audit([]),
        evidence_retriever=retriever,
        knowledge_index=_Index("ready"),
        settings=_settings(),
    )
    fresh = fresh_builder.resolve_grounding(
        session=_session(),
        resource=_resource(),
        message="rerank",
        turn_id="turn-2",
        question_context=_question(),
    )
    assert fresh.source == "fresh_retrieval"
    assert fresh.evidence[0].evidence_id == "ev-fresh"
    assert fresh.retrieval_query_hash is not None

    closed = TutorContextBuilder(
        audit_repository=_Audit([]),
        evidence_retriever=retriever,
        knowledge_index=_Index("not_ready"),
        settings=_settings(),
    ).resolve_grounding(
        session=_session(),
        resource=_resource(),
        message="rerank",
        turn_id="turn-3",
        question_context=_question(),
    )
    assert closed.status == "evidence_insufficient"
    assert closed.source == "none"


def test_context_builder_can_use_explicit_source_ref_when_frozen_lookup_fails():
    builder = TutorContextBuilder(
        audit_repository=_FailingAudit(),
        evidence_retriever=None,
        knowledge_index=None,
        settings=_settings(),
    )
    resolution = builder.resolve_grounding(
        session=_session(),
        resource=_resource(
            [SourceRef(doc_id="legacy", title="Legacy", snippet="可信片段", score=0.8)]
        ),
        message="rerank",
        turn_id="turn-audit-failure",
        question_context=_question(),
    )
    assert resolution.source == "source_refs"


def _agent_input():
    evidence = make_evidence(evidence_id="ev-allowed")
    snapshot = PersistedEvidenceSnapshot.from_evidence(
        evidence,
        run_id="run-1",
        retrieval_step_id="step-1",
    )
    builder = TutorContextBuilder(
        audit_repository=_Audit([snapshot]),
        evidence_retriever=None,
        knowledge_index=None,
        settings=_settings(),
    )
    grounding = builder.resolve_grounding(
        session=_session(),
        resource=_resource(),
        message="为什么需要 rerank",
        turn_id="turn-agent",
        question_context=_question(),
    )
    return builder.build_input(
        session=_session(),
        turn_id="turn-agent",
        profile=_profile(),
        resource=_resource(),
        question_context=_question(),
        recent_turns=[],
        message="为什么需要 rerank",
        hint_level=1,
        allowed_actions=("hint", "guided_question"),
        grounding=grounding,
    )


def test_tutor_agent_uses_gateway_and_validates_citation_subset():
    gateway = ScriptedLLMGateway(
        [
            {
                "pedagogy_action": "hint",
                "answer_text": "先关注召回结果的数量与质量。",
                "follow_up_question": "候选很多时能全部放进 Prompt 吗？",
                "target_knowledge_points": ["rerank"],
                "cited_evidence_ids": ["ev-allowed"],
            }
        ]
    )
    result = TutorAgent(llm_gateway=gateway, settings=_settings()).invoke(_agent_input())
    assert result.output.pedagogy_action == "hint"
    human_prompt = gateway.calls[0]["messages"][1].content
    assert '"skill_level": "初级"' in human_prompt
    assert "ev-allowed" in human_prompt
    assert "learner_id" not in human_prompt


@pytest.mark.parametrize(
    "patch",
    [
        {"cited_evidence_ids": ["ev-invented"]},
        {"pedagogy_action": "explanation"},
    ],
)
def test_tutor_agent_rejects_invented_citation_or_level_escape(patch):
    output = {
        "pedagogy_action": "hint",
        "answer_text": "提示",
        "follow_up_question": "你能继续推理吗？",
        "target_knowledge_points": ["rerank"],
        "cited_evidence_ids": ["ev-allowed"],
        **patch,
    }
    gateway = ScriptedLLMGateway([output])
    with pytest.raises(TutorGroundingValidationError):
        TutorAgent(llm_gateway=gateway, settings=_settings()).invoke(_agent_input())
