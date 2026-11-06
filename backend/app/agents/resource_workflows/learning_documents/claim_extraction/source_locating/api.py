"""Pure programmatic source locating entry: A (exact) -> B (format) -> C (edit).

This module owns only the deterministic search; it imports no executor, Service
or API. Callers supply the frozen ``SourceLocatingPolicy`` and, for tolerant
mode, the frozen rules asset and a shared work counter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from fractions import Fraction

from . import approximate, normalization
from .rules import Rules, load_rules
from .types import LocateCode, LocateResult, WorkCounter, WorkLimitExceeded


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    level: str
    edits: int = 0
    score: float | None = None
    categories: tuple[str, ...] = ()


def _exact_occurrences(text: str, start: int, end: int, needle: str) -> list[int]:
    positions = []
    cursor = start
    while True:
        found = text.find(needle, cursor, end)
        if found < 0:
            break
        positions.append(found)
        cursor = found + 1
    return positions


def locate(
    text: str,
    unit,
    source_text: str,
    policy,
    rules: Rules | None = None,
    work: WorkCounter | None = None,
    deadline_check: Callable[[], None] | None = None,
) -> LocateResult:
    """Locate one reference inside its target unit and return an outcome.

    ``unit.start``/``unit.end`` are full-text Python indexes; all results are
    full-text half-open intervals. Rejections are controlled (never exceptions)
    and carry a stable private code.
    """
    if deadline_check is not None:
        deadline_check()
    locating = policy.source_locating
    if locating is None:
        raise ValueError("source locating requires a frozen source_locating sub-contract")
    rules = rules or load_rules()
    revised = locating.locator_algorithm_version == "locator-v2"
    if rules.hash != locating.rules_hash:
        return LocateResult(None, None, "exact", LocateCode.RULES_DRIFT.value)
    if len(source_text) > locating.max_candidate_chars:
        return LocateResult(None, None, "exact", LocateCode.SOURCE_TOO_LONG.value)

    # A: unique exact match inside the target unit only.
    exact = _exact_occurrences(text, unit.start, unit.end, source_text)
    if len(exact) == 1:
        return LocateResult(exact[0], exact[0] + len(source_text), "exact",
                            LocateCode.ACCEPTED.value)
    if len(exact) > 1:
        return LocateResult(None, None, "exact", LocateCode.AMBIGUOUS_EXACT.value)

    if locating.mode == "exact_v1":
        return LocateResult(None, None, "exact", LocateCode.NO_CANDIDATE.value)

    # B: controlled format match (CRLF + narrative space folding).
    comp = normalization.build_comparison(text, unit, rules)
    norm_ref = normalization.normalize_reference(source_text)
    normalized = _exact_occurrences(comp.text, 0, len(comp.text), norm_ref)
    mapped: list[tuple[int, int]] = []
    for pos in normalized:
        try:
            orig_start, orig_end = normalization.map_interval(comp, pos, pos + len(norm_ref))
        except ValueError:
            return LocateResult(None, None, "normalized", LocateCode.MAPPING_INVALID.value)
        if orig_end - orig_start > locating.max_candidate_chars:
            return LocateResult(None, None, "normalized", LocateCode.SOURCE_TOO_LONG.value)
        if (orig_start, orig_end) not in mapped:
            mapped.append((orig_start, orig_end))
    if len(mapped) == 1:
        return LocateResult(mapped[0][0], mapped[0][1], "normalized", LocateCode.ACCEPTED.value)
    if len(mapped) > 1:
        return LocateResult(None, None, "normalized", LocateCode.AMBIGUOUS_NORMALIZED.value)

    # C: bounded edit-distance candidates (tolerant mode only).
    if work is None:
        work = WorkCounter(locating.max_work_cells_per_batch)
    if unit.end - unit.start > locating.max_unit_chars:
        return LocateResult(None, None, "approximate", LocateCode.NO_CANDIDATE.value)
    information = (sum(c.isalnum() for c in norm_ref) if revised else len(source_text))
    minimum = locating.min_effective_chars if revised else rules.thresholds.min_effective_chars
    if information < minimum:
        return LocateResult(None, None, "approximate", LocateCode.NO_CANDIDATE.value)
    try:
        candidates = approximate.approximate_candidates(
            norm_ref, comp, locating.max_edits, rules, work,
            max_dp_cells_per_ref=(locating.max_dp_cells_per_ref if revised else None),
            strict_duplicates=revised)
    except WorkLimitExceeded:
        return LocateResult(None, None, "approximate", LocateCode.WORK_LIMIT_EXCEEDED.value)
    if len(candidates) > locating.max_distinct_intervals:
        return LocateResult(None, None, "approximate", LocateCode.WORK_LIMIT_EXCEEDED.value)
    ratio = Fraction(str(locating.max_edit_ratio))
    valid = [c for c in candidates if c.allowed and not c.protected_violation
             and c.edits <= locating.max_edits
             and (not revised or (
                 c.orig_end - c.orig_start <= locating.max_candidate_chars
                 and c.edits * ratio.denominator
                     <= max(len(norm_ref), c.comparison_length) * ratio.numerator))]
    if not valid:
        if not candidates:
            return LocateResult(None, None, "approximate", LocateCode.NO_CANDIDATE.value)
        # Report the rejection from the best (fewest-edit) candidate, not any
        # spurious alignment: a protected-content change outranks a plain
        # unknown edit only when the best match itself touches protected content.
        best = candidates[0]
        if best.protected_violation:
            return LocateResult(None, None, "approximate", LocateCode.PROTECTED_CONTENT_CHANGED.value)
        return LocateResult(None, None, "approximate", LocateCode.EDIT_NOT_ALLOWED.value)
    if len(valid) == 1:
        best = valid[0]
        return LocateResult(best.orig_start, best.orig_end, "approximate", LocateCode.ACCEPTED.value,
                            edits=best.edits, score=best.score, edit_categories=best.categories)
    best, second = valid[0], valid[1]
    gap = round(best.score - second.score, 6)
    if gap < locating.min_score_margin:
        return LocateResult(None, None, "approximate", LocateCode.AMBIGUOUS_APPROXIMATE.value,
                            edits=best.edits, score=best.score, second_score=second.score, second_gap=gap)
    return LocateResult(best.orig_start, best.orig_end, "approximate", LocateCode.ACCEPTED.value,
                        edits=best.edits, score=best.score, second_score=second.score, second_gap=gap,
                        edit_categories=best.categories)
