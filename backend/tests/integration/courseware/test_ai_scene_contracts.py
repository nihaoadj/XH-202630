"""Focused tests for the bounded LLM-to-SceneSpec boundary."""

from types import SimpleNamespace

import pytest
from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewareNarrativeEnrichment, CoursewarePracticeEnrichment, CoursewareSceneSpec,
)
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
from app.agents.resource_workflows.interactive_courseware.practice_structure_agent import extract_practice_step_structure
from app.agents.resource_workflows.interactive_courseware.contracts import CoursewarePracticeStepExtraction
from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import review_courseware_quality_decision
from app.core.courseware.renderer import render_courseware
from app.services.courseware.review import source_trace_review


def _source():
    return {
        "resource_id": "lecture", "blocks": [
            {"block_id": "b1", "text": "RAG 先检索可信上下文。"},
            {"block_id": "b2", "text": "再基于上下文生成答案。"},
        ],
    }


def _scene():
    return {
        "kind": "explain", "title": "RAG 原理", "blocks": ["RAG 的流程。"],
        "source_refs": ["lecture"], "source_block_ids": ["b1", "b2"],
        "source_map": {"blocks": [["b1", "b2"]]},
    }


def test_ai_scene_is_flattened_only_after_source_validation(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.scene_composer_agent as composition

    monkeypatch.setattr(composition, "courseware_ai_available", lambda _gateway: True)
    spec = CoursewareSceneSpec.model_validate({
        "kind": "explain", "title": "RAG 原理",
        "blocks": [{
            "block_id": "block-1", "component": "callout", "text": "先检索可信上下文，再生成答案。",
            "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1", "b2"]}],
        }],
    })

    class Gateway:
        def options_for(self, *_args, **_kwargs):
            return object()

        def invoke_structured(self, **_kwargs):
            return SimpleNamespace(output=spec)

    rendered, warning = compose_courseware_scene(Gateway(), "run-1", "scene-1", _scene(), _source())
    assert warning is None
    assert rendered and rendered["blocks"] == ["先检索可信上下文，再生成答案。"]
    assert rendered["source_map"]["blocks"] == [["b1", "b2"]]
    assert not source_trace_review({"scenes": [rendered]}, [_source()])


def test_scene_prompt_prefers_first_attempt_safe_component_contract(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.scene_composer_agent as composition

    monkeypatch.setattr(composition, "courseware_ai_available", lambda _gateway: True)
    spec = CoursewareSceneSpec.model_validate({
        "kind": "explain", "title": "RAG 原理",
        "blocks": [{"block_id": "block-1", "component": "callout", "text": "先检索可信上下文。",
                    "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}]}],
    })

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **kwargs):
            self.messages = kwargs["messages"]
            return SimpleNamespace(output=spec)

    gateway = Gateway()
    compose_courseware_scene(gateway, "run-1", "scene-1", _scene(), _source())
    assert "pedagogical_role（仅 explain/example/warning/recap）" in gateway.messages[0].content
    assert '"schema_version":"2.0","kind":"explain"' in gateway.messages[0].content
    assert "2 至 4 个互补信息区" in gateway.messages[0].content
    assert '"transformation":"paraphrase"' in gateway.messages[0].content
    request = gateway.messages[1].content
    assert "flashcard" not in request
    assert '"supported_components": ["callout", "key_point", "steps", "single_choice", "multiple_choice", "recap"]' in request


def test_practice_uses_small_enrichment_contract_and_preserves_platform_provenance(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.scene_composer_agent as composition

    monkeypatch.setattr(composition, "courseware_ai_available", lambda _gateway: True)
    deterministic = {
        "scene_id": "practice-1", "kind": "practice", "title": "原始标题", "lead": "原始引导",
        "blocks": ["准备", "执行", "检查", "总结"], "steps": ["旧步骤一", "旧步骤二"], "conclusion": "原始结论",
        "source_refs": ["lecture"], "source_block_ids": ["b1", "b2"],
        "source_map": {"blocks": [["b1"], ["b1"], ["b2"], ["b2"]]},
        "component_blocks": [{"component": "steps", "text": "按步骤操作", "steps": ["旧步骤一"],
                              "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}]}],
    }

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **kwargs):
            self.output_schema = kwargs["output_schema"]
            return SimpleNamespace(output=CoursewarePracticeEnrichment(
                title="步骤一：准备环境", lead="完成本页准备后再进入下一步。", steps=["准备环境并确认依赖可用"], conclusion="核对准备结果。",
            ))

    gateway = Gateway()
    rendered, warning = compose_courseware_scene(gateway, "run-1", "practice-1", deterministic, _source())
    assert gateway.output_schema is CoursewarePracticeEnrichment
    assert warning is None
    assert rendered["steps"] == ["准备环境并确认依赖可用"]
    assert rendered["component_blocks"][0]["steps"] == ["准备环境并确认依赖可用"]
    assert rendered["source_map"]["steps"] == [["b1"]]


def test_llm_cover_enrichment_formats_title_and_updates_learning_overview(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.scene_composer_agent as composition

    monkeypatch.setattr(composition, "courseware_ai_available", lambda _gateway: True)
    source_ref = [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}]
    deterministic = {
        "scene_id": "cover-1", "kind": "intro", "page_role": "cover", "title": "课程导览",
        "lead": "确定性引导", "conclusion": "确定性结论", "blocks": ["学习概述：旧内容", "学习方法：旧方法"],
        "source_refs": ["lecture"], "source_block_ids": ["b1"],
        "component_blocks": [
            {"schema_version": "1.0", "block_id": "scope", "component": "callout",
             "text": "学习概述：旧内容", "source_refs": source_ref},
            {"schema_version": "1.0", "block_id": "method", "component": "key_point",
             "text": "学习方法：旧方法", "source_refs": source_ref},
        ],
    }

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()

        def invoke_structured(self, **_kwargs):
            return SimpleNamespace(output=CoursewareNarrativeEnrichment(
                title="RAG 相似度检索工程实操", lead="先理解检索目标。",
                learning_overview="围绕文档切分、向量索引与相似度检索完成一轮实操。",
                conclusion="完成后回到来源核对关键判断。",
            ))

    rendered, warning = compose_courseware_scene(Gateway(), "run-1", "cover-1", deterministic, _source())
    assert warning is None
    assert rendered["llm_enriched"] is True
    assert rendered["title"] == "实操指南 | RAG 相似度检索工程实操"
    assert rendered["component_blocks"][0]["text"].startswith("学习概述：")

    html = render_courseware({"title": "确定性回退标题", "scenes": [rendered]}).decode("utf-8")
    assert "<h2>实操指南 | RAG 相似度检索工程实操</h2>" in html
    assert "学习概述：围绕文档切分、向量索引与相似度检索完成一轮实操。" in html


def test_llm_practice_structure_requires_ordered_complete_source_coverage(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.practice_structure_agent as extraction

    monkeypatch.setattr(extraction, "courseware_ai_available", lambda _gateway: True)

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **kwargs):
            self.output_schema = kwargs["output_schema"]
            return SimpleNamespace(output=CoursewarePracticeStepExtraction.model_validate({"steps": [
                {"title": "准备", "source_block_ids": ["b1", "b1-detail"]},
                {"title": "执行", "source_block_ids": ["b2", "b2-detail"]},
            ], "context_block_ids": ["intro"]}))

    gateway = Gateway()
    groups, warning = extract_practice_step_structure(gateway, "run-1", {
        "resource_id": "guide", "role": "practice", "blocks": [
            {"block_id": "intro", "kind": "paragraph", "text": "开始前说明"},
            {"block_id": "b1", "kind": "heading", "text": "## 步骤 1：准备环境"}, {"block_id": "b1-detail", "kind": "paragraph", "text": "创建环境"},
            {"block_id": "b2", "kind": "heading", "text": "## 步骤 2：执行验证"}, {"block_id": "b2-detail", "kind": "paragraph", "text": "运行检查"},
        ],
    })
    assert gateway.output_schema is CoursewarePracticeStepExtraction
    assert warning is None
    assert groups == [
        {"title": "准备", "source_block_ids": ["b1", "b1-detail"]}, {"title": "执行", "source_block_ids": ["b2", "b2-detail"]},
    ]


def test_invalid_llm_practice_structure_falls_back_without_accepting_partial_groups(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.practice_structure_agent as extraction

    monkeypatch.setattr(extraction, "courseware_ai_available", lambda _gateway: True)

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **_kwargs):
            return SimpleNamespace(output=CoursewarePracticeStepExtraction.model_validate({"steps": [
                {"title": "遗漏来源块", "source_block_ids": ["b1"]},
            ]}))

    groups, warning = extract_practice_step_structure(Gateway(), "run-1", {
        "resource_id": "guide", "role": "practice", "blocks": [
            {"block_id": "b1", "kind": "heading", "text": "## 步骤 1：准备环境"}, {"block_id": "b2", "kind": "paragraph", "text": "执行验证"},
        ],
    })
    assert groups is None
    assert warning and warning["code"] == "AI_PRACTICE_STRUCTURE_FALLBACK"


def test_llm_practice_structure_allows_only_labelled_summary_as_trailing_context(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.practice_structure_agent as extraction

    monkeypatch.setattr(extraction, "courseware_ai_available", lambda _gateway: True)

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **_kwargs):
            return SimpleNamespace(output=CoursewarePracticeStepExtraction.model_validate({
                "steps": [{"title": "建立索引", "source_block_ids": ["h1", "detail"]}],
                "context_block_ids": ["intro", "summary", "summary-detail"],
            }))

    groups, warning = extract_practice_step_structure(Gateway(), "run-1", {
        "resource_id": "guide", "role": "practice", "blocks": [
            {"block_id": "intro", "kind": "paragraph", "text": "前言"},
            {"block_id": "h1", "kind": "heading", "text": "## 步骤 1：建立索引"},
            {"block_id": "detail", "kind": "paragraph", "text": "执行索引构建。"},
            {"block_id": "summary", "kind": "heading", "text": "## 总结"},
            {"block_id": "summary-detail", "kind": "paragraph", "text": "复核全部结果。"},
        ],
    })
    assert warning is None
    assert groups == [{"title": "建立索引", "source_block_ids": ["h1", "detail"]}]


@pytest.mark.parametrize("invalid_fields", [
    {"steps": ["先操作"], "feedback": "根据来源复盘。"},
    {"steps": [], "feedback": None},
])
def test_quiz_contract_requires_one_primary_action_and_feedback(invalid_fields):
    payload = {
        "kind": "quiz", "title": "检索检查",
        "blocks": [{
            "block_id": "quiz-block", "component": "single_choice", "text": "第一步是什么？",
            "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}],
        }],
        "options": ["检索", "跳过来源"], "answer": ["检索"],
        **invalid_fields,
    }

    with pytest.raises(ValueError):
        CoursewareSceneSpec.model_validate(payload)


def test_unsafe_ai_scene_is_blocked_before_renderer(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.scene_composer_agent as composition

    monkeypatch.setattr(composition, "courseware_ai_available", lambda _gateway: True)
    spec = CoursewareSceneSpec.model_validate({
        "kind": "explain", "title": "RAG 原理",
        "blocks": [{
            "block_id": "block-1", "text": "<script>alert(1)</script>",
            "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}],
        }],
    })

    class Gateway:
        def options_for(self, *_args, **_kwargs):
            return object()

        def invoke_structured(self, **_kwargs):
            return SimpleNamespace(output=spec)

    rendered, warning = compose_courseware_scene(Gateway(), "run-1", "scene-1", _scene(), _source())
    # Unsafe prose is isolated to this scene and the caller retains its deterministic fallback.
    assert rendered is None
    assert warning and warning["code"] == "AI_SCENE_FALLBACK"


def test_renderer_rejects_unregistered_component_before_artifact_creation():
    with pytest.raises(ValueError, match="未注册互动组件"):
        render_courseware({
            "title": "组件边界", "scenes": [{
                "kind": "intro", "title": "开始", "blocks": ["安全内容"],
                "source_refs": ["lecture"], "source_block_ids": ["b1"],
                "component_blocks": [{"component": "arbitrary_html", "text": "不应渲染"}],
            }],
        })


def test_renderer_dispatches_registered_component_through_catalog_owned_markup():
    artifact = render_courseware({
        "title": "组件边界", "scenes": [{
            "kind": "intro", "title": "开始", "blocks": ["安全内容"],
            "source_refs": ["lecture"], "source_block_ids": ["b1"],
                "component_blocks": [{"component": "key_point", "text": "只渲染受控文本。", "source_refs": [{"source_resource_id": "lecture", "source_block_ids": ["b1"]}]}],
        }],
    })
    assert b'aria-label="' in artifact
    assert b"component-key-point" in artifact


def test_unavailable_quality_reviewer_is_never_recorded_as_approved(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent as reviewer

    monkeypatch.setattr(reviewer, "courseware_ai_available", lambda _gateway: False)
    decision, warning = review_courseware_quality_decision(None, "run-1", {"title": "课件", "scenes": []})

    assert decision.decision == "unavailable"
    assert warning == {
        "code": "AI_QUALITY_REVIEW_UNAVAILABLE",
        "message": "AI 教学质量审核不可用",
        "fallback_version": "deterministic-v1",
    }


def test_invalid_quality_reviewer_output_is_unavailable(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent as reviewer

    monkeypatch.setattr(reviewer, "courseware_ai_available", lambda _gateway: True)

    class Gateway:
        def options_for(self, *_args, **_kwargs):
            return object()

        def invoke_structured(self, **_kwargs):
            raise RuntimeError("malformed response")

    decision, warning = review_courseware_quality_decision(Gateway(), "run-1", {"title": "课件", "scenes": []})
    assert decision.decision == "unavailable"
    assert warning and warning["code"] == "AI_QUALITY_REVIEW_INVALID_OUTPUT"


def test_quality_review_prompt_enumerates_required_status_and_severity(monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent as reviewer

    monkeypatch.setattr(reviewer, "courseware_ai_available", lambda _gateway: True)

    class Gateway:
        def options_for(self, *_args, **_kwargs): return object()
        def invoke_structured(self, **kwargs):
            self.messages = kwargs["messages"]
            self.output_schema = kwargs["output_schema"]
            return SimpleNamespace(output=reviewer.CoursewareReviewDecision(status="pass", schema_version="2.0"))

    gateway = Gateway()
    review_courseware_quality_decision(gateway, "run-1", {"title": "课件", "scenes": []})
    assert gateway.output_schema.__name__ == "CoursewareReviewDecisionV2Draft"
    assert "severity 只能是 info、warning 或 error" in gateway.messages[0].content
    assert "status=pass" in gateway.messages[0].content
    assert "severity=error" in gateway.messages[0].content
    assert "MISSING_ANSWER 只能用于实际 kind=quiz" in gateway.messages[0].content
    assert '"schema_version":"2.0","status":"pass","issues":[]' in gateway.messages[0].content


def test_review_draft_without_localizer_becomes_course_level_issue():
    from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import (
        normalize_review_draft_for_durable_contract,
    )

    normalized = normalize_review_draft_for_durable_contract({
        "schema_version": "2.0", "status": "revise",
        "issues": [{"severity": "error", "scope": "block", "instruction": "补充反馈"}],
        "rubric_scores": {"coherence": 3, "not_a_rubric": 5},
    })

    assert normalized["issues"][0]["severity"] == "error"
    assert normalized["issues"][0]["scope"] == "course"
    assert normalized["rubric_scores"] == {"coherence": 3}
