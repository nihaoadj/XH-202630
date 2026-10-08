"""Counterexamples for the normal AI-first courseware path.

These use the same workflow-facing fake gateway used by offline acceptance;
they must never need an API key or make a network request.
"""

import json

from app.agents.resource_workflows.interactive_courseware import runtime
from app.config import Settings
from app.models.courseware import CoursewareJobCreateRequest
from app.models.shared.llm import (
    LLMAttemptSummary,
    LLMCallOptions,
    LLMCallResult,
    LLMUsage,
    StructuredOutputMode,
)
from backend.tests.fakes.llm import ScriptedLLMGateway
from backend.tests.integration.courseware.test_api import _client, _run_worker


class _WorkflowFakeGateway:
    """A deterministic fake provider that exercises the real agent contracts."""

    def __init__(self):
        self.calls: list[str] = []

    def options_for(self, _node_name, *, temperature=0.0):
        return LLMCallOptions(temperature=temperature, max_attempts=1)

    def invoke_structured(self, **kwargs):
        context = kwargs["context"]
        self.calls.append(context.node_name)
        payload = json.loads(kwargs["messages"][-1].content)
        if context.node_name == "courseware_spec_builder":
            response = {
                "schema_version": "2.0", "course_title": "AI-first RAG 课件",
                "course_summary": "基于冻结来源的 RAG 课程。",
                "objectives": [],
                "scenes": [
                    {
                        "scene_id": scene["scene_id"],
                        "title": f"AI：{scene['scene_id']}",
                        "teaching_intent": scene["interaction_purpose"],
                        "preferred_component_ids": [],
                    }
                    for scene in payload["storyboard"]["scenes"]
                    if scene["kind"] != "recap"
                ],
            }
        elif context.node_name == "courseware_scene_composer":
            source_id = payload["source_resource_id"]
            source_blocks = payload["source_blocks"][:4]
            block_id = source_blocks[0]["block_id"]
            response = {
                "schema_version": "2.0",
                "kind": payload["required_kind"], "title": f"AI：{payload['scene_id']}",
                "lead": source_blocks[0]["text"],
                "blocks": [
                    {
                        "block_id": f"ai-{item['block_id']}", "component": "callout",
                        "text": item["text"],
                        "source_refs": [{"source_resource_id": source_id, "source_block_ids": [item["block_id"]]}],
                    }
                    for item in source_blocks
                ],
                "conclusion": source_blocks[-1]["text"],
                "title_source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}],
            }
            if response["kind"] == "practice":
                response["steps"] = ["按来源完成操作步骤"]
            elif response["kind"] == "quiz":
                response.update({"options": ["检索", "随机生成"], "answer": ["检索"],
                                 "feedback": "先检索可信上下文。",
                                 "feedback_source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}]})
        elif context.node_name == "courseware_quality_reviewer":
            response = {
                "decision": "approved", "issues": [],
                "rubric_scores": {
                    "objective_alignment": 4, "coherence": 4, "explanation_depth": 3,
                    "example_usefulness": 3, "misconception_handling": 3, "practice_gradient": 3,
                    "feedback_quality": 4, "interaction_purpose": 4, "cognitive_load": 3,
                },
            }
        else:  # pragma: no cover - makes unexpected production calls visible.
            raise AssertionError(f"unexpected AI node: {context.node_name}")
        output = kwargs["output_schema"].model_validate(response)
        usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        return LLMCallResult(
            output=output, call_id=context.call_id, model_name="offline-courseware-fake",
            structured_output_mode=StructuredOutputMode.JSON_MODE, attempt_count=1,
            retry_count=0, latency_ms=1, usage=usage,
            attempts=[LLMAttemptSummary(attempt=1, status="success", latency_ms=1,
                                        structured_output_mode=StructuredOutputMode.JSON_MODE, usage=usage)],
        )


def test_normal_configuration_accepts_an_injected_fake_ai_gateway(monkeypatch):
    """A fake gateway represents the normal offline evaluation model route."""

    monkeypatch.setattr(runtime, "get_settings", lambda: Settings(_env_file=None))

    assert runtime.courseware_ai_available(ScriptedLLMGateway([])) is True


def test_normal_job_uses_planner_and_review_with_safe_scene_fallback(tmp_path, monkeypatch):
    """A valid AI plan is reviewed even when scene composition is safely skipped."""

    monkeypatch.setattr(runtime, "get_settings", lambda: Settings(_env_file=None))
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake

    created = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["guide"],
    ))
    _run_worker(client)
    completed = service.get_job(created.run_id)

    assert completed is not None and completed.status in {"published", "published_with_warnings"}
    assert fake.calls.count("courseware_spec_builder") == 1
    assert fake.calls.count("courseware_scene_composer") == 0
    assert fake.calls.count("courseware_quality_reviewer") == 1
    assert all(item["code"] != "AI_SCENE_FALLBACK" for item in completed.warnings)
    detail = service.get_job_detail(created.run_id)
    assert detail and all(scene.agent_version in {"ai-v1", "deterministic-v1"} for scene in detail.scenes)
    assert detail.quality_summary["rubric_passed"] is True


def test_requested_learning_preferences_are_durable_and_reach_the_planner(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "get_settings", lambda: Settings(_env_file=None))
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake
    captured = []
    original = fake.invoke_structured

    def observe(**kwargs):
        if kwargs["context"].node_name == "courseware_spec_builder":
            captured.append(json.loads(kwargs["messages"][-1].content)["learner_request"])
        return original(**kwargs)

    fake.invoke_structured = observe
    created = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["guide"],
        learning_goal="掌握检索流程", expected_duration_minutes=25,
        interaction_intensity="high", visual_style_id="midnight",
    ))
    _run_worker(client)
    assert service.get_job(created.run_id).request_options == {
        "learning_goal": "掌握检索流程", "expected_duration_minutes": 25,
        "interaction_intensity": "high", "visual_style_id": "midnight",
    }
    assert captured == [service.get_job(created.run_id).request_options]
