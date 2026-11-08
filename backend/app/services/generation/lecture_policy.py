"""Freeze and validate the private lecture strategy at submission boundaries."""
from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.shared.persistence import canonical_hash
from app.agents.resource_workflows.learning_documents.reviewing.lecture_authority import (
    CONTRACT_VERSIONS, PRIVATE_KEYS, LECTURE_WORKFLOW_VERSIONS, LEGACY_WORKFLOW_VERSIONS,
    _validate_frozen_fields,
)


def freeze_lecture_policy(request, settings):
    strategy = settings.lecture_review_strategy
    if strategy not in {"legacy_content_v2", *CONTRACT_VERSIONS}:
        raise ValueError("unknown lecture review strategy")
    if strategy == "legacy_content_v2" or not request.include_review or not ({"text", "讲义"} & set(request.resource_types)):
        return {}
    if strategy == "lecture_issue_v2":
        # M is frozen from the reviewer options active at creation, never raised here.
        policy = LectureReviewPolicyV2(
            context_tokens=settings.lecture_review_context_tokens,
            max_output_tokens=settings.llm_max_output_tokens,
            max_physical_attempts=settings.llm_max_attempts).model_dump(mode="json")
        contract_version = "2.0"
    else:
        policy = LectureReviewPolicyV1(context_tokens=settings.lecture_review_context_tokens,
                                       max_output_tokens=settings.llm_max_output_tokens).model_dump(mode="json")
        contract_version = "1.0"
    return {"lecture_review_contract_version": contract_version, "lecture_review_policy": policy,
            "lecture_review_policy_hash": canonical_hash(policy)}


def lecture_fields(source):
    if not PRIVATE_KEYS.intersection(source):
        return {}
    return _validate_frozen_fields(source)


def resolve_lecture_dispatch(snapshot):
    version = snapshot.get("workflow_version")
    if version not in LECTURE_WORKFLOW_VERSIONS:
        if version not in LEGACY_WORKFLOW_VERSIONS or PRIVATE_KEYS.intersection(snapshot) or "base_workflow_version" in snapshot or "lecture_dispatch_hash" in snapshot:
            raise ValueError("unsupported frozen lecture dispatch")
        return version, {}
    fields = lecture_fields(snapshot)
    if not fields or snapshot.get("base_workflow_version") not in LEGACY_WORKFLOW_VERSIONS:
        raise ValueError("lecture dispatch fields missing")
    if snapshot.get("lecture_dispatch_hash") != canonical_hash({k: v for k, v in snapshot.items() if k != "lecture_dispatch_hash"}):
        raise ValueError("lecture dispatch hash mismatch")
    return snapshot["base_workflow_version"], fields
