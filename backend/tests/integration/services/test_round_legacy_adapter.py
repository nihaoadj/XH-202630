"""Legacy import keeps old evidence read-only and never invents a primary."""

from datetime import datetime, timezone

import pytest

from app.core.security.errors import ApplicationError, ErrorCode
from app.models.feedback.feedback_loop import FeedbackFollowupSelection, LearningIntent
from app.models.learning_documents.schemas import (
    ExerciseItem, GenerateRequest, LearningResource, RunAttemptSubmitRequest,
)
from app.services.feedback.legacy_round_adapter import LegacyRoundAdapter
from tests.integration.services.test_round_generation import fixture


def legacy_attempt(service, profile, nodes=("a",)):
    jobs = service.feedback.generation_job_service
    job = jobs.create_job(profile, GenerateRequest(
        learner_id="learner", knowledge_base_id="kb", topic="legacy", target_skill_nodes=list(nodes),
        resource_types=["分阶测试题"], difficulty_preference="初级", include_review=True,
    ), run_id="legacy-run", batch_id="legacy-batch", submission_hash="legacy-submission")
    resources = []
    for node in nodes:
        resource = LearningResource(resource_id=f"legacy-{node}", learner_id="learner", topic="legacy",
                                    resource_type="分阶测试题", difficulty="初级", content_text="frozen",
                                    knowledge_points=[node], source_refs=[], learning_path_node=node,
                                    publication_status="published", run_id=job.run_id, batch_id=job.batch_id,
                                    exercise_items=[ExerciseItem(question_id=f"q-{node}", question_type="single_choice",
                                                                 question="synthetic?", options=["A", "B"],
                                                                 answer="A", skill_node_id=node)])
        service.feedback.resource_repo.save(resource, learner_id="learner", topic="legacy")
        resources.append(resource)
    knowledge = service.feedback.mastery_service.knowledge_service
    session = service.feedback.build_run_evaluation_session(profile, job.run_id, resources, knowledge)
    payload = RunAttemptSubmitRequest(
        learner_id="learner", run_id=job.run_id, source_resource_id=resources[0].resource_id,
        idempotency_key="legacy-attempt", expected_profile_version=profile.profile_version,
        submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": question.question_id, "answer": "B"} for question in session.questions],
    )
    return service.feedback.submit_run_attempt(profile, job.run_id, resources, payload, knowledge)


def selection(attempt_id, nodes=("a",)):
    return FeedbackFollowupSelection(learner_id="learner", attempt_id=attempt_id,
                                     option_id="personalized-correction-package-v1",
                                     learning_intent=LearningIntent.REINFORCE_WEAKNESS,
                                     selected_skill_node_ids=list(nodes))


def test_legacy_attempt_imports_with_legacy_roles_and_reuses_the_same_round():
    service, profile = fixture()
    result = legacy_attempt(service, profile)

    imported, created = LegacyRoundAdapter(service).choose_correction(profile, selection(result.attempt.attempt_id))
    round_row = service.repository.one("learning_rounds", round_id=created.round_id)

    assert round_row["protocol_version"] == "legacy-correction/v1"
    assert created.primary_node_id is None
    assert [member.role for member in created.members] == ["legacy"]
    assert imported.round_summary["round_id"] == created.round_id
    assert imported.followup_run_id == created.members[0].job_ids[0]
    assert imported.attempt.attempt_id == result.attempt.attempt_id

    # Importing the same attempt again (new selection key) must stay in the
    # original container instead of duplicating old evidence.
    again, second = LegacyRoundAdapter(service).choose_correction(profile, selection(result.attempt.attempt_id))
    assert second.round_id == created.round_id
    assert len(service.repository.find("learning_rounds")) == 1
    # Correction stages still open a real, bound Run per member.
    bindings = service.repository.find("learning_round_job_bindings")
    assert {row["relation_kind"] for row in bindings} == {"production"}


def test_new_round_attempt_is_not_imported_as_legacy_evidence():
    from tests.integration.services.test_round_generation import create_payload, publish, submit

    service, profile = fixture()
    created = service.create(profile, create_payload())
    publish(service, created)
    submitted = submit(service, profile, created, "round-submit")

    with pytest.raises(ApplicationError) as caught:
        LegacyRoundAdapter(service).choose_correction(profile, selection(submitted.attempt_id))
    assert caught.value.code == ErrorCode.ROUND_SELECTION_INVALID


def test_legacy_import_requires_answerable_legacy_evidence():
    service, profile = fixture()
    result = legacy_attempt(service, profile)
    attempt = service.feedback.feedback_loop_repo.get_attempt("learner", result.attempt.attempt_id)

    assert attempt.metadata.get("question_trace")
    assert attempt.metadata.get("round_context") is None
