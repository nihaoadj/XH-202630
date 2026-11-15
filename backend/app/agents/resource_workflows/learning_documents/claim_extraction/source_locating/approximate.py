"""Bounded edit-distance substring search (C) with traceback scripts.

Only runs on the controlled comparison copy produced by B. Candidates are
found by exact-seed anchoring (pigeonhole: with ``k`` edits, one of ``k+1``
segments matches exactly) and verified with banded global alignment, so the DP
cost stays bounded and every accepted match carries a reversible edit script.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rules import Rules, edits_allowed
from .types import EditOp, WorkCounter, WorkLimitExceeded
from .normalization import map_interval


@dataclass(frozen=True)
class Candidate:
    orig_start: int
    orig_end: int
    edits: int
    score: float
    categories: tuple[str, ...]
    allowed: bool
    protected_violation: bool
    comparison_length: int = 0


def _segments(m: int, parts: int) -> list[tuple[int, int]]:
    base, rem = divmod(m, parts)
    segments = []
    i = 0
    for p in range(parts):
        length = base + (1 if p < rem else 0)
        segments.append((i, i + length))
        i += length
    return segments


def _global_align(pattern: str, text: str, k: int, work: WorkCounter, ref_cells: list):
    """Banded global edit distance (both ends anchored) with traceback.

    Returns ``(distance, ops)`` or ``None`` when ``distance > k`` or the
    length difference exceeds ``k``. Charges both the shared batch counter and
    the per-reference cell accumulator.
    """
    m, n = len(pattern), len(text)
    if abs(m - n) > k:
        return None
    inf = k + 1
    dp = [dict() for _ in range(m + 1)]
    back = [dict() for _ in range(m + 1)]
    dp[0][0] = 0
    for j in range(1, min(n, k) + 1):
        dp[0][j] = j
        back[0][j] = ("ins", 0, j)
    for i in range(1, min(m, k) + 1):
        dp[i][0] = i
        back[i][0] = ("del", i, 0)
    for i in range(1, m + 1):
        lo = max(1, i - k)
        hi = min(n, i + k)
        row = dp[i]
        brow = back[i]
        for j in range(lo, hi + 1):
            sub = dp[i - 1].get(j - 1, inf) + (0 if pattern[i - 1] == text[j - 1] else 1)
            dele = dp[i - 1].get(j, inf) + 1
            ins = row.get(j - 1, inf) + 1
            best = min(sub, dele, ins)
            row[j] = best
            if best == sub:
                brow[j] = ("sub", i - 1, j - 1)
            elif best == dele:
                brow[j] = ("del", i - 1, j)
            else:
                brow[j] = ("ins", i, j - 1)
    cells = sum(len(r) for r in dp)
    work.charge(cells)
    ref_cells[0] += cells
    distance = dp[m].get(n, inf)
    if distance > k:
        return None
    ops: list[EditOp] = []
    i, j = m, n
    while i > 0 or j > 0:
        op, pi, pj = back[i][j]
        if op == "sub":
            if pattern[i - 1] != text[j - 1]:
                ops.append(EditOp("sub", i - 1, j - 1, pattern[i - 1], text[j - 1]))
            i, j = i - 1, j - 1
        elif op == "del":
            ops.append(EditOp("del", i - 1, j, pattern[i - 1], ""))
            i, j = i - 1, j
        else:
            ops.append(EditOp("ins", i, j - 1, "", text[j - 1]))
            i, j = i, j - 1
    ops.reverse()
    return distance, ops


def approximate_candidates(ref: str, comp, k: int, rules: Rules, work: WorkCounter,
                           *, max_dp_cells_per_ref: int | None = None,
                           strict_duplicates: bool = False) -> list[Candidate]:
    """Find all bounded-edit candidate intervals, not yet accepted."""
    m = len(ref)
    comp_text = comp.text
    n = len(comp_text)
    if m == 0 or n == 0:
        return []
    segments = _segments(m, k + 1)
    best_by_interval: dict[tuple[int, int], Candidate] = {}
    max_seed = 512
    ref_cells = [0]
    per_ref_limit = (rules.thresholds.max_dp_cells_per_ref if max_dp_cells_per_ref is None
                     else max_dp_cells_per_ref)
    for seg_start, seg_end in segments:
        seg = ref[seg_start:seg_end]
        if not seg:
            continue
        prefix = ref[:seg_start]
        suffix = ref[seg_end:]
        pos = comp_text.find(seg)
        seen = 0
        while pos != -1 and seen < max_seed:
            seen += 1
            lefts = []
            lo = max(0, pos - len(prefix) - k)
            hi = min(pos, pos - len(prefix) + k)
            for L in range(lo, hi + 1):
                res = _global_align(prefix, comp_text[L:pos], k, work, ref_cells)
                if ref_cells[0] > per_ref_limit:
                    raise WorkLimitExceeded("per-reference cell budget exceeded")
                if res is not None:
                    lefts.append((L, res))
            rights = []
            seg_end_c = pos + len(seg)
            lo = max(seg_end_c, seg_end_c + len(suffix) - k)
            hi = min(n, seg_end_c + len(suffix) + k)
            for R in range(lo, hi + 1):
                res = _global_align(suffix, comp_text[seg_end_c:R], k, work, ref_cells)
                if ref_cells[0] > per_ref_limit:
                    raise WorkLimitExceeded("per-reference cell budget exceeded")
                if res is not None:
                    rights.append((R, res))
            for L, (ld, lops) in lefts:
                for R, (rd, rops) in rights:
                    total = ld + rd
                    if total > k:
                        continue
                    try:
                        orig_start, orig_end = map_interval(comp, L, R)
                    except ValueError:
                        continue
                    cand_len = R - L
                    score = 1 - total / max(m, cand_len)
                    # lops ref indexes are relative to ref[:seg_start] and their
                    # candidate indexes to comp[L:pos]; both already align to the
                    # full ref and comp[L:R]. rops need offsets into the same frames.
                    shifted = [EditOp(o.op, o.ref_index + seg_end, o.cand_index + (seg_end_c - L),
                                      o.ref_char, o.cand_char) for o in rops]
                    ops = lops + shifted
                    categories, all_allowed, protected = edits_allowed(
                        ops, ref, comp_text[L:R], rules, strict_duplicates=strict_duplicates)
                    key = (orig_start, orig_end)
                    current = best_by_interval.get(key)
                    cand = Candidate(orig_start, orig_end, total, score, categories, all_allowed,
                                     protected, cand_len)
                    if current is None or total < current.edits or (total == current.edits and score > current.score):
                        best_by_interval[key] = cand
            pos = comp_text.find(seg, pos + 1)
    return sorted(best_by_interval.values(), key=lambda c: (c.edits, -c.score, c.orig_start))
