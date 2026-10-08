"""Deterministic local learner-mastery journey backed by temporary SQLite."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.learners.profiles import update_profile
from app.core.security.errors import ApplicationError
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learners.mastery import SQLMasteryRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.migrations.p0_19_learner_mastery import MIGRATION_ID, apply_p0_19_learner_mastery_migration
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import AgentRunORM, Base, UserProfileORM
from app.models.feedback.feedback_loop import LearningAttemptSubmit
from app.models.learning_documents.schemas import (
    ExerciseItem,
    GenerateRequest,
    LearnerProfile,
    LearningResource,
    RunAttemptSubmitRequest,
)
from app.models.reports.contracts import ReportResponse
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService
from app.services.knowledge.knowledge import KnowledgeService
from app.services.learners.mastery import MasteryService
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService


UTC = timezone.utc


class _NoopGenerationService:
    pass


def _assert(report: dict, name: str, condition: bool, actual) -> None:
    if not condition:
        raise AssertionError(f"{name}: {actual!r}")
    report["assertions"].append({"name": name, "status": "passed", "actual": actual})


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ApplicationError):
        return exc.code.value
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        return str(exc.detail.get("code"))
    return type(exc).__name__


def _expect_error(report: dict, name: str, expected: str, callback) -> None:
    try:
        callback()
    except Exception as exc:  # noqa: BLE001 - journey records the public failure contract
        code = _error_code(exc)
        _assert(report, name, code == expected, code)
        report["negative_checks"].append({"name": name, "code": code})
        return
    raise AssertionError(f"{name}: expected {expected}")


def _legacy_unmapped_check(path: Path) -> dict:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE knowledge_bases (knowledge_base_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE learner_profiles (learner_id VARCHAR(64) PRIMARY KEY, knowledge_base_id VARCHAR(128), "
            "knowledge_states JSON, theory_scores JSON, weak_points JSON, strong_points JSON, profile_version INTEGER)"
        ))
        connection.execute(text(
            "CREATE TABLE rag_skill_nodes (node_id VARCHAR(128) PRIMARY KEY, knowledge_base_id VARCHAR(128), name VARCHAR(256))"
        ))
        connection.execute(text(
            "CREATE TABLE knowledge_states (state_id VARCHAR(128) PRIMARY KEY, learner_id VARCHAR(64), "
            "knowledge_base_id VARCHAR(128), skill_node_id VARCHAR(128), mastery_score FLOAT, status VARCHAR(32), "
            "evidence JSON, attempt_count INTEGER DEFAULT 0, last_attempt_id VARCHAR(128), row_version INTEGER DEFAULT 1, "
            "last_updated DATETIME)"
        ))
        connection.execute(text("INSERT INTO knowledge_bases VALUES ('legacy-kb')"))
        connection.execute(text("INSERT INTO rag_skill_nodes VALUES ('legacy-a','legacy-kb','同名')"))
        connection.execute(text("INSERT INTO rag_skill_nodes VALUES ('legacy-b','legacy-kb','同名')"))
        connection.execute(text(
            "INSERT INTO learner_profiles VALUES ('legacy-learner','legacy-kb',:states,'{}','[]','[]',1)"
        ), {"states": json.dumps({"同名": {"score": 0.9}}, ensure_ascii=False)})
    apply_p0_19_learner_mastery_migration(engine)
    apply_p0_19_learner_mastery_migration(engine)
    with engine.begin() as connection:
        row = connection.execute(text(
            "SELECT mapped_count,canonical_preserved_count,unmapped_count,unmapped_entries "
            "FROM learner_mastery_migration_reports WHERE migration_id=:migration_id"
        ), {"migration_id": MIGRATION_ID}).one()
        state_count = connection.execute(text("SELECT COUNT(*) FROM knowledge_states")).scalar_one()
        event_count = connection.execute(text("SELECT COUNT(*) FROM ability_state_events")).scalar_one()
    engine.dispose()
    return {
        "mapped_count": row.mapped_count,
        "canonical_preserved_count": row.canonical_preserved_count,
        "unmapped_count": row.unmapped_count,
        "unmapped_entries": json.loads(row.unmapped_entries),
        "state_count": state_count,
        "event_count": event_count,
    }


def _build_repositories(db_path: Path):
    engine = configure_sqlite_foreign_keys(create_engine(
        f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False}, poolclass=NullPool
    ))
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, factory


def run_journey(work_dir: Path) -> dict:
    report = {
        "schema_version": "1.0",
        "status": "PARTIAL",
        "fixture": "sanitized-local-sqlite",
        "assertions": [],
        "steps": [],
        "negative_checks": [],
    }
    db_path = work_dir / "learner-mastery-journey.db"
    engine, factory = _build_repositories(db_path)
    Base.metadata.create_all(engine)

    learner_repo = SQLLearnerRepository(factory)
    catalog = KnowledgeCatalogRepository(factory)
    knowledge = KnowledgeService(catalog=catalog)
    mastery_repo = SQLMasteryRepository(factory)
    mastery = MasteryService(mastery_repo, knowledge)
    jobs_repo = SQLGenerationJobRepository(factory)
    jobs = GenerationJobService(jobs_repo, _NoopGenerationService(), mastery)
    resources = SQLResourceRepository(factory)
    loop = SQLFeedbackLoopRepository(factory)
    feedback = FeedbackService(
        MemoryFeedbackRepository(), feedback_loop_repo=loop, knowledge_catalog=catalog
    )

    with factory() as db:
        db.add(UserProfileORM(
            user_id="journey-user", username="journey-user", display_name="Journey User",
            identity="测试", education="本科", major="软件工程", is_active=True,
        ))
        db.commit()
    catalog.upsert_knowledge_base({
        "knowledge_base_id": "journey-kb", "name": "Journey KB", "version": "1.0",
        "domain": "testing", "description": "sanitized fixture", "learner_levels": ["beginner"],
    })
    catalog.upsert_skill_nodes([
        {"node_id": "foundation", "name": "基础能力", "level": "L1"},
        {"node_id": "application", "name": "应用能力", "level": "L2", "prerequisites": ["foundation"]},
    ], "journey-kb")
    catalog.upsert_knowledge_base({
        "knowledge_base_id": "other-kb", "name": "Other KB", "version": "1.0",
        "domain": "testing", "description": "negative scope", "learner_levels": ["beginner"],
    })
    catalog.upsert_skill_nodes([{"node_id": "outside", "name": "外部节点"}], "other-kb")

    profile = LearnerProfile(
        learner_id="journey-learner", user_id="journey-user", learner_type="问卷学习者",
        education="本科", major="软件工程", knowledge_base_id="journey-kb",
        learning_goal="验证画像能力闭环",
    )
    learner_repo.save(profile)
    _assert(report, "create_profile_version", profile.profile_version == 1, profile.profile_version)
    report["steps"].append({"step": "create_profile", "profile_version": 1})

    states, prior_version, changed = mastery.apply_onboarding_answers(
        profile,
        {"experience": {"options": [{
            "value": "beginner", "self_report_score": 30,
            "diagnostic_scope_add": ["foundation"],
        }]}},
        {"experience": "beginner"},
    )
    prior = {item.skill_node_id: item for item in states}
    _assert(report, "onboarding_low_confidence_prior", (
        changed and prior["foundation"].self_report_prior == 0.3
        and prior["foundation"].status.value == "self_reported"
        and prior["foundation"].confidence.value == "low"
        and prior["foundation"].objective_evidence_count == 0
    ), prior["foundation"].model_dump(mode="json"))
    _assert(report, "onboarding_unselected_is_unassessed", (
        prior["application"].mastery_score is None and prior["application"].status.value == "unassessed"
    ), prior["application"].model_dump(mode="json"))
    _assert(report, "onboarding_does_not_increment_profile_version", prior_version == 1, prior_version)
    report["steps"].append({
        "step": "onboarding", "profile_version": prior_version,
        "states": {key: value.model_dump(mode="json") for key, value in prior.items()},
    })

    # Keep evidence chronology faithful even though onboarding owns its clock.
    diagnosis_time = datetime.now(UTC) + timedelta(minutes=1)
    diagnosed, diagnosis_version, diagnosis_changed = mastery.apply_diagnosis(
        learner_repo.get(profile.learner_id), {"foundation": 0.4},
        source_id="diagnosis-journey-1", source_hash="d" * 64, occurred_at=diagnosis_time,
    )
    diagnosis_state = {item.skill_node_id: item for item in diagnosed}["foundation"]
    _assert(report, "diagnosis_prior_formula", diagnosis_state.mastery_score == 0.38,
            diagnosis_state.model_dump(mode="json"))
    _assert(report, "diagnosis_version_once", diagnosis_changed and diagnosis_version == 2, diagnosis_version)
    report["steps"].append({
        "step": "diagnosis", "profile_version": diagnosis_version,
        "before": prior["foundation"].model_dump(mode="json"),
        "after": diagnosis_state.model_dump(mode="json"),
    })

    profile = learner_repo.get(profile.learner_id)
    first_job = jobs.create_job(profile, GenerateRequest(
        learner_id=profile.learner_id, topic="基础能力补强", knowledge_base_id="journey-kb",
        resource_types=["分阶测试题"], profile_focus_mode="auto",
    ), run_id="journey-run-first", batch_id="journey-batch-first")
    _assert(report, "first_focus_adopts_confirmed_weak", first_job.focus_snapshot.adopted_node_ids == ["foundation"],
            first_job.focus_snapshot.model_dump(mode="json"))
    report["steps"].append({"step": "first_generation", "focus": first_job.focus_snapshot.model_dump(mode="json")})

    with factory() as db:
        db.add(AgentRunORM(
            run_id="journey-run-first", learner_id=profile.learner_id,
            knowledge_base_id="journey-kb", topic="基础能力补强", status="completed",
        ))
        db.commit()
    resource = LearningResource(
        resource_id="journey-resource", learner_id=profile.learner_id, topic="基础能力补强",
        resource_type="分阶测试题", difficulty="初级", content_text="sanitized exercise",
        knowledge_points=["foundation"], source_refs=[], learning_path_node="foundation",
        publication_status="published", published_at=diagnosis_time + timedelta(minutes=1),
        run_id="journey-run-first", batch_id="journey-batch-first",
        exercise_items=[ExerciseItem(
            question_id="foundation-check", question_type="single_choice",
            options=["A", "B"], skill_node_id="foundation", knowledge_point="基础能力",
            question="选择正确项", answer="A",
        )],
    )
    resources.save(resource, profile.learner_id, resource.topic, run_id=resource.run_id, batch_id=resource.batch_id)
    resource = resources.get(resource.resource_id)
    _assert(report, "published_text_resource_ready", resource.publication_status == "published", resource.resource_id)

    session = feedback.build_run_evaluation_session(profile, "journey-run-first", [resource], knowledge)
    question_id = session.questions[0].question_id
    attempt_payload = RunAttemptSubmitRequest(
        learner_id=profile.learner_id, run_id="journey-run-first",
        source_resource_id=resource.resource_id, idempotency_key="journey-attempt-0001",
        expected_profile_version=diagnosis_version,
        submitted_at=diagnosis_time + timedelta(minutes=2),
        answers=[{"question_id": question_id, "answer": "B"}],
    )
    feedback_result = feedback.submit_run_attempt(
        profile, "journey-run-first", [resource], attempt_payload, knowledge
    )
    mutation = feedback_result.knowledge_state_updates[0]
    _assert(report, "feedback_ewma_formula", mutation.after.mastery == 0.266,
            mutation.model_dump(mode="json"))
    _assert(report, "feedback_commits_attempt_event_mutation_path_version", (
        feedback_result.profile_version == 3
        and feedback_result.path_mutation.attempt_id == feedback_result.attempt.attempt_id
        and len(mastery_repo.list_events(profile.learner_id, "journey-kb")) == 3
    ), feedback_result.model_dump(mode="json"))
    report["steps"].append({
        "step": "run_feedback", "attempt_id": feedback_result.attempt.attempt_id,
        "profile_version": feedback_result.profile_version,
        "before": mutation.before.model_dump(mode="json"), "after": mutation.after.model_dump(mode="json"),
        "path_mutation_id": feedback_result.path_mutation.mutation_id,
    })

    event_count = len(mastery_repo.list_events(profile.learner_id, "journey-kb"))
    replay = feedback.submit_run_attempt(
        learner_repo.get(profile.learner_id), "journey-run-first", [resource], attempt_payload, knowledge
    )
    replay_profile = learner_repo.get(profile.learner_id)
    _assert(report, "feedback_replay_is_idempotent", (
        replay.idempotent_replay and replay.profile_version == 3
        and replay_profile.profile_version == 3
        and len(mastery_repo.list_events(profile.learner_id, "journey-kb")) == event_count
    ), replay.model_dump(mode="json"))
    report["steps"].append({
        "step": "feedback_replay", "attempt_id": replay.attempt.attempt_id,
        "idempotent_replay": replay.idempotent_replay, "profile_version": replay.profile_version,
    })

    profile = learner_repo.get(profile.learner_id)
    report_payload = ReportService(
        resources, MemoryFeedbackRepository(), loop, jobs_repo, mastery
    ).build_report(profile)
    ReportResponse.model_validate(report_payload)
    canonical = {item.skill_node_id: item for item in mastery_repo.list_states(profile.learner_id, "journey-kb")}
    trend_sources = [item["source_type"] for item in report_payload["mastery_trend"]]
    _assert(report, "report_matches_canonical_mastery", (
        report_payload["knowledge_mastery"]["foundation"]["mastery_score"]
        == canonical["foundation"].mastery_score == 0.266
        and report_payload["as_of_profile_version"] == profile.profile_version == 3
        and len(report_payload["mastery_trend"]) == event_count
    ), {"report": report_payload["knowledge_mastery"]["foundation"],
        "canonical": canonical["foundation"].model_dump(mode="json")})
    _assert(report, "report_trend_is_chronological_and_typed", trend_sources == [
        "onboarding_self_report", "diagnosis", "learning_attempt",
    ], trend_sources)
    report["steps"].append({
        "step": "report", "as_of_profile_version": report_payload["as_of_profile_version"],
        "mastery": report_payload["knowledge_mastery"]["foundation"],
        "trend_event_ids": [item["event_id"] for item in report_payload["mastery_trend"]],
    })

    next_job = jobs.create_job(profile, GenerateRequest(
        learner_id=profile.learner_id, topic="下一批补强", knowledge_base_id="journey-kb",
        resource_types=["讲义"], profile_focus_mode="auto",
    ), run_id="journey-run-next")
    explicit_job = jobs.create_job(profile, GenerateRequest(
        learner_id=profile.learner_id, topic="显式目标", knowledge_base_id="journey-kb",
        target_skill_nodes=["application"], resource_types=["讲义"], profile_focus_mode="auto",
    ), run_id="journey-run-explicit")
    off_job = jobs.create_job(profile, GenerateRequest(
        learner_id=profile.learner_id, topic="关闭焦点", knowledge_base_id="journey-kb",
        resource_types=["讲义"], profile_focus_mode="off",
    ), run_id="journey-run-off")
    _assert(report, "next_auto_focus_uses_highest_priority", next_job.focus_snapshot.adopted_node_ids[0] == "foundation",
            next_job.focus_snapshot.model_dump(mode="json"))
    _assert(report, "explicit_focus_overrides_auto", explicit_job.focus_snapshot.adopted_node_ids == ["application"],
            explicit_job.focus_snapshot.model_dump(mode="json"))
    _assert(report, "focus_off_adopts_nothing", off_job.focus_snapshot.adopted_node_ids == [],
            off_job.focus_snapshot.model_dump(mode="json"))
    report["steps"].append({
        "step": "next_focus", "first_hash": first_job.focus_snapshot.mastery_snapshot_hash,
        "next_hash": next_job.focus_snapshot.mastery_snapshot_hash,
        "auto": next_job.focus_snapshot.model_dump(mode="json"),
        "explicit": explicit_job.focus_snapshot.model_dump(mode="json"),
        "off": off_job.focus_snapshot.model_dump(mode="json"),
    })

    raw_attempt = LearningAttemptSubmit(
        learner_id=profile.learner_id, source_resource_id=resource.resource_id,
        source_resource_version=resource.version, source_run_id=resource.run_id,
        idempotency_key="journey-unverified", expected_profile_version=profile.profile_version,
        submitted_at=diagnosis_time + timedelta(minutes=3),
        knowledge_point_results=[{
            "knowledge_point_id": "foundation", "question_ids": [question_id],
            "correct_count": 1, "total_count": 1,
        }],
    )
    _expect_error(report, "unverified_score_rejected", "FEEDBACK_EVIDENCE_UNVERIFIED",
                  lambda: feedback.process_learning_attempt(profile, resource, raw_attempt, verified_evidence=False))
    _expect_error(report, "cross_knowledge_base_node_rejected", "ValueError",
                  lambda: mastery.apply_diagnosis(
                      profile, {"outside": 1.0}, source_id="cross-kb", source_hash="x" * 64,
                      occurred_at=diagnosis_time,
                  ))
    bad_question = RunAttemptSubmitRequest.model_validate({**attempt_payload.model_dump(mode="json"),
        "idempotency_key": "journey-bad-question",
        "expected_profile_version": profile.profile_version,
        "answers": [{"question_id": "journey-resource:not-in-session", "answer": "A"}],
    })
    _expect_error(report, "cross_resource_question_rejected", "ValueError",
                  lambda: feedback.submit_run_attempt(profile, "journey-run-first", [resource], bad_question, knowledge))
    stale = attempt_payload.model_copy(update={"idempotency_key": "journey-stale-version"})
    _expect_error(report, "stale_profile_version_rejected", "LEARNER_PROFILE_VERSION_CONFLICT",
                  lambda: feedback.submit_run_attempt(profile, "journey-run-first", [resource], stale, knowledge))
    conflict = RunAttemptSubmitRequest.model_validate({**attempt_payload.model_dump(mode="json"),
        "answers": [{"question_id": question_id, "answer": "A"}],
    })
    _expect_error(report, "idempotency_payload_conflict", "FEEDBACK_IDEMPOTENCY_CONFLICT",
                  lambda: feedback.submit_run_attempt(profile, "journey-run-first", [resource], conflict, knowledge))

    fake_request = SimpleNamespace(app=SimpleNamespace(container=SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo)
    )))
    _expect_error(report, "profile_system_patch_rejected", "PROFILE_SYSTEM_FIELD_READ_ONLY",
                  lambda: update_profile(profile.learner_id, fake_request, {"theory_scores": {"foundation": 99}}))

    legacy = _legacy_unmapped_check(work_dir / "legacy-migration.db")
    _assert(report, "ambiguous_legacy_name_is_not_guessed", (
        legacy["unmapped_count"] == 1 and legacy["mapped_count"] == 0
        and legacy["state_count"] == 0 and legacy["event_count"] == 0
    ), legacy)
    report["migration"] = legacy

    empty_profile = LearnerProfile(
        learner_id="empty-focus", learner_type="测试", education="本科", major="软件工程",
        knowledge_base_id="other-kb", learning_goal="空重点",
    )
    learner_repo.save(empty_profile)
    mastery.ensure_profile_projection(empty_profile)
    empty_focus = mastery.focus_snapshot(empty_profile, mode="auto", explicit_node_ids=[])
    _assert(report, "no_eligible_weakness_is_safe", (
        empty_focus.adopted_node_ids == [] and empty_focus.skipped[0].reason_code == "NO_ELIGIBLE_WEAKNESS"
    ), empty_focus.model_dump(mode="json"))

    before_restart = {
        "profile_version": profile.profile_version,
        "states": [item.model_dump(mode="json") for item in mastery_repo.list_states(profile.learner_id, "journey-kb")],
        "events": [item.model_dump(mode="json") for item in mastery_repo.list_events(profile.learner_id, "journey-kb")],
        "priorities": [item.model_dump(mode="json") for item in mastery.weakness_priorities(profile)],
    }
    engine.dispose()
    restarted_engine, restarted_factory = _build_repositories(db_path)
    restarted_learner_repo = SQLLearnerRepository(restarted_factory)
    restarted_catalog = KnowledgeCatalogRepository(restarted_factory)
    restarted_mastery_repo = SQLMasteryRepository(restarted_factory)
    restarted_mastery = MasteryService(restarted_mastery_repo, KnowledgeService(catalog=restarted_catalog))
    restarted_profile = restarted_learner_repo.get(profile.learner_id)
    after_restart = {
        "profile_version": restarted_profile.profile_version,
        "states": [item.model_dump(mode="json") for item in restarted_mastery_repo.list_states(profile.learner_id, "journey-kb")],
        "events": [item.model_dump(mode="json") for item in restarted_mastery_repo.list_events(profile.learner_id, "journey-kb")],
        "priorities": [item.model_dump(mode="json") for item in restarted_mastery.weakness_priorities(restarted_profile)],
    }
    _assert(report, "sqlite_restart_consistency", before_restart == after_restart,
            {"before": before_restart, "after": after_restart})
    restarted_engine.dispose()
    report["steps"].append({"step": "restart", "consistent": True, **after_restart})

    report["learner_id"] = profile.learner_id
    report["profile_version"] = profile.profile_version
    report["first_focus_snapshot_hash"] = first_job.focus_snapshot.mastery_snapshot_hash
    report["next_focus_snapshot_hash"] = next_job.focus_snapshot.mastery_snapshot_hash
    report["report_as_of_profile_version"] = report_payload["as_of_profile_version"]
    report["restart_consistency"] = True
    report["status"] = "LOCAL_READY"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="learner-mastery-") as temporary:
        report = run_journey(Path(temporary))
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
