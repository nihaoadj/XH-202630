"""Append-only V1 generic resource observations (T44).

One shared ledger for the six text resources.  Model-origin and program-gate
observations share the same identity, parent and replay rules; the only
difference is that a program-gate observation records a deterministic gate
failure with zero semantic calls, while a model observation carries the frozen
semantic output and the derived decision.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.models.reviews.resource_review import (
    ResourceIssueHistoryV1,
    ResourceLedgerV1,
    ResourceObservationV1,
    ResourceProgramGateResultV1,
    ResourceReviewBindingV1,
    ResourceReviewOutputV1,
    model_issue_id,
    program_issue_id,
)
from app.models.reviews.evidence_context import EvidenceContextCarryOverV1, validate_carry_over
from app.models.shared.persistence import canonical_hash

from .adapters.base import ResourceMaterial
from .decisions import derive_decision
from .validation import ValidationError, require, validate_resource_review


def _check_temp_ids(output: ResourceReviewOutputV1, previous: ResourceLedgerV1 | None) -> None:
    raw_ids = [item.issue_id for item in output.issues]
    require(len(set(raw_ids)) == len(raw_ids), "ISSUE_ID_DUPLICATED", "issues",
            "temporary issue identifiers must be unique")
    existing = {item.issue.issue_id for item in previous.issues} if previous is not None else set()
    require(not (set(raw_ids) & existing), "ISSUE_ID_COLLISION", "issues",
            "a new issue cannot reuse an existing identifier")


def _freeze_previous(previous: ResourceLedgerV1 | None, binding: ResourceReviewBindingV1,
                     step_id: str, carry_over=None) -> tuple[list[ResourceIssueHistoryV1], int, object]:
    if previous is None:
        if carry_over is not None:
            raise ValueError("carry-over requires its predecessor ledger")
        return [], 0, None
    old = previous.binding
    for key in ("run_id", "resource_spec_id", "lineage_id",
                "policy_hash", "resource_type"):
        if getattr(old, key) != getattr(binding, key):
            raise ValueError("ledger resource or frozen context mismatch")
    if binding.version != old.version + 1:
        raise ValueError("ledger parent version mismatch")
    if len({entry.step_id for entry in previous.observations}) != len(previous.observations):
        raise ValueError("ledger duplicate observation step")
    if old.evidence_snapshot_hash != binding.evidence_snapshot_hash:
        if carry_over is None:
            raise ValueError("ledger resource or frozen context mismatch")
        carried = validate_carry_over(
            carry_over, binding=binding, previous_ledger=previous,
            history_model=ResourceIssueHistoryV1)
        if carry_over.previous_comparison_hash != previous.observations[-1].comparison_hash:
            raise ValueError("carry-over predecessor comparison hash mismatch")
        return carried, carry_over.consecutive_unchanged, carry_over
    if carry_over is not None:
        raise ValueError("carry-over requires a changed evidence context")
    return list(previous.issues), previous.observations[-1].consecutive_unchanged, previous.carry_over


def _char_delta(parent_text: str | None, text: str) -> tuple[int, int]:
    if parent_text is None:
        return 0, 0
    added = removed = 0
    for tag, start_a, end_a, start_b, end_b in SequenceMatcher(
            a=parent_text, b=text, autojunk=False).get_opcodes():
        if tag != "equal":
            added += end_b - start_b
            removed += end_a - start_a
    return added, removed


def append_model_observation_v1(
    *,
    previous: ResourceLedgerV1 | None,
    binding: ResourceReviewBindingV1,
    step_id: str,
    output: ResourceReviewOutputV1,
    material: ResourceMaterial,
    adapter,
    parent_text: str | None,
    parent_comparison_hash: str | None,
    revision_kind: str = "ordinary",
    coverage_threshold: float = 0.8,
    max_consecutive_unchanged: int = 2,
    gate: ResourceProgramGateResultV1 | None = None,
    parent_material=None,
    carry_over: EvidenceContextCarryOverV1 | None = None,
) -> ResourceLedgerV1:
    """Return a new ledger with one model observation; callers persist atomically."""
    if revision_kind not in {"ordinary", "claim"}:
        raise ValueError("unknown resource revision kind")
    if not step_id:
        raise ValidationError("BINDING_MISMATCH", "step_id", "observation step id missing")
    if output.binding != binding:
        raise ValidationError("BINDING_MISMATCH", "binding",
                              "observation does not belong to the bound resource")
    if material.artifact_exact_hash != binding.artifact_exact_hash:
        raise ValidationError("BINDING_MISMATCH", "binding.artifact_exact_hash",
                              "bound content does not match the frozen artifact")
    if previous is not None:
        require(parent_material is not None and parent_material.artifact_exact_hash == previous.binding.artifact_exact_hash,
                "BINDING_MISMATCH", "parent_material", "parent material does not match the previous ledger")
        require(parent_text == parent_material.text
                and parent_comparison_hash == previous.binding.comparison_hash,
                "BINDING_MISMATCH", "parent_material", "parent text or comparison hash mismatch")
    _check_temp_ids(output, previous)

    histories, count, carried = _freeze_previous(previous, binding, step_id, carry_over)
    epoch_start = previous is not None and carry_over is not None
    if previous is not None and any(entry.step_id == step_id for entry in previous.observations):
        # Idempotent replay: the same step may only produce one observation.
        raise ValueError("observation replay conflict")

    old_open = tuple(item.issue for item in histories
                     if item.status == "open" and item.issue.origin == "model_review")
    old_closed = tuple(item.issue for item in histories
                       if item.status == "closed" and item.issue.origin == "model_review")

    result = validate_resource_review(
        output=output, binding=binding, material=material, adapter=adapter,
        previous_comparison_hash=parent_comparison_hash,
        old_open=old_open, old_closed=old_closed, parent_material=parent_material)

    ordered = sorted(enumerate(output.issues),
                     key=lambda pair: (pair[1].location.unit_id or pair[1].location.paragraph_id or "", pair[0]))
    new_issues = [item.model_copy(update={"issue_id": model_issue_id(
        run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
        lineage_id=binding.lineage_id, step_id=step_id, ordinal=number)})
        for number, (_, item) in enumerate(ordered, 1)]
    normalized = output.model_copy(update={"issues": new_issues})
    digest = canonical_hash(normalized.model_dump(mode="json"))

    unchanged = result.unchanged
    consecutive = count if revision_kind == "claim" else (count + 1 if unchanged else 0)
    decision = derive_decision(
        open_issues=result.open_issues, dimensions_pass=result.dimensions_pass,
        coverage_rate=result.coverage_rate, unchanged=unchanged,
        consecutive_unchanged=consecutive, coverage_threshold=coverage_threshold,
        max_consecutive_unchanged=max_consecutive_unchanged)

    resolutions = {item.issue_id: item.result for item in normalized.resolutions}
    reopened = {item.issue_id for item in normalized.reopen}
    closed_program = set(gate.resolved_program_issues) if gate is not None else set()
    updated: list[ResourceIssueHistoryV1] = []
    for item in histories:
        status = item.status
        if item.issue.origin == "program_gate" and item.issue.issue_id in closed_program:
            status = "closed"
        if item.issue.origin == "model_review":
            if resolutions.get(item.issue.issue_id) in {"fixed", "false_positive"}:
                status = "closed"
            if item.issue.issue_id in reopened:
                status = "open"
        updated.append(item.model_copy(update={"status": status}))
    updated.extend(ResourceIssueHistoryV1(issue=item, introduced_step_id=step_id,
                   introduced_version=binding.version, status="open" if item.blocking else "closed")
                   for item in new_issues)

    added, removed = _char_delta(parent_text, material.text)
    observation = ResourceObservationV1(
        origin="model_review", step_id=step_id, binding=binding, output_hash=digest,
        comparison_hash=material.comparison_hash,
        parent_content_hash=previous.binding.artifact_exact_hash if previous is not None else None,
        revision_kind=revision_kind, unchanged=unchanged, consecutive_unchanged=consecutive,
        characters_added=added, characters_removed=removed, gate=gate, output=normalized,
        coverage_rate=result.coverage_rate, decision=decision)
    return ResourceLedgerV1(binding=binding, issues=updated, carry_over=carried,
                            observations=[*([] if epoch_start else (previous.observations if previous else [])), observation])


def append_program_gate_observation_v1(
    *,
    previous: ResourceLedgerV1 | None,
    binding: ResourceReviewBindingV1,
    step_id: str,
    gate: ResourceProgramGateResultV1,
    material: ResourceMaterial,
    parent_comparison_hash: str | None,
    carry_over: EvidenceContextCarryOverV1 | None = None,
) -> ResourceLedgerV1:
    """Record a deterministic gate failure with zero semantic calls.

    The observation carries the gate result and the resulting program-origin
    issues; model-origin open issues are carried forward verbatim and are never
    reported fixed by a gate.
    """
    if gate.passed:
        raise ValueError("a passed gate must be folded into the model observation")
    if not step_id:
        raise ValidationError("BINDING_MISMATCH", "step_id", "observation step id missing")
    if material.artifact_exact_hash != binding.artifact_exact_hash:
        raise ValidationError("BINDING_MISMATCH", "binding.artifact_exact_hash",
                              "bound content does not match the frozen artifact")
    histories, count, carried = _freeze_previous(previous, binding, step_id, carry_over)
    epoch_start = previous is not None and carry_over is not None
    if previous is not None and any(entry.step_id == step_id for entry in previous.observations):
        raise ValueError("observation replay conflict")

    # The gate migration must be complete against the prior program issues.
    prior_program_open = [item.issue for item in histories
                          if item.status == "open" and item.issue.origin == "program_gate"]
    expected_migration = set(gate.resolved_program_issues) | set(gate.still_open_program_issues)
    require(expected_migration == {item.issue_id for item in prior_program_open},
            "BINDING_MISMATCH", "gate", "program issue migration is incomplete")
    # Carry forward every open model issue verbatim.
    prior_model_open = {item.issue.issue_id for item in histories
                        if item.status == "open" and item.issue.origin == "model_review"}
    require(prior_model_open == set(gate.carry_forward_model_issues),
            "BINDING_MISMATCH", "gate", "model issue carry-forward is incomplete")
    require(len(gate.new_issues) == len(gate.keys), "BINDING_MISMATCH", "gate",
            "gate keys and new issues disagree")
    for key, issue in zip(gate.keys, gate.new_issues):
        expected_id = program_issue_id(run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
                                       gate_rule_id=key.gate_rule_id, scope_locator=key.scope_locator,
                                       failure_code=key.failure_code)
        require(issue.issue_id == expected_id, "BINDING_MISMATCH", "gate.new_issues",
                "program issue identity mismatch")

    resolved = set(gate.resolved_program_issues)
    updated: list[ResourceIssueHistoryV1] = []
    for item in histories:
        status = item.status
        if item.issue.origin == "program_gate" and item.issue.issue_id in resolved:
            status = "closed"
        updated.append(item.model_copy(update={"status": status}))
    existing_ids = {item.issue.issue_id for item in updated}
    failing_ids = {item.issue_id for item in gate.new_issues}
    updated = [item.model_copy(update={"status": "open"}) if item.issue.issue_id in failing_ids else item
               for item in updated]
    updated.extend(ResourceIssueHistoryV1(issue=item, introduced_step_id=step_id,
                   introduced_version=binding.version, status="open")
                   for item in gate.new_issues if item.issue_id not in existing_ids)

    unchanged = parent_comparison_hash is not None and material.comparison_hash == parent_comparison_hash
    observation = ResourceObservationV1(
        origin="program_gate", step_id=step_id, binding=binding, output_hash=None,
        comparison_hash=material.comparison_hash,
        parent_content_hash=previous.binding.artifact_exact_hash if previous is not None else None,
        revision_kind="ordinary", unchanged=unchanged, consecutive_unchanged=count,
        characters_added=0, characters_removed=0, gate=gate, output=None,
        coverage_rate=None, decision=None)
    return ResourceLedgerV1(binding=binding, issues=updated, carry_over=carried,
                            observations=[*([] if epoch_start else (previous.observations if previous else [])), observation])


def replay_resource_ledger(data: dict) -> ResourceLedgerV1:
    """Validate and rebuild a ledger from its persisted payload."""
    return ResourceLedgerV1.model_validate(data)
