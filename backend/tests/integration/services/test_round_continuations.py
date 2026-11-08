"""Round-bound append/recovery: scope, idempotency, limits and rollback."""

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.learning_documents.schemas import ContinueResourceBatchRequest, GenerateRequest
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_learning import RoundLearningService
from app.services.feedback.round_uow import RoundUnitOfWork
from app.services.generation.round_continuations import create_bound_job
from tests.integration.services.test_round_generation import (
    create_payload, dual_round, fixture, publish, submit,
)


def wired(sql=False, *, creation_enabled=True):
    """Attach the production UOW factory the container normally injects."""
    service, profile = fixture(sql)
    service.settings = Settings(learning_round_creation_enabled=creation_enabled)
    jobs = service.feedback.generation_job_service
    jobs.round_uow_factory = lambda: RoundUnitOfWork(service.repository, service.feedback, service.learners)
    return service, profile


def continuation_payload(run_id, resource_types=("案例分析",), **extra):
    return ContinueResourceBatchRequest(learner_id="learner", source_run_id=run_id,
                                        resource_types=list(resource_types), **extra)


def continue_batch(service, payload, key):
    jobs = service.feedback.generation_job_service
    batch_id = jobs.job_repo.get(payload.source_run_id).batch_id
    from app.services.generation.dispatch import submission_identity

    identity = submission_identity(service.learners.get("learner"), payload, key, f"continuation:{batch_id}")
    return jobs.create_continuation(
        service.learners.get("learner"), batch_id, payload,
        resource_service_factory=lambda: SimpleNamespace(list_by_learner=service.feedback.resource_repo.list_by_learner),
        feedback_repo_factory=lambda: service.feedback.feedback_loop_repo,
        # The HTTP entry points pass the container factory explicitly.
        round_uow_factory=jobs.round_uow_factory,
        **identity,
    )


def binding(service, run_id):
    return service.repository.one("learning_round_job_bindings", run_id=run_id)


def stage_node(service, result, role="primary"):
    member = next(item for item in result.members if item.role == role)
    rows = service.repository.find("learning_round_stage_nodes", stage_id=result.stage_id)
    return next(row for row in rows if row["round_node_id"] == member.member_id)


@pytest.mark.parametrize("sql", [False, True])
def test_primary_append_adds_types_in_the_same_stage_and_replays(sql):
    service, profile = wired(sql)
    created = service.create(profile, create_payload())
    source = created.members[0].job_ids[0]
    payload = continuation_payload(source)

    job, request = continue_batch(service, payload, "append-key")

    assert request.resource_types == ["案例分析"]
    assert job.batch_id == created.members[0].batch_id
    stored = binding(service, job.run_id)
    assert stored["relation_kind"] == "append"
    assert stored["source_run_id"] == source
    node = stage_node(service, created)
    assert node["resource_types"] == ["讲义", "案例分析"]
    stage = service.repository.one("learning_round_stages", stage_id=created.stage_id)
    # The append owns its own budget scope; it never widens another member.
    assert stage["budget_snapshot"]["scopes"][node["stage_node_id"]] == 2 * stage["budget_snapshot"]["resource_tokens"]

    replay, _ = continue_batch(service, payload, "append-key")
    assert replay.run_id == job.run_id
    assert len(service.feedback.generation_job_service.job_repo.list_by_learner("learner")) == 2
    assert len(service.repository.find("learning_round_job_bindings", relation_kind="append")) == 1


@pytest.mark.parametrize("sql", [False, True])
def test_review_append_is_rejected_without_writing(sql):
    service, profile = wired(sql)
    result = dual_round(service, profile)
    review = next(item for item in result.members if item.role == "review")
    review_run = review.job_ids[0]
    before = len(service.feedback.generation_job_service.job_repo.list_by_learner("learner"))

    with pytest.raises(ApplicationError) as caught:
        continue_batch(service, continuation_payload(review_run), "review-append")

    assert caught.value.code == ErrorCode.ROUND_SELECTION_INVALID
    assert caught.value.status_code == 422
    assert len(service.feedback.generation_job_service.job_repo.list_by_learner("learner")) == before
    assert binding(service, review_run)["relation_kind"] == "production"


@pytest.mark.parametrize("sql", [False, True])
def test_recovery_respects_budget_limit_and_never_replaces_published_work(sql):
    service, profile = wired(sql)
    created = service.create(profile, create_payload())
    source = created.members[0].job_ids[0]
    jobs = service.feedback.generation_job_service
    jobs.job_repo.mark_completed(source, [])
    request = GenerateRequest.model_validate(jobs.job_repo.get(source).request_payload)
    stored = binding(service, source)
    limit = service.repository.one("learning_round_stages", stage_id=created.stage_id)["budget_snapshot"]["H"]

    for index in range(limit):
        create_bound_job(jobs, profile, stored, request.model_copy(deep=True), f"recovery-{index}",
                         canonical_hash(["recovery", index]), relation="retry", source_run_id=source)

    with pytest.raises(ApplicationError) as caught:
        create_bound_job(jobs, profile, stored, request.model_copy(deep=True), "recovery-overflow",
                         canonical_hash(["recovery", "overflow"]), relation="retry", source_run_id=source)
    assert caught.value.code == ErrorCode.ROUND_CORRECTION_BUDGET_EXHAUSTED
    assert caught.value.status_code == 409

    publish(service, created)
    with pytest.raises(ApplicationError) as published:
        create_bound_job(jobs, profile, stored, request.model_copy(deep=True), "recovery-published",
                         canonical_hash(["recovery", "published"]), relation="retry", source_run_id=source)
    assert published.value.code == ErrorCode.ROUND_SELECTION_CONFLICT


@pytest.mark.parametrize("sql", [False, True])
def test_failure_inside_the_uow_rolls_back_job_binding_and_budget(sql, monkeypatch):
    service, profile = wired(sql)
    created = service.create(profile, create_payload())
    source = created.members[0].job_ids[0]
    node_before = stage_node(service, created)
    original = service.repository.insert

    def failing(table, values):
        if table == "learning_round_job_bindings":
            raise RuntimeError("injected binding failure")
        return original(table, values)

    monkeypatch.setattr(service.repository, "insert", failing)
    payload = continuation_payload(source)
    with pytest.raises(RuntimeError, match="injected"):
        continue_batch(service, payload, "append-rollback")

    assert len(service.feedback.generation_job_service.job_repo.list_by_learner("learner")) == 1
    node_after = stage_node(service, created)
    assert node_after["resource_types"] == node_before["resource_types"]
    assert node_after["row_version"] == node_before["row_version"]


def test_recovery_keeps_working_when_new_round_creation_is_disabled():
    service, profile = wired(creation_enabled=False)
    created = RoundLearningService(service.repository, service.feedback, service.learners,
                                   Settings(learning_round_creation_enabled=True)).create(profile, create_payload())
    source = created.members[0].job_ids[0]
    service.feedback.generation_job_service.job_repo.mark_completed(source, [])

    job, _ = continue_batch(service, continuation_payload(source), "append-disabled")

    assert binding(service, job.run_id)["relation_kind"] == "append"
    with pytest.raises(ApplicationError) as caught:
        service.create(profile, create_payload("another-key", "b"))
    assert caught.value.code == ErrorCode.ROUND_CREATION_DISABLED


def test_missing_round_transaction_factory_is_a_persistence_outage():
    service, profile = wired()
    created = service.create(profile, create_payload())
    jobs = service.feedback.generation_job_service
    jobs.round_uow_factory = None
    payload = continuation_payload(created.members[0].job_ids[0])

    with pytest.raises(ApplicationError) as caught:
        continue_batch(service, payload, "append-no-factory")
    assert caught.value.code == ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
    assert caught.value.status_code == 503
