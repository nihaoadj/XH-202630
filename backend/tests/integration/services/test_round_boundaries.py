"""Offline acceptance of the remaining round boundaries; synthetic fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.core.security.errors import ApplicationError
from app.models.feedback.rounds import RoundCorrectionSelectionV1
from app.services.feedback.round_corrections import RoundCorrections
from app.services.feedback.round_assessment import RoundAssessment
from app.services.feedback.round_feedback import RoundFeedback
from app.services.feedback.feedback import FeedbackService
from tests.integration.services.test_round_generation import (
    fixture, dual_round, submit, publish_correction_questions, create_payload, publish,
)
from tests.integration.services.test_round_failure_recovery import freeze_submission


def correction(service, profile, created, node, attempt, key):
    return RoundCorrections(service).create(service.learners.get(profile.learner_id), created.round_id,
        RoundCorrectionSelectionV1(learner_id=profile.learner_id, selection_key=key,
                                  targets=[{"node_id": node, "source_attempt_id": attempt}]))


@pytest.mark.parametrize("sql", [False, True])
def test_correct_a_then_b_preserves_b_source_and_rejects_replaced_a_source(sql, monkeypatch):
    service, profile = fixture(sql)
    monkeypatch.setattr(FeedbackService, "_short_answer_score", lambda *args: 0.0)
    created = dual_round(service, profile)
    first = submit(service, profile, created, "dual-original", "B")
    a, b = [node.node_id for node in first.nodes]
    stage_a = correction(service, profile, created, a, first.attempt_id, "correct-first-a")
    publish_correction_questions(service, stage_a)
    second = submit(service, service.learners.get(profile.learner_id), stage_a, "a-retested", "B")
    assert [node.node_id for node in second.nodes] == [a]
    with pytest.raises(ApplicationError):
        correction(service, profile, created, a, first.attempt_id, "a-old-source")
    stage_b = correction(service, profile, created, b, first.attempt_id, "correct-later-b")
    assert stage_b.round_id == created.round_id
    assert [member.node_id for member in stage_b.members] == [b]
    replay = correction(service, profile, created, b, first.attempt_id, "correct-later-b")
    assert replay == stage_b


@pytest.mark.parametrize("sql", [False, True])
@pytest.mark.parametrize("point", ["profile", "curriculum", "tier", "session", "stage", "events"])
def test_late_commit_fault_rolls_back_all_formal_facts(sql, point, monkeypatch):
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    before = service.learners.get(profile.learner_id).model_dump(mode="json")
    if point in {"session", "stage"}:
        original = type(service.repository).compare_and_set
        def fail(self, table, key, version, values):
            result = original(self, table, key, version, values)
            if (point == "session" and values.get("grading_state") == "submitted"
                    or point == "stage" and values.get("state") == "completed"):
                raise RuntimeError("injected late failure")
            return result
        monkeypatch.setattr(type(service.repository), "compare_and_set", fail)
    else:
        owner, name = {
            "profile": (FeedbackService, "_apply_profile_copy"),
            "curriculum": (type(service.feedback.mastery_service), "record_curriculum_verification"),
            "tier": (type(service.feedback.mastery_service), "apply_tier_feedback"),
            "events": (FeedbackService, "_record_feedback_events"),
        }[point]
        original = getattr(owner, name)
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected late failure")
        monkeypatch.setattr(owner, name, staticmethod(fail) if point == "profile" else fail)
    with pytest.raises(RuntimeError, match="injected late failure"):
        RoundFeedback(service).submit(profile, created.round_id, created.stage_id, payload)
    assert service.learners.get(profile.learner_id).model_dump(mode="json") == before
    assert service.feedback.feedback_loop_repo.list_attempts(profile.learner_id) == []
    assert service.repository.find("feedback_node_decisions") == []
    assert service.repository.find("learner_remediation_needs") == []
    assert service.repository.one("learning_round_evaluation_sessions", session_id=payload.session_id)["attempt_id"] is None
    assert service.repository.one("learning_round_stages", stage_id=created.stage_id)["state"] != "completed"


def test_concurrent_submissions_keep_one_owner_and_reject_another_key(monkeypatch):
    service, profile = fixture()
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    entered, release = Event(), Event()
    original = RoundAssessment.prepare
    def paused(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(RoundAssessment, "prepare", paused)
    feedback = RoundFeedback(service)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(feedback.submit, profile, created.round_id, created.stage_id, payload)
        try:
            assert entered.wait(10)
            assert feedback.submit(profile, created.round_id, created.stage_id, payload).state == "grading"
            with pytest.raises(ApplicationError) as conflict:
                feedback.submit(profile, created.round_id, created.stage_id,
                                payload.model_copy(update={"idempotency_key": "concurrent-other-key"}))
            assert conflict.value.status_code == 409
        finally:
            release.set()
        result = first.result(timeout=10)
    assert feedback.submit(profile, created.round_id, created.stage_id, payload) == result
    assert len(service.feedback.feedback_loop_repo.list_attempts(profile.learner_id)) == 1


@pytest.mark.parametrize("limit", [1, 3])
def test_correction_limit_boundary_is_frozen_and_enforced(limit, monkeypatch):
    service, profile = fixture()
    service.settings.learning_round_correction_stage_limit = limit
    monkeypatch.setattr(FeedbackService, "_short_answer_score", lambda *args: 0.0)
    created = service.create(profile, create_payload())
    publish(service, created)
    result = submit(service, profile, created, "initial-low", "B")
    for number in range(limit):
        stage = correction(service, profile, created, "a", result.attempt_id, f"boundary-correct-{number}")
        save = service.feedback.resource_repo.save
        def unique_save(resource, **kwargs):
            from hashlib import sha256
            identity = sha256(f"{stage.stage_id}:{resource.resource_id}".encode()).hexdigest()[:48]
            resource = resource.model_copy(update={"resource_id": identity})
            return save(resource, **kwargs)
        with monkeypatch.context() as local:
            local.setattr(service.feedback.resource_repo, "save", unique_save)
            publish_correction_questions(service, stage)
        result = submit(service, service.learners.get(profile.learner_id), stage, f"boundary-retest-{number}", "B")
    with pytest.raises(ApplicationError) as exhausted:
        correction(service, profile, created, "a", result.attempt_id, "boundary-overflow")
    assert exhausted.value.code.value == "ROUND_CORRECTION_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("limit", [0, 3])
def test_resource_recovery_limit_boundary(limit):
    from app.models.learning_documents.schemas import GenerateRequest
    from app.models.shared.persistence import canonical_hash
    from app.services.generation.round_continuations import create_bound_job
    from tests.integration.services.test_round_continuations import wired, binding
    service, profile = wired()
    service.settings.learning_round_resource_recovery_limit = limit
    created = service.create(profile, create_payload())
    jobs = service.feedback.generation_job_service
    source = created.members[0].job_ids[0]
    jobs.job_repo.mark_failed(source, "synthetic failure")
    request = GenerateRequest.model_validate(jobs.job_repo.get(source).request_payload)
    for number in range(limit):
        create_bound_job(jobs, profile, binding(service, source), request, f"bounded-retry-{number}",
                         canonical_hash(number), relation="retry", source_run_id=source)
    with pytest.raises(ApplicationError) as exhausted:
        create_bound_job(jobs, profile, binding(service, source), request, "bounded-overflow",
                         canonical_hash("overflow"), relation="retry", source_run_id=source)
    assert exhausted.value.code.value == "ROUND_CORRECTION_BUDGET_EXHAUSTED"
