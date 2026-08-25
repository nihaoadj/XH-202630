from datetime import datetime, timezone
from types import SimpleNamespace

from dependency_injector import providers
from fastapi import Request
from fastapi.testclient import TestClient

from app import config as config_module
from app import main as main_module
from app.api.dependencies import get_current_user
from app.db.shared import database as database_module
from app.db.shared.models import KnowledgeBaseORM, RagSkillNodeORM
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.feedback.feedback_loop import LearningAttemptSubmit
from app.models.users.users import UserProfile
from app.services.generation.jobs import GenerationJobService


class _NoopGenerationService:
    pass


def _restart_user() -> UserProfile:
    return UserProfile(
        user_id="restart-user",
        username="restart-user",
        display_name="Restart User",
        identity="测试",
        education="本科",
        major="软件工程",
    )


def _authenticated_restart_user(request: Request) -> UserProfile:
    user = _restart_user()
    request.state.current_user = user
    return user


def _ready_report(*_args, **_kwargs):
    return SimpleNamespace(
        status="ready",
        app_mode="development",
        storage=SimpleNamespace(mode="sqlite"),
        error_codes=[],
    )


def _clear_runtime_caches():
    database_module.get_session_factory.cache_clear()
    engine = database_module.get_engine.cache_info()
    if engine.currsize:
        cached_engine = database_module.get_engine()
        if hasattr(cached_engine, "dispose"):
            cached_engine.dispose()
    database_module.get_engine.cache_clear()
    config_module.get_settings.cache_clear()


def _override_generation(container):
    container.generation_service.override(providers.Object(_NoopGenerationService()))
    container.generation_job_service.override(providers.Singleton(
        GenerationJobService,
        job_repo=container.generation_job_repository,
        generation_service=container.generation_service,
    ))


def test_feedback_survives_full_fastapi_lifespan_restart(monkeypatch, tmp_path):
    db_path = tmp_path / "feedback-app-restart.db"
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setattr(main_module, "build_health_report", _ready_report)
    monkeypatch.setattr(GenerationJobService, "run_job", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(
        main_module.app.dependency_overrides,
        get_current_user,
        _authenticated_restart_user,
    )
    _clear_runtime_caches()
    payload = {
        "learner_id": "restart-learner",
        "source_resource_id": "restart-resource",
        "source_resource_version": 1,
        "idempotency_key": "app-restart-idempotency",
        "expected_profile_version": 1,
        "submitted_at": datetime(2026, 8, 15, tzinfo=timezone.utc).isoformat(),
        "knowledge_point_results": [{
            "knowledge_point_id": "skill-restart",
            "question_ids": ["question-1"],
            "correct_count": 4,
            "total_count": 10,
        }],
    }

    with TestClient(main_module.app) as first_client:
        container = main_module.app.container
        _override_generation(container)
        container.user_repository().save(_restart_user())
        with container.db_session_factory()() as db:
            db.add(KnowledgeBaseORM(
                knowledge_base_id="restart-kb",
                name="Restart KB",
                version="1.0",
            ))
            db.add(RagSkillNodeORM(
                node_id="skill-restart",
                knowledge_base_id="restart-kb",
                name="Restart skill",
                level="beginner",
            ))
            db.commit()
        container.learner_repository().save(LearnerProfile(
            learner_id="restart-learner",
            user_id="restart-user",
            learner_type="测试",
            education="本科",
            major="软件工程",
            knowledge_base_id="restart-kb",
            learning_goal="验证重启恢复",
        ))
        container.resource_repository().save(LearningResource(
            resource_id="restart-resource",
            learner_id="restart-learner",
            topic="检索",
            resource_type="测试题",
            difficulty="初级",
            content_text="restart exercise",
            knowledge_points=["skill-restart"],
            source_refs=[],
            publication_status="published",
        ), "restart-learner", "检索")

        first_result = container.feedback_service().process_learning_attempt(
            container.learner_repository().get("restart-learner"),
            container.resource_repository().get("restart-resource"),
            LearningAttemptSubmit.model_validate(payload),
            verified_evidence=True,
        )
        first = first_result.model_dump(mode="json")
        assert first["profile_version"] == 2
        assert first["followup_generation_status"] == "not_requested"
        assert first["followup_run_id"] is None

    # A new lifespan creates a fresh dependency container. Its startup recovery
    # must reconcile the BackgroundTask that could not survive process shutdown.
    with TestClient(main_module.app) as restarted_client:
        container = main_module.app.container
        _override_generation(container)

        profile = restarted_client.get("/api/profiles/restart-learner")
        assert profile.status_code == 200
        assert profile.json()["profile_version"] == 2
        assert profile.json()["knowledge_states"]["skill-restart"]["score"] == 0.4

        attempts = restarted_client.get("/api/feedback/attempts/restart-learner")
        assert attempts.status_code == 200
        assert len(attempts.json()) == 1
        assert attempts.json()[0]["attempt_id"] == first["attempt"]["attempt_id"]

        path = restarted_client.get("/api/feedback/path/restart-learner")
        assert path.status_code == 200
        assert path.json()["learner_id"] == "restart-learner"

        report = restarted_client.get("/api/report/restart-learner")
        assert report.status_code == 200
        assert first["attempt"]["attempt_id"] in report.text

        history = restarted_client.get("/api/learning-history/restart-learner/timeline")
        assert history.status_code == 200
        assert history.json()["learner_id"] == "restart-learner"

        persisted = container.feedback_loop_repository().get_by_idempotency_key(
            "restart-learner",
            "app-restart-idempotency",
        )
        assert persisted.followup_generation_status.value == "not_requested"
        assert persisted.followup_error_code is None

        selected = restarted_client.post(
            "/api/feedback/followups/select",
            json={
                "learner_id": "restart-learner",
                "attempt_id": first["attempt"]["attempt_id"],
                "option_id": "remediate-core",
            },
        )
        assert selected.status_code == 200
        selected_body = selected.json()
        assert selected_body["followup_generation_status"] == "queued"
        child_run_id = selected_body["followup_run_id"]
        assert child_run_id

        replay = container.feedback_service().process_learning_attempt(
            container.learner_repository().get("restart-learner"),
            container.resource_repository().get("restart-resource"),
            LearningAttemptSubmit.model_validate(payload),
            verified_evidence=True,
        ).model_dump(mode="json")
        assert replay["idempotent_replay"] is True
        assert replay["followup_run_id"] == child_run_id
        assert replay["followup_generation_status"] == "queued"

        jobs = restarted_client.get("/api/generate/jobs?learner_id=restart-learner")
        assert jobs.status_code == 200
        assert jobs.json()["total"] == 1

    _clear_runtime_caches()


def test_lifespan_reload_keeps_a_recent_running_generation_job(monkeypatch, tmp_path):
    """A development reload must not fail a job whose workflow lease is valid."""
    db_path = tmp_path / "generation-reload.db"
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setattr(main_module, "build_health_report", _ready_report)
    _clear_runtime_caches()

    run_id = "recent-running-generation"
    with TestClient(main_module.app):
        container = main_module.app.container
        container.user_repository().save(_restart_user())
        with container.db_session_factory()() as db:
            db.add(KnowledgeBaseORM(
                knowledge_base_id="reload-kb",
                name="Reload KB",
                version="1.0",
            ))
            db.commit()
        container.learner_repository().save(LearnerProfile(
            learner_id="reload-learner",
            user_id="restart-user",
            learner_type="测试",
            education="本科",
            major="软件工程",
            knowledge_base_id="reload-kb",
            learning_goal="验证热重载生成任务",
        ))
        jobs = container.generation_job_repository()
        jobs.create(
            run_id=run_id,
            batch_id=run_id,
            learner_id="reload-learner",
            topic="reload-safe generation",
            knowledge_base_id="reload-kb",
            request_payload={},
        )
        assert jobs.mark_running(run_id).job_status == "running"

    with TestClient(main_module.app):
        job = main_module.app.container.generation_job_repository().get(run_id)
        assert job is not None
        assert job.job_status == "running"
        assert job.error_message is None

    _clear_runtime_caches()
