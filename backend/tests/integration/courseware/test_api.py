"""Integration tests for the supported interactive-courseware sources."""

from pathlib import Path
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.courseware import courseware
from app.api.resource_library import library as resource_library
from app.db.courseware import models as _courseware_models  # noqa: F401 -- register SQL tables
from app.db.courseware.repository import MemoryCoursewareRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource, SourceRef
from app.services.courseware import CoursewareService
from app.services.courseware.executor import CoursewareExecutor
from app.services.learning_documents.resources import ResourceService
from app.services.learners.profiles import ProfileService


class _AuditRepository:
    def get_run(self, _run_id):
        return None


def _source_ref(kb: str = "kb-courseware") -> SourceRef:
    return SourceRef(
        doc_id="doc-1", title="课程资料", snippet="已验证来源", score=1.0,
        provenance_status="verified", knowledge_base_id=kb,
    )


def _resource(resource_id: str, resource_type: str, content: str, *, kb: str = "kb-courseware", exercises=None):
    return LearningResource(
        resource_id=resource_id, learner_id="courseware-learner", topic="RAG 基础",
        resource_type=resource_type, difficulty="初级", content_text=content,
        knowledge_points=["检索增强生成"], source_refs=[_source_ref(kb)],
        run_id=f"run-{resource_id}", batch_id="batch-courseware",
        publication_status="published", exercise_items=exercises or [],
    )


def _client(tmp_path, monkeypatch, *, with_quiz=True, mixed_feedback_batches=False):
    from app.core.storage import file_storage
    from app.services.courseware import service as courseware_service_module

    monkeypatch.setattr(file_storage, "_get_resources_dir", lambda: tmp_path / "resources")
    monkeypatch.setattr(
        courseware_service_module,
        "load_resource_file",
        lambda relative_path: (
            tmp_path / "resources" / "courseware" / "courseware-learner" / Path(relative_path).name
        ).read_bytes(),
    )
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="courseware-learner", learner_type="测试", education="本科", major="计算机",
        learning_goal="测试互动课件", knowledge_base_id="kb-courseware",
    ))
    resource_repo = MemoryResourceRepository()
    lecture = _resource("lecture", "讲义", "# RAG\nRAG 先检索，再使用可信上下文生成答案。")
    guide = _resource("guide", "实操指南", "\n".join([
        "第一步准备文档并确认版本、知识范围与敏感信息边界。",
        "第二步使用稳定规则切片并建立索引，同时保存块标识与内容哈希。",
        "第三步针对代表性问题验证召回结果，记录缺失证据与排序异常。",
        "第四步执行生成与审核，确认正确、失败和恢复路径均通过检查。",
    ]))
    # The public courseware contract admits a practice guide only when its
    # reviewed V3 phase package and matching hash are present.
    practice_payload = json.loads(Path("backend/tests/fixtures/courseware/structured_practice_full_preview.json").read_text(encoding="utf-8"))
    density_padding = " 记录来源、预期结果和异常恢复路径，确保页面信息完整且可复核。"
    practice_payload["preparation"]["goal"] += density_padding * 2
    practice_payload["preparation"]["items"] = [item + density_padding for item in practice_payload["preparation"]["items"]]
    practice_payload["practice"]["goal"] += density_padding * 2
    for step in practice_payload["practice"]["steps"]:
        step["instruction_text"] += density_padding * 2
        step["verification"] += density_padding * 2
    practice_payload["verification"]["goal"] += density_padding * 2
    practice_payload["verification"]["checklist"] = [item + density_padding for item in practice_payload["verification"]["checklist"]]
    practice_payload["reflection"]["goal"] += density_padding * 2
    practice_payload["reflection"]["summary"] += density_padding * 2
    canonical = json.dumps(practice_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    guide = guide.model_copy(update={
        "practice_guide_payload": {**practice_payload, "payload_hash": payload_hash},
        "practice_guide_payload_hash": payload_hash,
    })
    if mixed_feedback_batches:
        guide = guide.model_copy(update={"batch_id": "feedback-batch-other"})
    checklist = _resource("checklist", "复习清单", "\n".join([
        "确认是否理解问题边界、来源冻结和检索验证。",
        "确认是否能解释证据覆盖与结果排序异常。",
        "确认是否能根据失败结果回到对应流程检查点。",
        "确认是否完成来源一致性与可追溯性检查。",
    ]))
    exercises = [{"question_id": "q1", "question_type": "single_choice", "question": "RAG 的第一步是什么？",
                  "options": ["检索", "随机生成"], "answer": "检索", "explanation": "先检索上下文。"}] if with_quiz else []
    assessment = _resource("assessment", "分阶测试题", "自测题", exercises=exercises)
    for item in (lecture, guide, assessment, checklist):
        resource_repo.save(item, "courseware-learner", "RAG 基础")
    service = CoursewareService(
        MemoryCoursewareRepository(), ResourceService(resource_repo), _AuditRepository()
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(resource_repo),
        courseware_service=lambda: service,
    )
    app.include_router(courseware.router, prefix="/api/resources")
    app.include_router(resource_library.router, prefix="/api/resource-library")
    return TestClient(app)


def _run_worker(client, limit=10):
    service = client.app.container.courseware_service()
    return CoursewareExecutor(
        repo=service.repo, workflow=service.workflow, owner_id="test-worker",
        batch_size=limit, lease_seconds=120,
    ).run_once(limit=limit)


def test_multi_select_creates_resource_scoped_jobs_for_supported_sources(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    created = client.post("/api/resources/courseware/jobs/batch", json={
        "learner_id": "courseware-learner",
        "resource_ids": ["guide", "checklist"],
        "interaction_intensity": "high",
    })

    assert created.status_code == 202
    jobs = created.json()["jobs"]
    assert len(jobs) == 2
    assert [client.app.container.courseware_service().repo.get_job(job["run_id"])["source_resource_ids"] for job in jobs] == [
        ["guide"], ["checklist"],
    ]


def test_reselecting_the_same_supported_resource_creates_a_new_courseware_run(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = {"learner_id": "courseware-learner", "resource_ids": ["guide"]}

    first = client.post("/api/resources/courseware/jobs/batch", json=payload)
    second = client.post("/api/resources/courseware/jobs/batch", json=payload)

    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["jobs"][0]["run_id"] != second.json()["jobs"][0]["run_id"]
