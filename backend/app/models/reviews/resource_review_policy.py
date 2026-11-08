"""Frozen resource-review policy and pure snapshot validation (T44).

``ResourceReviewPolicyV1`` is the single frozen contract for the
``resource_issue_v1`` strategy.  It pins the actual reviewer model window,
physical attempt budget, the one-business-correction limit and the frozen
type->adapter/profile/schema/rubric/locator/hash/renderer registry version.

Nothing here imports the engine, agents, services, repositories or clients.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .resource_review import ResourceContract


# Frozen registry version.  Bumping any adapter profile/schema/rubric/locator/
# hash/renderer mapping requires a new policy version; it never changes silently.
TYPE_REGISTRY_VERSION = "resource-registry-v1"

RESOURCE_REVIEW_STRATEGIES = ("compat", "resource_issue_v1")

# Canonical type -> adapter identity frozen into the policy.  The adapter module
# must agree with this mapping; mismatch is rejected at freeze time.
RESOURCE_ADAPTER_TYPES = (
    "讲义", "实操指南", "分阶测试题", "案例分析", "复习清单", "个性化纠错训练包",
)


class ResourceReviewPolicyV1(ResourceContract):
    schema_version: Literal["1.0"] = "1.0"
    strategy: Literal["resource_issue_v1"] = "resource_issue_v1"
    contract_version: Literal["1.0"] = "1.0"
    initial_profile: Literal["resource_issue_initial_v1"] = "resource_issue_initial_v1"
    recheck_profile: Literal["resource_issue_recheck_v1"] = "resource_issue_recheck_v1"
    rubric_version: Literal["resource-rubric-v1"] = "resource-rubric-v1"
    normalization_version: Literal["crlf-lf-v1"] = "crlf-lf-v1"
    locator_version: Literal["resource-locator-v1"] = "resource-locator-v1"
    comparison_projection_version: Literal["comparison-projection-v1"] = "comparison-projection-v1"
    registry_version: Literal["resource-registry-v1"] = TYPE_REGISTRY_VERSION
    max_open_issues: Literal[24] = 24
    max_new_issues_per_review: Literal[12] = 12
    max_consecutive_unchanged: Literal[2] = 2
    coverage_threshold: Literal[0.8] = 0.8
    # Frozen from the reviewer options that were actually active at creation.
    max_physical_attempts: int = Field(ge=1, le=3)
    business_correction_limit: Literal[1] = 1
    context_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def window_has_input_space(self) -> "ResourceReviewPolicyV1":
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("review output reserve exhausts context window")
        return self


def policy_hash(policy: ResourceReviewPolicyV1 | dict) -> str:
    from app.models.shared.persistence import canonical_hash
    data = policy.model_dump(mode="json") if isinstance(policy, ResourceReviewPolicyV1) else policy
    return canonical_hash(data)


def validate_registry_mapping(registry: dict) -> None:
    """The frozen registry must cover exactly the six supported text types."""
    if set(registry) != set(RESOURCE_ADAPTER_TYPES):
        raise ValueError("resource review registry does not match the frozen type set")


class ResourceReviewExecutionIdentityV1(ResourceContract):
    """Execution identity is outside the sealed V1 policy to preserve old hashes."""
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())
    schema_version: Literal["1.0"] = "1.0"
    role: Literal["reviewer"] = "reviewer"
    model_name: str = Field(min_length=1)


def execution_identity_fields(model_name: str) -> dict:
    identity = ResourceReviewExecutionIdentityV1(model_name=model_name).model_dump(mode="json")
    return {"resource_review_identity": identity,
            "resource_review_identity_hash": policy_hash(identity)}


def validate_execution_identity(state: dict, gateway) -> None:
    """Refuse execution of unbound historical identities or a changed reviewer."""
    if state.get("resource_review_contract_version") != "1.1":
        raise ValueError("historical resource review identity is read-only; create a new run")
    identity = ResourceReviewExecutionIdentityV1.model_validate(state.get("resource_review_identity") or {})
    if policy_hash(identity.model_dump(mode="json")) != state.get("resource_review_identity_hash"):
        raise ValueError("resource review execution identity hash mismatch")
    if gateway.transport.model_name != identity.model_name:
        raise ValueError("resource reviewer model differs from frozen execution identity")
