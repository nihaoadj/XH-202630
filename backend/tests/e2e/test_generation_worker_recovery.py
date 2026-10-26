"""Real isolated subprocesses exercise accepted intents, lost claims and worker lifecycle."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.shared.models import AgentRunORM, GenerationJobORM


CHILD = r'''
import json, os, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.generation import generation as api
from app.core.execution import current_execution_fence
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, LearnerProfileORM
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.models.learning_documents.schemas import LearnerProfile, GenerateRequest
from app.models.shared.persistence import CreateRunCommand, RunStatus, canonical_hash
from app.services.generation.jobs import GenerationJobService
from app.services.generation.worker import GenerationWorker
engine = configure_sqlite_foreign_keys(create_engine('sqlite:///' + sys.argv[1]))
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, autoflush=False)
repo, audit = SQLGenerationJobRepository(factory), SQLAuditRepository(factory)
mode, marker, accepted = sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
class SyntheticGeneration:
    audit_repo = audit
    def generate_with_run_id(self, learner, req, run_id, batch_id):
        now = datetime.now(timezone.utc)
        audit.create_run(CreateRunCommand(run_id=run_id, learner_id=learner.learner_id, request_snapshot={},
            request_hash=canonical_hash({}), owner_instance_id=current_execution_fence().owner, lease_expires_at=now + timedelta(seconds=60)))
        audit.start_run(run_id, occurred_at=now, lease_expires_at=now + timedelta(seconds=60))
        with marker.open('a') as stream: stream.write('synthetic-execution\n')
        if mode == 'start-crash': os._exit(17)
        audit.mark_finalizing(run_id, workflow_status='completed', current_node='fixture', generation_attempt=1,
            revision_count=0, retrieval_status='empty', final_decision='synthetic', occurred_at=now)
        audit.complete_run(run_id, status=RunStatus.COMPLETED, workflow_status='completed', execution_status='success',
            final_decision='synthetic', occurred_at=now)
        return SimpleNamespace(resources=[], workflow_status='completed')
service = GenerationJobService(repo, SyntheticGeneration(), dispatch_mode='worker')
if mode == 'create':
    with factory() as db:
        db.add(LearnerProfileORM(learner_id='learner', learner_type='fixture', education='本科', major='软件', learning_goal='fixture'))
        db.commit()
    learner = LearnerProfile(learner_id='learner', learner_type='fixture', education='本科', major='软件', learning_goal='fixture')
    app = FastAPI()
    app.container = SimpleNamespace(profile_service=lambda: SimpleNamespace(get=lambda _: learner), generation_job_service=lambda: service)
    app.include_router(api.router, prefix='/api/generate')
    api.build_health_report = lambda _: SimpleNamespace(status='ready', error_codes=[])
    with TestClient(app) as client:
        response = client.post('/api/generate/jobs', json=GenerateRequest(learner_id='learner', topic='fixture', resource_types=['讲义'], profile_focus_mode='off').model_dump(mode='json'))
        assert response.status_code == 200
        accepted.write_text(json.dumps(response.json()))
elif mode == 'claim-crash':
    assert repo.claim_next('lost-process', 60)
    os._exit(13)
else:
    feedback = SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0)
    worker = GenerationWorker(repo, feedback, lambda: service, lease_seconds=60, poll_seconds=.01)
    print(json.dumps(worker.run_once()))
'''


def child(tmp_path, mode):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run([sys.executable, "-c", CHILD, str(tmp_path / "jobs.db"), mode,
                             str(tmp_path / "calls.txt"), str(tmp_path / "accepted.json")],
                            capture_output=True, text=True, encoding="utf-8", timeout=45, **options)
    if mode not in {"claim-crash", "start-crash"}:
        assert result.returncode == 0, result.stderr
    return result


def records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    return engine, sessionmaker(bind=engine, autoflush=False)


def expire(factory):
    with factory() as db:
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.query(GenerationJobORM).update({"lease_expires_at": past})
        db.query(AgentRunORM).update({"lease_expires_at": past})
        db.commit()


def test_accepted_web_process_exits_before_consumer(tmp_path):
    child(tmp_path, "create")
    run_id = json.loads((tmp_path / "accepted.json").read_text())["run_id"]
    engine, factory = records(tmp_path)
    repo = SQLGenerationJobRepository(factory)
    assert repo.get(run_id).job_status == "queued"
    assert not (tmp_path / "calls.txt").exists()
    result = child(tmp_path, "work")
    assert json.loads(result.stdout)["claimed"] == 1
    assert repo.get(run_id).job_status == "completed"
    assert (tmp_path / "calls.txt").read_text().count("synthetic-execution") == 1
    engine.dispose()


def test_crash_after_claim_recovers_same_unstarted_intent(tmp_path):
    child(tmp_path, "create")
    assert child(tmp_path, "claim-crash").returncode == 13
    engine, factory = records(tmp_path)
    repo = SQLGenerationJobRepository(factory)
    expire(factory)
    assert repo.reconcile()["requeued"] == 1
    with factory() as db:
        db.query(GenerationJobORM).update({"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit()
    assert json.loads(child(tmp_path, "work").stdout)["processed"] == 1
    assert (tmp_path / "calls.txt").read_text().count("synthetic-execution") == 1
    engine.dispose()


def test_started_process_crash_becomes_interrupted_without_reexecution(tmp_path):
    child(tmp_path, "create")
    assert child(tmp_path, "start-crash").returncode == 17
    engine, factory = records(tmp_path)
    expire(factory)
    assert json.loads(child(tmp_path, "work").stdout)["claimed"] == 0
    with factory() as db:
        assert db.query(GenerationJobORM).one().status == "failed"
        assert db.query(AgentRunORM).one().status == "interrupted"
    assert (tmp_path / "calls.txt").read_text().count("synthetic-execution") == 1
    engine.dispose()


def test_sqlite_background_config_is_rejected():
    with pytest.raises(ValueError, match="CFG_SQLITE_REQUIRES_GENERATION_WORKER"):
        Settings(_env_file=None, db_type="sqlite", generation_dispatch_mode="background")
    assert Settings(_env_file=None, db_type="memory", generation_dispatch_mode="background").db_type == "memory"


def test_cli_health_single_instance_and_graceful_shutdown(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    stop = tmp_path / "stop"
    env = {**os.environ, "DB_TYPE": "sqlite", "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}",
           "APP_MODE": "development", "LLM_API_KEY": "", "RUN_LIVE_LLM": "0", "COURSEWARE_LIVE_EVAL": "0",
           "GENERATION_WORKER_POLL_SECONDS": "0.1"}
    script = Path(__file__).resolve().parents[2] / "scripts/generation_worker.py"
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with (tmp_path / "worker.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(script), "--health-port", str(port), "--shutdown-file", str(stop)],
                                   env=env, stdout=log, stderr=subprocess.STDOUT, **options)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=1) as response:
                        assert json.load(response)["live"]
                    break
                except (OSError, urllib.error.URLError):
                    assert process.poll() is None, (tmp_path / "worker.log").read_text()
                    assert time.monotonic() < deadline
                    time.sleep(.05)
            duplicate = subprocess.run([sys.executable, str(script), "--once"], env=env, capture_output=True, timeout=30, **options)
            assert duplicate.returncode == 2
            assert b"GENERATION_WORKER_ALREADY_RUNNING" in duplicate.stderr
            stop.touch()
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)
