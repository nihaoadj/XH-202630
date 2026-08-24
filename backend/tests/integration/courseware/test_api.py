"""End-to-end tests for the isolated, fault-tolerant courseware workflow."""

from types import SimpleNamespace
from pathlib import Path
import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.courseware import courseware
from app.api.resource_library import library as resource_library
from app.db.courseware.repository import MemoryCoursewareRepository
from app.db.courseware.repository import SQLCoursewareRepository
from app.db.courseware import models as _courseware_models  # noqa: F401 -- register SQL tables
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.models import Base
from app.models.learning_documents.schemas import LearnerProfile, LearningResource, SourceRef
from app.models.courseware import CoursewareJobCreateRequest
from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.services.courseware import CoursewareService
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from app.services.courseware.executor import CoursewareExecutor


class _AuditRepository:
    def get_run(self, _run_id):
        return None


def _source_ref(kb: str = "kb-courseware") -> SourceRef:
    return SourceRef(doc_id="doc-1", title="课程资料", snippet="已验证来源", score=1.0,
                     provenance_status="verified", knowledge_base_id=kb)


def _resource(resource_id: str, resource_type: str, content: str, *, kb: str = "kb-courseware", exercises=None):
    return LearningResource(
        resource_id=resource_id, learner_id="courseware-learner", topic="RAG 基础",
        resource_type=resource_type, difficulty="初级", content_text=content,
        knowledge_points=["检索增强生成"], source_refs=[_source_ref(kb)], run_id=f"run-{resource_id}",
        batch_id="batch-courseware", publication_status="published", exercise_items=exercises or [],
    )


def _client(tmp_path, monkeypatch, *, with_quiz=True, mixed_feedback_batches=False):
    from app.core.storage import file_storage
    from app.services.courseware import service as courseware_service_module

    monkeypatch.setattr(file_storage, "_get_resources_dir", lambda: tmp_path / "resources")
    monkeypatch.setattr(
        courseware_service_module,
        "load_resource_file",
        lambda relative_path: (tmp_path / "resources" / "courseware" / "courseware-learner" / Path(relative_path).name).read_bytes(),
    )
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="courseware-learner", learner_type="测试", education="本科", major="计算机",
        learning_goal="测试互动课件", knowledge_base_id="kb-courseware",
    ))
    resource_repo = MemoryResourceRepository()
    lecture = _resource("lecture", "讲义", "\n".join([
        "RAG 先检索冻结知识来源，再使用可信上下文生成答案，从而把回答依据限制在可追溯证据范围内。",
        "工程链路需要分别记录入库、切片、索引、检索、生成和审核结果，任何阶段失败都应留下稳定状态与诊断信息。",
        "定位错误时先检查检索结果是否覆盖问题，再检查提示约束是否要求引用证据，最后检查模型是否忠实使用上下文。",
        "验收不仅检查回答是否流畅，还要检查来源覆盖、证据一致、失败恢复、重复执行幂等以及最终产物是否可审计。",
    ]))
    guide = _resource("guide", "实操指南", "\n".join([
        "第一步准备文档并确认版本、知识范围与敏感信息边界，冻结后续流程使用的来源快照。",
        "第二步使用稳定规则切片并建立索引，同时保存块标识、内容哈希和所属资源，避免跨版本混用。",
        "第三步针对代表性问题验证召回结果，记录缺失证据、错误证据与排序异常，再定向调整检索参数。",
        "第四步执行生成与审核，输出必须带来源映射；完成标准是正确路径、失败路径和恢复路径均通过检查。",
    ]))
    if mixed_feedback_batches:
        guide = guide.model_copy(update={"batch_id": "feedback-batch-other"})
    exercises = [{"question_id": "q1", "question_type": "single_choice", "question": "RAG 的第一步是什么？",
                  "options": ["检索", "随机生成"], "answer": "检索", "explanation": "先检索上下文。"}] if with_quiz else []
    assessment = _resource("assessment", "分阶测试题", "\n".join([
        "知识检查聚焦检索、证据与回答之间的顺序关系，作答时必须说明判断依据。",
        "错误选项通常忽略来源冻结或直接跳到生成阶段，因此即使措辞流畅也不能视为正确。",
        "提交答案后先阅读错误原因，再返回对应流程检查点复盘，避免只记住选项而没有掌握方法。",
        "下一步应使用新的代表性问题重复检索验证，并确认输出中的每个关键结论都能回到冻结证据。",
    ]), exercises=exercises)
    for item in (lecture, guide, assessment):
        resource_repo.save(item, "courseware-learner", "RAG 基础")
    service = CoursewareService(MemoryCoursewareRepository(), ResourceService(resource_repo), _AuditRepository())
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


def test_multi_select_creates_resource_scoped_jobs_not_a_merged_course(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    created = client.post("/api/resources/courseware/jobs/batch", json={
        "learner_id": "courseware-learner",
        "resource_ids": ["guide", "assessment"],
        "interaction_intensity": "high",
    })

    assert created.status_code == 202
    jobs = created.json()["jobs"]
    assert len(jobs) == 2
    assert [client.app.container.courseware_service().repo.get_job(job["run_id"])["source_resource_ids"] for job in jobs] == [
        ["guide"], ["assessment"],
    ]


def test_reselecting_the_same_resource_creates_a_new_courseware_run(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    payload = {"learner_id": "courseware-learner", "resource_ids": ["guide"]}

    first = client.post("/api/resources/courseware/jobs/batch", json=payload)
    second = client.post("/api/resources/courseware/jobs/batch", json=payload)

    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["jobs"][0]["run_id"] != second.json()["jobs"][0]["run_id"]


def test_courseware_full_chain_preview_download_and_library(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide", "assessment"],
        "title": "RAG 互动课件",
        "publish_mode": "automatic",
    })
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    _run_worker(client)
    job = client.get(f"/api/resources/courseware/jobs/{run_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "published_with_warnings"
    assert any(warning["code"] == "AI_QUALITY_REVIEW_UNAVAILABLE" for warning in job.json()["warnings"])
    resource_id = job.json()["resource_id"]

    library = client.get("/api/resource-library/courseware-learner")
    assert library.status_code == 200
    assert any(item["id"] == resource_id and item["resource_kind"] == "interactive_courseware" for item in library.json())

    detail = client.get(f"/api/resources/courseware/items/{resource_id}")
    assert detail.status_code == 200
    assert len(detail.json()["source_summary"]) == 3
    assert all(item["usage"]["adopted"] is True for item in detail.json()["source_summary"])
    preview = client.get(f"/api/resources/courseware/items/{resource_id}/preview")
    assert preview.status_code == 200
    assert "Content-Security-Policy" in preview.headers
    assert preview.headers["x-content-type-options"] == "nosniff"
    assert "RAG 互动课件" in preview.text
    download = client.get(f"/api/resources/courseware/items/{resource_id}/file")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    detail_job = client.get(f"/api/resources/courseware/jobs/{run_id}/detail")
    assert detail_job.status_code == 200
    assert len(detail_job.json()["scenes"]) >= 3
    assert {review["kind"] for review in detail_job.json()["reviews"]} == {
        "source_trace", "teaching_quality", "ai_teaching_quality", "page_quality",
    }
    assert {artifact["artifact_format"] for artifact in detail_job.json()["artifacts"]} == {"html", "zip", "scorm", "xapi"}
    events = client.get(f"/api/resources/courseware/jobs/{run_id}/events")
    assert events.status_code == 200
    assert "event: courseware_progress" in events.text
    assert '"status":"published_with_warnings"' in events.text
    for package_format, required_name in (("zip", "manifest.json"), ("scorm", "imsmanifest.xml"), ("xapi", "tincan.xml")):
        package = client.get(f"/api/resources/courseware/items/{resource_id}/packages/{package_format}")
        assert package.status_code == 200
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            assert "index.html" in archive.namelist()
            assert required_name in archive.namelist()


def test_courseware_job_list_is_scoped_to_the_learner_generation_workspace(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    })
    assert created.status_code == 200

    listed = client.get("/api/resources/courseware/jobs", params={"learner_id": "courseware-learner"})

    assert listed.status_code == 200
    assert [item["run_id"] for item in listed.json()["items"]] == [created.json()["run_id"]]
    assert listed.json()["items"][0]["status"] == "queued"


def test_optional_scene_failure_degrades_to_published_courseware(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, with_quiz=False)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide", "assessment"],
        "publish_mode": "automatic",
    })
    run_id = created.json()["run_id"]
    _run_worker(client)
    completed = client.get(f"/api/resources/courseware/jobs/{run_id}").json()
    assert completed["status"] == "published_with_warnings"
    assert completed["resource_id"]
    assert any(item["code"] in {"ASSESSMENT_SCENE_SKIPPED", "ASSESSMENT_SCENE_OPTIONAL"} for item in completed["warnings"])


def test_default_publish_mode_releases_after_automatic_quality_gates(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    })
    run_id = created.json()["run_id"]
    _run_worker(client)
    published = client.get(f"/api/resources/courseware/jobs/{run_id}").json()
    assert published["status"] == "published_with_warnings"
    resource_id = published["resource_id"]
    assert any(item["id"] == resource_id for item in client.get("/api/resource-library/courseware-learner").json())


def test_courseware_admission_requires_both_lecture_and_practice_guide(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture"],
    }).json()
    _run_worker(client)
    rejected = client.get(f"/api/resources/courseware/jobs/{created['run_id']}").json()
    assert rejected["status"] == "rejected_admission"
    assert "实操指南" in rejected["error_message"]


def test_strict_policy_quarantines_when_ai_quality_review_is_unavailable(tmp_path, monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.workflow as workflow_module

    monkeypatch.setattr(
        workflow_module,
        "get_settings",
        lambda: SimpleNamespace(
            courseware_release_policy="strict",
            courseware_total_run_timeout_seconds=900,
            courseware_total_llm_token_budget=32768,
        ),
    )
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    })
    _run_worker(client)

    completed = client.get(f"/api/resources/courseware/jobs/{created.json()['run_id']}").json()
    assert completed["status"] == "quarantined"
    assert completed["resource_id"] is None
    assert completed["error_code"] == "AI_QUALITY_REVIEW_UNAVAILABLE"


def test_admission_rejects_invalid_source_without_publishing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # The missing source must be rejected before snapshot/render, with no partial resource published.
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "missing"],
    })
    run_id = created.json()["run_id"]
    _run_worker(client)
    completed = client.get(f"/api/resources/courseware/jobs/{run_id}").json()
    assert completed["status"] == "rejected_admission"
    assert completed["resource_id"] is None


def test_admission_rejects_sources_from_different_feedback_batches(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, mixed_feedback_batches=True)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    })
    assert created.status_code == 200
    _run_worker(client)

    completed = client.get(f"/api/resources/courseware/jobs/{created.json()['run_id']}").json()
    assert completed["status"] == "rejected_admission"
    assert completed["resource_id"] is None
    assert completed["error_code"] == "COURSEWARE_SOURCE_ADMISSION_REJECTED"
    assert "同一反馈批次" in completed["error_message"]


def test_partial_artifact_failure_stays_hidden_and_retry_recovers(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    original_save_artifact = service.repo.save_artifact
    calls = {"count": 0}

    def fail_first_artifact(row):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("simulated artifact registry outage")
        return original_save_artifact(row)

    service.repo.save_artifact = fail_first_artifact
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
        "publish_mode": "automatic",
    }).json()
    _run_worker(client)
    failed = client.get(f"/api/resources/courseware/jobs/{created['run_id']}").json()
    assert failed["status"] == "failed"
    assert not any(item["resource_kind"] == "interactive_courseware"
                   for item in client.get("/api/resource-library/courseware-learner").json())

    service.repo.save_artifact = original_save_artifact
    client.post(f"/api/resources/courseware/jobs/{created['run_id']}/retry")
    _run_worker(client)
    retried = client.get(f"/api/resources/courseware/jobs/{created['run_id']}").json()
    assert retried["status"] == "published_with_warnings"
    assert sum(item["resource_kind"] == "interactive_courseware"
               for item in client.get("/api/resource-library/courseware-learner").json()) == 1


def test_release_gate_failure_event_preserves_redacted_failed_dimensions(tmp_path, monkeypatch):
    import app.agents.resource_workflows.interactive_courseware.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "quality_gate_report", lambda *_args, **_kwargs: {
        "failed_dimensions": [
            "interaction.one_primary_action_per_scene",
            "visual.contrast",
        ],
    })
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
        "publish_mode": "automatic",
    }).json()

    _run_worker(client)

    service = client.app.container.courseware_service()
    job = service.repo.get_job(created["run_id"])
    failed = [event for event in service.repo.list_events(created["run_id"])
              if event["stage"] == "release_gate" and event["status"] == "failed"]
    assert job["status"] == "release_blocked"
    assert failed[-1]["payload"] == {
        "error_type": "CoursewareReleaseGateError",
        "error_code": "COURSEWARE_QUALITY_GATE_FAILED",
        "failed_dimensions": ["interaction.one_primary_action_per_scene"],
        "candidate_id": None,
        "release_id": None,
    }


def test_new_source_family_version_marks_published_courseware_stale(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
        "publish_mode": "automatic",
    }).json()
    _run_worker(client)
    resource_id = client.get(f"/api/resources/courseware/jobs/{created['run_id']}").json()["resource_id"]
    resource_service = client.app.container.resource_service()
    next_lecture = resource_service.get("lecture").model_copy(update={
        "resource_id": "lecture-v2", "resource_family_id": "lecture", "version": 2,
        "content_text": "RAG 新版本仍然先检索，再基于可信上下文生成。",
    })
    resource_service.repo.save(next_lecture, "courseware-learner", "RAG 基础")

    library = client.get("/api/resource-library/courseware-learner").json()
    courseware = next(item for item in library if item["id"] == resource_id)
    assert courseware["status"] == "stale"
    assert client.get(f"/api/resources/courseware/items/{resource_id}/preview").status_code == 200


def test_scene_retry_only_composes_the_target_scene_and_records_a_revision(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
        "publish_mode": "automatic",
    }).json()
    _run_worker(client)
    run_id = created["run_id"]
    before = service.get_job_detail(run_id)
    resource_before = service.get_resource(before.resource_id)
    target = next(scene for scene in before.scenes if scene.kind == "intro")
    attempts_before = {scene.scene_id: scene.attempt for scene in before.scenes}
    calls = []

    def compose_one(_gateway, _run_id, scene_id, deterministic_scene, _source):
        calls.append(scene_id)
        return ({**deterministic_scene, "blocks": ["局部修订后的内容。"]}, None)

    from app.services.courseware import service as courseware_service_module
    monkeypatch.setattr(courseware_service_module, "compose_courseware_scene", compose_one)
    retried = service.retry_scene(run_id, target.scene_id)
    assert retried and retried.run_id == run_id
    after = service.get_job_detail(run_id)
    assert calls == [target.scene_id]
    assert next(scene for scene in after.scenes if scene.scene_id == target.scene_id).attempt == attempts_before[target.scene_id] + 1
    assert all(scene.attempt == attempts_before[scene.scene_id] for scene in after.scenes if scene.scene_id != target.scene_id)
    assert len(after.scene_revisions[target.scene_id]) == 1
    drained = service.process_scene_outbox(run_id)
    assert drained["skipped"] == 1
    from app.agents.resource_workflows.interactive_courseware.worker import CoursewareSceneWorker
    assert CoursewareSceneWorker(service.workflow).run_once(run_id) == {"processed": 0, "skipped": 0, "failed": 0}
    assert service.get_resource(before.resource_id).artifact_sha256 != resource_before.artifact_sha256
    review = client.get(f"/api/resources/courseware/jobs/{run_id}/scenes/{target.scene_id}/review")
    assert review.status_code == 200
    assert review.json()["scene_id"] == target.scene_id
    assert len(review.json()["revisions"]) == 1
    assert "prompt" not in review.json()


def test_ai_review_automatically_revises_a_mapped_scene_before_publish(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    workflow = service.workflow
    import app.agents.resource_workflows.interactive_courseware.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "courseware_ai_available", lambda _gateway: True)
    calls = {"review": 0, "revision": 0}

    def compose(_gateway, _run_id, _scene_id, scene, source):
        if scene.get("_review_instruction"):
            calls["revision"] += 1
        updated = {key: value for key, value in scene.items() if key != "_review_instruction"}
        component_blocks = [dict(block) for block in updated.get("component_blocks") or []]
        if component_blocks:
            component_blocks[0]["block_id"] = "auto-block"
        updated["component_blocks"] = component_blocks
        return updated, None

    def review(_gateway, _run_id, _document):
        calls["review"] += 1
        if calls["review"] == 1:
            return CoursewareReviewDecision.model_validate({
                "decision": "revision_required",
                "issues": [{"code": "CLARIFY", "instruction": "澄清关键点", "block_id": "auto-block"}],
            }), None
        return CoursewareReviewDecision(decision="approved"), None

    workflow.scene_composer = compose
    monkeypatch.setattr(workflow_module, "review_courseware_quality_decision", review)
    job = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide"],
    ))
    completed = service.run_job(job.run_id)
    assert completed.status == "published"
    assert calls == {"review": 2, "revision": 1}
    detail = service.get_job_detail(job.run_id)
    assert any(revision["trigger"] == "auto_review" for revisions in detail.scene_revisions.values() for revision in revisions)


def test_unmappable_ai_review_issue_uses_verified_fallback_under_resilient_policy(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    import app.agents.resource_workflows.interactive_courseware.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "courseware_ai_available", lambda _gateway: True)
    monkeypatch.setattr(workflow_module, "review_courseware_quality_decision", lambda *_args: (
        CoursewareReviewDecision.model_validate({
            "decision": "revision_required",
            "issues": [{"code": "GLOBAL", "instruction": "无法安全定位的全局问题"}],
        }), None,
    ))
    job = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide"],
    ))
    completed = service.run_job(job.run_id)
    assert completed.status == "published_with_warnings"
    assert completed.resource_id is not None
    assert any(item["code"] == "AI_REVISION_BUDGET_EXHAUSTED_FALLBACK" for item in completed.warnings)


def test_thin_but_schema_valid_ai_scenes_fall_back_to_rich_deterministic_pages(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    workflow = service.workflow
    import app.agents.resource_workflows.interactive_courseware.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "courseware_ai_available", lambda _gateway: True)
    monkeypatch.setattr(workflow_module, "review_courseware_quality_decision", lambda *_args: (
        CoursewareReviewDecision(decision="approved"), None,
    ))

    def thin_scene(_gateway, _run_id, _scene_id, scene, _source):
        return {**scene, "lead": "过短", "blocks": ["过短"], "conclusion": "过短"}, None

    workflow.scene_composer = thin_scene
    job = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide"],
    ))

    completed = service.run_job(job.run_id)

    assert completed.status == "published_with_warnings"
    assert completed.resource_id is not None
    assert any(item["code"] == "PAGE_QUALITY_DETERMINISTIC_FALLBACK" for item in completed.warnings)
    assert all(scene.agent_version == "deterministic-v1" for scene in service.get_job_detail(job.run_id).scenes)


def test_sqlite_persistence_keeps_published_artifact_and_lineage(tmp_path, monkeypatch):
    """Exercise the real SQL schema rather than only the in-memory fallback."""
    from app.core.storage import file_storage
    from app.services.courseware import service as courseware_service_module

    engine = create_engine(f"sqlite:///{tmp_path / 'courseware.db'}")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    learner_repo = SQLLearnerRepository(sessions)
    learner_repo.save(LearnerProfile(
        learner_id="courseware-learner", learner_type="测试", education="本科", major="计算机",
        learning_goal="测试互动课件", knowledge_base_id="kb-courseware",
    ))
    source_repo = SQLResourceRepository(sessions)
    dense_lecture = "\n".join([
        "RAG 先检索冻结知识来源，再使用可信上下文生成答案，从而把回答依据限制在可追溯证据范围内。",
        "工程链路分别记录入库、切片、索引、检索、生成和审核结果，任何阶段失败都留下稳定诊断信息。",
        "定位错误时先检查检索覆盖，再检查提示约束，最后检查模型是否忠实使用上下文与引用证据。",
        "验收需要覆盖来源一致、失败恢复、重复执行幂等以及最终产物可审计等关键要求。",
    ])
    dense_guide = "\n".join([
        "第一步准备文档并确认版本、知识范围与敏感信息边界，冻结后续流程使用的来源快照。",
        "第二步使用稳定规则切片并建立索引，同时保存块标识、内容哈希和所属资源。",
        "第三步针对代表性问题验证召回结果，记录缺失证据、错误证据与排序异常。",
        "第四步执行生成与审核，完成标准是正确路径、失败路径和恢复路径均通过检查。",
    ])
    for item in (_resource("lecture", "讲义", dense_lecture), _resource("guide", "实操指南", dense_guide)):
        item = item.model_copy(update={"run_id": None, "batch_id": "batch-courseware"})
        source_repo.save(item, "courseware-learner", "RAG 基础")
    monkeypatch.setattr(file_storage, "_get_resources_dir", lambda: tmp_path / "artifacts")
    monkeypatch.setattr(
        courseware_service_module,
        "load_resource_file",
        lambda relative_path: (tmp_path / "artifacts" / "courseware" / "courseware-learner" / Path(relative_path).name).read_bytes(),
    )
    service = CoursewareService(SQLCoursewareRepository(sessions), ResourceService(source_repo), _AuditRepository())
    job = service.create_job(CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["lecture", "guide"],
        publish_mode="automatic",
    ))
    completed = service.run_job(job.run_id)
    assert completed.status == "published_with_warnings"
    assert completed.resource_id
    reloaded = SQLCoursewareRepository(sessions).get_resource(completed.resource_id)
    assert reloaded and reloaded["artifact_sha256"]
    assert len(SQLCoursewareRepository(sessions).get_links(completed.resource_id)) == 2
    persisted = SQLCoursewareRepository(sessions)
    spec = persisted.get_spec_by_run(job.run_id)
    assert spec and len(persisted.list_scenes(spec["spec_id"])) >= 3
    assert len(persisted.list_reviews(job.run_id)) == 4
    assert {item["artifact_format"] for item in persisted.list_artifacts(completed.resource_id)} == {"html", "zip", "scorm", "xapi"}
    assert persisted.list_events(job.run_id)
    assert service.artifact(completed.resource_id)[1].startswith(b"<!doctype html>")
