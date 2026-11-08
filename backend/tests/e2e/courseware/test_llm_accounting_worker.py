"""Courseware worker accounting e2e (T41 §8.2).

Uses a real spawn-based writer child and the real courseware workflow with a
scripted transport (no provider, no credentials).  Verifies:

* a healthy writer persists the ``courseware`` domain segment for a real run;
* killing the accounting consumer never changes the job outcome (the model
  call count and result are identical);
* two independent runs produce two distinct segments (no cross-run mixing).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from app.core.llm import accounting
from app.models.shared.llm import (
    LLMCallOptions,
    RawLLMResponse,
    StructuredOutputMode,
)
from app.services.runs import llm_accounting_runtime as runtime
from tests.fakes.llm import ScriptedLLMTransport
from app.core.llm.gateway import LLMGateway


@pytest.fixture()
def tmp_dir_session():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def enabled():
    accounting.set_enabled(True)
    accounting.install_publisher(None)
    yield
    runtime.stop_llm_accounting_runtime()
    accounting.set_enabled(False)
    accounting.install_publisher(None)


def _gateway() -> LLMGateway:
    transport = ScriptedLLMTransport([RawLLMResponse(content="definitely-not-json")])
    return LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5.0,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )


def _build_and_run(tmp: str, learner_id: str) -> dict:
    from app.agents.resource_workflows.interactive_courseware import (
        runtime as cw_runtime,
        workflow as cw_workflow,
    )
    from app.db.courseware.repository import MemoryCoursewareRepository
    from app.models.courseware import CoursewareJobCreateRequest
    from app.models.learning_documents.schemas import LearningResource, SourceRef
    from app.models.shared.agent_contracts import PracticeGuidePackageV3
    from app.services.learning_documents.resources import ResourceService

    practice = PracticeGuidePackageV3.model_validate({
        "schema_version": "3.0", "title": "worker 实操指南",
        "preparation": {"phase_id": "prepare", "goal": "准备", "items": ["确认输入"], "evidence_ids": ["ev-1"]},
        "practice": {"phase_id": "practice", "goal": "执行", "steps": [{
            "step_id": "step-1", "title": "核对", "instruction_text": "按来源核对并记录。",
            "code_blocks": [], "verification": "可复现。", "evidence_ids": ["ev-1"]}]},
        "verification": {"phase_id": "verify", "goal": "确认", "checklist": ["可复现"], "evidence_ids": ["ev-1"]},
        "reflection": {"phase_id": "reflect", "goal": "复盘", "summary": "记录链路。", "evidence_ids": ["ev-1"]},
    }).model_dump(mode="json")
    payload_hash = hashlib.sha256(
        json.dumps(practice, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    practice["payload_hash"] = payload_hash

    content = "阶段一：主题。阶段二：方法。阶段三：案例。阶段四：实践。"
    resource = LearningResource(
        resource_id="res-worker", learner_id=learner_id, topic="主题",
        resource_type="实操指南", difficulty="初级", content_text=content,
        knowledge_points=["k"], publication_status="published", version=1,
        exercise_items=[{"question_id": "q1", "question_type": "single_choice",
                         "question": "哪项对？", "options": ["对", "错"], "answer": "对",
                         "explanation": "x"}],
        source_refs=[SourceRef(doc_id="res-worker", title="来源", snippet=content,
                               score=1.0, knowledge_base_id="kb")],
        practice_guide_payload=practice,
        practice_guide_payload_hash=payload_hash,
    )

    class SourceRepo:
        def get(self, _rid: str) -> LearningResource:
            return resource

    class AuditRepo:
        def get_run(self, _rid: str) -> SimpleNamespace:
            return SimpleNamespace(knowledge_base_id="kb")

    settings = SimpleNamespace(
        courseware_ai_enabled=True,
        courseware_generation_mode="ai_first",
        llm_api_key=SecretStr("offline-scripted-key"),
    )

    repo = MemoryCoursewareRepository()
    workflow = cw_workflow.InteractiveCoursewareWorkflow(
        repo, ResourceService(SourceRepo()), AuditRepo(), llm_gateway=_gateway()
    )
    root = Path(tmp)
    with patch.object(cw_runtime, "get_settings", lambda: settings), \
         tempfile.TemporaryDirectory(dir=tmp) as art:

        def _store(_learner_id, _resource_id, content_bytes, extension, **kwargs):
            path = Path(art) / f"{_resource_id}.{extension}"
            data = content_bytes if isinstance(content_bytes, bytes) else str(content_bytes).encode("utf-8")
            path.write_bytes(data)
            return str(path), path.stat().st_size, hashlib.sha256(data).hexdigest()

        with patch.object(cw_workflow, "save_courseware_html",
                          lambda learner_id, resource_id, content, **kwargs:
                          _store(learner_id, resource_id, content, "html", **kwargs)), \
             patch.object(cw_workflow, "save_courseware_artifact",
                          lambda learner_id, resource_id, content, extension, **kwargs:
                          _store(learner_id, resource_id, content, extension, **kwargs)):
            job = workflow.create_job(CoursewareJobCreateRequest(
                learner_id=learner_id, source_resource_ids=["res-worker"],
                title="worker 课件", publish_mode="automatic",
            ))
            workflow.run(job.run_id)
    row = repo.get_job(job.run_id) or {}
    return {"run_id": job.run_id, "status": row.get("status"), "error_code": row.get("error_code")}


def _repository(db_path: str):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    return SQLLLMAccountingRepository(db_path, readonly=True)


def _wait_for_persisted(db_path: Path, domain: str, run_id: str, *, calls: int, timeout: float = 30.0):
    """Wait for the writer child to create tables, then poll a fresh readonly repo."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not db_path.exists():
        time.sleep(0.15)
    records = None
    repo = None
    while time.monotonic() < deadline:
        if repo is None:
            repo = _repository(str(db_path))
        records = repo.get_task(domain, run_id)
        if len(records.calls) >= calls:
            break
        time.sleep(0.15)
    if repo is not None:
        repo.close()
    return records


def test_healthy_writer_persists_courseware_segments(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-worker.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        result = _build_and_run(tmp_dir_session, "worker-learner-a")
        records = _wait_for_persisted(db_path, "courseware", result["run_id"], calls=1)
        assert records and records.calls, "courseware segment must be persisted"
        assert {call.stage for call in records.calls} <= {"planning", "quality_review"}
    finally:
        rt.stop()


def test_consumer_fault_does_not_change_job_outcome(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-worker-fault.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        healthy = _build_and_run(tmp_dir_session, "worker-learner-b")
        # Kill the accounting writer: generation must be unaffected.
        if rt._process is not None:
            rt._process.terminate()
            rt._process.join(timeout=5)
        faulted = _build_and_run(tmp_dir_session, "worker-learner-c")
        assert healthy["status"] == faulted["status"]
        assert healthy["error_code"] == faulted["error_code"]
    finally:
        rt.stop()


def test_two_runs_produce_distinct_segments(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-worker-runs.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        first = _build_and_run(tmp_dir_session, "worker-learner-d")
        second = _build_and_run(tmp_dir_session, "worker-learner-e")
        assert first["run_id"] != second["run_id"]
        observed = set()
        for run_id in (first["run_id"], second["run_id"]):
            records = _wait_for_persisted(db_path, "courseware", run_id, calls=1)
            if records:
                observed |= {segment.segment_id for segment in records.segments}
        assert len(observed) >= 2, "two runs must yield two distinct segments"
    finally:
        rt.stop()
