"""Server-owned frozen context for retrying one text resource in a new Run."""
from __future__ import annotations

from typing import Any, Literal
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.knowledge.knowledge import EvidenceAllocation, RESOURCE_AWARE_STRATEGY
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.agent_contracts import ResourceSpec
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash
from app.models.reviews.claim_evidence_retrieval import ClaimReviewEvidenceSetV1
from app.models.reviews.evidence_lineage import evidence_from_snapshot, evidence_item_hash


class RetryEvidenceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    resource_version: int = Field(ge=1)


class RetrySupplementContext(BaseModel):
    """Verified source grants; new runs import snapshots, never old verdicts."""
    model_config = ConfigDict(extra="forbid")
    lineage: list[RetryEvidenceIdentity] = Field(min_length=1, max_length=100)
    scopes: list[ClaimReviewEvidenceSetV1] = Field(min_length=1, max_length=100)
    evidence: list[PersistedEvidenceSnapshot] = Field(min_length=1, max_length=16)

    def validate_source(self, *, run_id, knowledge_base_id, parent, base_ids):
        identities = {(item.resource_id, item.resource_version) for item in self.lineage}
        if parent is None or (parent.resource_id, parent.version) not in identities:
            raise ValueError("retry supplement parent missing")
        allowed, hashes = set(), {}
        for scope in self.scopes:
            if (scope.run_id != run_id or scope.purpose != "generation"
                    or (scope.resource_id, scope.resource_version) not in identities):
                raise ValueError("retry supplement grant mismatch")
            for ident in scope.added_evidence_ids:
                value = scope.snapshot_hashes[ident]
                if ident in hashes and hashes[ident] != value:
                    raise ValueError("retry supplement grants conflict")
                hashes[ident] = value
                allowed.add(ident)
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)) or set(ids) != allowed - set(base_ids):
            raise ValueError("retry supplement snapshots differ from grants")
        for item in self.evidence:
            if (item.run_id != run_id or item.knowledge_base_id != knowledge_base_id
                    or evidence_item_hash(evidence_from_snapshot(item)) != hashes[item.evidence_id]):
                raise ValueError("retry supplement snapshot mismatch")


class ResourceRetryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    source_run_id: str = Field(min_length=1)
    source_spec_id: str = Field(min_length=1)
    source_checkpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner: LearnerProfile
    request: GenerateRequest
    diagnosis: dict[str, Any]
    learning_plan: dict[str, Any]
    spec: ResourceSpec
    evidence: list[PersistedEvidenceSnapshot] = Field(min_length=1, max_length=20)
    query_texts: dict[str, str] = Field(default_factory=dict)
    evidence_allocation: EvidenceAllocation | None = None
    retrieval_strategy_version: str
    retrieval_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_resource: LearningResource | None = None
    revision_feedback: dict[str, Any] = Field(default_factory=dict)
    supplement_context: RetrySupplementContext | None = None
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_snapshot(cls, value: dict) -> "ResourceRetryContext":
        # SourceLocator intentionally validates enums strictly for Python
        # objects; persisted JSON must use the JSON validation path.
        return cls.model_validate_json(json.dumps(value, ensure_ascii=False))

    @model_validator(mode="after")
    def validate_binding(self):
        if canonical_hash(self.model_dump(mode="json", exclude={"context_hash"})) != self.context_hash:
            raise ValueError("resource retry context hash mismatch")
        if (self.request.learner_id != self.learner.learner_id
                or self.request.resource_types != [self.spec.resource_type]
                or self.spec.resource_spec_id != self.source_spec_id):
            raise ValueError("resource retry input scope mismatch")
        kb = self.request.knowledge_base_id or self.learner.knowledge_base_id
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)) or any(
            item.run_id != self.source_run_id or item.knowledge_base_id != kb
            or item.config_hash != self.retrieval_config_hash for item in self.evidence
        ) or not set(self.spec.evidence_ids) <= set(ids):
            raise ValueError("resource retry evidence scope mismatch")
        if self.retrieval_strategy_version == RESOURCE_AWARE_STRATEGY:
            allocation = self.evidence_allocation
            if (allocation is None or allocation.evidence_ids != ids
                    or allocation.config_hash != self.retrieval_config_hash
                    or allocation.available_ids(self.spec.resource_type) != self.spec.evidence_ids):
                raise ValueError("resource retry allocation scope mismatch")
            for evidence_id in self.spec.evidence_ids:
                hashes = allocation.evidence_query_hashes.get(evidence_id, [])
                if not any(binding.resource_type in {None, self.spec.resource_type}
                           for query in hashes for binding in allocation.query_bindings.get(query, [])):
                    raise ValueError("selected evidence lacks applicable query binding")
        elif (self.retrieval_strategy_version != "legacy" or self.evidence_allocation is not None
              or ids != self.spec.evidence_ids):
            raise ValueError("unsupported or inconsistent legacy retry context")
        if self.source_resource is not None and (
            self.source_resource.run_id != self.source_run_id
            or self.source_resource.resource_spec_id != self.source_spec_id
            or self.source_resource.learner_id != self.learner.learner_id
            or self.source_resource.resource_type != self.spec.resource_type
            or self.source_resource.resource_family_id != self.spec.resource_family_id
            or self.source_resource.representation != "text"
        ):
            raise ValueError("resource retry parent scope mismatch")
        if self.supplement_context is not None:
            self.supplement_context.validate_source(
                run_id=self.source_run_id, knowledge_base_id=kb, parent=self.source_resource,
                base_ids=self.spec.evidence_ids,
            )
            if len(self.spec.evidence_ids) + len(self.supplement_context.evidence) > 20:
                raise ValueError("retry frozen evidence exceeds limit")
        return self
