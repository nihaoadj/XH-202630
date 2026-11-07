"""Recover expired scoring owners and project current resource retry outcomes."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security.errors import ApplicationError, ErrorCode
from app.models.feedback.rounds import RoundAttemptSubmitV1
from app.models.learning_documents.schemas import GenerateRequest
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_assessment import RoundAssessment
from app.services.feedback.round_feedback import RoundFeedback
from app.services.generation.round_continuations import create_bound_job
from tests.integration.services.test_round_continuations import binding, wired
from tests.integration.services.test_round_generation import create_payload, fixture, publish


def freeze_submission(service, profile, created):
    session = RoundAssessment(service).session(profile, created.round_id, created.stage_id)
    return RoundAttemptSubmitV1(
        learner_id=profile.learner_id, session_id=session.session_id,
        manifest_hash=session.manifest_hash, idempotency_key="frozen-recovery-submit",
        expected_profile_version=profile.profile_version, submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": question.question_id, "answer": "A"}
                 for group in session.groups for question in group.questions],
    )


def claim_scoring(service, payload, *, expired=True):
    with service.repository.transaction() as tx:
        row = tx.one("learning_round_evaluation_sessions", session_id=payload.session_id)
        return tx.compare_and_set("learning_round_evaluation_sessions", payload.session_id, row["row_version"], {
            "grading_state": "grading", "grading_owner": "abandoned-owner", "grading_generation": 1,
            "grading_lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=-5 if expired else 5),
            "submission_key": payload.idempotency_key, "submission_hash": canonical_hash(payload.model_dump(mode="json")),
        })


@pytest.mark.parametrize("sql", [False, True])
def test_expired_scoring_becomes_resumable_without_mutating_the_frozen_submission(sql, monkeypatch):
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    abandoned = claim_scoring(service, payload)
    before_version = service.learners.get(profile.learner_id).profile_version
    feedback = RoundFeedback(service)

    status = feedback.result(profile, created.round_id, created.stage_id)
    assert status.state == "not_submitted"
    assert service.repository.one("learning_round_evaluation_sessions", session_id=payload.session_id) == abandoned
    assert service.feedback.feedback_loop_repo.list_attempts(profile.learner_id) == []
    assert service.learners.get(profile.learner_id).profile_version == before_version

    original_prepare = RoundAssessment.prepare
    prepared_by_new_owner = []

    def prepare(self, current, row, request):
        prepared, anchor = original_prepare(self, current, row, request)
        prepared_by_new_owner.append((row, prepared, anchor))
        # The new owner has only acquired the lease; no Attempt exists yet.
        # Rejection here must come from the owner fence, not a submitted flag.
        assert row["attempt_id"] is None
        with pytest.raises(ApplicationError) as stale_owner:
            feedback._commit(profile, created.round_id, created.stage_id, abandoned, prepared, anchor,
                             "abandoned-owner", abandoned["submission_hash"])
        assert stale_owner.value.code == ErrorCode.ROUND_ATTEMPT_CONFLICT
        return prepared, anchor

    monkeypatch.setattr(RoundAssessment, "prepare", prepare)
    submitted = feedback.submit(profile, created.round_id, created.stage_id, payload)
    assert feedback.submit(profile, created.round_id, created.stage_id, payload) == submitted
    assert len(service.feedback.feedback_loop_repo.list_attempts(profile.learner_id)) == 1
    assert service.learners.get(profile.learner_id).profile_version == before_version + 1
    assert prepared_by_new_owner[0][0]["grading_generation"] == 2

    # The old owner's completed work cannot write after a successful takeover.
    _, prepared, anchor = prepared_by_new_owner[0]
    with pytest.raises(ApplicationError) as late_owner:
        feedback._commit(profile, created.round_id, created.stage_id, abandoned, prepared, anchor,
                         "abandoned-owner", abandoned["submission_hash"])
    assert late_owner.value.code == ErrorCode.ROUND_ATTEMPT_CONFLICT
    assert len(service.feedback.feedback_loop_repo.list_attempts(profile.learner_id)) == 1
    assert service.learners.get(profile.learner_id).profile_version == before_version + 1


@pytest.mark.parametrize("sql", [False, True])
def test_expired_scoring_keeps_conflicting_keys_and_content_rejected(sql):
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    abandoned = claim_scoring(service, payload)
    feedback = RoundFeedback(service)
    for changed in [payload.model_copy(update={"idempotency_key": "different-recovery-key"}),
                    payload.model_copy(update={"answers": [item.model_copy(update={"answer": "B"}) for item in payload.answers]})]:
        with pytest.raises(ApplicationError) as conflict:
            feedback.submit(profile, created.round_id, created.stage_id, changed)
        assert conflict.value.code == ErrorCode.ROUND_ATTEMPT_CONFLICT
        assert conflict.value.status_code == 409
    assert service.repository.one("learning_round_evaluation_sessions", session_id=payload.session_id) == abandoned


@pytest.mark.parametrize("sql", [False, True])
def test_live_scoring_lease_still_polls_and_does_not_grade_twice(sql, monkeypatch):
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    active = claim_scoring(service, payload, expired=False)

    def unexpected(*args):
        pytest.fail("a live owner must not be replaced")

    monkeypatch.setattr(RoundAssessment, "prepare", unexpected)
    feedback = RoundFeedback(service)
    assert feedback.result(profile, created.round_id, created.stage_id).state == "grading"
    assert feedback.submit(profile, created.round_id, created.stage_id, payload).state == "grading"
    assert service.repository.one("learning_round_evaluation_sessions", session_id=payload.session_id) == active


@pytest.mark.parametrize("sql", [False, True])
def test_resource_retry_states_follow_the_effective_attempt_and_keep_history(sql):
    service, profile = wired(sql)
    created = service.create(profile, create_payload())
    jobs = service.feedback.generation_job_service
    source_id = created.members[0].job_ids[0]
    jobs.job_repo.mark_failed(source_id, "first failure")
    assert service.detail(profile.learner_id, created.round_id).members[0].state == "failed"
    request = GenerateRequest.model_validate(jobs.job_repo.get(source_id).request_payload)

    retry, _ = create_bound_job(jobs, profile, binding(service, source_id), request, "retry-one",
                                canonical_hash("retry-one"), relation="retry", source_run_id=source_id)
    recovering = service.detail(profile.learner_id, created.round_id).members[0]
    assert recovering.state == "producing" and recovering.failed_job_count == 0
    jobs.job_repo.mark_failed(retry.run_id, "second failure")
    failed = service.detail(profile.learner_id, created.round_id).members[0]
    assert failed.state == "failed" and failed.failed_job_count == 1

    retry2, _ = create_bound_job(jobs, profile, binding(service, retry.run_id), request, "retry-two",
                                 canonical_hash("retry-two"), relation="retry", source_run_id=retry.run_id)
    jobs.job_repo.mark_completed(retry2.run_id, [])
    member = created.members[0].model_copy(update={"job_ids": [retry2.run_id]})
    publish(service, created.model_copy(update={"members": [member]}))
    recovered = service.detail(profile.learner_id, created.round_id).members[0]
    assert recovered.state == "awaiting_assessment" and recovered.failed_job_count == 0
    assert recovered.resource_ids
    assert jobs.job_repo.get(source_id).job_status == "failed"
    assert jobs.job_repo.get(retry.run_id).job_status == "failed"
    assert len(service.repository.find("learning_round_job_bindings")) == 3


@pytest.mark.parametrize("sql", [False, True])
def test_partial_resource_recovery_never_hides_another_unresolved_type(sql):
    service, profile = wired(sql)
    payload = create_payload().model_copy(update={"resource_types": ["讲义", "案例分析"]})
    created = service.create(profile, payload)
    jobs = service.feedback.generation_job_service
    source_id = created.members[0].job_ids[0]
    jobs.job_repo.mark_failed(source_id, "both types failed")
    request = GenerateRequest.model_validate(jobs.job_repo.get(source_id).request_payload)
    request = request.model_copy(update={"resource_types": ["讲义"]})
    retry, _ = create_bound_job(jobs, profile, binding(service, source_id), request, "partial-retry",
                                canonical_hash("partial-retry"), relation="retry", source_run_id=source_id)
    pending = service.detail(profile.learner_id, created.round_id).members[0]
    assert pending.state == "producing" and pending.failed_job_count == 1
    jobs.job_repo.mark_completed(retry.run_id, [])
    member = created.members[0].model_copy(update={"job_ids": [retry.run_id], "resource_types": ["讲义"]})
    publish(service, created.model_copy(update={"members": [member]}))
    partial = service.detail(profile.learner_id, created.round_id).members[0]
    assert partial.state == "failed" and partial.failed_job_count == 1
    assert len(partial.resource_ids) == 1
