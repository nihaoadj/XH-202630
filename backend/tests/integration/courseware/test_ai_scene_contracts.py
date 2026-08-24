"""Focused tests for the bounded LLM-to-SceneSpec boundary."""

from types import SimpleNamespace

import pytest
from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSceneSpec
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
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
        "source_refs": ["lecture"], "source_block_ids": ["b1"],
        "source_map": {"blocks": [["b1"]]},
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
    request = gateway.messages[1].content
    assert "flashcard" not in request
    assert '"supported_components": ["callout", "key_point", "steps", "single_choice", "multiple_choice", "recap"]' in request


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
    assert '"schema_version":"2.0","status":"pass","issues":[]' in gateway.messages[0].content
