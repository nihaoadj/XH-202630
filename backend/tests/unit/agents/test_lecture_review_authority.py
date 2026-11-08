"""Isolated authority primitives; production entry points are not wired yet."""

import copy

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_authority import (
    LECTURE_WORKFLOW_VERSION, validate_lecture_authority,
)
from app.models.generation.dispatch import TEXT_WORKFLOW_VERSION
from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.shared.persistence import canonical_hash


def frozen():
    policy = LectureReviewPolicyV1(context_tokens=64000, max_output_tokens=12000).model_dump(mode="json")
    return {"lecture_review_contract_version": "1.0", "lecture_review_policy": policy,
            "lecture_review_policy_hash": canonical_hash(policy)}


def inputs():
    request = {"topic": "test", **frozen()}
    dispatch = {"workflow_version": LECTURE_WORKFLOW_VERSION, "base_workflow_version": TEXT_WORKFLOW_VERSION,
                **frozen()}
    dispatch["lecture_dispatch_hash"] = canonical_hash(dispatch)
    digest = canonical_hash(request)
    return dict(request_snapshot=request, request_hash=digest, created_event_request_hash=digest,
                dispatch=dispatch, checkpoint=frozen())


def test_valid_contract_and_legacy():
    assert validate_lecture_authority(**inputs()) == "lecture_issue_v1"
    snapshot = {"topic": "old"}
    digest = canonical_hash(snapshot)
    assert validate_lecture_authority(request_snapshot=snapshot, request_hash=digest,
                                      created_event_request_hash=digest) == "legacy_content_v2"


@pytest.mark.parametrize("field", ["lecture_review_contract_version", "lecture_review_policy", "lecture_review_policy_hash"])
def test_removed_required_fields_never_fall_back(field):
    values = inputs()
    del values["checkpoint"][field]
    with pytest.raises(ValueError):
        validate_lecture_authority(**values)


def test_deleted_inner_policy_field_does_not_get_pydantic_default():
    values = inputs()
    for snapshot in (values["request_snapshot"], values["dispatch"], values["checkpoint"]):
        policy = snapshot["lecture_review_policy"]
        del policy["max_open_issues"]
        snapshot["lecture_review_policy_hash"] = canonical_hash(policy)
    values["request_hash"] = canonical_hash(values["request_snapshot"])
    values["created_event_request_hash"] = values["request_hash"]
    values["dispatch"]["lecture_dispatch_hash"] = canonical_hash(
        {k: v for k, v in values["dispatch"].items() if k != "lecture_dispatch_hash"})
    with pytest.raises(ValueError, match="fields"):
        validate_lecture_authority(**values)


def test_mutation_or_missing_marker_is_rejected():
    values = inputs()
    values["request_snapshot"]["topic"] = "changed"
    with pytest.raises(ValueError, match="creation"):
        validate_lecture_authority(**values)
    values = inputs()
    values["dispatch"]["workflow_version"] = TEXT_WORKFLOW_VERSION
    with pytest.raises(ValueError, match="legacy"):
        validate_lecture_authority(**values)
    values = inputs()
    values["checkpoint"] = {}
    with pytest.raises(ValueError, match="incomplete"):
        validate_lecture_authority(**values)


def test_policy_swap_and_dispatch_hash_tampering_are_rejected():
    values = inputs()
    values["dispatch"]["lecture_review_policy"] = copy.deepcopy(values["dispatch"]["lecture_review_policy"])
    values["dispatch"]["lecture_review_policy"]["context_tokens"] += 1
    with pytest.raises(ValueError, match="dispatch"):
        validate_lecture_authority(**values)
