"""Deterministic evidence epochs shared by audit production and replay.

A review ledger owns exactly one frozen evidence context.  When a child version
is generated from an authorised supplement scope the evidence snapshot changes,
so a new ledger epoch begins instead of rewriting the predecessor.  The new
epoch records an explicit, hash-bound carry-over of every still-open issue and
the stop counter, which is what makes an evidence change auditable rather than
a silent reset.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.shared.persistence import canonical_hash

_HASH = r"^[0-9a-f]{64}$"


class EvidenceContextCarryOverV1(BaseModel):
    """Audited transition fact between two ledger epochs of one resource spec.

    ``open_issues`` stores the predecessor's full issue-history records, not just
    identifiers: the new epoch must reuse the original definition, acceptance
    and introduced step/version verbatim, otherwise a rewritten acceptance
    criterion could close an old defect without fixing it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["1.0"] = "1.0"
    release_reason: Literal["evidence_context_changed"] = "evidence_context_changed"
    previous_ledger_hash: str = Field(pattern=_HASH)
    previous_context_id: str = Field(pattern=_HASH)
    previous_evidence_snapshot_hash: str = Field(pattern=_HASH)
    previous_comparison_hash: str = Field(pattern=_HASH)
    previous_resource_id: str = Field(min_length=1)
    previous_version: int = Field(ge=1)
    previous_content_hash: str = Field(pattern=_HASH)
    open_issues: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    open_issue_hash: str = Field(pattern=_HASH)
    # Carried verbatim so an evidence change cannot hand back a fresh
    # "no progress" allowance.
    consecutive_unchanged: int = Field(ge=0)

    @model_validator(mode="after")
    def issue_digest_matches(self) -> "EvidenceContextCarryOverV1":
        if canonical_hash({"open_issues": self.open_issues}) != self.open_issue_hash:
            raise ValueError("carry-over issue digest mismatch")
        identifiers = [(item.get("issue") or {}).get("issue_id") for item in self.open_issues]
        if any(not isinstance(item, str) or not item for item in identifiers):
            raise ValueError("carry-over issue identity missing")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("carry-over duplicate issue identity")
        if any(item.get("status") != "open" for item in self.open_issues):
            raise ValueError("carry-over may only carry open issues")
        return self


def _field(binding, key: str):
    return binding[key] if isinstance(binding, dict) else getattr(binding, key)


def context_id(binding) -> str:
    """Stable identity of one frozen evidence context."""

    return canonical_hash({key: _field(binding, key) for key in (
        "run_id", "resource_spec_id", "lineage_id", "evidence_snapshot_hash",
    )})


def context_fields(previous_binding, current_binding) -> dict[str, str | None]:
    """Context fields for a binding that continues or replaces ``previous``.

    A same-context observation inherits the predecessor fields verbatim (a
    legacy ledger without epoch fields stays legacy), while a changed evidence
    snapshot starts a new context bound to the predecessor context identity.
    """

    if previous_binding is None:
        return {"evidence_context_id": context_id(current_binding),
                "parent_evidence_context_hash": None}
    if _field(previous_binding, "evidence_snapshot_hash") == _field(current_binding, "evidence_snapshot_hash"):
        return {
            "evidence_context_id": _field(previous_binding, "evidence_context_id"),
            "parent_evidence_context_hash": _field(previous_binding, "parent_evidence_context_hash"),
        }
    return {"evidence_context_id": context_id(current_binding),
            "parent_evidence_context_hash": context_id(previous_binding)}


def validate_context_transition(previous, current) -> None:
    """Reject a binding whose epoch fields do not describe its predecessor."""

    ident = _field(current, "evidence_context_id")
    parent = _field(current, "parent_evidence_context_hash")
    if ident is None or parent is None and previous is None:
        if ident is not None:
            raise ValueError("evidence context identity requires a predecessor")
        if parent is not None:
            raise ValueError("evidence context parent requires an identity")
        if previous is not None and _field(previous, "evidence_context_id") is not None:
            raise ValueError("evidence context fields cannot be dropped mid-ledger")
        return
    if ident != context_id(current):
        raise ValueError("evidence context identity mismatch")
    if previous is None:
        raise ValueError("evidence context parent requires a predecessor")
    if _field(previous, "evidence_snapshot_hash") == _field(current, "evidence_snapshot_hash"):
        if ident != _field(previous, "evidence_context_id"):
            raise ValueError("evidence context changed without new epoch")
        if parent != _field(previous, "parent_evidence_context_hash"):
            raise ValueError("evidence context parent changed inside one epoch")
        return
    if parent != context_id(previous):
        raise ValueError("evidence context transition is not bound to its predecessor")


def build_carry_over(ledger, *, history_model) -> EvidenceContextCarryOverV1:
    """Build the transition fact for ``ledger``'s successor epoch."""

    binding = ledger.binding
    open_issues = [item.model_dump(mode="json") for item in ledger.issues if item.status == "open"]
    for item in open_issues:
        history_model.model_validate(item)
    previous_context = _field(binding, "evidence_context_id") or context_id(binding)
    return EvidenceContextCarryOverV1(
        previous_ledger_hash=canonical_hash(ledger.model_dump(mode="json")),
        previous_context_id=previous_context,
        previous_evidence_snapshot_hash=_field(binding, "evidence_snapshot_hash"),
        previous_comparison_hash=ledger.observations[-1].comparison_hash,
        previous_resource_id=_field(binding, "resource_id"),
        previous_version=_field(binding, "version"),
        previous_content_hash=_field(binding, "content_hash")
        if hasattr(binding, "content_hash") else _field(binding, "artifact_exact_hash"),
        open_issues=open_issues,
        open_issue_hash=canonical_hash({"open_issues": open_issues}),
        consecutive_unchanged=ledger.observations[-1].consecutive_unchanged,
    )


def validate_carry_over(carry_over: EvidenceContextCarryOverV1, *, binding, previous_ledger,
                        history_model) -> list:
    """Validate a carry-over against the immutable predecessor ledger."""

    if _field(binding, "evidence_snapshot_hash") == carry_over.previous_evidence_snapshot_hash:
        raise ValueError("carry-over does not change the evidence context")
    if carry_over.previous_ledger_hash != canonical_hash(previous_ledger.model_dump(mode="json")):
        raise ValueError("carry-over predecessor ledger hash mismatch")
    if carry_over.previous_version != _field(previous_ledger.binding, "version"):
        raise ValueError("carry-over predecessor version mismatch")
    if _field(binding, "version") != carry_over.previous_version + 1:
        raise ValueError("carry-over version is not the direct successor")
    if carry_over.previous_resource_id != _field(previous_ledger.binding, "resource_id"):
        raise ValueError("carry-over predecessor resource mismatch")
    expected_open = [item.model_dump(mode="json") for item in previous_ledger.issues
                     if item.status == "open"]
    if expected_open != carry_over.open_issues:
        raise ValueError("carry-over does not carry the predecessor open issues verbatim")
    if carry_over.consecutive_unchanged != previous_ledger.observations[-1].consecutive_unchanged:
        raise ValueError("carry-over stop counter mismatch")
    return [history_model.model_validate(item) for item in carry_over.open_issues]


__all__ = [
    "EvidenceContextCarryOverV1",
    "build_carry_over",
    "context_fields",
    "context_id",
    "validate_carry_over",
    "validate_context_transition",
]
