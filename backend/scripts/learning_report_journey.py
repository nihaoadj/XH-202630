"""Deterministic local SQLite journey for the dynamic learning-report read model."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from learner_mastery_journey import _build_repositories, run_journey as run_mastery_journey

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learners.mastery import SQLMasteryRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.services.learners.mastery import MasteryService
from app.services.knowledge.knowledge import KnowledgeService
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.services.reports.reports import ReportService
from app.models.learning_documents.schemas import LearningResource, SourceRef
from app.models.reviews.claims import ClaimJudgement, ClaimRecord


def _service(factory):
    learners = SQLLearnerRepository(factory)
    catalog = KnowledgeCatalogRepository(factory)
    mastery = MasteryService(SQLMasteryRepository(factory), KnowledgeService(catalog=catalog))
    return learners, ReportService(
        resource_repo=SQLResourceRepository(factory), feedback_repo=MemoryFeedbackRepository(),
        feedback_loop_repo=SQLFeedbackLoopRepository(factory), generation_job_repo=SQLGenerationJobRepository(factory),
        mastery_service=mastery, claim_repo=SQLClaimRepository(factory), audit_repo=SQLAuditRepository(factory),
    )


def run_journey(work_dir: Path) -> dict:
    started = time.monotonic()
    base = run_mastery_journey(work_dir)
    assertions = {"mastery_base": base["status"] == "LOCAL_READY"}
    db_path = work_dir / "learner-mastery-journey.db"
    engine, factory = _build_repositories(db_path)
    learners, service = _service(factory)
    profile = learners.get("journey-learner")
    attempts = SQLFeedbackLoopRepository(factory).list_attempts(profile.learner_id, 100)
    as_of = max(item.submitted_at for item in attempts) + timedelta(seconds=1)
    first = service.build_report(profile, window_days=30, now=as_of)
    assertions.update({
        "report_3_contract": first["report_schema_version"] == "3.0" and first["report_revision"].startswith("rpt_"),
        "weighted_activity": first["learning_activity"]["answered_item_count"] > 0 and first["learning_activity"]["answered_item_count"] >= first["learning_activity"]["correct_item_count"],
        "mastery_projection": first["knowledge_mastery"] == {
            node.skill_node_id: node.mastery.model_dump(mode="json") for node in first["ability_nodes"]
        },
        "not_measured_null": first["review_summary"]["average_hallucination_rate"] is None,
    })
    resources = SQLResourceRepository(factory)
    audit = SQLAuditRepository(factory)
    claims = SQLClaimRepository(factory)
    def source_ref():
        return SourceRef(doc_id="journey-doc", title="Journey doc", snippet="safe", score=1.0,
                         provenance_status="verified", evidence_id="journey-evidence", knowledge_base_id="journey-kb",
                         document_version="1", chunk_id="journey-chunk")
    def resource(resource_id, *, version, review_id=None, claim_status=None):
        value = LearningResource(
            resource_id=resource_id, learner_id=profile.learner_id, topic=resource_id, resource_type="讲义",
            difficulty="初级", content_text="可核验事实", knowledge_points=["foundation"], source_refs=[source_ref()],
            publication_status="published", published_at=as_of - timedelta(seconds=1), run_id="journey-run-first",
            review_id=review_id, review_status="approved" if review_id else None, claim_metric_status=claim_status,
            version=version,
        )
        resources.save(value, profile.learner_id, value.topic, run_id=value.run_id)
        return value
    trusted = resource("report-trusted", version=2, review_id="review-trusted", claim_status="not_applicable")
    attention = resource("report-attention", version=3, review_id="review-attention")
    resource("report-legacy", version=4)
    audit.save_review(trusted.resource_id, {"review_id": trusted.review_id, "status": "approved", "issues": []}, trusted.run_id)
    audit.save_review(attention.resource_id, {"review_id": attention.review_id, "status": "approved", "issues": []}, attention.run_id)
    claim = ClaimRecord(
        claim_id=f"clm_{'b' * 32}", run_id=attention.run_id, resource_id=attention.resource_id,
        resource_version=attention.version, review_id=attention.review_id, claim_index=0,
        claim_text="可核验事实", claim_type="factual", source_text="可核验事实", source_start=0, source_end=5,
        source_text_hash="c" * 64, source_evidence_ids=[], extractor_prompt_version="journey-v1", claim_hash="d" * 64,
    )
    claims.save_audit([claim], [ClaimJudgement(
        judgement_id=f"jdg_{'b' * 32}", claim_id=claim.claim_id, run_id=attention.run_id,
        resource_id=attention.resource_id, resource_version=attention.version, review_id=attention.review_id,
        status="completed", verdict="not_in_evidence", evidence_ids=[], reason="fixture", judge_type="deterministic", judge_prompt_version="journey-v1",
    )])
    graded = service.build_report(profile, window_days=30, now=as_of)
    grades = {item["resource_id"]: item["grade"] for item in graded["recent_resource_credibility"]}
    assertions["three_resource_grades"] = grades.get("report-trusted") == "trusted" and grades.get("report-attention") == "attention" and grades.get("report-legacy") == "insufficient_evidence"
    assertions["resource_change_updates_revision"] = graded["report_revision"] != first["report_revision"]
    revision_before_restart = first["report_revision"]
    engine.dispose()
    restarted_engine, restarted_factory = _build_repositories(db_path)
    restarted_learners, restarted_service = _service(restarted_factory)
    second = restarted_service.build_report(restarted_learners.get("journey-learner"), window_days=30, now=as_of)
    assertions["restart_consistency"] = graded["report_revision"] == second["report_revision"]
    restarted_engine.dispose()
    complete = all(assertions.values())
    return {
        "schema_version": "1.0", "status": "LOCAL_READY" if complete else "PARTIAL",
        "task_status": "TASK_READY" if complete else "TASK_PARTIAL", "joint_status": "JOINT_PENDING",
        "base_head": base.get("base_head"), "initial_report_revision": revision_before_restart,
        "final_report_revision": second["report_revision"], "as_of_profile_version": first["as_of_profile_version"],
        "window_days": 30, "weighted_activity": {"numerator": first["learning_activity"]["correct_item_count"], "denominator": first["learning_activity"]["answered_item_count"]},
        "mastery_consistency_assertions": assertions["mastery_projection"], "weakness_group_assertions": bool(first["weakness_groups"]),
        "resource_grade_assertions": {"grades": grades, "summary": graded["resource_credibility_summary"]}, "etag_200_304_assertions": "covered by API suite",
        "sse_snapshot_change_reconnect_assertions": "covered by stream and frontend suites", "authorization_assertions": "covered by API suite",
        "restart_consistency": assertions["restart_consistency"], "assertions": assertions,
        "remaining_gates": ["joint_courseware_report_regression"],
        "test_duration_seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="learning-report-") as directory:
        result = run_journey(Path(directory))
    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
