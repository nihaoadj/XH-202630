"""Lossless Markdown span scanning. Source text is never reserialized."""
from __future__ import annotations

import re

from app.models.reviews.claim_extraction import ExtractionUnit, Span, content_digest, digest

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_SENTENCE = re.compile(r'''[。！？；][”’」』"]*|[.!?;]["']*(?=\s|$)''')


def unit_for(text, start, end, kind, context=(), required_context=()):
    return ExtractionUnit(unit_id="u_" + digest([content_digest(text), start, end, kind])[:32],
                          start=start, end=end, kind=kind, context=list(context)[-16:], required_context=list(required_context))


def scan_units(text: str) -> list[ExtractionUnit]:
    if not text:
        raise ValueError("empty extraction source")
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    units = []
    headings = []
    i = 0
    while i < len(lines):
        begin = i
        line = lines[i]
        heading, fence = _HEADING.match(line), _FENCE.match(line)
        context = [span for _, span in headings]
        if not line.strip():
            kind = "whitespace"
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
        elif heading:
            kind = "heading"
            i += 1
            level = len(heading.group(1))
            headings = [(depth, span) for depth, span in headings if depth < level]
            headings.append((level, Span(start=offsets[begin], end=offsets[i])))
        elif fence:
            kind = "code"
            marker = fence.group(1)
            i += 1
            while i < len(lines):
                closing = lines[i].lstrip()
                i += 1
                if closing.startswith(marker) and set(closing.strip()) <= {marker[0]}:
                    break
        elif i + 1 < len(lines) and "|" in line and _TABLE_SEPARATOR.match(lines[i + 1]):
            kind = "table"
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                i += 1
        else:
            kind = "list" if _LIST.match(line) else "paragraph"
            i += 1
            while i < len(lines) and lines[i].strip():
                if _HEADING.match(lines[i]) or _FENCE.match(lines[i]):
                    break
                if i + 1 < len(lines) and "|" in lines[i] and _TABLE_SEPARATOR.match(lines[i + 1]):
                    break
                if kind == "paragraph" and _LIST.match(lines[i]):
                    break
                i += 1
        units.append(unit_for(text, offsets[begin], offsets[i], kind, context))
    assert_partition(text, units)
    return units


def assert_partition(text, units, *, start=0, end=None):
    end = len(text) if end is None else end
    cursor = start
    for unit in units:
        if unit.start != cursor or unit.end > end or text[unit.start:unit.end] == "":
            raise ValueError("extraction target ranges are not an exact partition")
        cursor = unit.end
    if cursor != end:
        raise ValueError("extraction target ranges omit source characters")


def split_unit(text, unit, *, max_tokens, counter, force=False):
    """Only sentence/line boundaries; an oversized unsplittable line fails."""
    if not force and counter.count_text(text[unit.start:unit.end]) <= max_tokens:
        return [unit]
    piece = text[unit.start:unit.end]
    boundaries = [unit.start]
    cursor = unit.start
    context = list(unit.context)
    required_context = list(unit.required_context)
    lines = piece.splitlines(keepends=True)
    if unit.kind == "table" and len(lines) >= 2 and _TABLE_SEPARATOR.match(lines[1]):
        required_context = [Span(start=unit.start, end=unit.start + len(lines[0]) + len(lines[1]))]
    elif unit.kind == "code" and _FENCE.match(piece):
        required_context = [Span(start=unit.start, end=unit.start + len(lines[0]))]
    for line in lines:
        if unit.kind in {"paragraph", "list", "heading"}:
            boundaries.extend(cursor + match.end() for match in _SENTENCE.finditer(line) if cursor + match.end() < unit.end)
        cursor += len(line)
        boundaries.append(cursor)
    boundaries = sorted(set(boundaries))
    if force:
        choices = [p for p in boundaries if unit.start < p < unit.end]
        if not choices:
            raise ValueError("extraction minimum source granularity reached")
        middle = min(choices, key=lambda p: (abs(p - (unit.start + unit.end) / 2), p))
        pieces = [unit_for(text, unit.start, middle, unit.kind, context, required_context), unit_for(text, middle, unit.end, unit.kind, context, required_context)]
    else:
        pieces = []
        begin = unit.start
        while begin < unit.end:
            choices = [p for p in boundaries if p > begin and counter.count_text(text[begin:p]) <= max_tokens]
            if not choices:
                raise ValueError("extraction source line exceeds safe unit capacity")
            finish = max(choices)
            pieces.append(unit_for(text, begin, finish, unit.kind, context, required_context))
            begin = finish
    assert_partition(text, pieces, start=unit.start, end=unit.end)
    return pieces
