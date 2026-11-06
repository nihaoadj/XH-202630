"""Target-local source validation, conservative deduplication and legacy IDs.

v1 keeps the historical model-offset relocation path. v2 (source_locating) asks
the model for verbatim copies only and programmatically locates the span inside
the target unit, then rewrites ``source_text`` from the frozen resource text so
the materializer's exact-substring gate never needs its full-text fallback.
"""
from app.models.reviews.claim_extraction import (
    BatchOutput,
    BatchOutputV2,
    LocationDiagnostic,
    content_digest,
    digest,
)
from app.models.reviews.claims import ClaimCandidate, materialize_claims

from .source_locating import locate, load_rules, WorkCounter


class SourceLocatingRejected(ValueError):
    """A private, bounded rejection audit that survives executor recovery."""

    def __init__(self, diagnostics):
        self.diagnostics = tuple(d for d in diagnostics if not d.accepted)[:8]
        super().__init__(f"extraction source locating rejected: {self.diagnostics[-1].code}")


def _check_header(text, batch, output, resource):
    if (output.resource_id, output.resource_version, output.content_hash, output.batch_id) != (
            resource.resource_id, resource.version, content_digest(text), batch.batch_id):
        raise ValueError("extraction batch/resource version mismatch")


def _check_units(batch, output):
    units = {u.unit_id: u for u in batch.units}
    returned = [u.unit_id for u in output.units]
    if len(set(returned)) != len(returned) or set(returned) != set(units):
        raise ValueError("extraction target units missing or repeated")
    return units


def _validate_v1(text, batch, output, *, resource, policy, allowed_nodes):
    """Historical path: model offsets are advisory; exact substring relocates."""
    _check_header(text, batch, output, resource)
    units = _check_units(batch, output)
    if sum(len(u.claims) for u in output.units) >= policy.batch_claims:
        raise ValueError("extraction candidate cap reached")
    candidates = []
    for result in output.units:
        unit = units[result.unit_id]
        if result.status == "uncertain":
            raise ValueError("extraction unit unresolved")
        for raw in result.claims:
            start, end = unit.start + raw.source_start, unit.start + raw.source_end
            if not (unit.start <= start < end <= unit.end and text[start:end] == raw.source_text):
                positions, cursor = [], unit.start
                while True:
                    found = text.find(raw.source_text, cursor, unit.end)
                    if found < 0:
                        break
                    positions.append(found)
                    cursor = found + 1
                if not positions:
                    raise ValueError("extraction source substring absent in target")
                distance = min(abs(p - start) for p in positions)
                nearest = [p for p in positions if abs(p - start) == distance]
                if len(nearest) != 1:
                    raise ValueError("extraction source relocation is ambiguous")
                start, end = nearest[0], nearest[0] + len(raw.source_text)
            if raw.knowledge_point_id is not None and raw.knowledge_point_id not in allowed_nodes:
                raise ValueError("extraction unknown knowledge label")
            source = raw.source_text
            left = len(source) - len(source.lstrip())
            right = len(source.rstrip())
            source = source.strip()
            start, end = start + left, start + right
            if not source or text[start:end] != source:
                raise ValueError("extraction whitespace normalization mismatch")
            candidates.append(ClaimCandidate(claim_text=raw.claim_text.strip(), claim_type=raw.claim_type,
                source_text=source, source_start=start, source_end=end, knowledge_point_id=raw.knowledge_point_id,
                source_evidence_ids=[]))
    return candidates


def _validate_v2(text, batch, output, *, resource, policy, allowed_nodes):
    """Neutral-v2: programmatic locating then authoritative source write-back."""
    _check_header(text, batch, output, resource)
    units = _check_units(batch, output)
    if sum(len(u.claims) for u in output.units) >= policy.batch_claims:
        raise ValueError("extraction candidate cap reached")
    rules = load_rules()
    if rules.hash != policy.source_locating.rules_hash:
        raise ValueError("source locating rules drift")
    work = WorkCounter(policy.source_locating.max_work_cells_per_batch)
    candidates = []
    diagnostics = []
    for result in output.units:
        unit = units[result.unit_id]
        if result.status == "uncertain":
            raise ValueError("extraction unit unresolved")
        for idx, raw in enumerate(result.claims):
            before = work.used
            outcome = locate(text, unit, raw.source_text, policy, rules, work)
            work_cells = work.used - before
            ref_hash = digest(raw.source_text)
            if not outcome.accepted:
                diagnostics.append(LocationDiagnostic(
                    unit_id=unit.unit_id, candidate_index=idx, ref_hash=ref_hash,
                    level=outcome.level, accepted=False, code=outcome.code,
                    edits=outcome.edits, score=outcome.score, second_score=outcome.second_score,
                    second_gap=outcome.second_gap, edit_categories=list(outcome.edit_categories),
                    work_cells=work_cells))
                raise SourceLocatingRejected(diagnostics)
            start, end = outcome.start, outcome.end
            source_slice = text[start:end]
            left = len(source_slice) - len(source_slice.lstrip())
            right = len(source_slice.rstrip())
            source = source_slice.strip()
            start, end = start + left, start + right
            if not source or text[start:end] != source:
                raise ValueError("extraction source write-back mismatch")
            if raw.knowledge_point_id is not None and raw.knowledge_point_id not in allowed_nodes:
                raise ValueError("extraction unknown knowledge label")
            candidates.append(ClaimCandidate(claim_text=raw.claim_text.strip(), claim_type=raw.claim_type,
                source_text=source, source_start=start, source_end=end, knowledge_point_id=raw.knowledge_point_id,
                source_evidence_ids=[]))
            diagnostics.append(LocationDiagnostic(
                unit_id=unit.unit_id, candidate_index=idx, ref_hash=ref_hash,
                level=outcome.level, accepted=True, code=outcome.code,
                start=start, end=end, edits=outcome.edits, score=outcome.score,
                second_score=outcome.second_score, second_gap=outcome.second_gap,
                edit_categories=list(outcome.edit_categories), work_cells=work_cells))
    return candidates, diagnostics


def validate_output_with_diagnostics(text, batch, output, *, resource, policy, allowed_nodes):
    """Validate one batch and return (candidates, diagnostics).

    v1 returns ``diagnostics=None``; v2 returns a bounded per-candidate list.
    """
    is_v2 = getattr(policy, "source_locating", None) is not None
    if is_v2:
        parsed = BatchOutputV2.model_validate(output)
        candidates, diagnostics = _validate_v2(text, batch, parsed, resource=resource,
                                               policy=policy, allowed_nodes=allowed_nodes)
    else:
        parsed = BatchOutput.model_validate(output)
        candidates = _validate_v1(text, batch, parsed, resource=resource,
                                  policy=policy, allowed_nodes=allowed_nodes)
        diagnostics = None
    conservative_merge(candidates)
    return candidates, diagnostics


def validate_output(text, batch, output, *, resource, policy, allowed_nodes):
    candidates, _ = validate_output_with_diagnostics(text, batch, output, resource=resource,
                                                     policy=policy, allowed_nodes=allowed_nodes)
    return candidates


def conservative_merge(candidates):
    seen = {}
    for candidate in candidates:
        identity = (candidate.source_start, candidate.source_end, candidate.claim_text.strip())
        classification = (candidate.claim_type.value, candidate.knowledge_point_id)
        previous = seen.get(identity)
        if previous is not None and (previous.claim_type.value, previous.knowledge_point_id) != classification:
            raise ValueError("extraction classification/label conflict")
        if previous is not None and previous.source_text != candidate.source_text:
            raise ValueError("extraction source conflict")
        seen[identity] = candidate
    return sorted(seen.values(), key=lambda c: (c.source_start, c.source_end, c.claim_text.strip(), c.claim_type.value, c.knowledge_point_id or ""))


def materialize_result(candidates, *, text, resource, review_id, run_id, policy, created_at):
    candidates = conservative_merge(candidates)
    if not candidates:
        raise ValueError("empty extraction retains legacy failure semantics")
    if len(candidates) > policy.resource_claims:
        raise ValueError("extraction exceeds resource/Judge capacity")
    if any(text[c.source_start:c.source_end] != c.source_text for c in candidates):
        raise ValueError("extraction final span mismatch")
    claims = materialize_claims(candidates=candidates, resource_content=text, resource_id=resource.resource_id,
        resource_version=resource.version, review_id=review_id, run_id=run_id, allowed_evidence_ids=set(),
        allowed_knowledge_point_ids={c.knowledge_point_id for c in candidates if c.knowledge_point_id is not None},
        extractor_prompt_version=policy.prompt_version, extractor_model=(policy.profile.model_name if policy.schema_version=="1.0" else policy.model_name))
    return [claim.model_copy(update={"created_at": created_at}) for claim in claims]
