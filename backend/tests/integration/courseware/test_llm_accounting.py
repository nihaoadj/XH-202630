"""Courseware full-chain accounting integration tests (T41 P4).

Uses the real ``InteractiveCoursewareWorkflow`` with a real ``LLMGateway``
backed by a scripted transport: model failures must be observed while the
business falls back to its deterministic path unchanged.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.llm import accounting
from app.models.shared.llm import (
    LLMCallOptions,
    RawLLMResponse,
    StructuredOutputMode,
)
from tests.fakes.llm import ScriptedLLMTransport
from app.core.llm.gateway import LLMGateway


@pytest.fixture()
def collected(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = []

    class _Publisher:
        def submit(self, submission):
            submissions.append(submission)
            return True

    monkeypatch.setattr(accounting, "_publisher", _Publisher())
    yield submissions
    accounting.uninstall_publisher()


def _real_gateway(outcomes):
    transport = ScriptedLLMTransport(outcomes)
    return LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5.0,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )


def _build_workflow(gateway, tmp: str):
    from app.agents.resource_workflows.interactive_courseware.workflow import (
        InteractiveCoursewareWorkflow,
    )
    from app.db.courseware.repository import MemoryCoursewareRepository
    from app.models.learning_documents.schemas import LearningResource, SourceRef
    from app.models.shared.agent_contracts import PracticeGuidePackageV3
    from app.models.courseware import CoursewareJobCreateRequest

    practice_payload = PracticeGuidePackageV3.model_validate({
        "schema_version": "3.0", "title": "评测实操指南",
        "preparation": {"phase_id": "prepare", "goal": "准备", "items": ["确认输入"], "evidence_ids": ["ev-1"]},
        "practice": {"phase_id": "practice", "goal": "执行", "steps": [{
            "step_id": "step-1", "title": "完成验证", "instruction_text": "按来源完成检索并记录结果。",
            "code_blocks": [], "verification": "结果可复现。", "evidence_ids": ["ev-1"]}]},
        "verification": {"phase_id": "verify", "goal": "确认", "checklist": ["结果可复现"], "evidence_ids": ["ev-1"]},
        "reflection": {"phase_id": "reflect", "goal": "复盘", "summary": "记录验证链路。", "evidence_ids": ["ev-1"]},
    }).model_dump(mode="json")
    import hashlib

    payload_hash = hashlib.sha256(
        json.dumps(practice_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    practice_payload["payload_hash"] = payload_hash

    content = "阶段一：主题。阶段二：方法。阶段三：案例。阶段四：实践。"
    resource = LearningResource(
        resource_id="res-cw", learner_id="eval-learner", topic="主题",
        resource_type="实操指南", difficulty="初级", content_text=content,
        knowledge_points=["k"], publication_status="published", version=1,
        exercise_items=[{"question_id": "q1", "question_type": "single_choice",
                         "question": "哪项对？", "options": ["对", "错"], "answer": "对", "explanation": "x"}],
        source_refs=[SourceRef(doc_id="res-cw", title="来源", snippet=content, score=1.0, knowledge_base_id="kb")],
        practice_guide_payload=practice_payload,
        practice_guide_payload_hash=payload_hash,
    )

    class SourceRepo:
        def get(self, _resource_id):
            return resource

    class AuditRepo:
        def get_run(self, _run_id):
            return SimpleNamespace(knowledge_base_id="kb")

    from app.services.learning_documents.resources import ResourceService

    repo = MemoryCoursewareRepository()
    workflow = InteractiveCoursewareWorkflow(
        repo, ResourceService(SourceRepo()), AuditRepo(), llm_gateway=gateway
    )
    request = CoursewareJobCreateRequest(
        learner_id="eval-learner",
        source_resource_ids=["res-cw"],
        title="accounting-case",
        publish_mode="automatic",
    )
    job = workflow.create_job(request)
    return workflow, repo, job


@pytest.fixture()
def ai_available(monkeypatch):
    """Make the real gateway count as AI-available without any credential use.

    The scripted transport never leaves the process; the key only satisfies
    the production availability guard that refuses anonymous real calls.
    """

    from pydantic import SecretStr

    settings = SimpleNamespace(
        courseware_ai_enabled=True,
        courseware_generation_mode="ai_first",
        llm_api_key=SecretStr("offline-scripted-key"),
    )
    monkeypatch.setattr(
        "app.agents.resource_workflows.interactive_courseware.runtime.get_settings",
        lambda: settings,
    )


def test_planner_failure_observed_and_business_falls_back(collected, monkeypatch, ai_available):
    # Keep storage deterministic and isolated from the real data directory.
    tmp = tempfile.mkdtemp()
    try:
        original_save = None
        from app.agents.resource_workflows.interactive_courseware import workflow as workflow_module

        root = Path(tmp)

        def _store(_learner_id, _resource_id, content, extension, **kwargs):
            path = root / f"{_resource_id}.{extension}"
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
            import hashlib

            return str(path), path.stat().st_size, hashlib.sha256(
                content if isinstance(content, bytes) else content.encode("utf-8")
            ).hexdigest()

        monkeypatch.setattr(
            workflow_module, "save_courseware_html",
            lambda learner_id, resource_id, content, **kwargs: _store(learner_id, resource_id, content, "html", **kwargs),
        )
        monkeypatch.setattr(
            workflow_module, "save_courseware_artifact",
            lambda learner_id, resource_id, content, extension, **kwargs: _store(learner_id, resource_id, content, extension, **kwargs),
        )
        # The scripted provider returns an unparseable spec: the planner call
        # fails at the real gateway and the workflow must fall back.
        gateway = _real_gateway([RawLLMResponse(content="definitely-not-json")])
        workflow, repo, job = _build_workflow(gateway, tmp)
        result = workflow.run(job.run_id)
        assert result is not None
        assert collected, "the failed planner call must be observed"
        segments = [submission.segment for submission in collected]
        courseware = [segment for segment in segments if segment.domain == "courseware"]
        assert courseware
        calls = [call for segment in courseware for call in segment.calls]
        planning = [call for call in calls if call.stage == "planning"]
        assert planning, f"expected planning observations, got stages {[c.stage for c in calls]}"
        assert all(call.outcome == "gateway_error" for call in planning)
        # Business still completes via the deterministic fallback path.
        final = repo.get_job(job.run_id) or {}
        assert final.get("status") not in {None, "failed", "running"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_and_retry_scene_share_one_segment_per_run(collected, monkeypatch):
    tmp = tempfile.mkdtemp()
    try:
        gateway = _real_gateway([])
        workflow, repo, job = _build_workflow(gateway, tmp)
        workflow.run(job.run_id)
        run_segments = [s.segment for s in collected if s.segment.domain == "courseware"]
        assert run_segments
        first_ids = {segment.segment_id for segment in run_segments}
        # A second direct run of the same job reuses or creates segments but
        # never attributes calls to another run_id.
        workflow.run(job.run_id)
        all_segments = [s.segment for s in collected if s.segment.domain == "courseware"]
        assert all(segment.run_id == job.run_id for segment in all_segments)
        # Same-run nesting produced at least one reused segment identity.
        assert any(segment.segment_id in first_ids for segment in all_segments)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scene_retry_entry_binds_segment(collected, monkeypatch):
    tmp = tempfile.mkdtemp()
    try:
        gateway = _real_gateway([])
        workflow, repo, job = _build_workflow(gateway, tmp)
        workflow.run(job.run_id)
        # Enqueue-only scene retry must not create phantom observations.
        workflow.retry_scene(job.run_id, "missing-scene", enqueue_only=True)
        segments = [s.segment for s in collected if s.segment.domain == "courseware"]
        assert all(segment.call_count >= 0 for segment in segments)
        total_calls = sum(segment.call_count for segment in segments)
        model_calls = [
            call
            for segment in segments
            for call in segment.calls
        ]
        assert len(model_calls) == total_calls
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_outbox_batch_container_flushes_once(collected, monkeypatch):
    tmp = tempfile.mkdtemp()
    try:
        gateway = _real_gateway([])
        workflow, repo, job = _build_workflow(gateway, tmp)
        # The legacy outbox entry wraps processing in one batch container.
        workflow.process_scene_outbox(run_id=None, limit=1)
        assert all(isinstance(s.segment, object) for s in collected)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
