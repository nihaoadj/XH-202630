"""Opt-in structural Markdown chunks with exact normalized-source offsets.

This is deliberately not a Markdown renderer. Fenced blocks and pipe tables
remain literal source; nothing from a retrieved document is executed.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter


STRUCTURE_STRATEGY = "markdown_structure_v1"
MAX_ATOMIC_CHARS = 12000
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _closing(line: str, fence: str) -> bool:
    return bool(re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line))


def _sections(text: str) -> Iterator[tuple[int, int, str | None]]:
    stack: dict[int, str] = {}
    start = offset = 0
    section: str | None = None
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if fence is not None:
            if _closing(line, fence):
                fence = None
        elif marker:
            fence = marker.group(1)
        else:
            heading = _HEADING.match(line)
            if heading:
                if offset > start:
                    yield start, offset, section
                level = len(heading.group(1))
                stack = {key: value for key, value in stack.items() if key < level}
                stack[level] = re.sub(r"\s+#+\s*$", "", heading.group(2)).strip()
                section = " / ".join(stack[key] for key in sorted(stack))
                start = offset
        offset += len(line)
    if fence is not None:
        raise ValueError("Unclosed Markdown fence; preserve source and repair before indexing")
    if offset > start:
        yield start, offset, section


def _blocks(text: str) -> Iterator[tuple[int, int, bool]]:
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def is_table(index: int) -> bool:
        return index + 1 < len(lines) and "|" in lines[index] and bool(_TABLE_RULE.match(lines[index + 1]))

    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        start = index
        fence = _FENCE.match(lines[index])
        atomic = bool(fence) or is_table(index)
        if fence:
            index += 1
            while index < len(lines) and not _closing(lines[index], fence.group(1)):
                index += 1
            if index == len(lines):
                raise ValueError("Unclosed Markdown fence")
            index += 1
        elif is_table(index):
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                index += 1
        else:
            index += 1
            while index < len(lines) and lines[index].strip():
                if _FENCE.match(lines[index]) or is_table(index):
                    break
                index += 1
        yield offsets[start], offsets[index], atomic


def _document_sections(document: Document) -> Iterator[tuple[int, int, str | None, int | None]]:
    """Use verified page spans for PDF-derived text, never guess its headings."""
    spans = document.metadata.get("page_spans")
    if spans is None:
        for start, end, section in _sections(document.page_content):
            yield start, end, section, None
        return
    if not isinstance(spans, list) or not spans:
        raise ValueError("page_spans must be a non-empty ordered page list")
    lines = document.page_content.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    next_line = 1
    validated = []
    for expected_page, span in enumerate(spans, 1):
        if not isinstance(span, dict) or any(
            type(span.get(key)) is not int for key in ("page", "line_start", "line_end")
        ):
            raise ValueError("page_spans requires integer page/line_start/line_end")
        page, start, end = span["page"], span["line_start"], span["line_end"]
        if page != expected_page or start != next_line or not start <= end <= len(lines):
            raise ValueError("page_spans must cover ordered contiguous pages and lines")
        if lines[start - 1].strip() != f"## PDF page {page}":
            raise ValueError("page_spans marker does not match the physical page")
        validated.append((offsets[start - 1], offsets[end], f"PDF page {page}", page))
        next_line = end + 1
    if next_line != len(lines) + 1:
        raise ValueError("page_spans does not cover the complete normalized document")
    yield from validated


def structural_chunks(document: Document, *, chunk_size: int, chunk_overlap: int) -> list[Document]:
    """Split within headings, preserving code/tables and character locations.

    Ordinary paragraphs use the legacy length fallback. Atomic blocks can
    exceed the character target, but never the explicit safety bound. Their
    length is observable; callers must not interpret this as a token budget.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""],
        add_start_index=True,
    )
    result: list[Document] = []
    mapping = document.metadata.get("section_knowledge_points", {})
    if not isinstance(mapping, dict) or any(
        not isinstance(key, str) or not isinstance(values, list)
        or any(not isinstance(point, str) for point in values)
        for key, values in mapping.items()
    ):
        raise ValueError("section_knowledge_points must be a heading-path mapping")
    for section_start, section_end, section, page in _document_sections(document):
        points = document.metadata.get("knowledge_points", [])
        if mapping:
            matching = [key for key in mapping if section == key or (section or "").startswith(key + " / ")]
            points = mapping[max(matching, key=len)] if matching else []
        text = document.page_content[section_start:section_end]
        pending: tuple[int, int, bool] | None = None
        packed: list[tuple[int, int, bool]] = []
        blocks = _blocks(text) if page is None else [(0, len(text), False)]
        for start, end, atomic in blocks:
            if pending is not None:
                if not atomic and end - pending[0] <= chunk_size:
                    pending = (pending[0], end, False)
                    continue
                packed.append(pending)
                pending = None
            if atomic:
                packed.append((start, end, True))
            else:
                pending = (start, end, False)
        if pending is not None:
            packed.append(pending)
        for start, end, atomic in packed:
            block = text[start:end]
            if atomic and len(block) > MAX_ATOMIC_CHARS:
                raise ValueError(f"Markdown atomic block exceeds {MAX_ATOMIC_CHARS} characters")
            pieces = (
                [Document(page_content=block.strip(), metadata={
                    "start_index": len(block) - len(block.lstrip()),
                })]
                if atomic else splitter.create_documents([block])
            )
            for piece in pieces:
                piece.metadata.update(
                    start_index=section_start + start + int(piece.metadata["start_index"]),
                    section=section,
                    knowledge_points=list(points),
                    atomic_block=atomic,
                    oversized_block=len(piece.page_content) > chunk_size,
                )
                if page is not None:
                    piece.metadata["page"] = page
                result.append(piece)
    return result
