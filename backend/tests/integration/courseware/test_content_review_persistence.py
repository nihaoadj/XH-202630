from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.courseware.models import Base
from app.db.shared.models import LearnerProfileORM
from app.db.courseware.repository import MemoryCoursewareRepository, SQLCoursewareRepository
from app.models.courseware.content_review import ContentReviewStateV1, ContentReviewConflict, json_hash, binding_for_spec
from app.agents.resource_workflows.interactive_courseware.content_review.persistence import freeze_policy, read_state
from tests.fakes.courseware_content_review import fixture_settings, ContentReviewGateway


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    engine = None
    if request.param == "memory":
        repo = MemoryCoursewareRepository()
    else:
        engine = create_engine(f"sqlite:///{tmp_path/'content.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine); factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(LearnerProfileORM(learner_id="learner", learner_type="test", education="test", major="test", learning_goal="test", skill_level="test")); db.commit()
        repo = SQLCoursewareRepository(factory)
    yield repo
    if engine: engine.dispose()


def create(repo, *, enabled=True, run_id="run", request_hash="request"):
    deadline = datetime.now(timezone.utc)+timedelta(minutes=10)
    row = dict(run_id=run_id, learner_id="learner", request_hash=request_hash, source_resource_ids=[], source_snapshots=[], status="queued", deadline_at=deadline)
    task = dict(outbox_id=f"cwo_{run_id}", run_id=run_id, event_type="courseware.run", task_kind="courseware.run", idempotency_key=f"courseware.run:{run_id}", payload={"run_id": run_id})
    policy = freeze_policy(fixture_settings(), ContentReviewGateway(), deadline)
    raw = {"content_review": ContentReviewStateV1(policy=policy).model_dump(mode="json")}
    spec = dict(run_id=run_id, spec_id=f"cws_{run_id}", schema_version="1.0", prompt_version="content-v1", runtime_version="1.0", status="pending", spec_json=raw, content_hash=json_hash(raw))
    return repo.create_job_with_task_once(row, task, initial_spec=spec if enabled else None)


def test_atomic_creation_binding_lifetime_and_deepcopy(repository):
    create(repository)
    state, spec = read_state(repository, "run")
    binding = repository.get_run_content_review_binding("run")
    assert binding == binding_for_spec(spec)
    binding["policy_hash"] = "0"*64
    assert repository.get_run_content_review_binding("run")["policy_hash"] != "0"*64
    tasks = repository.claim_task_batch("worker")
    assert len(tasks) == 1
    repository.complete_task(tasks[0]["outbox_id"], "worker")
    assert repository.get_run_content_review_binding("run") == binding_for_spec(spec)
    assert read_state(repository, "run")[0] == state


@pytest.mark.parametrize("initial_enabled", [False, True])
def test_same_request_keeps_original_policy_across_switches(repository, initial_enabled):
    create(repository, enabled=initial_enabled)
    prior = repository.get_spec_by_run("run")
    reused = create(repository, enabled=not initial_enabled, run_id="discarded")
    assert reused["run_id"] == "run" and repository.get_spec_by_run("discarded") is None
    assert repository.get_spec_by_run("run") == prior
    assert repository.list_outbox(pending_only=False)[0]["payload"]["run_id"] == "run"
    if not initial_enabled:
        assert prior is None and repository.get_run_content_review_binding("run") is None


def test_cas_conflict_idempotence_namespace_and_created_at(repository):
    create(repository)
    old = repository.get_spec_by_run("run"); new = deepcopy(old)
    new["spec_json"]["title"] = "first"; new["content_hash"] = json_hash(new["spec_json"])
    saved = repository.save_content_review_spec_once("run", "cws_run", old["content_hash"], new)
    assert saved["created_at"] == old["created_at"]
    assert repository.save_content_review_spec_once("run", "cws_run", old["content_hash"], new)["content_hash"] == saved["content_hash"]
    other = deepcopy(old); other["spec_json"]["title"] = "other"; other["content_hash"] = json_hash(other["spec_json"])
    with pytest.raises(ContentReviewConflict):
        repository.save_content_review_spec_once("run", "cws_run", old["content_hash"], other)
    assert repository.get_spec_by_run("run")["spec_json"]["title"] == "first"
    saved["spec_json"]["title"] = "external mutation"
    assert repository.get_spec_by_run("run")["spec_json"]["title"] == "first"


def test_invalid_initial_spec_leaves_no_partial_job_or_task(repository):
    # A malformed binding must fail inside the same creation transaction.
    original = repository.create_job_with_task_once
    deadline = datetime.now(timezone.utc)+timedelta(minutes=10)
    with pytest.raises(Exception):
        original(dict(run_id="bad", learner_id="learner", request_hash="bad", source_resource_ids=[], status="queued"),
            dict(outbox_id="bad", run_id="bad", event_type="courseware.run", idempotency_key="courseware.run:bad", payload={}),
            initial_spec=dict(run_id="bad", spec_id="wrong", spec_json={}, content_hash="0"*64))
    assert repository.get_job("bad") is None and repository.list_outbox("bad", pending_only=False) == []
