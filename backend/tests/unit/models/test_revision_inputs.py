"""Unit tests for the private generation revision-input contracts (T46)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.resource_workflows.learning_documents.revision_inputs import (
    is_revision_input_envelope,
    pack_revision_input,
    unpack_revision_input,
)
from app.core.retrieval.knowledge_ids import sha256_hex
from app.models.reviews.revision_inputs import (
    CLAIM_KIND,
    ORDINARY_KIND,
    RESERVED_REVISION_INPUT_KEYS,
    REVISION_INPUT_ENVELOPE_VERSION,
    REVISION_INPUT_SCHEMA_VERSION,
    ClaimReviewRevisionInput,
    ClaimRevisionContextGroupV1,
    ClaimRevisionProblemV1,
    ResourceReviewRevisionInput,
    RevisionSourceSpanV1,
)


def _span(span_id="sp_0000", text="合成原文", start=0, end=4):
    return RevisionSourceSpanV1(
        span_id=span_id,
        source_text=text,
        source_start=start,
        source_end=end,
        source_text_hash=sha256_hex(text),
    )


def _problem(claim_id="clm_a", span_id="sp_0000", verdict="contradicted", evidence_ids=None):
    return ClaimRevisionProblemV1(
        claim_id=claim_id,
        claim_index=0,
        claim_text="合成断言",
        verdict=verdict,
        reason="合成判定理由",
        source_span_id=span_id,
        evidence_ids=evidence_ids if evidence_ids is not None else ["evidence"],
    )


def _claim_input():
    spans = [_span()]
    problems = [_problem()]
    groups = [ClaimRevisionContextGroupV1(group_id="grp_0000", unit_id="u_0", problem_claim_ids=["clm_a"])]
    return ClaimReviewRevisionInput(
        resource_spec_id="spec",
        parent_resource_id="parent",
        parent_version=1,
        content_hash=sha256_hex("合成原文"),
        previous_text="合成原文",
        targets=["node"],
        spans=spans,
        problems=problems,
        groups=groups,
    )


def test_reserved_revision_input_keys_cover_private_generation_channels():
    assert RESERVED_REVISION_INPUT_KEYS == frozenset({
        "generation_revision_inputs",
        "resource_review_revision",
        "claim_review_revision",
    })


def test_envelope_constants_are_stable_and_distinct():
    assert REVISION_INPUT_SCHEMA_VERSION == "1.0"
    assert REVISION_INPUT_ENVELOPE_VERSION == "revision-input-v1"
    assert ORDINARY_KIND == "ordinary" and CLAIM_KIND == "claim"


def test_envelope_pack_unpack_round_trip_preserves_kind_and_payload():
    model = _claim_input()
    envelope = pack_revision_input(model)
    assert is_revision_input_envelope(envelope)
    assert envelope["schema_version"] == REVISION_INPUT_ENVELOPE_VERSION
    assert envelope["kind"] == CLAIM_KIND
    restored = unpack_revision_input(envelope)
    assert restored == model
    assert isinstance(restored, ClaimReviewRevisionInput)


def test_ordinary_envelope_round_trip():
    model = ResourceReviewRevisionInput(
        resource_spec_id="spec",
        parent_resource_id="parent",
        revision_source="compat",
        feedback={"issues": [{"resource_id": "parent"}]},
    )
    envelope = pack_revision_input(model)
    assert envelope["kind"] == ORDINARY_KIND
    assert unpack_revision_input(envelope) == model


def test_is_revision_input_envelope_rejects_legacy_feedback_and_junk():
    assert not is_revision_input_envelope({"issues": [], "revision_instructions": []})
    # Versioned candidates must reach strict unpacking instead of legacy fallback.
    assert is_revision_input_envelope({"schema_version": "1.0"})
    assert not is_revision_input_envelope("not-a-dict")
    assert not is_revision_input_envelope(None)


def test_unpack_rejects_unknown_version_and_kind():
    with pytest.raises(ValueError):
        unpack_revision_input({"schema_version": "other", "kind": CLAIM_KIND, "input": {}})
    with pytest.raises(ValueError):
        unpack_revision_input({"schema_version": REVISION_INPUT_ENVELOPE_VERSION, "kind": "other", "input": {}})


def test_source_whitespace_survives_serialization_with_matching_hash():
    text = "  source\n"
    original = ClaimReviewRevisionInput(
        resource_spec_id="spec", parent_resource_id="parent", parent_version=1,
        previous_text=text, content_hash=sha256_hex(text), spans=[_span(text=text, end=len(text))],
    )
    restored = ClaimReviewRevisionInput.model_validate_json(original.model_dump_json())
    assert restored.previous_text == restored.spans[0].source_text == text
    assert restored.spans[0].source_text_hash == sha256_hex(text)


def test_claim_input_rejects_span_reference_and_group_coverage_gaps():
    # Problem referencing a missing span.
    model = _claim_input()
    bad = model.model_copy(update={"problems": [_problem(span_id="sp_missing")]})
    with pytest.raises(ValidationError):
        ClaimReviewRevisionInput.model_validate(bad.model_dump(mode="json"))

    # Group not covering every problem.
    missing = model.model_copy(update={
        "groups": [ClaimRevisionContextGroupV1(group_id="grp_0000", unit_id="u_0", problem_claim_ids=[])],
    })
    with pytest.raises(ValidationError):
        ClaimReviewRevisionInput.model_validate(missing.model_dump(mode="json"))


def test_not_in_evidence_problem_forbids_evidence_ids():
    model = _claim_input()
    bad = model.model_copy(update={
        "problems": [_problem(verdict="not_in_evidence", evidence_ids=["evidence"])],
    })
    with pytest.raises(ValidationError):
        ClaimReviewRevisionInput.model_validate(bad.model_dump(mode="json"))


def test_not_in_evidence_problem_with_empty_evidence_is_valid():
    model = _claim_input()
    ok = model.model_copy(update={
        "problems": [_problem(verdict="not_in_evidence", evidence_ids=[])],
    })
    assert ClaimReviewRevisionInput.model_validate(ok.model_dump(mode="json")).problems[0].evidence_ids == []
