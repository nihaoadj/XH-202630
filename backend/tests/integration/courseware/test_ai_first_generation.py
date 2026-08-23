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
            scenes = [
                {
                    "source_resource_id": scene["source_resource_ids"][0],
                    "kind": scene["kind"],
                    "title": f"AI：{scene['scene_id']}",
                    "learning_objective": scene["interaction_purpose"],
                    "source_block_ids": scene["source_block_ids"],
                    "required": scene["required"],
                }
                for scene in payload["storyboard"]["scenes"]
                if scene["kind"] != "recap" and scene["source_resource_ids"]
            ]
            response = {"title": "AI-first RAG 课件", "learning_objectives": ["理解 RAG"], "scenes": scenes}
        elif context.node_name == "courseware_scene_composer":
            block_id = payload["source_blocks"][0]["block_id"]
            source_id = payload["source_resource_id"]
            response = {
                "kind": payload["required_kind"], "title": f"AI：{payload['scene_id']}",
                "blocks": [{
                    "block_id": f"ai-{block_id}", "component": "callout",
                    "text": "AI 根据冻结来源组织的学习说明。",
                    "source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}],
                }],
                "title_source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}],
            }
            if response["kind"] == "practice":
                response["steps"] = ["按来源完成操作步骤"]
            elif response["kind"] == "quiz":
                response.update({"options": ["检索", "随机生成"], "answer": ["检索"],
                                 "feedback": "先检索可信上下文。",
                                 "feedback_source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}]})
        elif context.node_name == "courseware_quality_reviewer":
            response = {"decision": "approved", "issues": []}
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


def test_normal_job_uses_planner_scene_and_review_without_deterministic_fallback(tmp_path, monkeypatch):
    """Normal offline evaluation follows the same AI-first workflow topology."""

    monkeypatch.setattr(runtime, "get_settings", lambda: Settings(_env_file=None))
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake

    created = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide", "assessment"],
    ))
    _run_worker(client)
    completed = service.get_job(created.run_id)

    assert completed is not None and completed.status == "published"
    assert fake.calls.count("courseware_spec_builder") == 1
    assert fake.calls.count("courseware_scene_composer") >= 2
    assert fake.calls.count("courseware_quality_reviewer") == 1
    assert not any(item["code"].endswith("FALLBACK") for item in completed.warnings)
    detail = service.get_job_detail(created.run_id)
    assert detail and all(scene.agent_version == "ai-v1" for scene in detail.scenes)


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
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide", "assessment"],
        learning_goal="掌握检索流程", expected_duration_minutes=25,
        interaction_intensity="high", visual_style_id="midnight",
    ))
    _run_worker(client)
    assert service.get_job(created.run_id).request_options == {
        "learning_goal": "掌握检索流程", "expected_duration_minutes": 25,
        "interaction_intensity": "high", "visual_style_id": "midnight",
    }
    assert captured == [service.get_job(created.run_id).request_options]
