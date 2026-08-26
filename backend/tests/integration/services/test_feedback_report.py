from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult, LearningAttemptSubmit
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.reports.reports import ReportService
from app.services.learners.profiles import ProfileService
from app.api.reports import report as report_routes
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.models.learning_documents.schemas import SourceRef
from app.models.reviews.claims import ClaimJudgement, ClaimRecord


def test_report_reads_persisted_profile_path_attempt_and_version_history():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="kb",
        learning_goal="闭环",
    )
    learners.save(profile)
    resources = MemoryResourceRepository()
    resource = LearningResource(
        resource_id="resource",
        learner_id="learner",
        topic="检索",
        resource_type="测试题",
        difficulty="初级",
        content_text="测试",
        knowledge_points=["skill-a"],
        source_refs=[],
        publication_status="published",
    )
    resources.save(resource, "learner", "检索")
    loop = MemoryFeedbackLoopRepository(learners)
    feedback = MemoryFeedbackRepository()
    FeedbackService(feedback, feedback_loop_repo=loop).process_learning_attempt(
        profile,
        resource,
        LearningAttemptSubmit(
            learner_id="learner",
            source_resource_id="resource",
            idempotency_key="report-idempotency",
            expected_profile_version=1,
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a",
                question_ids=["q1"],
                correct_count=7,
                total_count=10,
            )],
        ),
    )
    report = ReportService(resources, feedback, loop).build_report(learners.get("learner"))
    assert report["profile_version"] == 2
    assert report["knowledge_mastery"]["skill-a"]["score"] == 0.7
    assert report["current_learning_path"]["path_id"]
    assert len(report["recent_attempts"]) == 1
    assert report["recent_feedback_decisions"][0]["action"] == "practice"
    assert report["recent_knowledge_state_mutations"][0]["after"]["mastery"] == 0.7
    assert report["recent_followup_runs"] == []
    assert report["agent_flow"][0]["action"] == "practice"
    assert report["profile_versions"][0]["source_attempt_id"] == report["recent_attempts"][0]["attempt_id"]


def test_formal_feedback_makes_report_available_when_initial_calibration_is_pending():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner", learner_type="测试", education="本科", major="软件工程",
        knowledge_base_id="kb", learning_goal="闭环",
        learning_preferences={"metadata": {"initial_diagnostic_flow": {"status": "pending"}}},
    )
    learners.save(profile)
    resources = MemoryResourceRepository()
    resource = LearningResource(
        resource_id="resource", learner_id="learner", topic="检索", resource_type="测试题",
        difficulty="初级", content_text="测试", knowledge_points=["skill-a"], source_refs=[],
        publication_status="published",
    )
    resources.save(resource, "learner", "检索")
    loop = MemoryFeedbackLoopRepository(learners)
    FeedbackService(MemoryFeedbackRepository(), feedback_loop_repo=loop).process_learning_attempt(
        profile,
        resource,
        LearningAttemptSubmit(
            learner_id="learner", source_resource_id="resource", idempotency_key="pending-calibration",
            expected_profile_version=1, submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a", question_ids=["q1"], correct_count=7, total_count=10,
            )],
        ),
    )

    report = ReportService(resources, MemoryFeedbackRepository(), loop).build_report(learners.get("learner"))

    assert report["report_availability"]["status"] == "ready"
    assert report["metric_summary"]["feedback_count"] == 1


def test_report_excludes_superseded_and_replaced_resources():
    profile = LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        learning_goal="闭环",
    )
    resources = MemoryResourceRepository()
    jobs = MemoryGenerationJobRepository()
    for run_id, payload in [
        ("obsolete", {"constraints": {}}),
        ("base", {"constraints": {}}),
        ("guide-replacement", {"constraints": {"replacement_resource_types": ["实操指南"]}}),
    ]:
        jobs.create(run_id, "learner", "检索", "kb", payload, batch_id="batch")
        jobs.mark_completed(run_id, [])
    jobs.mark_superseded("obsolete", "base")

    for resource_id, run_id, resource_type in [
        ("old-lecture", "obsolete", "讲义"),
        ("lecture", "base", "讲义"),
        ("assessment", "base", "分阶测试题"),
        ("old-guide", "base", "实操指南"),
        ("guide", "guide-replacement", "实操指南"),
    ]:
        resources.save(
            LearningResource(
                resource_id=resource_id,
                learner_id="learner",
                topic="检索",
                resource_type=resource_type,
                difficulty="初级",
                content_text="测试",
                knowledge_points=["kp"],
                source_refs=[],
                publication_status="published",
                run_id=run_id,
                batch_id="batch",
            ),
            "learner",
            "检索",
            run_id=run_id,
            batch_id="batch",
        )

    report = ReportService(
        resources,
        MemoryFeedbackRepository(),
        generation_job_repo=jobs,
    ).build_report(profile)

    assert report["metric_summary"]["resource_count"] == 3
    assert {item.resource_id for item in report["recent_resources"]} == {"lecture", "assessment", "guide"}


def test_report_keeps_prior_resource_visible_when_later_run_does_not_publish_replacement_type():
    profile = LearnerProfile(
        learner_id="learner", learner_type="测试", education="本科",
        major="软件工程", learning_goal="闭环",
    )
    resources = MemoryResourceRepository()
    jobs = MemoryGenerationJobRepository()
    jobs.create("base", "learner", "检索", "kb", {"resource_types": ["分阶测试题"]}, batch_id="batch")
    jobs.create(
        "append-checklist", "learner", "检索", "kb",
        {"resource_types": ["复习清单"], "constraints": {"replacement_resource_types": ["分阶测试题"]}},
        batch_id="batch",
    )
    for run_id in ("base", "append-checklist"):
        jobs.mark_completed(run_id, [])
    for resource_id, run_id, resource_type in [
        ("assessment", "base", "分阶测试题"),
        ("checklist", "append-checklist", "复习清单"),
    ]:
        resources.save(
            LearningResource(
                resource_id=resource_id, learner_id="learner", topic="检索",
                resource_type=resource_type, difficulty="初级", content_text="测试",
                knowledge_points=["kp"], source_refs=[], publication_status="published",
                run_id=run_id, batch_id="batch",
            ),
            "learner", "检索", run_id=run_id, batch_id="batch",
        )

    report = ReportService(resources, MemoryFeedbackRepository(), generation_job_repo=jobs).build_report(profile)

    assert {item.resource_id for item in report["recent_resources"]} == {"assessment", "checklist"}


def test_report_excludes_published_parent_when_published_child_exists():
    resources = MemoryResourceRepository()
    parent = LearningResource(resource_id="parent", learner_id="learner", topic="t", resource_type="讲义", difficulty="初级", content_text="p", knowledge_points=[], source_refs=[], publication_status="published")
    child = parent.model_copy(update={"resource_id": "child", "parent_resource_id": "parent", "version": 2})
    resources.save(parent, "learner", "t")
    resources.save(child, "learner", "t")
    visible = ReportService(resources, MemoryFeedbackRepository())._visible_resources("learner")
    assert [item.resource_id for item in visible] == ["child"]


def test_learning_activity_uses_question_weighting_and_keeps_empty_measurement_null():
    service = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    attempts = [
        SimpleNamespace(source_resource_id="one", submitted_at=now - timedelta(seconds=1), knowledge_point_results=[SimpleNamespace(correct_count=1, total_count=1)]),
        SimpleNamespace(source_resource_id="two", submitted_at=now - timedelta(seconds=1), knowledge_point_results=[SimpleNamespace(correct_count=1, total_count=9)]),
    ]
    summary = service._learning_activity(attempts, now, 30)
    assert summary["answered_item_count"] == 10
    assert summary["correct_item_count"] == 2
    assert summary["verified_accuracy"] == 0.2
    empty = service._learning_activity([], now, 30)
    assert empty["status"] == "not_measured"
    assert empty["verified_accuracy"] is None


def test_resource_credibility_is_not_trusted_without_complete_evidence():
    resource = LearningResource(
        resource_id="legacy", learner_id="learner", topic="检索", resource_type="讲义", difficulty="初级",
        content_text="text", knowledge_points=[], source_refs=[], publication_status="published",
        review_status="passed", review_id="review", claim_metric_status="incomplete",
    )
    item = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())._resource_credibility([resource])["items"][0]
    assert item["grade"] == "insufficient_evidence"
    assert item["claim_support"]["unsupported_rate"] is None


def test_resource_credibility_uses_review_claim_and_verified_source_together():
    audit, claims = MemoryAuditRepository(), MemoryClaimRepository()
    audit.save_review("trusted", {"review_id": "review-trusted", "status": "approved", "issues": []}, "run")
    record = ClaimRecord(
        claim_id="clm_" + "a" * 32, run_id="run", resource_id="trusted", resource_version=1,
        review_id="review-trusted", claim_index=0, claim_text="事实", claim_type="factual",
        source_text="事实", source_start=0, source_end=2, source_text_hash="b" * 64,
        source_evidence_ids=["evidence"], extractor_prompt_version="v1", claim_hash="c" * 64,
    )
    judgement = ClaimJudgement(
        judgement_id="jdg_" + "d" * 32, claim_id=record.claim_id, run_id="run", resource_id="trusted",
        resource_version=1, review_id="review-trusted", status="completed", verdict="supported",
        evidence_ids=["evidence"], reason="supported", judge_type="deterministic", judge_prompt_version="v1",
    )
    claims.save_audit([record], [judgement])
    resource = LearningResource(
        resource_id="trusted", learner_id="learner", topic="检索", resource_type="讲义", difficulty="初级",
        content_text="事实", knowledge_points=[], publication_status="published", run_id="run", review_id="review-trusted",
        source_refs=[SourceRef(doc_id="doc", title="doc", snippet="x", score=1.0, provenance_status="verified", evidence_id="evidence", knowledge_base_id="kb", document_version="1", chunk_id="chunk")],
    )
    item = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository(), claim_repo=claims, audit_repo=audit)._resource_credibility([resource])["items"][0]
    assert item["grade"] == "trusted"
    assert item["claim_support"]["unsupported_rate"] == 0.0


def test_resource_credibility_flags_cross_knowledge_base_reference():
    resource = LearningResource(
        resource_id="cross-kb", learner_id="learner", topic="检索", resource_type="讲义", difficulty="初级",
        content_text="text", knowledge_points=[], publication_status="published",
        source_refs=[SourceRef(doc_id="doc", title="doc", snippet="x", score=1.0, provenance_status="verified",
                               evidence_id="evidence", knowledge_base_id="other-kb", document_version="1", chunk_id="chunk")],
    )
    item = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())._resource_credibility(
        [resource], knowledge_base_id="learner-kb"
    )["items"][0]
    assert item["source_traceability"]["status"] == "failed"
    assert item["grade"] == "attention"
    assert item["reason_codes"] == ["SOURCE_REF_CROSS_KNOWLEDGE_BASE"]


def test_report_etag_is_stable_and_supports_conditional_read():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(learner_id="learner", learner_type="测试", education="本科", major="软件", learning_goal="学习")
    learners.save(profile)
    service = ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())
    app = FastAPI()
    app.container = SimpleNamespace(profile_service=lambda: ProfileService(learners), report_service=lambda: service)
    app.include_router(report_routes.router, prefix="/api/report")
    client = TestClient(app)
    response = client.get("/api/report/learner?window_days=30")
    assert response.status_code == 200
    assert response.json()["report_schema_version"] == "4.1"
    assert response.headers["cache-control"] == "private, no-cache"
    cached = client.get("/api/report/learner?window_days=30", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""
