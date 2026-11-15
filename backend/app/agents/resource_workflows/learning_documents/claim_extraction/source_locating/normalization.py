"""Controlled comparison copy (B) with origin-preserving interval mapping.

Only two format rules are enabled initially (T42 §4.2): CRLF -> LF everywhere,
and horizontal-ASCII-space folding inside plain narrative. Each normalized
character keeps its original source interval so a match in the comparison copy
can always be mapped back to full-text Python indexes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_URL = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_FORMULA = re.compile(r"\$\$.*?\$\$|\$[^$\n]+\$|\\\(.*?\\\)|\\\[.*?\\\]", re.S)
_HSPACE = re.compile(r"[ \t]+")

_SENSITIVE_KINDS = frozenset({"code", "table"})


@dataclass(frozen=True)
class Comparison:
    """Normalized text plus per-character original intervals."""

    text: str
    # mapping[i] == (orig_start, orig_end) for normalized character i.
    mapping: tuple[tuple[int, int], ...]
    # Original-coordinate sensitive ranges where only CRLF folding applies.
    sensitive: tuple[tuple[int, int], ...] = field(default_factory=tuple)


def _merge(ranges):
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def sensitive_ranges(text: str, start: int, end: int, kind: str) -> tuple[tuple[int, int], ...]:
    """Original-coordinate spans that must not receive space folding.

    Whole-unit kinds (code/table) are sensitive by construction; narrative
    units additionally detect inline code, URLs and formulas. Detection is
    deliberately conservative: anything not confidently narrative is left
    sensitive, so B degrades toward A instead of mis-folding.
    """
    if kind in _SENSITIVE_KINDS:
        return ((start, end),)
    window = text[start:end]
    found: list[tuple[int, int]] = []
    for pattern in (_URL, _INLINE_CODE, _FORMULA):
        for match in pattern.finditer(window):
            found.append((start + match.start(), start + match.end()))
    return tuple(_merge(found))


def _inside(ranges, index):
    for start, end in ranges:
        if start <= index < end:
            return True
    return False


def build_comparison(text: str, unit, rules=None) -> Comparison:
    """Build the comparison copy for one unit.

    ``rules`` is accepted for signature stability but the initial format set is
    fixed by this module's version; callers must ensure the frozen locator
    algorithm version matches before trusting the result.
    """
    start, end = unit.start, unit.end
    sensitive = sensitive_ranges(text, start, end, unit.kind)
    out: list[str] = []
    mapping: list[tuple[int, int]] = []
    i = start
    while i < end:
        if i + 1 < end and text[i] == "\r" and text[i + 1] == "\n":
            out.append("\n")
            mapping.append((i, i + 2))
            i += 2
            continue
        ch = text[i]
        if ch in " \t" and not _inside(sensitive, i):
            run = i
            while i < end and text[i] in " \t" and not _inside(sensitive, i):
                i += 1
            out.append(" ")
            mapping.append((run, i))
            continue
        out.append(ch)
        mapping.append((i, i + 1))
        i += 1
    return Comparison(text="".join(out), mapping=tuple(mapping), sensitive=sensitive)


def normalize_reference(value: str) -> str:
    """Normalize a model reference with the same two format rules.

    The reference is a flat verbatim-copy attempt without sensitive-region
    knowledge; space folding here is bounded by the unit comparison copy, so a
    sensitive-space difference simply fails to match and is never mis-bound.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return _HSPACE.sub(" ", value)


def map_interval(comp: Comparison, a: int, b: int) -> tuple[int, int]:
    """Map a half-open comparison interval back to original coordinates."""
    if a < 0 or b <= a or b > len(comp.mapping):
        raise ValueError("comparison interval out of range")
    orig_start = comp.mapping[a][0]
    orig_end = comp.mapping[b - 1][1]
    if orig_end <= orig_start:
        raise ValueError("degenerate comparison mapping")
    return orig_start, orig_end
