from datetime import datetime, timezone
from types import SimpleNamespace

from dependency_injector import providers
from fastapi.testclient import TestClient

from app import config as config_module
from app import main as main_module
from app.db import database as database_module
from app.db.models import KnowledgeBaseORM, RagSkillNodeORM
from app.models.schemas import LearnerProfile, LearningResource
from app.services.generation_job_service import GenerationJobService


class _NoopGenerationService:
    pass


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

        submitted = first_client.post("/api/feedback/attempts", json=payload)
        assert submitted.status_code == 200
        first = submitted.json()
        assert first["profile_version"] == 2
        assert first["followup_generation_status"] == "queued"
        child_run_id = first["followup_run_id"]
        assert child_run_id

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

        job = restarted_client.get(f"/api/generate/jobs/{child_run_id}")
        assert job.status_code == 200
        assert job.json()["job_status"] == "failed"
        assert job.json()["error_message"] == "GENERATION_JOB_INTERRUPTED"

        persisted = container.feedback_loop_repository().get_by_idempotency_key(
            "restart-learner",
            "app-restart-idempotency",
        )
        assert persisted.followup_generation_status.value == "failed"
        assert persisted.followup_error_code == "GENERATION_JOB_INTERRUPTED"

        replayed = restarted_client.post("/api/feedback/attempts", json=payload)
        assert replayed.status_code == 200
        replay = replayed.json()
        assert replay["idempotent_replay"] is True
        assert replay["followup_run_id"] == child_run_id
        assert replay["followup_generation_status"] == "queued"

        jobs = restarted_client.get("/api/generate/jobs?learner_id=restart-learner")
        assert jobs.status_code == 200
        assert jobs.json()["total"] == 1

    _clear_runtime_caches()
