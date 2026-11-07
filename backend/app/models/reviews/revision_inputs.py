"""Server-private generation revision inputs (T46).

Two mutually exclusive generation-side revision inputs replace the mixed
``revision_feedback`` / ``resource_revision`` / ``lecture_revision`` fields that
were previously fed straight into the resource worker prompt:

* ``ResourceReviewRevisionInput`` (kind ``ordinary``) — the projection of one
  ordinary resource review, adapting either the new ``resource_issue_v1`` work
  order, the dedicated lecture revision, or an explicit ``compat`` reviewer
  feedback. It never carries Claim problems and never controls the Claim budget.
* ``ClaimReviewRevisionInput`` (kind ``claim``) — the targeted Claim-audit
  revision: for every bad factual Claim it carries the original ``claim_text``,
  the verbatim located ``source_text`` (pooled, never duplicated), the Judge
  verdict + reason, the Judge's direct evidence ids, and a shared per-unit
  context group.

These are private inputs, not a new model output schema. They reuse the existing
Claim/Judgement/Evidence identifiers and must not be exposed through HTTP, public
trace, SSE or the read-only checkpoint projection. The in-memory
``state.resource_revision`` / ``state.lecture_revision`` records stay unchanged:
they keep carrying parent-version validation and recheck tracking.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


REVISION_INPUT_SCHEMA_VERSION = "1.0"
REVISION_INPUT_ENVELOPE_VERSION = "revision-input-v1"
ORDINARY_KIND = "ordinary"
CLAIM_KIND = "claim"

# Client-supplied constraint keys that must be stripped at the state
# construction boundary and written back only by the server-side prepare /
# verified retry import. A client can never inject a generation revision input.
RESERVED_REVISION_INPUT_KEYS = frozenset({
    "generation_revision_inputs",
    "resource_review_revision",
    "claim_review_revision",
})


class _Private(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False,
                              allow_inf_nan=False)


class RevisionSourceSpanV1(_Private):
    """One pooled verbatim source span from the parent ``content_text``.

    Multiple problems may reference the same span; a span is de-duplicated by
    (parent resource, version, start, end, hash), while identical text at a
    different offset keeps its own span so location differences are preserved.
    """

    span_id: str = Field(min_length=1, max_length=80)
    source_text: str = Field(min_length=1, max_length=2000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    source_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _span_order(self) -> "RevisionSourceSpanV1":
        if self.source_end <= self.source_start:
            raise ValueError("source span is empty or reversed")
        return self


class ClaimRevisionProblemV1(_Private):
    """One bad factual Claim that must be revised, bound to a pooled span."""

    claim_id: str = Field(min_length=1, max_length=128)
    claim_index: int = Field(ge=0)
    claim_text: str = Field(min_length=1, max_length=4000)
    verdict: Literal["contradicted", "not_in_evidence"]
    reason: str = Field(min_length=1, max_length=4000)
    knowledge_point_id: str | None = Field(default=None, max_length=256)
    source_span_id: str = Field(min_length=1, max_length=80)
    # Judge's direct evidence ids. Always empty for ``not_in_evidence``; a
    # contradicted claim references frozen evidence from the resource pool.
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class ClaimRevisionContextGroupV1(_Private):
    """Claims fully inside one lossless Markdown unit share context; cross-unit
    claims each get their own group. ``context_text`` is omitted when the unit
    is absent or exceeds the 1600-character optional-context cap."""

    group_id: str = Field(min_length=1, max_length=80)
    unit_id: str = Field(min_length=1, max_length=80)
    context_text: str | None = Field(default=None, max_length=2000)
    problem_claim_ids: list[str] = Field(default_factory=list, max_length=128)


class ClaimRevisionEvidenceV1(_Private):
    """Readable projection of one frozen resource-scoped evidence item."""

    evidence_id: str = Field(min_length=1, max_length=128)
    source: str = Field(default="", max_length=1024)
    section: str = Field(default="", max_length=512)
    excerpt: str = Field(default="", max_length=10000)


class ClaimReviewRevisionInput(_Private):
    """Targeted Claim-audit revision requirement for one resource spec."""

    schema_version: Literal["1.0"] = REVISION_INPUT_SCHEMA_VERSION
    kind: Literal["claim"] = CLAIM_KIND
    revision_source: Literal["claim"] = "claim"
    input_version: Literal["1.0"] = "1.0"
    resource_spec_id: str = Field(min_length=1, max_length=128)
    parent_resource_id: str = Field(min_length=1, max_length=128)
    parent_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: list[str] = Field(default_factory=list, max_length=50)
    previous_text: str = Field(default="", max_length=500000)
    previous_structured_payload: dict | None = None
    spans: list[RevisionSourceSpanV1] = Field(default_factory=list, max_length=300)
    problems: list[ClaimRevisionProblemV1] = Field(default_factory=list, max_length=300)
    groups: list[ClaimRevisionContextGroupV1] = Field(default_factory=list, max_length=300)
    evidence: list[ClaimRevisionEvidenceV1] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _integrity(self) -> "ClaimReviewRevisionInput":
        if hashlib.sha256(self.previous_text.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("revision parent content hash mismatch")
        for span in self.spans:
            if (self.previous_text[span.source_start:span.source_end] != span.source_text
                    or hashlib.sha256(span.source_text.encode("utf-8")).hexdigest() != span.source_text_hash):
                raise ValueError("revision span does not match parent content")
        span_ids = {item.span_id for item in self.spans}
        if any(item.source_span_id not in span_ids for item in self.problems):
            raise ValueError("claim problem references an unknown source span")
        grouped = [claim_id for group in self.groups for claim_id in group.problem_claim_ids]
        problem_ids = {item.claim_id for item in self.problems}
        if len(grouped) != len(set(grouped)):
            raise ValueError("context groups contain a duplicate claim")
        if set(grouped) != problem_ids:
            raise ValueError("context groups must cover exactly all problems")
        if any(item.verdict == "not_in_evidence" and item.evidence_ids for item in self.problems):
            raise ValueError("not_in_evidence claim cannot cite evidence")
        return self


class ResourceReviewRevisionInput(_Private):
    """Ordinary-review revision requirement for one resource spec.

    ``issues`` / ``closed_issues`` are populated from the typed ``resource_issue_v1``
    work order or the dedicated lecture revision; ``feedback`` carries the compat
    reviewer feedback projection when no typed work order exists.
    """

    schema_version: Literal["1.0"] = REVISION_INPUT_SCHEMA_VERSION
    kind: Literal["ordinary"] = ORDINARY_KIND
    revision_source: Literal["ordinary", "compat"] = "ordinary"
    input_version: Literal["1.0"] = "1.0"
    resource_spec_id: str = Field(min_length=1, max_length=128)
    parent_resource_id: str | None = Field(default=None, max_length=128)
    parent_version: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    targets: list[str] = Field(default_factory=list, max_length=50)
    previous_text: str | None = Field(default=None, max_length=500000)
    previous_structured_payload: dict | None = None
    issues: list[dict] = Field(default_factory=list, max_length=300)
    closed_issues: list[dict] = Field(default_factory=list, max_length=300)
    unchanged: bool = False
    feedback: dict | None = None


__all__ = [
    "REVISION_INPUT_SCHEMA_VERSION",
    "REVISION_INPUT_ENVELOPE_VERSION",
    "ORDINARY_KIND",
    "CLAIM_KIND",
    "RESERVED_REVISION_INPUT_KEYS",
    "RevisionSourceSpanV1",
    "ClaimRevisionProblemV1",
    "ClaimRevisionContextGroupV1",
    "ClaimRevisionEvidenceV1",
    "ClaimReviewRevisionInput",
    "ResourceReviewRevisionInput",
]
