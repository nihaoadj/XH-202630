"""Contracts for the optional Claim evidence retrieval switch and envelopes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
    GenerateRequest,
)
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimQueryBatchOutputV1,
    ClaimSupplementJudgementLLMOutput,
    normalize_inherited_switch,
    session_id_for,
    validate_feature_switch,
)


def _request(**overrides) -> dict:
    payload = {
        "learner_id": "learner-1",
        "topic": "RAG",
        "resource_types": ["讲义"],
        "include_review": True,
        "include_claim_check": True,
        "include_claim_evidence_retrieval": True,
    }
    payload.update(overrides)
    return payload


def test_switch_defaults_to_closed_and_legacy_payload_decodes():
    request = GenerateRequest.model_validate({
        "learner_id": "learner-1", "topic": "RAG", "resource_types": ["讲义"],
    })

    assert request.include_claim_evidence_retrieval is False
    assert request.include_claim_check is False


def test_switch_without_claim_audit_is_rejected():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(_request(include_claim_check=False))


def test_switch_without_ordinary_review_is_rejected():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(_request(include_review=False))


def test_switch_requires_one_resource_type():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(_request(resource_types=["讲义", "实操指南"]))


def test_switch_accepts_the_supported_combination():
    request = GenerateRequest.model_validate(_request())
    assert request.include_claim_evidence_retrieval is True


def test_feature_switch_helper_is_explicit():
    validate_feature_switch(
        include_claim_evidence_retrieval=False,
        include_claim_check=False,
        include_review=False,
    )
    with pytest.raises(ValueError):
        validate_feature_switch(
            include_claim_evidence_retrieval=True,
            include_claim_check=False,
            include_review=True,
        )


def test_continuation_tristate_inherits_and_closes_with_claim_audit():
    assert normalize_inherited_switch(
        requested=None, inherited=True, inherited_claim_check=True,
        effective_claim_check=True,
    ) is True
    assert normalize_inherited_switch(
        requested=None, inherited=True, inherited_claim_check=True,
        effective_claim_check=False,
    ) is False
    assert normalize_inherited_switch(
        requested=False, inherited=True, inherited_claim_check=True,
        effective_claim_check=True,
    ) is False
    assert normalize_inherited_switch(
        requested=True, inherited=False, inherited_claim_check=False,
        effective_claim_check=True,
    ) is True


def test_continuation_request_keeps_the_tristate_field():
    payload = ContinueResourceBatchRequest.model_validate({
        "learner_id": "learner-1", "resource_types": ["讲义"],
    })
    assert payload.include_claim_evidence_retrieval is None


def test_policy_defaults_match_the_frozen_engineering_limits():
    policy = ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
    )
    assert policy.max_sessions_per_resource_version == 1
    assert policy.query_batch_claims == 16
    assert policy.rejudge_batch_claims == 16
    assert policy.max_queries == 96
    assert policy.queries_per_request == 6
    assert policy.max_new_excerpts_per_resource == 8
    assert policy.max_new_excerpts == 16
    assert policy.max_logical_calls == 16
    assert policy.max_attempts == 24
    assert policy.attempts_per_call == 3
    assert policy.max_wall_seconds == 600
    assert policy.downstream_reserve_seconds == 300
    assert len(policy.policy_hash) == 64


def test_policy_rejects_an_inconsistent_quota():
    with pytest.raises(ValidationError):
        ClaimEvidenceRetrievalPolicyV1(
            queries_per_claim=3, max_queries_per_claim=2,
            query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
            rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        )


def test_query_schema_rejects_duplicate_claims_and_overlong_queries():
    with pytest.raises(ValidationError):
        ClaimQueryBatchOutputV1.model_validate({
            "batch_id": "b1", "input_hash": "a" * 64,
            "items": [
                {"claim_id": "clm_" + "1" * 32, "queries": [{"text": "a"}]},
                {"claim_id": "clm_" + "1" * 32, "queries": [{"text": "b"}]},
            ],
        })
    with pytest.raises(ValidationError):
        ClaimQueryBatchOutputV1.model_validate({
            "batch_id": "b1", "input_hash": "a" * 64,
            "items": [{"claim_id": "clm_" + "1" * 32, "queries": [{"text": "x" * 513}]}],
        })


def test_supplement_output_rejects_empty_conflict_list():
    with pytest.raises(ValidationError):
        ClaimSupplementJudgementLLMOutput.model_validate({
            "judgements": [{
                "claim_id": "clm_" + "1" * 32,
                "verdict": "supported",
                "evidence_ids": ["ev-1"],
                "reason": "ok",
                "confidence": 0.5,
                "evidence_conflict": True,
                "conflicting_evidence_ids": [],
            }],
        })


def test_session_id_is_stable_and_binding_scoped():
    first = session_id_for(
        run_id="r1", resource_id="res1", resource_version=1,
        review_id="rev1", content_hash="a" * 64, policy_hash="b" * 64,
    )
    second = session_id_for(
        run_id="r1", resource_id="res1", resource_version=1,
        review_id="rev1", content_hash="a" * 64, policy_hash="b" * 64,
    )
    other = session_id_for(
        run_id="r1", resource_id="res1", resource_version=2,
        review_id="rev1", content_hash="a" * 64, policy_hash="b" * 64,
    )
    assert first == second
    assert first != other
    assert first.startswith("cers_")


def test_terminal_session_requires_completed_at():
    with pytest.raises(ValidationError):
        ClaimEvidenceRetrievalSessionV1(
            session_id="cers_" + "1" * 32,
            run_id="r1", resource_id="res1", resource_version=1, review_id="rev1",
            content_hash="a" * 64, policy_hash="b" * 64,
            base_evidence_set_hash="c" * 64, initial_judgement_hash="d" * 64,
            status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
        )
    session = ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32,
        run_id="r1", resource_id="res1", resource_version=1, review_id="rev1",
        content_hash="a" * 64, policy_hash="b" * 64,
        base_evidence_set_hash="c" * 64, initial_judgement_hash="d" * 64,
        status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
        completed_at=datetime.now(timezone.utc),
    )
    assert session.status is ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE
