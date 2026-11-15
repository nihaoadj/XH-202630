"""Isolated child process for T31 lifecycle tests; actual SQL/service/graph/Worker."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.extraction import SQLClaimExtractionRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, KnowledgeBaseORM, LearnerProfileORM
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.services.generation.jobs import GenerationJobService
from app.services.generation.worker import GenerationWorker
from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder
from tests.fakes.claim_extraction import graph_service, NeutralScriptedGateway, neutral_settings, extract_every_unit, judge_all


def main():
    root, mode, entry = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    root.mkdir(parents=True, exist_ok=True)
    patch = pytest.MonkeyPatch()
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{root / 'run.db'}", connect_args={"check_same_thread": False}))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    audit, resources, claims = SQLAuditRepository(factory), SQLResourceRepository(factory), SQLClaimRepository(factory)
    with factory() as db:
        if not db.get(KnowledgeBaseORM, "kb-fixture"):
            db.add(KnowledgeBaseORM(knowledge_base_id="kb-fixture", name="synthetic"))
            db.add(LearnerProfileORM(learner_id="learner", learner_type="test", education="本科", major="软件", learning_goal="test"))
            db.commit()
    learner = LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件",
                             learning_goal="test", knowledge_base_id="kb-fixture")
    request = GenerateRequest(learner_id="learner", topic="fixture", resource_types=["讲义"], include_claim_check=True,
                              profile_focus_mode="off", max_iterations=0, claim_max_iterations=0)

    def route(call):
        with (root / "calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(run_id=call["context"].run_id, node=call["context"].node_name)) + "\n")
        return extract_every_unit(call) if call["context"].node_name == "claim_extractor" else judge_all(call)
    gateway = NeutralScriptedGateway([route]*64)
    service, _, _ = graph_service(patch, audit, resources, claims, gateway=gateway,
        settings=neutral_settings(resource_aware_retrieval_enabled=False, claim_extraction_target_tokens=8), content="A fact.\n\nB fact.",
        output_path=root / "artifact.md")
    jobs = SQLGenerationJobRepository(factory)
    dispatch = GenerationJobService(jobs, service, dispatch_mode="worker")
    original_cas = SQLClaimExtractionRepository.compare_and_swap

    def cas(repo, old, new, **kwargs):
        settling = any(t.status == "in_flight" and new.tickets[k].status != "in_flight" for k, t in old.state.tickets.items())
        finalizing = any(r.status == "completed" and old.state.results[k].status == "running" for k, r in new.results.items())
        if (mode == "returned_before_settle" and settling) or (mode == "batches_before_final" and finalizing):
            os._exit(29)
        result = original_cas(repo, old, new, **kwargs)
        if mode == "reserved_before_request" and any(k not in old.state.tickets for k in new.tickets):
            os._exit(29)
        if mode == "partial_batch" and settling and any(r.status == "running" and 0 < len(r.outputs) < len(r.batches) for r in new.results.values()):
            os._exit(29)
        if mode == "final_before_step" and finalizing:
            os._exit(29)
        return result
    patch.setattr(SQLClaimExtractionRepository, "compare_and_swap", cas)
    original_step = SQLAuditRepository.complete_step
    def complete_step(repo, command):
        result = original_step(repo, command)
        if mode == "step_before_artifact" and command.trace.get("agent_name") == "claim_extractor":
            os._exit(29)
        return result
    patch.setattr(SQLAuditRepository, "complete_step", complete_step)
    original_record = WorkflowArtifactRecorder.record
    def record(recorder, state, trace):
        result = original_record(recorder, state, trace)
        if mode == "artifact_before_checkpoint" and trace.get("agent_name") == "claim_extractor":
            os._exit(29)
        return result
    patch.setattr(WorkflowArtifactRecorder, "record", record)
    original_checkpoint = SQLAuditRepository.save_checkpoint
    def save_checkpoint(repo, **kwargs):
        result = original_checkpoint(repo, **kwargs)
        if mode == "complete_checkpoint" and kwargs["node_name"] in {"claim_extractor", "claim_extract"}:
            os._exit(29)
        return result
    patch.setattr(SQLAuditRepository, "save_checkpoint", save_checkpoint)

    if entry == "worker":
        if mode == "retry":
            job = dispatch.create_job(learner, request, run_id="process-run", retry_failed=True)
            (root / "retry-identity.json").write_text(json.dumps(dict(run_id=job.run_id)), encoding="utf-8")
        elif mode != "reconcile":
            dispatch.create_job(learner, request, run_id="process-run")
        worker = GenerationWorker(jobs, SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
            lambda: dispatch, lease_seconds=1260, poll_seconds=.05)
        result = worker.run_once()
    else:
        try:
            response = service.generate_with_run_id(learner, request, run_id="process-run")
            result = dict(workflow_status=response.workflow_status)
        except Exception as exc:
            if mode != "reenter":
                raise
            result = dict(error=type(exc).__name__)
    (root / f"{mode}.json").write_text(json.dumps(result), encoding="utf-8")
    patch.undo()
    engine.dispose()


if __name__ == "__main__":
    main()
