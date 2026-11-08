from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.feedback.rounds import (
    GenerateRoundCreateRequestV1,
    RoundAttemptSubmitV1,
    RoundCorrectionSelectionV1,
    RoundCreationResponseV1,
    RoundEvaluationSessionV1,
    RoundIdentityV1,
    RoundJobBindingV1,
    RoundNextSelectionV1,
    RoundAnswerV1,
)
from app.models.learning_documents.schemas import GenerateCreateRequest, GenerateRequest
from app.models.shared.llm import LLMCallContext
from app.core.security.errors import ApplicationError, ErrorCode


def test_round_application_errors_match_frozen_public_fixture():
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "learning_round_errors.json"
    for row in json.loads(fixture.read_text(encoding="utf-8")):
        error = ApplicationError(ErrorCode(row["code"]), status_code=row["status_code"])
        assert error.code.value == row["code"]
        assert error.status_code == row["status_code"]
        assert error.public_message == row["message"]


@pytest.mark.parametrize("value", [None, "", "  ", []])
def test_required_answer_rejects_empty_values(value):
    with pytest.raises(ValidationError):
        RoundAnswerV1(question_id="question", answer=value)


@pytest.mark.parametrize("value", [False, 0, "A", ["A", "B"]])
def test_required_answer_preserves_nonempty_answers(value):
    assert RoundAnswerV1(question_id="question", answer=value).answer == value


def test_new_create_and_persisted_legacy_have_separate_target_limits():
    payload = {"learner_id": "learner", "topic": "topic", "target_skill_nodes": ["a", "b"]}
    assert GenerateRequest.model_validate(payload).target_skill_nodes == ["a", "b"]
    with pytest.raises(ValidationError):
        GenerateCreateRequest.model_validate(payload)
    assert GenerateCreateRequest.model_validate({**payload, "target_skill_nodes": ["a"]}).target_skill_nodes == ["a"]
    with pytest.raises(ValidationError):
        GenerateCreateRequest.model_validate({**payload, "target_skill_nodes": ["a"], "role": "review"})


def test_selection_rejects_duplicate_node_and_client_role():
    payload = {
        "learner_id": "learner", "source_attempt_id": "attempt", "primary_node_id": "a",
        "primary_learning_intent": "learn_new_knowledge", "primary_resource_types": ["讲义"],
        "selection_key": "selection-key",
    }
    with pytest.raises(ValidationError):
        RoundNextSelectionV1.model_validate({**payload, "review_node_id": "a"})
    with pytest.raises(ValidationError):
        RoundNextSelectionV1.model_validate({**payload, "role": "review"})
    with pytest.raises(ValidationError):
        RoundNextSelectionV1.model_validate({**payload, "primary_resource_types": ["个性化纠错训练包"]})
    with pytest.raises(ValidationError):
        RoundNextSelectionV1.model_validate({**payload, "primary_resource_types": ["unsupported"]})


def test_correction_rejects_duplicate_node_even_with_different_sources():
    with pytest.raises(ValidationError):
        RoundCorrectionSelectionV1.model_validate({
            "learner_id": "learner", "selection_key": "selection-key",
            "targets": [{"node_id": "a", "source_attempt_id": "one"},
                        {"node_id": "a", "source_attempt_id": "two"}],
        })


def test_submission_rejects_duplicate_questions_and_authoritative_fields():
    payload = {
        "learner_id": "learner", "session_id": "session", "manifest_hash": "a" * 64,
        "idempotency_key": "submission-key", "expected_profile_version": 1,
        "submitted_at": datetime.now(timezone.utc),
        "answers": [{"question_id": "q", "answer": "A"}],
    }
    assert RoundAttemptSubmitV1.model_validate(payload).answers[0].answer == "A"
    with pytest.raises(ValidationError):
        RoundAttemptSubmitV1.model_validate({**payload, "score": 1})
    with pytest.raises(ValidationError):
        RoundAttemptSubmitV1.model_validate({**payload, "answers": payload["answers"] * 2})


def test_session_requires_at_least_one_nonempty_group():
    payload = {"session_id": "s", "round_id": "r", "stage_id": "t", "manifest_hash": "a" * 64}
    with pytest.raises(ValidationError):
        RoundEvaluationSessionV1.model_validate({**payload, "groups": []})
    with pytest.raises(ValidationError):
        RoundEvaluationSessionV1.model_validate({**payload, "groups": [
            {"member_id": "m", "node_id": "n", "role": "primary", "questions": []}
        ]})


def test_normal_and_legacy_identities_do_not_guess_roles():
    primary = {"member_id": "a", "node_id": "a", "role": "primary"}
    review = {"member_id": "b", "node_id": "b", "role": "review"}
    assert RoundIdentityV1(protocol_version="learning-round/v1", members=[primary, review])
    legacy = [{**member, "role": "legacy"} for member in (primary, review)]
    assert RoundIdentityV1(protocol_version="legacy-correction/v1", members=legacy)
    with pytest.raises(ValidationError):
        RoundIdentityV1(protocol_version="legacy-correction/v1", members=[primary, review])
    with pytest.raises(ValidationError):
        RoundIdentityV1(protocol_version="learning-round/v1", members=legacy)


def test_round_claim_request_allows_multi_resource_but_job_does_not():
    payload = {
        "learner_id": "learner", "topic": "topic", "target_skill_nodes": ["node"],
        "resource_types": ["复习清单", "分阶测试题"], "include_claim_check": True,
        "selection_key": "selection-key",
    }
    assert GenerateRoundCreateRequestV1.model_validate(payload).include_claim_check
    with pytest.raises(ValidationError):
        GenerateCreateRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        GenerateRoundCreateRequestV1.model_validate({**payload, "constraints": {"selection_type": "lower_tier_selection"}})
    with pytest.raises(ValidationError):
        GenerateRoundCreateRequestV1.model_validate({**payload, "resource_types": ["个性化纠错训练包"]})


def test_legacy_binding_cannot_claim_a_primary_or_create_initial_job():
    binding = {
        "protocol_version": "legacy-correction/v1", "round_id": "round", "member_id": "member",
        "node_id": "node", "stage_id": "stage", "stage_node_id": "stage-node", "batch_id": "batch",
        "role": "legacy", "stage_kind": "correction",
    }
    assert RoundJobBindingV1.model_validate(binding).role == "legacy"
    with pytest.raises(ValidationError):
        RoundJobBindingV1.model_validate({**binding, "role": "primary"})
    with pytest.raises(ValidationError):
        RoundJobBindingV1.model_validate({**binding, "stage_kind": "initial"})


def test_public_session_omits_private_answer_and_rejects_cross_group_id_collision():
    question = {"question_id": "q", "question_type": "single", "question": "Question?", "answer": "A"}
    group = {"member_id": "a", "node_id": "a", "role": "primary", "questions": [question]}
    payload = {"session_id": "s", "round_id": "r", "stage_id": "t", "manifest_hash": "a" * 64}
    session = RoundEvaluationSessionV1.model_validate({**payload, "groups": [group]})
    assert "answer" not in session.model_dump()["groups"][0]["questions"][0]
    session.require_members({"a"})
    with pytest.raises(ValueError):
        session.require_members({"a", "b"})
    with pytest.raises(ValidationError):
        RoundEvaluationSessionV1.model_validate({**payload, "groups": [group, {
            "member_id": "b", "node_id": "b", "role": "review", "questions": [question],
        }]})


def test_round_budget_scope_must_match_purpose_without_changing_legacy_calls():
    context = {"run_id": "run", "step_id": "step", "node_name": "node", "schema_name": "schema"}
    assert LLMCallContext.model_validate(context).budget_scope is None
    scope = {"scope_id": "scope", "stage_id": "stage", "kind": "production"}
    assert LLMCallContext.model_validate({**context, "budget_scope": scope, "call_purpose": "production"})
    with pytest.raises(ValidationError):
        LLMCallContext.model_validate({**context, "call_purpose": "production"})
    with pytest.raises(ValidationError):
        LLMCallContext.model_validate({**context, "budget_scope": scope, "call_purpose": "assessment"})


def test_correction_creation_can_contain_only_the_review_member():
    review = {"member_id": "b", "role": "review", "node_id": "b", "stage_node_id": "sb",
              "batch_id": "batch", "job_ids": ["run-b"], "state": "producing",
              "resource_types": ["个性化纠错训练包", "分阶测试题"]}
    result = RoundCreationResponseV1(round_id="round", stage_id="correction", primary_node_id="a",
                                     members=[review], state="producing")
    assert result.members[0].role == "review"
