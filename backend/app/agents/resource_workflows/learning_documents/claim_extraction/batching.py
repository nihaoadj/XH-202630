"""Deterministic adjacent packing, bounded read-only context and subdivision."""
from .segmentation import assert_partition, scan_units, split_unit
from app.models.reviews.claim_extraction import ESTIMATE, ExtractionBatch, digest

# claim-density-v1: risk kinds, single-unit exemption and the <= comparison are
# part of the frozen algorithm. Changing any of them requires a new version.
RISK_KINDS = frozenset({"paragraph", "list", "table", "code"})


def risk_chars(units):
    """Characters that may yield claims. Headings/whitespace weigh zero but are
    still segmented, packed, token-counted and required to answer per unit."""
    return sum(unit.end - unit.start for unit in units if unit.kind in RISK_KINDS)


def density_allows(policy, units):
    """T37 density gate. Absent/disabled policy keeps the historical planner.

    A candidate holding exactly one unit is exempt: the heuristic must never
    force a single paragraph to be split. Token/window/context conditions still
    apply, and a truly oversized single unit still fails through the original
    branches (or T36 subdivision downstream).
    """
    density = getattr(policy, "density_batching", None)
    if density is None or not density.enabled:
        return True
    if len(units) == 1:
        return True
    return risk_chars(units) <= density.chars_per_claim * policy.batch_claims * density.capacity_share


def make_batch(text, units, policy, counter, parent_id=None):
    context = []
    seen = set()
    context_tokens = 0
    for unit in units:
        for span in [*unit.required_context, *unit.context]:
            identity = (span.start, span.end)
            if identity in seen or any(u.start <= span.start and span.end <= u.end for u in units):
                continue
            tokens = counter.count_text(text[span.start:span.end])
            if context_tokens + tokens > policy.context_tokens or len(context) >= 32:
                if span in unit.required_context:
                    raise ValueError("required table/code context exceeds capacity")
                # Dropping auxiliary context never drops a target character.
                continue
            context.append(span)
            context_tokens += tokens
            seen.add(identity)
    return ExtractionBatch(batch_id="b_" + digest([parent_id, [u.unit_id for u in units]])[:32],
                           parent_id=parent_id, units=units, context=context)


def plan_batches(text, policy, counter, *, fits=lambda batch: True):
    original = scan_units(text)
    units = []
    for unit in original:
        units.extend(split_unit(text, unit, max_tokens=policy.target_tokens, counter=counter))
    assert_partition(text, units)
    pending = list(units)
    batches, current = [], []
    while pending:
        unit = pending.pop(0)
        if len(current) >= policy.max_units:
            batches.append(make_batch(text, current, policy, counter))
            current = []
        try:
            candidate = make_batch(text, current + [unit], policy, counter)
        except ValueError:
            if not current:
                raise
            batches.append(make_batch(text, current, policy, counter))
            current = []
            pending.insert(0, unit)
            continue
        target_tokens = sum(counter.count_text(text[u.start:u.end]) for u in candidate.units)
        if (len(candidate.units) <= policy.max_units
                and (policy.strategy == ESTIMATE or target_tokens <= policy.target_tokens)
                and density_allows(policy, candidate.units)
                and fits(candidate)):
            current.append(unit)
        elif current:
            batches.append(make_batch(text, current, policy, counter))
            current = []
            pending.insert(0, unit)
        else:
            pending[0:0] = split_unit(text, unit, max_tokens=policy.target_tokens, counter=counter, force=True)
    if current:
        batches.append(make_batch(text, current, policy, counter))
    assert_partition(text, [u for b in batches for u in b.units])
    return batches


def subdivide(text, batch, policy, counter, *, fits=lambda batch: True):
    if len(batch.units) > 1:
        middle = len(batch.units) // 2
        groups = [batch.units[:middle], batch.units[middle:]]
    else:
        pieces = split_unit(text, batch.units[0], max_tokens=policy.target_tokens, counter=counter, force=True)
        groups = [[piece] for piece in pieces]
    children = [make_batch(text, group, policy, counter, batch.batch_id) for group in groups]
    if any(not fits(child) for child in children):
        raise ValueError("subdivision exceeds extraction input capacity")
    assert_partition(text, [u for b in children for u in b.units], start=batch.units[0].start, end=batch.units[-1].end)
    return children
