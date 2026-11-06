"""Append-only lecture observations with exact version and lineage checks."""

from __future__ import annotations

from difflib import SequenceMatcher

from app.models.reviews.lecture_review import (
    LectureIssueHistoryV1, LectureLedgerV1, LectureObservationV1,
    LectureReviewBindingV1, LectureReviewOutputV1,
)
from app.models.shared.persistence import canonical_hash

from .lecture_contract import comparison_hash, issue_id, text_hash, validate_lecture_review


def append_lecture_observation(*, previous: LectureLedgerV1 | None,
                               binding: LectureReviewBindingV1, step_id: str,
                               output: LectureReviewOutputV1, content: str,
                               previous_content: str | None, parent_resource_id: str | None,
                               targets: list[str], evidence_hashes: dict[str, str],
                               teaching_rule_ids: set[str], revision_kind: str = "ordinary") -> LectureLedgerV1:
    """Return a new ledger; callers must atomically persist it before checkpointing.

    New issue IDs in model output are temporary. Only the server assigns logical
    IDs. Existing issue definitions and acceptance criteria are never overwritten.
    """
    if revision_kind not in {"ordinary", "claim"}:
        raise ValueError("unknown lecture revision kind")
    if not step_id or output.binding != binding or text_hash(content) != binding.content_hash:
        raise ValueError("observation binding mismatch")
    ordered = sorted(enumerate(output.issues), key=lambda pair: (pair[1].location.paragraph_id, pair[0]))
    new_issues = [item.model_copy(update={"issue_id": issue_id(
        run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
        lineage_id=binding.lineage_id, step_id=step_id, ordinal=number)})
        for number, (_, item) in enumerate(ordered, 1)]
    normalized = output.model_copy(update={"issues": new_issues})
    digest = canonical_hash(normalized.model_dump(mode="json"))
    if previous is not None:
        old = previous.binding
        for key in ("run_id", "resource_spec_id", "lineage_id", "evidence_snapshot_hash", "policy_hash"):
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
        histories = list(previous.issues)
        count = previous.observations[-1].consecutive_unchanged
    else:
        if previous_content is not None or parent_resource_id is not None:
            raise ValueError("revision requires its previous ledger")
        histories, count = [], 0
    if len({item.issue.issue_id for item in histories}) != len(histories):
        raise ValueError("ledger contains duplicate identities")
    existing_ids = {item.issue.issue_id for item in histories}
    if any(item.issue_id in existing_ids for item in output.issues):
        raise ValueError("new issue duplicates existing identity")
    result = validate_lecture_review(
        output=normalized, binding=binding, content=content, previous_content=previous_content,
        targets=targets, evidence_hashes=evidence_hashes, teaching_rule_ids=teaching_rule_ids,
        old_open=tuple(item.issue for item in histories if item.status == "open"),
        old_closed=tuple(item.issue for item in histories if item.status == "closed"),
        consecutive_unchanged=count, count_unchanged=revision_kind == "ordinary")
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
    updated.extend(LectureIssueHistoryV1(issue=item, introduced_step_id=step_id,
                   introduced_version=binding.version, status="open" if item.blocking else "closed")
                   for item in new_issues)
    added = removed = 0
    if previous_content is not None:
        for tag, start_a, end_a, start_b, end_b in SequenceMatcher(
                a=previous_content, b=content, autojunk=False).get_opcodes():
            if tag != "equal":
                added += end_b - start_b
                removed += end_a - start_a
    observation = LectureObservationV1(
        step_id=step_id, binding=binding, output_hash=digest,
        comparison_hash=comparison_hash(content),
        parent_content_hash=text_hash(previous_content) if previous_content is not None else None,
        revision_kind=revision_kind, unchanged=result.unchanged,
        consecutive_unchanged=(count if revision_kind == "claim" else count + 1 if result.unchanged else 0),
        characters_added=added, characters_removed=removed,
        output=normalized, decision=result.decision)
    return LectureLedgerV1(binding=binding, issues=updated,
                           observations=[*(previous.observations if previous else []), observation])
