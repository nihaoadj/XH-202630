"""Model-facing review schemas separated from the internal ledger records."""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, model_validator

from .resource_review import (
    ResourceContract,
    ResourceDimensionsV1,
    ResourceEvidenceRefV1,
    ResourceFindingV1,
    ResourceIssueV1,
    ResourceLocationV1,
    ResourceReopenV1,
    ResourceResolutionV1,
    ResourceReviewOutputV1,
    ResourceTargetCoverageV1,
)


class MarkdownModelLocationV3(ResourceContract):
    kind: Literal["paragraph", "root"]
    paragraph_id: str | None = None
    end_paragraph_id: str | None = None
    quote: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def valid_location(self) -> "MarkdownModelLocationV3":
        if self.kind == "paragraph" and self.paragraph_id is None:
            raise ValueError("paragraph location requires paragraph_id")
        if self.kind == "root" and any((self.paragraph_id, self.end_paragraph_id, self.quote)):
            raise ValueError("root location must be empty")
        return self


class MarkdownModelIssueV3(ResourceIssueV1):
    location: MarkdownModelLocationV3


class MarkdownModelTargetV3(ResourceTargetCoverageV1):
    location: MarkdownModelLocationV3 | None = None


class MarkdownModelResolutionV3(ResourceResolutionV1):
    current_location: MarkdownModelLocationV3 | None = None
    previous_location: MarkdownModelLocationV3 | None = None


class MarkdownModelReopenV3(ResourceReopenV1):
    current_location: MarkdownModelLocationV3


class MarkdownModelReviewOutputV3(ResourceReviewOutputV1):
    targets: list[MarkdownModelTargetV3] = Field(min_length=1)
    issues: list[MarkdownModelIssueV3] = Field(default_factory=list, max_length=300)
    resolutions: list[MarkdownModelResolutionV3] = Field(default_factory=list, max_length=300)
    reopen: list[MarkdownModelReopenV3] = Field(default_factory=list, max_length=300)


class MarkdownModelReviewInitialV3(MarkdownModelReviewOutputV3):
    pass


class MarkdownModelReviewRecheckV3(MarkdownModelReviewOutputV3):
    pass


LocationT = TypeVar("LocationT", ResourceLocationV1, MarkdownModelLocationV3)


class ModelIssueV4(ResourceContract, Generic[LocationT]):
    issue_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=64)
    severity: Literal["low", "medium", "high", "critical"]
    blocking: bool
    location: LocationT
    impact: str = Field(min_length=1, max_length=500)
    requirement: str = Field(min_length=1, max_length=1000)
    acceptance: str = Field(min_length=1, max_length=1000)
    path: Literal["add_from_evidence", "reorganize_existing", "remove_or_narrow", "synthetic_example",
                  "replace_or_drop_exercise", "evidence_insufficient"]
    evidence_refs: list[ResourceEvidenceRefV1] = Field(default_factory=list, max_length=24)
    teaching_rule_id: str | None = None
    executability: Literal["executable", "evidence_insufficient"]
    rationale: str = Field(min_length=1, max_length=1000)
    finding_keys: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_issue_content(self):
        # Keep the existing blocking, evidence and revision constraints at the
        # gateway boundary, where schema errors use the bounded repair path.
        ResourceIssueV1.model_validate(model_issue_record(self.model_dump(mode="json")))
        return self


class ContentModelIssueV4(ModelIssueV4[LocationT], Generic[LocationT]):
    dimension: Literal["factual_evidence", "difficulty", "self_contained"]


class CoverageModelIssueV4(ModelIssueV4[LocationT], Generic[LocationT]):
    dimension: Literal["coverage"]
    affected_target_ids: list[str] = Field(default_factory=list, max_length=12)


def model_issue_record(issue: dict) -> dict:
    """Metadata for a model issue in the internal ledger."""
    return {**issue, "origin": "model_review", "criteria_version": 1,
            "blocking_rule": f"model_{issue['dimension']}_v1" if issue["blocking"] else None}


class ModelReviewV4(ResourceContract):
    dimensions: ResourceDimensionsV1
    targets: list[ResourceTargetCoverageV1] = Field(min_length=1)
    hallucination_score: float = Field(ge=0, le=1)
    issues: list[Annotated[
        ContentModelIssueV4[ResourceLocationV1] | CoverageModelIssueV4[ResourceLocationV1],
        Field(discriminator="dimension"),
    ]] = Field(default_factory=list, max_length=300)
    resolutions: list[ResourceResolutionV1] = Field(default_factory=list, max_length=300)
    reopen: list[ResourceReopenV1] = Field(default_factory=list, max_length=300)
    omitted_blocking_issues: bool
    findings: list[ResourceFindingV1] = Field(default_factory=list, max_length=300)


class MarkdownModelReviewV4(ModelReviewV4):
    targets: list[MarkdownModelTargetV3] = Field(min_length=1)
    issues: list[Annotated[
        ContentModelIssueV4[MarkdownModelLocationV3] | CoverageModelIssueV4[MarkdownModelLocationV3],
        Field(discriminator="dimension"),
    ]] = Field(default_factory=list, max_length=300)
    resolutions: list[MarkdownModelResolutionV3] = Field(default_factory=list, max_length=300)
    reopen: list[MarkdownModelReopenV3] = Field(default_factory=list, max_length=300)
