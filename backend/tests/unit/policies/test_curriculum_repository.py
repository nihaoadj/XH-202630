from datetime import datetime, timezone

from app.db.learners.curriculum import MemoryCurriculumRepository


def test_curriculum_round_accumulates_debt_only_for_ready_unplanned_nodes():
    repository = MemoryCurriculumRepository()
    repository.ensure_nodes("learner", "kb", ["a", "b", "blocked"])
    now = datetime.now(timezone.utc)

    repository.schedule_round(
        "learner", "kb", run_id="run-1", selected_node_ids=["a"],
        eligible_unplanned_ids=["a", "b"], now=now,
    )
    by_id = {item.skill_node_id: item for item in repository.list_nodes("learner", "kb")}
    assert by_id["a"].progress_status.value == "scheduled"
    assert by_id["a"].wait_rounds == 0
    assert by_id["b"].wait_rounds == 1
    assert by_id["blocked"].wait_rounds == 0

    repository.schedule_round(
        "learner", "kb", run_id="run-2", selected_node_ids=["b"],
        eligible_unplanned_ids=["b"], now=now,
    )
    by_id = {item.skill_node_id: item for item in repository.list_nodes("learner", "kb")}
    assert by_id["b"].progress_status.value == "scheduled"
    assert by_id["b"].wait_rounds == 0


def test_curriculum_exposure_and_verification_are_idempotent():
    repository = MemoryCurriculumRepository()
    repository.ensure_nodes("learner", "kb", ["a"])
    now = datetime.now(timezone.utc)
    repository.reconcile_exposure("learner", "kb", {"a": 1}, now)
    repository.record_verification(
        "learner", "kb", attempt_id="attempt-1", scores={"a": 0.9}, now=now,
    )
    repository.record_verification(
        "learner", "kb", attempt_id="attempt-1", scores={"a": 0.9}, now=now,
    )
    row = repository.list_nodes("learner", "kb")[0]
    assert row.progress_status.value == "completed"
    assert row.published_resource_count == 1
    assert row.verified_attempt_count == 1


def test_failed_run_releases_unpublished_scheduled_node():
    repository = MemoryCurriculumRepository()
    now = datetime.now(timezone.utc)
    repository.ensure_nodes("learner", "kb", ["a"])
    repository.schedule_round(
        "learner", "kb", run_id="run-failed", selected_node_ids=["a"],
        eligible_unplanned_ids=["a"], now=now,
    )
    repository.release_failed_run("learner", "kb", run_id="run-failed", now=now)
    row = repository.list_nodes("learner", "kb")[0]
    assert row.progress_status.value == "unplanned"
    assert row.scheduled_run_id is None
