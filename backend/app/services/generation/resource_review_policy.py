"""Freeze and validate the generic resource-review strategy at submission boundaries.

``compat`` keeps every historical per-resource reviewer; ``resource_issue_v1``
routes the six text resources through the one shared closed loop.  The frozen
contract only depends on the policy models and injected settings; it never
imports engine-private functions.
"""

from app.models.reviews.resource_review_policy import (
    RESOURCE_ADAPTER_TYPES,
    RESOURCE_REVIEW_STRATEGIES,
    ResourceReviewPolicyV1,
    policy_hash,
    execution_identity_fields,
)
from app.models.shared.persistence import canonical_hash
from app.agents.resource_workflows.learning_documents.reviewing.resource_authority import (
    LEGACY_WORKFLOW_VERSIONS,
    RESOURCE_PRIVATE_KEYS,
    RESOURCE_IDENTITY_KEYS,
    RESOURCE_WORKFLOW_VERSION,
    _validate_frozen_fields,
)


def freeze_resource_review_policy(request, settings) -> dict:
    strategy = settings.resource_review_strategy
    if strategy not in RESOURCE_REVIEW_STRATEGIES:
        raise ValueError("unknown resource review strategy")
    if (strategy == "compat" or not request.include_review
            or not (set(request.resource_types) & set(RESOURCE_ADAPTER_TYPES))):
        return {}
    # M is frozen from the reviewer options active at creation, never raised here.
    policy = ResourceReviewPolicyV1(
        context_tokens=settings.resource_review_context_tokens,
        max_output_tokens=settings.llm_max_output_tokens,
        max_physical_attempts=settings.llm_max_attempts).model_dump(mode="json")
    return {"resource_review_contract_version": "1.1",
            **execution_identity_fields(settings.llm_model),
            "resource_review_policy": policy,
            "resource_review_policy_hash": policy_hash(policy)}


def resource_review_fields(source: dict) -> dict:
    if not (RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS).intersection(source):
        return {}
    return _validate_frozen_fields(source)


def resolve_resource_review_dispatch(snapshot: dict):
    """Return (base_workflow_version, frozen_resource_fields) for a snapshot."""
    version = snapshot.get("workflow_version")
    if version != RESOURCE_WORKFLOW_VERSION:
        if (version in LEGACY_WORKFLOW_VERSIONS and not (RESOURCE_PRIVATE_KEYS | RESOURCE_IDENTITY_KEYS).intersection(snapshot)
                and "base_workflow_version" not in snapshot and "resource_dispatch_hash" not in snapshot):
            return version, {}
        raise ValueError("unsupported frozen resource dispatch")
    fields = resource_review_fields(snapshot)
    if not fields or snapshot.get("base_workflow_version") not in LEGACY_WORKFLOW_VERSIONS:
        raise ValueError("resource dispatch fields missing")
    content = {key: value for key, value in snapshot.items() if key != "resource_dispatch_hash"}
    if snapshot.get("resource_dispatch_hash") != canonical_hash(content):
        raise ValueError("resource dispatch hash mismatch")
    return snapshot["base_workflow_version"], fields
