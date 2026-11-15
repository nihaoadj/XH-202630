"""Validate frozen lecture contracts at submission, execution and recovery boundaries."""

from __future__ import annotations

from app.models.generation.dispatch import (
    ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION, ESTIMATE_TEXT_WORKFLOW_VERSION,
    RESOURCE_RETRY_WORKFLOW_VERSION, TEXT_WORKFLOW_VERSION,
)
from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.shared.persistence import canonical_hash


LECTURE_WORKFLOW_VERSION = "learning_documents.lecture_issue.v1"
LECTURE_WORKFLOW_VERSION_V2 = "learning_documents.lecture_issue.v2"
LECTURE_WORKFLOW_VERSIONS = frozenset({LECTURE_WORKFLOW_VERSION, LECTURE_WORKFLOW_VERSION_V2})
# Contract version per selectable strategy. Legacy freezes nothing at all.
CONTRACT_VERSIONS = {"lecture_issue_v1": "1.0", "lecture_issue_v2": "2.0"}
POLICY_MODELS = {"1.0": LectureReviewPolicyV1, "2.0": LectureReviewPolicyV2}
WORKFLOW_VERSION_BY_CONTRACT = {"1.0": LECTURE_WORKFLOW_VERSION, "2.0": LECTURE_WORKFLOW_VERSION_V2}
STRATEGY_BY_CONTRACT = {"1.0": "lecture_issue_v1", "2.0": "lecture_issue_v2"}


def lecture_workflow_version(contract_version: str) -> str:
    try:
        return WORKFLOW_VERSION_BY_CONTRACT[contract_version]
    except KeyError:
        raise ValueError("unknown lecture review contract version") from None
LEGACY_WORKFLOW_VERSIONS = frozenset({
    TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION,
    ESTIMATE_TEXT_WORKFLOW_VERSION, ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION,
})
PRIVATE_KEYS = frozenset({"lecture_review_contract_version", "lecture_review_policy", "lecture_review_policy_hash"})


def _validate_frozen_fields(snapshot: dict) -> dict:
    if not PRIVATE_KEYS <= snapshot.keys():
        raise ValueError("lecture review frozen contract incomplete")
    version = snapshot["lecture_review_contract_version"]
    model = POLICY_MODELS.get(version)
    if model is None:
        raise ValueError("unknown lecture review contract version")
    data = snapshot["lecture_review_policy"]
    if not isinstance(data, dict) or set(data) != set(model.model_fields):
        raise ValueError("lecture review policy fields missing or unknown")
    policy = model.model_validate(data).model_dump(mode="json")
    if policy != data or canonical_hash(policy) != snapshot["lecture_review_policy_hash"]:
        raise ValueError("lecture review policy hash mismatch")
    return {key: snapshot[key] for key in PRIVATE_KEYS}


def validate_lecture_authority(*, request_snapshot: dict, request_hash: str,
                               created_event_request_hash: str, dispatch: dict | None = None,
                               checkpoint: dict | None = None) -> str:
    """Validate supplied authoritative records; never infer strategy from a checkpoint."""
    if (not isinstance(request_snapshot, dict) or not request_hash or
            canonical_hash(request_snapshot) != request_hash or created_event_request_hash != request_hash):
        raise ValueError("run creation snapshot or event hash mismatch")
    request_has_new_fields = bool(PRIVATE_KEYS & request_snapshot.keys())
    if dispatch is None:
        if not request_has_new_fields:
            if checkpoint is not None and PRIVATE_KEYS & checkpoint.keys():
                raise ValueError("legacy run has lecture policy checkpoint")
            return "legacy_content_v2"
    else:
        version = dispatch.get("workflow_version")
        if version in LEGACY_WORKFLOW_VERSIONS:
            if request_has_new_fields or PRIVATE_KEYS & dispatch.keys() or "base_workflow_version" in dispatch or "lecture_dispatch_hash" in dispatch:
                raise ValueError("legacy workflow contains lecture policy fragments")
            if checkpoint is not None and PRIVATE_KEYS & checkpoint.keys():
                raise ValueError("legacy run has lecture policy checkpoint")
            return "legacy_content_v2"
        if version not in LECTURE_WORKFLOW_VERSIONS or dispatch.get("base_workflow_version") not in LEGACY_WORKFLOW_VERSIONS:
            raise ValueError("unsupported lecture workflow version")
        content = {key: value for key, value in dispatch.items() if key != "lecture_dispatch_hash"}
        if dispatch.get("lecture_dispatch_hash") != canonical_hash(content):
            raise ValueError("dispatch contract hash mismatch")
        base = dispatch["base_workflow_version"]
        retry = "resource_retry_context" in dispatch
        estimate = bool(dispatch.get("claim_extraction_policy"))
        expected = (ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION if retry else ESTIMATE_TEXT_WORKFLOW_VERSION) if estimate else (
            RESOURCE_RETRY_WORKFLOW_VERSION if retry else TEXT_WORKFLOW_VERSION)
        if base != expected:
            raise ValueError("base workflow does not match claim/retry contract")
        if _validate_frozen_fields(dispatch) != _validate_frozen_fields(request_snapshot):
            raise ValueError("dispatch and run lecture contracts disagree")
    fields = _validate_frozen_fields(request_snapshot)
    if checkpoint is not None and _validate_frozen_fields(checkpoint) != fields:
        raise ValueError("checkpoint and run lecture contracts disagree")
    contract_version = fields["lecture_review_contract_version"]
    if dispatch is not None and dispatch.get("workflow_version") != lecture_workflow_version(contract_version):
        raise ValueError("lecture workflow version does not match the frozen contract")
    return STRATEGY_BY_CONTRACT[contract_version]
