"""Opt-in contiguous teaching units; old chunk strategies remain unchanged.

No model/DB access. Preserve exact source spans, physical pages and node scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from markdown_it import MarkdownIt

from app.core.retrieval.markdown_structure import MAX_ATOMIC_CHARS, _blocks, _document_sections

EVIDENCE_STRATEGY = "markdown_evidence_v2"
TARGET_CHARS = 900
SOFT_MAX_CHARS = 1200
MIN_CHARS = 200
OVERLAP_CHARS = 100
_PARSER = MarkdownIt("commonmark").enable("table")


@dataclass
class Unit:
    start: int
    end: int
    sections: tuple[str, ...]
    points: tuple[str, ...]
    page: int | None
    atomic: bool = False


def protected_ranges(text: str, *, pdf=False) -> list[tuple[int, int]]:
    """Include indented code, tables, inline/multiline code and display math."""
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    ranges = []
    for token in _PARSER.parse(text):
        if token.type in {"fence", "code_block", "table_open"} and token.map:
            ranges.append((offsets[token.map[0]], offsets[token.map[1]]))
    # Explicit fences inside raw HTML are not always parsed by CommonMark.
    fence, first = None, 0
    math, math_first = None, 0
    for index, line in enumerate(lines):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                ranges.append((offsets[first], offsets[index + 1]))
                fence = None
        elif match:
            fence, first = match[1], index
        elif math:
            if line.strip() == math:
                ranges.append((offsets[math_first], offsets[index + 1]))
                math = None
        elif line.strip() in {"$$", r"\["}:
            math, math_first = ("$$" if line.strip() == "$$" else r"\]"), index
    if fence or math:
        raise ValueError("unclosed code/math block")
    # Only parse inline code within prose gaps, never across fenced regions.
    merged = _merge_ranges(ranges)
    boundaries = [0, *[x for pair in merged for x in pair], len(text)]
    for index in range(0, len(boundaries) - 1, 2):
        start, end = boundaries[index:index + 2]
        pattern = r"(?<![\\`])(`+)(?!`)([^\n]*?)(?<!`)\1(?!`)" if pdf else r"(?<![\\`])(`+)(?!`)(.*?)(?<!`)\1(?!`)"
        for match in re.finditer(pattern, text[start:end], re.S):
            # Short inline code does not require a complete paragraph to be
            # atomic, but its own bytes must never be broken by long fallback.
            ranges.append((start + match.start(), start + match.end()))
    return _merge_ranges(ranges)


def _merge_ranges(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def _points(document, section):
    mapping = document.metadata.get("section_knowledge_points", {})
    if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, list)
                                            or any(not isinstance(p, str) for p in v) for k, v in mapping.items()):
        raise ValueError("invalid heading/node mapping")
    if not mapping:
        return tuple(document.metadata.get("knowledge_points", []))
    keys = [key for key in mapping if section == key or (section or "").startswith(key + " / ")]
    return tuple(mapping[max(keys, key=len)]) if keys else ()


def _compatible(left, right):
    return left.page == right.page and set(left.points) == set(right.points)


def _join(left, right):
    return Unit(left.start, max(left.end, right.end), tuple(dict.fromkeys((*left.sections, *right.sections))),
                left.points, left.page, left.atomic or right.atomic)


def evidence_chunks(document: Document, *, chunk_size=TARGET_CHARS, chunk_overlap=OVERLAP_CHARS):
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("invalid evidence chunk size/overlap")
    limit = max(chunk_size, SOFT_MAX_CHARS)
    text = document.page_content
    protected = protected_ranges(text, pdf=bool(document.metadata.get("page_spans")))
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "。", ". ", "；", "; ", "\n", " ", ""], add_start_index=True)
    units = []
    for section_start, section_end, section, page in _document_sections(document):
        points = _points(document, section)
        sections = (section,) if section else ()
        section_units = []
        for a, b, atomic in _blocks(text[section_start:section_end]):
            start, end = section_start + a, section_start + b
            # Merge adjacent blocks touched by the same protected span. This
            # retains blank lines inside indented code and mathematical blocks.
            matching = [(x, y) for x, y in protected if x < end and y > start]
            if matching:
                start = max(section_start, min([start, *[x for x, _ in matching]]))
                end = min(section_end, max([end, *[y for _, y in matching]]))
                atomic = True
            unit = Unit(start, end, sections, points, page, atomic)
            if section_units and unit.start < section_units[-1].end:
                section_units[-1] = _join(section_units[-1], unit)
            else:
                section_units.append(unit)
        # A heading and its first block form one unit when they fit. Heading
        # text is never emitted as a standalone retrieval hit if content follows.
        if len(section_units) > 1 and re.fullmatch(r"(?:\s*#{1,6}[^\n]*\n?)+\s*", text[section_units[0].start:section_units[0].end]):
            first, second = section_units[:2]
            if second.end - first.start <= (MAX_ATOMIC_CHARS if second.atomic else limit):
                section_units[:2] = [_join(first, second)]
        for unit in section_units:
            body = text[unit.start:unit.end]
            if unit.atomic:
                if len(body.strip()) > MAX_ATOMIC_CHARS:
                    raise ValueError("atomic evidence unit exceeds safety bound")
                units.append(unit)
            elif len(body) > limit:
                for piece in splitter.create_documents([body]):
                    begin = unit.start + int(piece.metadata["start_index"])
                    units.append(Unit(begin, begin + len(piece.page_content), sections, points, page))
            else:
                units.append(unit)
    packed = []
    for unit in units:
        if packed and _compatible(packed[-1], unit):
            previous = packed[-1]
            length, combined = previous.end - previous.start, unit.end - previous.start
            if combined <= limit and (length < chunk_size or unit.end - unit.start < MIN_CHARS):
                packed[-1] = _join(previous, unit)
                continue
        packed.append(unit)
    result = []
    for unit in packed:
        value = text[unit.start:unit.end]
        start = unit.start + len(value) - len(value.lstrip())
        value = value.strip()
        if not value:
            continue
        # Never silently discard a meaningful short definition or formula.
        if not re.search(r"[\w\u3400-\u9fff]", value):
            continue
        if re.fullmatch(r"(?:\s*#{1,6}[^\n]*\n?)+\s*", value):
            # Retain the heading in source/section paths, not as an empty
            # standalone evidence hit. A differently mapped following section
            # must not inherit its nodes merely to satisfy a length target.
            continue
        result.append(Document(page_content=value, metadata={
            "start_index": start, "section": " | ".join(unit.sections) or None,
            "source_start_index": start, "source_end_index": start + len(value),
            "sections": list(unit.sections), "knowledge_points": list(unit.points),
            "atomic_block": unit.atomic, "oversized_block": len(value) > limit,
            "short_context": len(value) < MIN_CHARS,
            **({"page": unit.page} if unit.page is not None else {}),
        }))
    return result
