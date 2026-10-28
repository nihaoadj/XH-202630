"""Small prompt/input contract checks; no real model or business persistence."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.agents.resource_agents import TextResourceAgent
from app.agents.resource_agents.base import BaseResourceGenerationAgent
from app.agents.resource_agents.lecture_contract import (
    LECTURE_CONTRACT_VERSION, LECTURE_REVIEW_GUIDANCE, TEACHING_RULES,
    node_display_names, teaching_contract,
)
from app.agents.resource_agents.text import TEXT_RESOURCE_PROMPT
from app.agents.resource_workflows.learning_documents.reviewer_agent import REVIEW_PROMPT, review_node
from app.core.retrieval.evidence import source_refs_from_evidence
from app.core.security.errors import ApplicationError
from app.models.learning_documents.schemas import LearningResource
from tests.fakes.llm import ScriptedLLMGateway
from tests.unit.agents.test_resource_type_agents import _inputs, CASE_STUDY_MARKDOWN


@pytest.mark.parametrize("difficulty,target", [("初级", [1800, 3200]), ("中级", [3200, 6000]), ("高级", [4500, 7500])])
def test_audience_targets_are_guidance_not_model_budget_changes(difficulty, target):
    contract = teaching_contract(difficulty, 1)
    assert contract["target_chars"] == target and contract["explanation_subsections"] == [2, 4]
    assert contract["version"] == LECTURE_CONTRACT_VERSION
    assert "最低字数" not in TEXT_RESOURCE_PROMPT or "不是最低字数" in TEXT_RESOURCE_PROMPT


def test_explicit_difficulty_precedes_stage_and_unknown_level_can_use_stage():
    assert teaching_contract("高级", 1, target_tier=1)["audience"] == "高级"
    assert teaching_contract("未指定", 2, target_tier=1, learner_level="高级")["audience"] == "初级"
    assert teaching_contract("未指定", 2, learner_level="高级")["audience"] == "高级"


def names_fixture(monkeypatch):
    monkeypatch.setattr("app.core.retrieval.knowledge_base.resolve_knowledge_base_dir_by_id", lambda kb: Path("synthetic"))
    monkeypatch.setattr("app.core.retrieval.knowledge_base.load_knowledge_base_manifest", lambda path: {
        "knowledge_base_id": "kb-fixture", "skill_nodes": [{"node_id": "rag_basics", "name": "RAG基础概念"}]})


def test_display_projection_never_changes_spec_context_or_frozen_evidence(monkeypatch):
    names_fixture(monkeypatch)
    spec, context, _ = _inputs("讲义")
    spec = spec.model_copy(update={"knowledge_points": ["rag_basics", "encode_query"],
        "learning_objective": "解释rag_basics和encode_query", "node_evidence_map": {}})
    context = context.model_copy(update={"topic": "讲义 · rag_basics · 第1阶",
        "learning_path": [{"topic": "rag_basics", "reason": "理解rag_basics"}]})
    before = deepcopy((spec.model_dump(), context.model_dump()))
    messages = TextResourceAgent().build_messages(spec, context)
    payload = json.loads(messages[1].content.split("\n", 1)[1])
    assert "RAG基础概念" in payload["display_title"] and "rag_basics" not in payload["display_title"]
    assert payload["learning_path"][0]["topic"] == "RAG基础概念"
    assert payload["learning_path"][0]["reason"] == "理解RAG基础概念"
    assert payload["learning_objective"] == "解释RAG基础概念和encode_query"
    assert "encode_query" in payload["learning_objective"]
    assert payload["knowledge_points"] == spec.knowledge_points
    original = BaseResourceGenerationAgent.common_prompt_payload(TextResourceAgent(), spec, context)
    assert payload["evidence"] == original["evidence"]
    assert before == (spec.model_dump(), context.model_dump())


def test_unknown_kb_and_mixed_scoped_kbs_do_not_guess_names(monkeypatch):
    names_fixture(monkeypatch)
    _, context, evidence = _inputs("讲义")
    other = evidence.model_copy(update={"knowledge_base_id": "other"})
    assert node_display_names(["rag_basics"], [evidence, other]) == {}
    monkeypatch.setattr("app.core.retrieval.knowledge_base.load_knowledge_base_manifest", lambda path: (_ for _ in ()).throw(ValueError("unavailable")))
    assert node_display_names(["rag_basics"], context.evidence) == {}


def test_out_of_scope_evidence_is_not_added_for_teaching_convenience():
    spec, context, _ = _inputs("讲义")
    with pytest.raises(ApplicationError):
        TextResourceAgent().build_messages(spec.model_copy(update={"evidence_ids": ["missing"]}), context)


def test_generation_and_review_share_all_teaching_rules_and_version():
    assert set(TEACHING_RULES) == {"self_contained", "audience", "presentation", "scope", "progression"}
    assert all(value in LECTURE_REVIEW_GUIDANCE for value in TEACHING_RULES.values())
    assert "lab-B" in TEXT_RESOURCE_PROMPT and "Q1–Q4" in TEXT_RESOURCE_PROMPT
    assert "内部完成" in TEXT_RESOURCE_PROMPT and "不输出自检报告" in TEXT_RESOURCE_PROMPT
    assert TextResourceAgent.prompt_version == "text-resource-v6-teaching-contract"


@pytest.mark.parametrize("kind", ["讲义", "案例分析"])
def test_existing_review_call_gets_rubric_only_for_lecture(kind):
    spec, context, evidence = _inputs(kind)
    resource = LearningResource(resource_id="lecture-rubric-test", learner_id="learner",
        run_id=context.run_id, batch_id=context.batch_id, topic=context.topic, resource_type=kind,
        difficulty="中级", knowledge_points=list(spec.knowledge_points),
        content_text="# 受控检索\n\n## 学习目标\n\n只使用已给证据。" if kind == "讲义" else CASE_STUDY_MARKDOWN,
        source_refs=source_refs_from_evidence([evidence]))
    gateway = ScriptedLLMGateway([{"decision": "approve", "hallucination_score": 0.0, "issues": [],
        "difficulty_match": True, "coverage_rate": 1.0, "suggestion": "符合证据与教学边界。", "revision_instructions": []}])
    result = review_node({"run_id": context.run_id, "batch_id": context.batch_id,
        "generated_resources": [resource], "retrieved_evidence": [evidence], "trace": []}, llm_gateway=gateway)
    assert len(gateway.calls) == 1 and result["review_result"]["decision"] == "approve"
    system = gateway.calls[0]["messages"][0].content
    if kind == "讲义":
        assert system == REVIEW_PROMPT + LECTURE_REVIEW_GUIDANCE
        assert "讲义教学控制信息" in gateway.calls[0]["messages"][1].content
    else:
        assert system == REVIEW_PROMPT and "讲义教学控制信息" not in gateway.calls[0]["messages"][1].content
