from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
from app.agents.resource_agents import AssessmentAgent, CaseStudyAgent, CorrectionTrainingPackageAgent, ReviewChecklistAgent
from app.agents.resource_agents.practice import PRACTICE_GUIDE_PROMPT
from app.agents.resource_agents.registry import get_resource_agent, normalize_resource_type
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.agents.resource_workflows.learning_documents.reviewer_agent import (
    _deterministic_practice_guide_review,
    _deterministic_resource_structure_review,
    review_node,
)
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import ResourceGenerationContext
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


CHECKLIST_MARKDOWN = """# 受控检索复习清单

## 复习目标

掌握受控检索的证据边界。

## 必会清单

- [ ] 能说明证据范围。

## 易错点

- 把证据外内容当成结论；应先核对证据 ID。

## 自测清单

- [ ] 我能说明答案对应的证据。

## 复习节奏

第 1 天完成必会清单，第 3 天完成自测。
"""


CASE_STUDY_MARKDOWN = """# 受控检索案例分析

## 案例背景

团队需要根据冻结证据回答检索问题。

## 任务目标

1. 判断可使用的证据范围。
2. 给出可验证的回答。

## 分析过程

事实：当前仅有冻结证据。判断：不能补充证据外结论。行动：核对证据 ID。

## 参考方案

依据冻结证据组织回答，并在提交前核对每项结论可映射到证据。

## 复盘要点

- 先确认事实边界，再形成判断。
"""


def _inputs(resource_type: str):
    evidence = make_evidence(evidence_id="ev-new-resource-type")
    specs = build_resource_specs(
        run_id="run-new-resource-type",
        resource_types=[resource_type],
        topic="受控检索",
        difficulty="中级",
        learning_plan={"learning_path": [{"topic": "检索", "order": 1}]},
        evidence=[evidence],
        target_skill_nodes=["skill-search"],
    )
    context = ResourceGenerationContext(
        run_id="run-new-resource-type",
        batch_id="run-new-resource-type",
        topic="受控检索",
        evidence=[evidence],
    )
    return specs[0], context, evidence


@pytest.mark.parametrize(
    ("resource_type", "agent_type", "markdown", "required_section"),
    [
        ("复习清单", ReviewChecklistAgent, CHECKLIST_MARKDOWN, "## 自测清单"),
        ("案例分析", CaseStudyAgent, CASE_STUDY_MARKDOWN, "## 参考方案"),
    ],
)
def test_new_resource_agents_generate_evidence_scoped_markdown(
    resource_type,
    agent_type,
    markdown,
    required_section,
):
    spec, context, _ = _inputs(resource_type)

    artifact = agent_type().generate(spec, context, llm_gateway=ScriptedLLMGateway([markdown]))

    assert artifact.metadata.resource_type == resource_type
    assert artifact.metadata.source_evidence_ids == spec.evidence_ids
    assert artifact.content_text.startswith("# ")
    assert required_section in artifact.content_text
    assert artifact.knowledge_points == spec.knowledge_points


@pytest.mark.parametrize(
    ("resource_type", "agent_type"),
    [("复习清单", ReviewChecklistAgent), ("案例分析", CaseStudyAgent)],
)
def test_new_resource_agents_reject_missing_required_sections(resource_type, agent_type):
    spec, context, _ = _inputs(resource_type)

    with pytest.raises(ApplicationError) as caught:
        agent_type().generate(
            spec,
            context,
            llm_gateway=ScriptedLLMGateway(["# 不完整资源\n\n## 学习目标\n\n内容"]),
        )

    assert caught.value.code == ErrorCode.LLM_OUTPUT_SCHEMA_INVALID


def test_new_resource_types_are_registered_and_requestable():
    assert isinstance(get_resource_agent("复习清单"), ReviewChecklistAgent)
    assert isinstance(get_resource_agent("案例分析"), CaseStudyAgent)
    assert normalize_resource_type("复习清单") == "复习清单"
    assert isinstance(get_resource_agent("个性化纠错训练包"), CorrectionTrainingPackageAgent)
    assert GenerateRequest(
        learner_id="learner-new-resource-type",
        topic="受控检索",
        resource_types=["复习清单", "案例分析"],
    ).resource_types == ["复习清单", "案例分析"]


def test_correction_package_requires_frozen_focus_and_complete_units():
    evidence = make_evidence(evidence_id="ev-correction")
    focus = {"focus_snapshot_hash": "a" * 64, "difficulty": "中级", "scaffolding_level": "high", "ordered_target_nodes": [
        {"skill_node_id": "skill-search", "name": "检索能力", "reason_codes": ["LEARNED_OBJECTIVELY_NOT_MASTERED"]}
    ]}
    spec = build_resource_specs(
        run_id="run-correction", resource_types=["个性化纠错训练包"], topic="受控检索", difficulty="中级",
        learning_plan={"correction_focus_snapshot": focus}, evidence=[evidence], target_skill_nodes=["skill-search"],
    )[0]
    context = ResourceGenerationContext(run_id="run-correction", batch_id="run-correction", topic="受控检索", evidence=[evidence], constraints={"correction_focus_snapshot": focus})
    content = """# 薄弱点强化包：受控检索
## 本次强化目标
目标。
## 薄弱模式概览
概览。
## 强化单元：检索能力
### 错误模式
误区。
### 核心概念补救
补救。
### 正误对照
对照。
### 完整示例
示例。
### 引导式练习
练习一。
### 同构练习
练习二。
### 迁移练习
练习三。
## 参考答案与分层反馈
反馈。
## 达标标准
标准。
## 后续复习动作
动作。
## 总结
总结。"""
    artifact = CorrectionTrainingPackageAgent().generate(spec, context, llm_gateway=ScriptedLLMGateway([content]))
    assert artifact.metadata.resource_type == "个性化纠错训练包"
    assert artifact.artifact_data["correction_focus_snapshot_hash"] == "a" * 64


def test_correction_package_uses_a_bounded_output_budget_and_repairs_format_once():
    evidence = make_evidence(evidence_id="ev-correction-repair")
    focus = {"focus_snapshot_hash": "b" * 64, "difficulty": "中级", "scaffolding_level": "high", "ordered_target_nodes": [
        {"skill_node_id": "skill-search", "name": "检索能力", "reason_codes": ["LEARNED_OBJECTIVELY_NOT_MASTERED"]}
    ]}
    spec = build_resource_specs(
        run_id="run-correction-repair", resource_types=["个性化纠错训练包"], topic="受控检索", difficulty="中级",
        learning_plan={"correction_focus_snapshot": focus}, evidence=[evidence], target_skill_nodes=["skill-search"],
    )[0]
    context = ResourceGenerationContext(
        run_id="run-correction-repair", batch_id="run-correction-repair", topic="受控检索", evidence=[evidence],
        constraints={"correction_focus_snapshot": focus},
    )
    incomplete = "# 薄弱点强化包\n\n## 本次强化目标\n\n目标。"
    complete = """# 薄弱点强化包：受控检索
## 本次强化目标
目标。
## 薄弱模式概览
概览。
## 强化单元：检索能力
### 错误模式
误区。
### 核心概念补救
补救。
### 正误对照
对照。
### 完整示例
示例。
### 引导式练习
练习一。
### 同构练习
练习二。
### 迁移练习
练习三。
## 参考答案与分层反馈
反馈。
## 达标标准
标准。
## 后续复习动作
动作。
## 总结
总结。"""
    gateway = ScriptedLLMGateway([incomplete, complete])

    artifact = CorrectionTrainingPackageAgent().generate(spec, context, llm_gateway=gateway)

    assert artifact.content_text == complete
    assert artifact.artifact_data["format_repair_attempted"] is True
    assert len(gateway.calls) == 2
    assert all(call["options"].max_output_tokens == 32768 for call in gateway.calls)
    assert all(call["options"].request_timeout_seconds == 300.0 for call in gateway.calls)
    assert all(call["options"].max_attempts == 2 for call in gateway.calls)


def test_correction_package_cannot_mix_with_general_resource_types():
    evidence = make_evidence(evidence_id="ev-correction-mixed")
    with pytest.raises(ApplicationError) as caught:
        build_resource_specs(
            run_id="run-correction-mixed", resource_types=["讲义", "个性化纠错训练包"], topic="受控检索",
            difficulty="中级", learning_plan={}, evidence=[evidence], target_skill_nodes=["skill-search"],
        )
    assert caught.value.code == ErrorCode.WORKFLOW_CONTRACT_INVALID


def test_practice_guide_prompt_forbids_literal_secret_examples():
    assert 'api_key="..."' in PRACTICE_GUIDE_PROMPT
    assert 'os.getenv("OPENAI_API_KEY")' in PRACTICE_GUIDE_PROMPT


def test_practice_guide_review_does_not_block_generated_secret_like_examples():
    placeholder = SimpleNamespace(
        resource_type="实操指南",
        content_text="# 示例\n\n准备\n实践步骤\n检查清单\n常见问题\n复盘建议\n\nOPENAI_API_KEY=\"YOUR_API_KEY\"",
    )
    real_secret = SimpleNamespace(
        resource_type="实操指南",
        content_text="# 示例\n\n准备\n实践步骤\n检查清单\n常见问题\n复盘建议\n\napi_key=\"sk-abcdefghijklmnopqrstuvwx\"",
    )

    assert _deterministic_practice_guide_review(placeholder)["decision"] == "approve"
    assert _deterministic_practice_guide_review(real_secret)["decision"] == "approve"


def test_assessment_agent_retries_node_json_structure_before_failing():
    spec, context, evidence = _inputs("分阶测试题")
    choice = lambda local_id, question_type, answers: {
        "local_id": local_id, "question_type": question_type, "stem": "受控检索应如何使用冻结证据？",
        "options": [{"option_id": key, "text": f"选项 {key}"} for key in "ABCD"],
        "answer_option_ids": answers, "knowledge_point_tags": ["skill-search"], "evidence_ids": [evidence.evidence_id],
    }
    valid = {
        "schema_version": "2.0", "skill_node_id": "skill-search", "skill_node_name": "检索能力",
        "single_choice_questions": [choice("single-1", "single_choice", ["A"]), choice("single-2", "single_choice", ["B"])],
        "multiple_choice_questions": [choice("multiple-1", "multiple_choice", ["A", "B"])],
        "short_answer_questions": [
            {"local_id": "short-1", "question_type": "short_answer", "stem": "说明依据。", "reference_answer": "依据冻结证据。", "rubric": [{"criterion": "引用证据", "points": 1}, {"criterion": "说明边界", "points": 1}], "knowledge_point_tags": ["skill-search"], "evidence_ids": [evidence.evidence_id]},
            {"local_id": "short-2", "question_type": "short_answer", "stem": "说明边界。", "reference_answer": "不引入证据外事实。", "rubric": [{"criterion": "识别边界", "points": 1}, {"criterion": "解释原因", "points": 1}], "knowledge_point_tags": ["skill-search"], "evidence_ids": [evidence.evidence_id]},
        ],
    }
    gateway = ScriptedLLMGateway([{}, valid])
    artifact = AssessmentAgent().generate(spec, context, llm_gateway=gateway)

    assert artifact.metadata.validation_status == "validated"
    assert len(gateway.calls) == 2
    assert artifact.mime_type == "text/markdown"
    assert len(artifact.artifact_data["assessment_package"]["node_blocks"]) == 1
    assert "参考答案" not in artifact.content_text


def test_new_resource_types_have_a_deterministic_review_structure_gate():
    malformed = SimpleNamespace(
        resource_type="案例分析",
        content_text="# 不完整案例\n\n## 案例背景\n\n缺少其余章节。",
    )

    result = _deterministic_resource_structure_review(malformed)

    assert result is not None
    assert result["decision"] == "revise"
    assert result["issues"][0]["code"] == "structure_quality"


def test_new_resource_types_flow_through_generation_and_independent_review(monkeypatch):
    monkeypatch.setattr(
        "app.agents.resource_workflows.learning_documents.generator_agent.get_settings",
        lambda: SimpleNamespace(resource_worker_max_concurrency=1),
    )
    learner = LearnerProfile(
        learner_id="learner-new-resource-type",
        learner_type="测试",
        education="本科",
        major="计算机",
        skill_level="中级",
        learning_goal="验证新增资源类型",
    )
    evidence = make_evidence(evidence_id="ev-new-resource-type")
    state = {
        "schema_version": "1.0",
        "run_id": "run-new-resource-pipeline",
        "batch_id": "batch-new-resource-pipeline",
        "learner": learner,
        "topic": "受控检索",
        "resource_types": ["复习清单", "案例分析"],
        "target_skill_nodes": ["skill-search"],
        "retrieved_evidence": [evidence],
        "learning_plan": {"learning_path": [{"topic": "检索", "order": 1}]},
        "generation_attempt": 1,
        "trace": [],
    }
    generated = generate_node(
        state,
        llm_gateway=ScriptedLLMGateway([CHECKLIST_MARKDOWN, CASE_STUDY_MARKDOWN]),
    )

    assert [item.resource_type for item in generated["generated_resources"]] == ["复习清单", "案例分析"]
    assert [item["agent_name"] for item in generated["resource_executions"]] == [
        "ReviewChecklistAgent",
        "CaseStudyAgent",
    ]

    reviewed = review_node(
        {**state, **generated},
        llm_gateway=ScriptedLLMGateway([
            {
                "decision": "approve", "hallucination_score": 0.0, "issues": [],
                "difficulty_match": True, "coverage_rate": 1.0,
                "suggestion": "证据、结构与难度均符合要求。", "revision_instructions": [],
            },
            {
                "decision": "approve", "hallucination_score": 0.0, "issues": [],
                "difficulty_match": True, "coverage_rate": 1.0,
                "suggestion": "证据、结构与难度均符合要求。", "revision_instructions": [],
            },
        ]),
    )

    assert reviewed["review_result"]["decision"] == "approve"
    assert set(item["resource_type"] for item in reviewed["resource_review_results"].values()) == {
        "复习清单", "案例分析",
    }
    assert {item.review_status for item in reviewed["generated_resources"]} == {"approved"}
