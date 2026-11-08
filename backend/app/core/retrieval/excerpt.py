"""Deterministic, provenance-preserving excerpt windows for Claim retrieval.

The legacy path takes a prefix of the normalized chunk text.  That silently cut
off qualifiers, table headers and negations that lived later in a chunk, so a
Claim could look unsupported simply because the decisive sentence was outside the
first N characters.  This module returns bounded *contiguous* windows around the
query terms instead.  It never summarizes, never rewrites and never drops a
negation: a window is always an exact slice of the normalized chunk text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.core.retrieval.knowledge_ids import normalize_text, sha256_hex


EXCERPT_STRATEGY_PREFIX = "prefix"
EXCERPT_STRATEGY_CLAIM_WINDOW = "claim_window_v1"
LOCATOR_RULE_VERSION = "claim-window-v1"

_SENTENCE_END = re.compile(r"(?<=[。！？；!?;])\s*|\n+")
_TOKEN = re.compile(r"[0-9A-Za-z_./-]{2,}|[\u4e00-\u9fff]{2,}")
_CONTEXT_INSUFFICIENT = "context_insufficient"


@dataclass(frozen=True)
class ExcerptWindow:
    start: int
    end: int
    text: str
    excerpt_hash: str
    matched_query: str
    locator_rule: str
    reason_code: str | None = None

    @property
    def excerpt_identity(self) -> str:
        return sha256_hex(f"{self.start}:{self.end}:{self.excerpt_hash}")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        if end > start:
            spans.append((start, end))
            start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def query_terms(query: str) -> list[str]:
    """Return deterministic lexical anchors, longest first."""

    normalized = normalize_text(query).casefold()
    terms = [item for item in _TOKEN.findall(normalized) if item.strip()]
    # A CJK term longer than four characters is still useful as a whole phrase;
    # otherwise the raw token is already a reasonable anchor.
    unique = list(dict.fromkeys(terms))
    return sorted(unique, key=lambda value: (-len(value), value))


def _expand_to_sentences(
    text: str,
    spans: Sequence[tuple[int, int]],
    position: int,
    *,
    cap: int,
) -> tuple[int, int]:
    index = 0
    for offset, (start, end) in enumerate(spans):
        if start <= position < end:
            index = offset
            break
    start, end = spans[index]
    # Grow symmetrically while the exact slice stays inside the structural cap.
    lower, upper = index, index
    while True:
        grew = False
        if upper + 1 < len(spans) and spans[upper + 1][1] - spans[lower][0] <= cap:
            upper += 1
            grew = True
        if lower - 1 >= 0 and spans[upper][1] - spans[lower - 1][0] <= cap:
            lower -= 1
            grew = True
        if not grew:
            break
    return spans[lower][0], spans[upper][1]


def build_excerpt_windows(
    chunk_text: str,
    matched_queries: Iterable[str],
    *,
    excerpt_chars: int = 2000,
    structural_cap: int = 4000,
    max_windows: int = 2,
) -> list[ExcerptWindow]:
    """Return bounded exact windows, one per distinct decisive region."""

    text = normalize_text(chunk_text)
    if not text:
        return []
    cap = max(excerpt_chars, min(structural_cap, 10000))
    spans = _sentence_spans(text)
    windows: list[ExcerptWindow] = []
    seen: set[tuple[int, int]] = set()
    for query in dict.fromkeys(normalize_text(item) for item in matched_queries):
        if not query:
            continue
        positions: list[int] = []
        lowered = text.casefold()
        for term in query_terms(query):
            position = lowered.find(term)
            if position >= 0:
                positions.append(position)
        if not positions:
            if len(text) <= cap:
                start, end = 0, len(text)
                rule = "full_chunk"
                reason = _CONTEXT_INSUFFICIENT
            else:
                # Never fabricate a "closest" window: record the gap instead.
                continue
        else:
            start, end = _expand_to_sentences(text, spans, min(positions), cap=cap)
            rule = "sentence_window"
            reason = None
        if end - start > structural_cap:
            end = start + structural_cap
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        excerpt = text[start:end]
        windows.append(ExcerptWindow(
            start=start,
            end=end,
            text=excerpt,
            excerpt_hash=sha256_hex(excerpt),
            matched_query=query,
            locator_rule=rule,
            reason_code=reason,
        ))
        if len(windows) >= max_windows:
            break
    if not windows and len(text) <= cap:
        excerpt = text
        windows.append(ExcerptWindow(
            start=0, end=len(text), text=excerpt,
            excerpt_hash=sha256_hex(excerpt),
            matched_query="",
            locator_rule="full_chunk",
            reason_code=_CONTEXT_INSUFFICIENT,
        ))
    return windows


__all__ = [
    "EXCERPT_STRATEGY_CLAIM_WINDOW",
    "EXCERPT_STRATEGY_PREFIX",
    "ExcerptWindow",
    "LOCATOR_RULE_VERSION",
    "build_excerpt_windows",
    "query_terms",
]
