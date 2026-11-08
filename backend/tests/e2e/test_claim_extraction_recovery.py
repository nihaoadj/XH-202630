"""Product interruptions fail the original run; no simulated checkpoint resume."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.extraction import SQLClaimExtractionRepository
from app.db.shared.models import AgentRunORM, GenerationJobORM, GeneratedResourceORM, ResourceClaimORM, WorkflowEventORM, AgentStepORM, WorkflowCheckpointORM

PHASES = ["reserved_before_request", "returned_before_settle", "partial_batch", "batches_before_final",
          "final_before_step", "step_before_artifact", "artifact_before_checkpoint", "complete_checkpoint"]


def child(root, mode, entry="sync"):
    script = Path(__file__).resolve().parents[1] / "fakes/claim_extraction_process.py"
    result = subprocess.run([sys.executable, str(script), str(root), mode, entry], capture_output=True,
        text=True, encoding="utf-8", timeout=50,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert result.returncode == (29 if mode in PHASES else 0), result.stderr
    return result


def calls(root):
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("entry", ["sync", "worker"])
@pytest.mark.parametrize("phase", PHASES)
def test_sqlite_process_crash_retains_budget_and_never_reexecutes_original(tmp_path, phase, entry):
    child(tmp_path, phase, entry)
    engine = create_engine(f"sqlite:///{tmp_path / 'run.db'}")
    factory = sessionmaker(bind=engine)
    repo, audit = SQLClaimExtractionRepository(factory), SQLAuditRepository(factory)
    before = repo.get("process-run")
    before_calls = calls(tmp_path)
    assert before.state.calls >= 1 and not before.state.session_closed
    if phase in {"reserved_before_request", "returned_before_settle"}:
        assert any(t.status == "in_flight" and t.charged_tokens is None for t in before.state.tickets.values())
        assert before.state.tokens == sum(t.tokens for t in before.state.tickets.values())
    if phase == "reserved_before_request":
        assert before_calls == []
    else:
        assert before_calls and all(c["node"] == "claim_extractor" for c in before_calls)
    result = next(iter(before.state.results.values()))
    if phase in {"final_before_step", "step_before_artifact", "artifact_before_checkpoint", "complete_checkpoint"}:
        assert result.status == "completed" and result.final_result_hash
    else:
        assert result.status == "running"
    with factory() as db:
        assert db.query(ResourceClaimORM).filter_by(run_id="process-run").count() == 0
        events_before = {e.event_id: (e.event_type, e.payload_hash) for e in db.query(WorkflowEventORM).filter_by(run_id="process-run")}
        resources_before = {r.resource_id for r in db.query(GeneratedResourceORM).filter_by(run_id="process-run")}
        step = db.query(AgentStepORM).filter_by(run_id="process-run", agent_name="claim_extractor").one()
        checkpoints = db.query(WorkflowCheckpointORM).filter_by(run_id="process-run", step_id=step.step_id).all()
        if phase in {"step_before_artifact", "artifact_before_checkpoint", "complete_checkpoint"}:
            assert step.status == "success"
        else:
            assert step.status == "running"
        assert len(checkpoints) == (1 if phase == "complete_checkpoint" else 0)
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.query(AgentRunORM).filter_by(run_id="process-run").update(dict(lease_expires_at=past))
        db.query(GenerationJobORM).filter_by(run_id="process-run").update(dict(lease_expires_at=past))
        db.commit()
    if entry == "worker":
        child(tmp_path, "reconcile", entry)
        assert json.loads((tmp_path / "reconcile.json").read_text())["claimed"] == 0
    else:
        now = datetime.now(timezone.utc)
        assert audit.mark_stale_interrupted(before=now, occurred_at=now) == 1
        child(tmp_path, "reenter", entry)
        assert "error" in json.loads((tmp_path / "reenter.json").read_text())
    assert audit.get_run("process-run").status.value == "interrupted"
    assert repo.get("process-run") == before  # All reserved/unknown charges intact.
    assert calls(tmp_path) == before_calls
    with factory() as db:
        assert {r.resource_id for r in db.query(GeneratedResourceORM).filter_by(run_id="process-run")} == resources_before
        events_after = {e.event_id: (e.event_type, e.payload_hash) for e in db.query(WorkflowEventORM).filter_by(run_id="process-run")}
        assert all(events_after[k] == v for k,v in events_before.items())
        added = [v[0] for k,v in events_after.items() if k not in events_before]
        assert added == ["run_interrupted"]
        assert db.query(WorkflowEventORM).filter_by(run_id="process-run").count() == len(events_after)
        if entry == "worker":
            assert db.get(GenerationJobORM, "process-run").status == "failed"
    engine.dispose()


def test_actual_worker_retry_executes_new_run_with_independent_frozen_identity(tmp_path):
    child(tmp_path, "returned_before_settle", "worker")
    engine = create_engine(f"sqlite:///{tmp_path / 'run.db'}")
    factory = sessionmaker(bind=engine)
    old = SQLClaimExtractionRepository(factory).get("process-run")
    with factory() as db:
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.query(AgentRunORM).update(dict(lease_expires_at=past))
        db.query(GenerationJobORM).update(dict(lease_expires_at=past))
        db.commit()
    child(tmp_path, "reconcile", "worker")
    child(tmp_path, "retry", "worker")
    new_id = json.loads((tmp_path / "retry-identity.json").read_text())["run_id"]
    assert new_id != "process-run"
    audit = SQLAuditRepository(factory)
    assert audit.get_run("process-run").status.value == "interrupted"
    assert audit.get_run(new_id).status.value == "completed"
    repo = SQLClaimExtractionRepository(factory)
    assert repo.get("process-run") == old
    new = repo.get(new_id)
    assert new.state.session_closed and new.state.calls == 2
    assert new.state.execution_session_id != old.state.execution_session_id
    assert all(c.run_id == new_id for r in new.state.results.values() for c in r.final_claims)
    assert [c["node"] for c in calls(tmp_path) if c["run_id"] == new_id] == ["claim_extractor"]*2 + ["claim_judge"]
    with factory() as db:
        assert db.query(ResourceClaimORM).filter_by(run_id="process-run").count() == 0
        assert db.query(ResourceClaimORM).filter_by(run_id=new_id).count() == 2
    engine.dispose()


def test_success_sql_http_timeline_events_sse_and_logs_exclude_private_state(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.api.runs import run_queries
    from app.db.claim.sql_repository import SQLClaimRepository
    from app.db.learning_documents.sql_repository import SQLResourceRepository
    from app.services.runs.queries import RunQueryService
    from app.services.runs.events import to_public_event, event_frame, RunEventStreamService
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.config import Settings
    completed = child(tmp_path, "normal")
    engine = create_engine(f"sqlite:///{tmp_path / 'run.db'}")
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    query = RunQueryService(audit, SQLResourceRepository(factory), SQLClaimRepository(factory))
    app = FastAPI()
    app.container = SimpleNamespace(run_query_service=lambda: query,
        run_event_stream_service=lambda: RunEventStreamService(audit,SQLGenerationJobRepository(factory),Settings(_env_file=None)))
    app.include_router(run_queries.router, prefix="/api/runs")
    private = {"claim_extraction_policy", "claim_extraction_policy_hash", "claim_extraction_mode",
        "claim_extraction_refs", "final_result_hash", "tickets", "active_owner", "ledger_epoch", "execution_session_id"}
    def scan(value):
        if isinstance(value, dict):
            assert not private.intersection(value)
            for item in value.values(): scan(item)
        elif isinstance(value, list):
            for item in value: scan(item)
    with TestClient(app) as client:
        for suffix in ("", "/timeline", "/claims", "/evidence"):
            response = client.get("/api/runs/process-run"+suffix)
            assert response.status_code == 200
            scan(response.json())
            assert "fixture-claim-v1" not in response.text
        stream = client.get("/api/runs/process-run/events")
        assert stream.status_code==200 and "text/event-stream" in stream.headers["content-type"]
        assert "fixture-claim-v1" not in stream.text
        for line in stream.text.splitlines():
            if line.startswith("data: "):
                scan(json.loads(line[6:]))
    for event in audit.list_events("process-run", limit=1000):
        scan(event.model_dump(mode="json"))
        public = to_public_event(event)
        scan(public.model_dump(mode="json"))
        assert "fixture-claim-v1" not in event_frame(public)
    assert all(key not in completed.stdout + completed.stderr for key in private)
    assert SQLClaimExtractionRepository(factory).get("process-run").state.session_closed
    engine.dispose()
