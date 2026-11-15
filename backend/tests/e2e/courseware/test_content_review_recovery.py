from copy import deepcopy
import pytest
from app.models.courseware.contracts import CoursewareJobCreateRequest
from tests.fakes.courseware_content_review import fixture_environment, make_workflow


def _content_process(database, directory, group, failure_window, result_path):
    """Each invocation owns a new SQL session factory and workflow process."""
    import json
    import os
    from pathlib import Path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.courseware.repository import SQLCoursewareRepository
    engine = create_engine(f"sqlite:///{database}")
    repo = SQLCoursewareRepository(sessionmaker(bind=engine))
    with fixture_environment(directory):
        wf, source = make_workflow(directory, group, repo=repo)
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id], idempotency_key="process-content"))
        original = wf._checkpoint_completed
        if failure_window:
            def checkpoint(run_id, stage, **kwargs):
                target = "scenes" if failure_window == "scenes" else "design"
                if stage == target:
                    if failure_window != "spec_before_checkpoint": original(run_id, stage, **kwargs)
                    os._exit(86)
                return original(run_id, stage, **kwargs)
            wf._checkpoint_completed = checkpoint
        result = wf.run(job.run_id)
        Path(result_path).write_text(json.dumps({"status": result.status, "calls": [c["output_schema"].__name__ for c in wf.llm_gateway.calls]}), encoding="utf-8")
    engine.dispose()


@pytest.mark.parametrize("group,window", [("review", "design"), ("practice_code", "scenes"), ("practice_noncode", "spec_before_checkpoint")])
def test_file_sqlite_approval_survives_real_process_exit_and_new_process_recovery(tmp_path, group, window):
    import json
    import multiprocessing
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.courseware.models import Base
    from app.db.shared.models import LearnerProfileORM
    from app.db.courseware.repository import SQLCoursewareRepository
    from app.agents.resource_workflows.interactive_courseware.content_review.persistence import mutate_spec
    database = tmp_path/"content-process.db"; directory = tmp_path/"artifacts"; result = tmp_path/"process.json"
    engine = create_engine(f"sqlite:///{database}"); Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(learner_id="content-learner", learner_type="test", education="test", major="test", learning_goal="test", skill_level="test")); db.commit()
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_content_process, args=(str(database), str(directory), group, window, str(result)))
    child.start(); child.join(45)
    if child.is_alive(): child.terminate(); child.join(); pytest.fail("content crash process timed out")
    assert child.exitcode == 86
    repo = SQLCoursewareRepository(factory); job = repo.list_jobs("content-learner")[0]
    prior = repo.get_spec_by_run(job["run_id"])["spec_json"]["content_review"]["record"]
    assert prior["status"] == "approved"
    # Advance only the abandoned private lease in this isolated test database.
    def expire(raw): raw["content_review"]["lease_until"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    mutate_spec(repo, job["run_id"], expire)
    resumed = context.Process(target=_content_process, args=(str(database), str(directory), group, None, str(result)))
    resumed.start(); resumed.join(45)
    if resumed.is_alive(): resumed.terminate(); resumed.join(); pytest.fail("content resume process timed out")
    assert resumed.exitcode == 0
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report == {"status": "published", "calls": ["CoursewareReviewDecisionV2Draft"]}
    final = repo.get_spec_by_run(job["run_id"])["spec_json"]["content_review"]["record"]
    assert final["identity"] == prior["identity"] and final["approved_values"] == prior["approved_values"]
    engine.dispose()


@pytest.mark.parametrize("group", ["review", "practice_code", "practice_noncode"])
@pytest.mark.parametrize("window", ["spec_before_checkpoint", "design", "scenes"])
def test_checkpoint_failure_resumes_approved_values_without_repeating_planner_or_field_calls(tmp_path, monkeypatch, group, window):
    with fixture_environment(tmp_path):
        wf, source = make_workflow(tmp_path, group)
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
        original = wf._checkpoint_completed; tripped = False
        def checkpoint(run_id, stage, **kwargs):
            nonlocal tripped
            target = "design" if window in {"spec_before_checkpoint", "design"} else "scenes"
            if stage == target and not tripped:
                tripped = True
                if window != "spec_before_checkpoint": original(run_id, stage, **kwargs)
                raise RuntimeError("synthetic process boundary")
            return original(run_id, stage, **kwargs)
        monkeypatch.setattr(wf, "_checkpoint_completed", checkpoint)
        with pytest.raises(RuntimeError): wf.run(job.run_id)
        state = wf.content_review.state(job.run_id)
        approved = deepcopy(state.record.approved_values)
        before = len(wf.llm_gateway.calls)
        monkeypatch.setattr(wf, "_checkpoint_completed", original)
        result = wf.run(job.run_id)
        assert result.status == "published" and result.error_code is None
        assert wf.content_review.state(job.run_id).record.approved_values == approved
        later = wf.llm_gateway.calls[before:]
        assert [c["output_schema"].__name__ for c in later] == ["CoursewareReviewDecisionV2Draft"]


def test_ledger_settlement_does_not_invalidate_design_checkpoint(tmp_path, monkeypatch):
    with fixture_environment(tmp_path):
        wf, source = make_workflow(tmp_path)
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
        original = wf._checkpoint_completed
        def stop(run_id, stage, **kwargs):
            original(run_id, stage, **kwargs)
            if stage == "design": raise RuntimeError("boundary")
        monkeypatch.setattr(wf, "_checkpoint_completed", stop)
        with pytest.raises(RuntimeError): wf.run(job.run_id)
        checkpoint = wf.repo.latest_checkpoint(job.run_id)
        wf.content_review.claim(job.run_id)
        ticket = wf.budget.before_call(job.run_id, "revision", requested_output_tokens=256, estimated_input_tokens=128)
        assert ticket.allowed
        wf.budget.reconcile(job.run_id, ticket.call_id, actual_input=2, actual_output=3)
        assert wf._checkpoint_valid(job.run_id, checkpoint)
        wf.content_review.release(job.run_id)
