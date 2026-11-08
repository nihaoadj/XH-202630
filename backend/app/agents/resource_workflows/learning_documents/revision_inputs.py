"""Pure construction and scope selection for generation revision inputs (T46).

This module turns already-persisted domain objects (resources, specs, Claims,
Judgements, frozen Evidence and an existing ordinary work order) into the
private ``ResourceReviewRevisionInput`` / ``ClaimReviewRevisionInput`` values
defined in ``app.models.reviews.revision_inputs``.

It performs no model calls, no SQL, no container initialization and no global
config reads. It must never mutate the resources/Claims/Judgements it receives,
and it never re-runs the Claim extraction or source-locating algorithms — it
only re-reads the materialized source spans and groups them by lossless Markdown
unit.
"""

from __future__ import annotations

import hashlib

from app.models.reviews.claims import ClaimJudgement, ClaimJudgementStatus, ClaimRecord, ClaimVerdict
from app.models.reviews.revision_inputs import (
    CLAIM_KIND,
    ORDINARY_KIND,
    REVISION_INPUT_ENVELOPE_VERSION,
    ClaimReviewRevisionInput,
    ClaimRevisionContextGroupV1,
    ClaimRevisionEvidenceV1,
    ClaimRevisionProblemV1,
    ResourceReviewRevisionInput,
    RevisionSourceSpanV1,
)

MAX_CONTEXT_CHARS = 1600
_BAD_VERDICTS = frozenset({ClaimVerdict.CONTRADICTED, ClaimVerdict.NOT_IN_EVIDENCE})


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _structured(resource) -> dict | None:
    for attr in ("practice_guide_payload", "assessment_payload", "review_practice_payload"):
        value = getattr(resource, attr, None)
        if isinstance(value, dict):
            return value
    return None


def build_resource_review_revision_input(
    *,
    resource_spec_id: str,
    resource,
    targets: tuple[str, ...] | list[str],
    work_order: dict | None = None,
    lecture_revision: dict | None = None,
    feedback: dict | None = None,
) -> ResourceReviewRevisionInput:
    """Build the ordinary generation revision input from one frozen source.

    ``work_order`` is the ``resource_issue_v1`` work order (``.as_dict()``);
    ``lecture_revision`` is the dedicated-lecture revision record; ``feedback``
    is the compat reviewer projection. Exactly one source is expected by the
    caller, but the richest available source wins here.
    """
    previous_text = getattr(resource, "content_text", None) or ""
    structured = _structured(resource)
    parent_id = getattr(resource, "resource_id", None)
    parent_version = getattr(resource, "version", None)
    issues: list[dict] = []
    closed: list[dict] = []
    unchanged = False
    revision_source = "ordinary"
    effective_feedback = None

    if work_order:
        previous_text = work_order.get("previous_text")
        structured = work_order.get("previous_structured_payload")
        parent_id = work_order.get("parent_resource_id") or parent_id
        binding = work_order.get("parent_binding") or {}
        parent_version = binding.get("version") or parent_version
        issues = [item for item in (work_order.get("open_issues") or []) if isinstance(item, dict)]
        closed = [item for item in (work_order.get("closed_issues") or []) if isinstance(item, dict)]
        unchanged = bool(work_order.get("unchanged"))
    elif lecture_revision:
        previous_text = lecture_revision.get("previous_content")
        parent_id = lecture_revision.get("parent_resource_id") or parent_id
        issues = [item for item in (lecture_revision.get("open_issues") or []) if isinstance(item, dict)]
        closed = [item for item in (lecture_revision.get("closed_issues") or []) if isinstance(item, dict)]
        unchanged = bool(lecture_revision.get("unchanged"))
    else:
        revision_source = "compat"
        effective_feedback = scope_ordinary_feedback(feedback or {}, resource_spec_id, resource)
        # The assessment specialized reviewer reports per-question findings for
        # every assessment spec in the run. Scope them to this spec's parent
        # resource so a sibling assessment never leaks another spec's findings.
        if getattr(resource, "resource_type", None) == "分阶测试题":
            findings = effective_feedback.get("assessment_findings")
            if findings:
                effective_feedback["assessment_findings"] = [
                    dict(item) for item in findings
                    if isinstance(item, dict)
                    and item.get("resource_spec_id") == resource_spec_id
                    and item.get("resource_id") == getattr(resource, "resource_id", None)
                ]

    content_hash = _sha256(previous_text or "")
    return ResourceReviewRevisionInput(
        resource_spec_id=resource_spec_id,
        parent_resource_id=parent_id,
        parent_version=parent_version,
        content_hash=content_hash,
        targets=list(targets),
        previous_text=previous_text,
        previous_structured_payload=structured,
        issues=issues,
        closed_issues=closed,
        unchanged=unchanged,
        feedback=effective_feedback,
        revision_source=revision_source,
    )


def _containing_unit(units, start: int, end: int):
    if not units:
        return None
    for unit in units:
        if unit.start <= start and end <= unit.end:
            return unit
    return None


def build_claim_review_revision_input(
    *,
    resource_spec_id: str,
    resource,
    targets: tuple[str, ...] | list[str],
    claims: list[ClaimRecord],
    judgements: list[ClaimJudgement],
    evidence,
) -> ClaimReviewRevisionInput:
    """Build the targeted Claim-audit revision input for one resource spec.

    Only completed factual Claims with a ``contradicted`` / ``not_in_evidence``
    verdict that belong to the bound parent resource/version are included. Their
    materialized source spans are re-read (never re-located) and pooled; claims
    fully inside the same lossless Markdown unit share an optional context group
    while cross-unit claims each get their own group.
    """
    from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import scan_units

    content = getattr(resource, "content_text", None) or ""
    parent_id = getattr(resource, "resource_id", "")
    parent_version = getattr(resource, "version", 1)
    judgement_by_claim = {
        item.claim_id: item
        for item in judgements
        if item.status == ClaimJudgementStatus.COMPLETED
    }

    bad: list[tuple[ClaimRecord, ClaimJudgement]] = []
    for claim in claims:
        if claim.resource_id != parent_id or claim.resource_version != parent_version:
            continue
        judgement = judgement_by_claim.get(claim.claim_id)
        if judgement is None or judgement.verdict not in _BAD_VERDICTS:
            continue
        bad.append((claim, judgement))
    bad.sort(key=lambda pair: (
        pair[0].source_start, pair[0].source_end, pair[0].claim_index, pair[0].claim_id,
    ))

    for claim, judgement in bad:
        if (content[claim.source_start:claim.source_end] != claim.source_text
                or _sha256(claim.source_text) != claim.source_text_hash):
            raise ValueError("revision source span does not match parent content")
        if (judgement.resource_id != parent_id or judgement.resource_version != parent_version
                or judgement.run_id != claim.run_id):
            raise ValueError("revision judgement crosses parent scope")

    spans: list[RevisionSourceSpanV1] = []
    span_id_by_key: dict[tuple, str] = {}
    problems: list[ClaimRevisionProblemV1] = []
    for claim, judgement in bad:
        key = (parent_id, parent_version, claim.source_start, claim.source_end, claim.source_text_hash)
        span_id = span_id_by_key.get(key)
        if span_id is None:
            span_id = f"sp_{len(spans):04d}"
            span_id_by_key[key] = span_id
            spans.append(RevisionSourceSpanV1(
                span_id=span_id,
                source_text=claim.source_text,
                source_start=claim.source_start,
                source_end=claim.source_end,
                source_text_hash=claim.source_text_hash,
            ))
        contradicted = judgement.verdict == ClaimVerdict.CONTRADICTED
        problems.append(ClaimRevisionProblemV1(
            claim_id=claim.claim_id,
            claim_index=claim.claim_index,
            claim_text=claim.claim_text,
            verdict=judgement.verdict.value,
            reason=judgement.reason,
            knowledge_point_id=claim.knowledge_point_id,
            source_span_id=span_id,
            evidence_ids=list(judgement.evidence_ids) if contradicted else [],
        ))

    span_by_id = {item.span_id: item for item in spans}
    units = None
    try:
        units = scan_units(content) if content else None
    except ValueError:
        units = None

    unit_of_problem: dict[str, object] = {}
    for problem in problems:
        span = span_by_id[problem.source_span_id]
        unit_of_problem[problem.claim_id] = _containing_unit(units, span.source_start, span.source_end)

    unit_groups: dict[str, list[ClaimRevisionProblemV1]] = {}
    solo: list[ClaimRevisionProblemV1] = []
    for problem in problems:
        unit = unit_of_problem[problem.claim_id]
        if unit is None:
            solo.append(problem)
        else:
            unit_groups.setdefault(unit.unit_id, []).append(problem)

    def first_key(items: list[ClaimRevisionProblemV1]):
        first = items[0]
        span = span_by_id[first.source_span_id]
        return (span.source_start, span.source_end, first.claim_index, first.claim_id)

    ordered_units: list[tuple[str | None, list[ClaimRevisionProblemV1]]] = [
        (unit_id, items) for unit_id, items in
        sorted(unit_groups.items(), key=lambda kv: first_key(kv[1]))
    ]
    ordered_units.extend((None, [problem]) for problem in solo)
    ordered_units.sort(key=lambda kv: first_key(kv[1]))

    groups: list[ClaimRevisionContextGroupV1] = []
    for index, (unit_id, group_problems) in enumerate(ordered_units):
        group_id = f"grp_{index:04d}"
        context_text: str | None = None
        resolved_unit_id = unit_id or group_id
        if unit_id is not None:
            unit = next(u for u in units if u.unit_id == unit_id)
            candidate = content[unit.start:unit.end]
            context_text = candidate if len(candidate) <= MAX_CONTEXT_CHARS else None
        groups.append(ClaimRevisionContextGroupV1(
            group_id=group_id,
            unit_id=resolved_unit_id,
            context_text=context_text,
            problem_claim_ids=[item.claim_id for item in group_problems],
        ))

    evidence_pool = [
        ClaimRevisionEvidenceV1(
            evidence_id=getattr(item, "evidence_id", ""),
            source=getattr(item.locator, "source_path", "") if getattr(item, "locator", None) else "",
            section=(getattr(item.locator, "section", None) or "") if getattr(item, "locator", None) else "",
            excerpt=getattr(item, "excerpt", ""),
        )
        for item in evidence
        if getattr(item, "evidence_id", "")
    ]

    return ClaimReviewRevisionInput(
        resource_spec_id=resource_spec_id,
        parent_resource_id=parent_id,
        parent_version=parent_version,
        content_hash=_sha256(content),
        targets=list(targets),
        previous_text=content,
        previous_structured_payload=_structured(resource),
        spans=spans,
        problems=problems,
        groups=groups,
        evidence=evidence_pool,
    )


def pack_revision_input(value: ResourceReviewRevisionInput | ClaimReviewRevisionInput) -> dict:
    """Wrap one revision input in the versioned, kind-tagged private envelope.

    The envelope is the boundary-compatible transfer shape used inside the
    in-memory ``generation_revision_inputs`` map and the retry
    ``revision_feedback`` slot. It never becomes a public model or API field.
    """
    return {
        "schema_version": REVISION_INPUT_ENVELOPE_VERSION,
        "kind": value.kind,
        "input": value.model_dump(mode="json"),
    }


def unpack_revision_input(envelope: dict) -> ResourceReviewRevisionInput | ClaimReviewRevisionInput:
    """Validate one envelope back into its typed revision input.

    An unknown version or kind is a contract error, never silently downgraded
    to the legacy ``revision_feedback`` shape.
    """
    if not isinstance(envelope, dict) or envelope.get("schema_version") != REVISION_INPUT_ENVELOPE_VERSION:
        raise ValueError("unsupported revision input envelope")
    kind = envelope.get("kind")
    payload = envelope.get("input")
    if kind == ORDINARY_KIND:
        return ResourceReviewRevisionInput.model_validate(payload)
    if kind == CLAIM_KIND:
        return ClaimReviewRevisionInput.model_validate(payload)
    raise ValueError("unknown revision input kind")


def is_revision_input_envelope(value: dict) -> bool:
    """Recognize envelope candidates, including invalid versions for rejection."""
    return isinstance(value, dict) and (
        "schema_version" in value or "kind" in value or "input" in value
    )


def scope_ordinary_feedback(feedback: dict, spec_id: str, resource) -> dict:
    """Separate reviewer sources and scope compat feedback to one parent."""
    def selected(item):
        if not isinstance(item, dict) or item.get("claim_ids") or item.get("target_claim_ids"):
            return False
        for keys, expected in (
            (("resource_id", "target_resource_id"), resource.resource_id),
            (("resource_spec_id", "target_resource_spec_id"), spec_id),
            (("resource_type", "target_resource_type"), resource.resource_type),
        ):
            if any(item.get(key) is not None and item[key] != expected for key in keys):
                return False
        return True
    result = dict(feedback)
    for key in ("issues", "revision_instructions"):
        result[key] = [dict(item) for item in feedback.get(key, []) if selected(item)]
    return result


__all__ = [
    "MAX_CONTEXT_CHARS",
    "build_resource_review_revision_input",
    "build_claim_review_revision_input",
    "pack_revision_input",
    "unpack_revision_input",
    "is_revision_input_envelope",
    "scope_ordinary_feedback",
]
