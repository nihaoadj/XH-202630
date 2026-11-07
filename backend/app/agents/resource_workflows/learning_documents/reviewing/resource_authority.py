"""Validate frozen generic resource-review contracts at submission/execution/recovery.

Mirrors the lecture authority: the new ``resource_issue_v1`` strategy freezes its
own private keys, workflow version and dispatch hash, and a legacy/compat run
must never carry those keys.  Old tasks are never upgraded in place.
"""

from __future__ import annotations

from app.models.generation.dispatch import (
    ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION, ESTIMATE_TEXT_WORKFLOW_VERSION,
    RESOURCE_RETRY_WORKFLOW_VERSION, TEXT_WORKFLOW_VERSION,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, ResourceReviewExecutionIdentityV1, policy_hash
from app.models.shared.persistence import canonical_hash


RESOURCE_WORKFLOW_VERSION = "learning_documents.resource_issue.v1"
RESOURCE_CONTRACT_VERSION = "1.1"
RESOURCE_IDENTITY_KEYS = frozenset({"resource_review_identity", "resource_review_identity_hash"})
RESOURCE_STRATEGY = "resource_issue_v1"

RESOURCE_PRIVATE_KEYS = frozenset({
    "resource_review_contract_version", "resource_review_policy", "resource_review_policy_hash",
})

LEGACY_WORKFLOW_VERSIONS = frozenset({
    TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION,
    ESTIMATE_TEXT_WORKFLOW_VERSION, ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION,
})


def resource_workflow_version(contract_version: str) -> str:
    if contract_version not in {"1.0", RESOURCE_CONTRACT_VERSION}:
        raise ValueError("unknown resource review contract version")
    return RESOURCE_WORKFLOW_VERSION


def _validate_frozen_fields(snapshot: dict) -> dict:
    if not RESOURCE_PRIVATE_KEYS <= snapshot.keys():
        raise ValueError("resource review frozen contract incomplete")
    version = snapshot["resource_review_contract_version"]
    if version not in {"1.0", RESOURCE_CONTRACT_VERSION}:
        raise ValueError("unknown resource review contract version")
    data = snapshot["resource_review_policy"]
    if not isinstance(data, dict) or set(data) != set(ResourceReviewPolicyV1.model_fields):
        raise ValueError("resource review policy fields missing or unknown")
    policy = ResourceReviewPolicyV1.model_validate(data).model_dump(mode="json")
    if policy != data or policy_hash(policy) != snapshot["resource_review_policy_hash"]:
        raise ValueError("resource review policy hash mismatch")
    fields = {key: snapshot[key] for key in RESOURCE_PRIVATE_KEYS}
    if version == "1.1":
        if not RESOURCE_IDENTITY_KEYS <= snapshot.keys():
            raise ValueError("resource execution identity missing")
        identity = ResourceReviewExecutionIdentityV1.model_validate(snapshot["resource_review_identity"])
        if identity.model_dump(mode="json") != snapshot["resource_review_identity"] or policy_hash(identity.model_dump(mode="json")) != snapshot["resource_review_identity_hash"]:
            raise ValueError("resource execution identity hash mismatch")
        fields.update({key: snapshot[key] for key in RESOURCE_IDENTITY_KEYS})
    elif RESOURCE_IDENTITY_KEYS & snapshot.keys():
        raise ValueError("historical resource contract contains identity fragments")
    return fields


def validate_resource_authority(*, request_snapshot: dict, request_hash: str,
                                created_event_request_hash: str, dispatch: dict | None = None,
                                checkpoint: dict | None = None) -> str:
    """Validate supplied authoritative records; never infer strategy from a checkpoint."""
    if (not isinstance(request_snapshot, dict) or not request_hash or
            canonical_hash(request_snapshot) != request_hash or created_event_request_hash != request_hash):
        raise ValueError("run creation snapshot or event hash mismatch")
    request_has_new_fields = bool((RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS) & request_snapshot.keys())
    if dispatch is None:
        if not request_has_new_fields:
            if checkpoint is not None and (RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS) & checkpoint.keys():
                raise ValueError("legacy run has resource policy checkpoint")
            return "compat"
    else:
        version = dispatch.get("workflow_version")
        if version in LEGACY_WORKFLOW_VERSIONS:
            if (request_has_new_fields or (RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS) & dispatch.keys()
                    or "base_workflow_version" in dispatch or "resource_dispatch_hash" in dispatch):
                raise ValueError("legacy workflow contains resource policy fragments")
            if checkpoint is not None and (RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS) & checkpoint.keys():
                raise ValueError("legacy run has resource policy checkpoint")
            return "compat"
        if version != RESOURCE_WORKFLOW_VERSION or dispatch.get("base_workflow_version") not in LEGACY_WORKFLOW_VERSIONS:
            raise ValueError("unsupported resource workflow version")
        content = {key: value for key, value in dispatch.items() if key != "resource_dispatch_hash"}
        if dispatch.get("resource_dispatch_hash") != canonical_hash(content):
            raise ValueError("resource dispatch contract hash mismatch")
        if _validate_frozen_fields(dispatch) != _validate_frozen_fields(request_snapshot):
            raise ValueError("dispatch and run resource contracts disagree")
    fields = _validate_frozen_fields(request_snapshot)
    if checkpoint is not None and _validate_frozen_fields(checkpoint) != fields:
        raise ValueError("checkpoint and run resource contracts disagree")
    if dispatch is not None and dispatch.get("workflow_version") != resource_workflow_version(fields["resource_review_contract_version"]):
        raise ValueError("resource workflow version does not match the frozen contract")
    return RESOURCE_STRATEGY
