"""Focused tests for the bounded LLM-to-SceneSpec boundary."""

from types import SimpleNamespace

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSceneSpec
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
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
