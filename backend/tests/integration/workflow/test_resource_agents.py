from __future__ import annotations

import json
from types import SimpleNamespace
from threading import Barrier

import pytest

from app.agents.resource_agents import (
    AssessmentAgent,
    HtmlPracticeGuideAgent,
    TextResourceAgent,
)
from app.agents.generator import derive_html_node, generate_node
from app.agents.reviewer import review_node
from app.agents.resource_agents.html_practice import (
    CANONICAL_GUIDE_PROMPT,
    HTML_CONVERSION_PROMPT,
    _derive_manifest,
    canonical_text_hash,
    normalize_canonical_markdown,
)
from app.agents.resource_agents.registry import get_resource_agent, normalize_resource_type
from app.agents.resource_spec_builder import build_resource_specs
from app.config import get_settings
from app.core.errors import ApplicationError, ErrorCode
from app.core.evidence import source_refs_from_evidence
from app.core.llm_gateway import LLMGatewayError
from app.models.agent_contracts import (
    ApprovedPracticeGuideSource,
    PracticeGuideManifest,
    ResourceGenerationContext,
    make_error_info,
)
from app.models.schemas import GenerateRequest, LearnerProfile, LearningResource
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def _specs():
    evidence = make_evidence(evidence_id="ev-resource-agent")
    specs = build_resource_specs(
        run_id="run-resource-agents",
        resource_types=["讲义", "实操指南", "分阶测试题"],
        topic="受控检索",
        difficulty="中级",
        learning_plan={"learning_path": [{"topic": "检索", "order": 1}]},
        evidence=[evidence],
        target_skill_nodes=["skill-search"],
    )
    context = ResourceGenerationContext(
        run_id="run-resource-agents",
        batch_id="run-resource-agents",
        topic="受控检索",
        evidence=[evidence],
    )
    return specs, context


def _manifest():
    return {
        "guide_version": "1.0",
        "sections": [
            {"section_id": "overview", "title": "概览", "order": 1, "knowledge_points": []},
            {"section_id": "prerequisites", "title": "准备", "order": 2, "knowledge_points": []},
            {"section_id": "practice", "title": "实践", "order": 3, "knowledge_points": ["skill-search"]},
        ],
        "steps": [{
            "step_id": "step-01",
            "section_id": "practice",
            "title": "执行检索",
            "order": 1,
            "knowledge_points": ["skill-search"],
        }],
        "code_ids": [],
        "checklist_ids": ["check-01"],
        "quiz_ids": ["quiz-01"],
    }


def _canonical_markdown():
    return """# 受控检索实操指南

<!-- section:overview -->
## 概览
完成一次受控检索。

<!-- section:prerequisites -->
## 准备
使用已提供的冻结证据。

<!-- section:practice -->
## 实践
<!-- step:step-01 -->
### 执行检索
操作：提交检索请求。
预期结果：返回证据。
验证方法：核对证据 ID。
失败排查：检查输入范围。
<!-- checklist:check-01 -->
- [ ] 已核对证据
<!-- quiz:quiz-01 -->
自测：是否只使用冻结证据？
"""


def _html_derivation_state(*, approved: bool = True):
    specs, context = _specs()
    spec = specs[1]
    markdown = _canonical_markdown()
    manifest = PracticeGuideManifest.model_validate(_manifest())
    resource = LearningResource(
        resource_id="practice-text-v1",
        learner_id="learner-html",
        topic="受控检索",
        run_id="run-resource-agents",
        batch_id="run-resource-agents",
        resource_spec_id=spec.resource_spec_id,
        resource_family_id=spec.resource_family_id,
        representation="text",
        resource_type="实操指南",
        difficulty="中级",
        content_text=markdown,
        mime_type="text/markdown",
        knowledge_points=spec.knowledge_points,
        source_refs=[],
        review_status="approved" if approved else "unreviewed_draft",
        review_id="review-practice-text-v1" if approved else None,
        publication_status="published" if approved else "unpublished",
        canonical_text_hash=canonical_text_hash(markdown, manifest),
        guide_manifest=manifest.model_dump(mode="json"),
    )
    state = {
        "schema_version": "1.0",
        "run_id": "run-resource-agents",
        "batch_id": "run-resource-agents",
        "learner": LearnerProfile(
            learner_id="learner-html",
            learner_type="测试",
            education="本科",
            major="计算机",
            skill_level="中级",
            learning_goal="验证 HTML 派生门禁",
        ),
        "topic": "受控检索",
        "resource_types": ["实操指南"],
        "target_skill_nodes": ["skill-search"],
        "retrieved_evidence": context.evidence,
        "learning_plan": {"learning_path": [{"topic": "检索", "order": 1}]},
        "resource_specs": [spec.model_dump(mode="json")],
        "generated_resources": [resource],
        "resource_executions": [],
        "generation_attempt": 1,
        "workflow_status": "completed",
        "trace": [],
    }
    return state, resource


def test_registry_is_exact_and_unknown_types_fail_before_generation():
    assert isinstance(get_resource_agent("讲义"), TextResourceAgent)
    assert isinstance(get_resource_agent("实操指南"), HtmlPracticeGuideAgent)
    assert isinstance(get_resource_agent("分阶测试题"), AssessmentAgent)
    assert normalize_resource_type("定制讲义") == "讲义"
    with pytest.raises(ApplicationError) as exc_info:
        get_resource_agent("视频")
    assert exc_info.value.code == ErrorCode.WORKFLOW_CONTRACT_INVALID


def test_generate_request_canonicalizes_alias_and_rejects_unknown_type():
    request = GenerateRequest(
        learner_id="learner-route",
        topic="受控路由",
        resource_types=["定制讲义", "实操指南"],
    )
    assert request.resource_types == ["讲义", "实操指南"]
    with pytest.raises(ValueError, match="unsupported resource_type"):
        GenerateRequest(
            learner_id="learner-route",
            topic="受控路由",
            resource_types=["视频"],
        )


def test_spec_builder_creates_three_text_representations():
    specs, _ = _specs()
    assert [item.resource_type for item in specs] == ["讲义", "实操指南", "分阶测试题"]
    representations = [
        (item.resource_type, representation.representation, representation.max_output_tokens)
        for item in specs
        for representation in item.representations
    ]
    assert representations == [
        ("讲义", "text", 32768),
        ("实操指南", "text", 32768),
        ("分阶测试题", "text", 32768),
    ]


def test_practice_guide_text_prompt_constraints():
    specs, context = _specs()
    spec = specs[1]
    markdown = _canonical_markdown()
    gateway = ScriptedLLMGateway([markdown])
    agent = HtmlPracticeGuideAgent()
    canonical = agent.generate(spec, context, llm_gateway=gateway)

    assert canonical.metadata.representation == "text"
    assert canonical.metadata.canonical_text_hash
    assert gateway.calls[0]["options"].max_output_tokens == 32768
    assert "唯一内容源" in CANONICAL_GUIDE_PROMPT
    assert "严格使用以下 Markdown 骨架" in CANONICAL_GUIDE_PROMPT
    assert "8,000" in CANONICAL_GUIDE_PROMPT
    assert "5～7" in CANONICAL_GUIDE_PROMPT
    assert "固定为少数步骤" in CANONICAL_GUIDE_PROMPT
    assert "直接输出完整 Markdown" in CANONICAL_GUIDE_PROMPT


def test_structured_assessment_schema_remains_small_while_long_documents_are_plain_text():
    from app.models.agent_contracts import AssessmentLLMOutput

    assessment_schema = AssessmentLLMOutput.model_json_schema()

    assert assessment_schema["properties"]["questions"]["maxItems"] == 8


def test_practice_guide_persists_server_owned_evidence_lineage():
    specs, context = _specs()
    spec = specs[1]
    gateway = ScriptedLLMGateway([_canonical_markdown()])

    artifact = HtmlPracticeGuideAgent().generate(spec, context, llm_gateway=gateway)

    assert artifact.metadata.source_evidence_ids == spec.evidence_ids
    assert artifact.artifact_data["source_evidence_ids"] == spec.evidence_ids


def test_manifest_derivation_preserves_standard_headings_and_rejects_incomplete_steps():
    specs, context = _specs()
    spec = specs[1]
    manifest = _derive_manifest(_canonical_markdown(), spec)

    assert [item.title for item in manifest.sections] == ["概览", "准备", "实践"]
    assert manifest.steps[0].title == "执行检索"

    incomplete = _canonical_markdown().replace("失败排查：检查输入范围。", "")
    with pytest.raises(ApplicationError) as exc_info:
        # Generate through the normal canonical route so the server-owned
        # manifest and the per-step formatting gate are both exercised.
        HtmlPracticeGuideAgent().generate(
            spec, context, llm_gateway=ScriptedLLMGateway([incomplete]),
        )
    assert exc_info.value.code == ErrorCode.LLM_OUTPUT_SCHEMA_INVALID


def test_canonical_markdown_repairs_plain_titles_after_stable_markers():
    source = """<!-- section:overview -->

概览
<!-- section:prerequisites -->
准备
<!-- section:practice -->
实践
<!-- step:step-01 -->
步骤 1：执行检索
"""
    normalized = normalize_canonical_markdown(source)

    assert "<!-- section:overview -->\n\n## 概览" in normalized
    assert "<!-- section:prerequisites -->\n## 准备" in normalized
    assert "<!-- step:step-01 -->\n### 步骤 1：执行检索" in normalized


def test_generator_uses_bounded_workers_and_preserves_route_metadata(monkeypatch):
    barrier = Barrier(2)
    progress_events = []

    class ProgressRecorder:
        def record_resource_queued(self, state, *, spec, execution, trace_item):
            progress_events.append(("queued", spec.resource_type, execution["representation"]))

        def record_resource_generated(self, state, *, resource, execution, trace_item):
            # The callback is invoked before generate_node publishes its final
            # aggregate state, which is the resource-level SSE boundary.
            assert not state.get("generated_resources")
            progress_events.append((execution["resource_execution_state"], resource.resource_type, resource.representation.value))

    def resource_output(call):
        barrier.wait(timeout=3)
        if call["context"].node_name == "TextResourceAgent":
            return "# 受控检索讲义\n\n## 学习目标\n\n完成检索。"
        return {
            "title": "分阶测试题",
            "instructions": "完成三个层级题目。",
            "difficulty": "中级",
            "knowledge_points": ["skill-search", "检索"],
            "questions": [
                {
                    "question_id": f"q-0{index}",
                    "level": level,
                    "question_type": "short_answer",
                    "stem": f"{level}题",
                    "options": [],
                    "answer": ["依据冻结证据回答"],
                    "explanation": "答案可由证据支持。",
                    "ability_node": "skill-search",
                    "knowledge_points": ["skill-search"],
                    "evidence_ids": ["ev-resource-agent"],
                }
                for index, level in enumerate(("基础", "进阶", "挑战"), start=1)
            ],
        }

    monkeypatch.setattr(
        "app.agents.generator.get_settings",
        lambda: SimpleNamespace(resource_worker_max_concurrency=2),
    )
    evidence = make_evidence(evidence_id="ev-resource-agent")
    gateway = ScriptedLLMGateway([resource_output, resource_output])
    result = generate_node({
        "schema_version": "1.0",
        "run_id": "run-concurrent-resources",
        "batch_id": "run-concurrent-resources",
        "learner_id": "learner-concurrent",
        "learner": LearnerProfile(
            learner_id="learner-concurrent",
            learner_type="测试",
            education="本科",
            major="计算机",
            skill_level="中级",
            learning_goal="验证资源并发",
        ),
        "topic": "受控检索",
        "target_skill_nodes": ["skill-search"],
        "resource_types": ["讲义", "分阶测试题"],
        "retrieved_evidence": [evidence],
        "learning_plan": {"learning_path": [{"topic": "检索", "order": 1}]},
        "generation_attempt": 1,
        "trace": [],
    }, llm_gateway=gateway, resource_progress_recorder=ProgressRecorder())

    assert [item.resource_type for item in result["generated_resources"]] == ["讲义", "分阶测试题"]
    assert [item["agent_name"] for item in result["resource_executions"]] == [
        "TextResourceAgent",
        "AssessmentAgent",
    ]
    worker_step_ids = [item["worker_step_id"] for item in result["resource_executions"]]
    assert len(set(worker_step_ids)) == 2
    assert all(call["context"].step_id in worker_step_ids for call in gateway.calls)
    assert {event[1] for event in progress_events if event[0] == "queued"} == {"讲义", "分阶测试题"}
    assert {event[1] for event in progress_events if event[0] == "generated"} == {"讲义", "分阶测试题"}


def test_practice_guide_generates_text_only(monkeypatch):
    monkeypatch.setattr(
        "app.agents.generator.get_settings",
        lambda: SimpleNamespace(resource_worker_max_concurrency=1),
    )
    state, _ = _html_derivation_state(approved=False)
    state["generated_resources"] = []
    state["resource_executions"] = []
    events = []

    class ProgressRecorder:
        def record_resource_queued(self, state, *, spec, execution, trace_item):
            events.append(("queued", execution["representation"]))

        def record_resource_generated(self, state, *, resource, execution, trace_item):
            events.append((execution["resource_execution_state"], resource.representation.value))

    gateway = ScriptedLLMGateway([_canonical_markdown()])
    result = generate_node(state, llm_gateway=gateway, resource_progress_recorder=ProgressRecorder())

    assert [(item.representation.value, item.review_status) for item in result["generated_resources"]] == [
        ("text", "pending_review"),
    ]
    assert result["resource_progress_summary"]["total"] == 1
    assert events == [("queued", "text"), ("generated", "text")]
