"""Append-only V2 lecture observations.

Same identity, parent and replay rules as V1.  The only semantic addition is the
program-derived ``coverage_rate`` stored next to the model output, so a replay
recomputes it instead of trusting a second model summary.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.models.reviews.evidence_context import (
    EvidenceContextCarryOverV1,
    validate_carry_over,
)
from app.models.reviews.lecture_review import LectureReviewBindingV1
from app.models.reviews.lecture_review_v2 import (
    LectureIssueHistoryV2,
    LectureLedgerV2,
    LectureObservationV2,
    LectureReviewOutputV2,
    derived_coverage_rate,
)
from app.models.shared.persistence import canonical_hash

from .lecture_contract import comparison_hash, text_hash
from .lecture_contract_v2 import issue_id_v2, validate_lecture_review_v2
from .lecture_errors import LectureReviewValidationError


def append_lecture_observation_v2(*, previous: LectureLedgerV2 | None,
                                  binding: LectureReviewBindingV1, step_id: str,
                                  output: LectureReviewOutputV2, content: str,
                                  previous_content: str | None, parent_resource_id: str | None,
                                  targets: list[str], evidence_hashes: dict[str, str],
                                  teaching_rule_ids: set[str], revision_kind: str = "ordinary",
                                  coverage_threshold: float = 0.8,
                                  carry_over: EvidenceContextCarryOverV1 | None = None) -> LectureLedgerV2:
    """Return a new ledger; callers must atomically persist it before checkpointing.

    New issue IDs in model output are temporary. Only the server assigns logical
    IDs. Existing issue definitions and acceptance criteria are never overwritten.
    """
    if revision_kind not in {"ordinary", "claim"}:
        raise ValueError("unknown lecture revision kind")
    if not step_id or output.binding != binding or text_hash(content) != binding.content_hash:
        raise LectureReviewValidationError("BINDING_MISMATCH", "binding",
                                           "observation does not belong to the bound content")
    # G6: validate the model's temporary identifiers BEFORE the server replaces
    # them.  Two identical temporary ids must not silently become two distinct
    # server ids; a temporary id that collides with an existing ledger id is a
    # model error (an authoritative-state collision is the caller's separate
    # problem and is never "corrected" by rewriting the old ledger).
    raw_ids = [item.issue_id for item in output.issues]
    if len(set(raw_ids)) != len(raw_ids):
        raise LectureReviewValidationError("ISSUE_ID_DUPLICATED", "issues",
                                           "temporary issue identifiers must be unique")
    existing_ids = {item.issue.issue_id for item in previous.issues} if previous is not None else set()
    if any(raw in existing_ids for raw in raw_ids):
        raise LectureReviewValidationError("ISSUE_ID_COLLISION", "issues",
                                           "a new issue cannot reuse an existing identifier")
    ordered = sorted(enumerate(output.issues), key=lambda pair: (pair[1].location.paragraph_id, pair[0]))
    new_issues = [item.model_copy(update={"issue_id": issue_id_v2(
        run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
        lineage_id=binding.lineage_id, step_id=step_id, ordinal=number)})
        for number, (_, item) in enumerate(ordered, 1)]
    normalized = output.model_copy(update={"issues": new_issues})
    digest = canonical_hash(normalized.model_dump(mode="json"))
    if previous is not None:
        old = previous.binding
        for key in ("run_id", "resource_spec_id", "lineage_id", "policy_hash"):
            if getattr(old, key) != getattr(binding, key):
                raise ValueError("ledger resource or frozen context mismatch")
        replay = [entry for entry in previous.observations if entry.step_id == step_id]
        if replay:
            if len(replay) != 1 or replay[0].binding != binding or replay[0].output_hash != digest:
                raise ValueError("observation replay conflict")
            return previous
        if (binding.version != old.version + 1 or parent_resource_id != old.resource_id or
                previous_content is None or text_hash(previous_content) != old.content_hash):
            raise ValueError("ledger parent version or content mismatch")
        if old.evidence_snapshot_hash != binding.evidence_snapshot_hash:
            if carry_over is None:
                raise ValueError("ledger resource or frozen context mismatch")
            carried_histories = validate_carry_over(
                carry_over, binding=binding, previous_ledger=previous,
                history_model=LectureIssueHistoryV2)
            if carry_over.previous_comparison_hash != previous.observations[-1].comparison_hash:
                raise ValueError("carry-over predecessor comparison hash mismatch")
            histories, count, carried = (
                carried_histories, carry_over.consecutive_unchanged, carry_over)
        else:
            if carry_over is not None:
                raise ValueError("carry-over requires a changed evidence context")
            histories = list(previous.issues)
            count = previous.observations[-1].consecutive_unchanged
            carried = previous.carry_over
    else:
        if carry_over is not None:
            raise ValueError("carry-over requires its predecessor ledger")
        if previous_content is not None or parent_resource_id is not None:
            raise ValueError("revision requires its previous ledger")
        histories, count, carried = [], 0, None
    epoch_start = previous is not None and carry_over is not None
    if len({item.issue.issue_id for item in histories}) != len(histories):
        raise ValueError("ledger contains duplicate identities")
    existing_ids = {item.issue.issue_id for item in histories}
    if any(item.issue_id in existing_ids for item in output.issues):
        raise ValueError("new issue duplicates existing identity")
    result = validate_lecture_review_v2(
        output=normalized, binding=binding, content=content, previous_content=previous_content,
        targets=targets, evidence_hashes=evidence_hashes, teaching_rule_ids=teaching_rule_ids,
        old_open=tuple(item.issue for item in histories if item.status == "open"),
        old_closed=tuple(item.issue for item in histories if item.status == "closed"),
        consecutive_unchanged=count, count_unchanged=revision_kind == "ordinary",
        coverage_threshold=coverage_threshold)
    resolutions = {item.issue_id: item.result for item in output.resolutions}
    reopened = {item.issue_id for item in output.reopen}
    updated = []
    for item in histories:
        status = item.status
        if resolutions.get(item.issue.issue_id) in {"fixed", "false_positive"}:
            status = "closed"
        if item.issue.issue_id in reopened:
            status = "open"
        updated.append(item.model_copy(update={"status": status}))
    updated.extend(LectureIssueHistoryV2(issue=item, introduced_step_id=step_id,
                   introduced_version=binding.version, status="open" if item.blocking else "closed")
                   for item in new_issues)
    added = removed = 0
    if previous_content is not None:
        for tag, start_a, end_a, start_b, end_b in SequenceMatcher(
                a=previous_content, b=content, autojunk=False).get_opcodes():
            if tag != "equal":
                added += end_b - start_b
                removed += end_a - start_a
    observation = LectureObservationV2(
        step_id=step_id, binding=binding, output_hash=digest,
        comparison_hash=comparison_hash(content),
        parent_content_hash=text_hash(previous_content) if previous_content is not None else None,
        revision_kind=revision_kind, unchanged=result.unchanged,
        consecutive_unchanged=(count if revision_kind == "claim" else count + 1 if result.unchanged else 0),
        characters_added=added, characters_removed=removed,
        coverage_rate=derived_coverage_rate(normalized.targets),
        output=normalized, decision=result.decision)
    return LectureLedgerV2(binding=binding, issues=updated, carry_over=carried,
                           observations=[*([] if epoch_start else (previous.observations if previous else [])), observation])
