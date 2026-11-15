"""Conservative, coverage-preserving deduplication of validated SQL evidence."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


VERSION = "sql-content-redundancy-v1"
MIN_CHARS = 160
SHINGLE_SIZE = 5
MIN_LENGTH_RATIO = 0.85
AUDIT_LIMIT = 20
_FACTS = re.compile(
    r"\d+(?:[.,]\d+)*|\b(?:not|no|never|without|cannot|\w+n['’]t)\b|不得|不能|无需|禁止|不|未|无|非|[<>=≤≥≠]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RedundancyCandidate:
    chunk_id: str
    text: str
    document_id: str
    document_version: str
    section: str | None = None
    # Exact node/resource purposes, not transferable query or evidence IDs.
    responsibilities: frozenset[tuple[str | None, str | None]] = frozenset()


def config_payload(threshold: float) -> dict[str, object]:
    return {"version": VERSION, "threshold": threshold, "min_chars": MIN_CHARS,
            "shingle_size": SHINGLE_SIZE, "min_length_ratio": MIN_LENGTH_RATIO,
            "near_scope": "same-document-version-section", "coverage": "single-retained-superset"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n"))
    if _preserve_layout(text):
        return text.strip("\n")  # Indentation and line boundaries can be executable meaning.
    return " ".join(text.split())


def _preserve_layout(text: str) -> bool:
    return (any(mark in text for mark in ("`", "|", "~~~"))
            or bool(re.search(r"(?:^|\n)(?: {4}|\t)", text)))


def _shingles(text: str) -> frozenset[str]:
    return frozenset(text[index:index + SHINGLE_SIZE] for index in range(len(text) - SHINGLE_SIZE + 1))


def filter_redundant(
    ranked: list[RedundancyCandidate], *, threshold: float = 0.90,
) -> tuple[list[str], dict[str, object]]:
    """Keep the existing stable priority; never merge provenance or purposes.

    Near-duplicate matching is lexical, not a claim of semantic equivalence.
    Code/table blocks only participate in full-text exact matching.
    """
    retained: list[tuple[RedundancyCandidate, str, frozenset[str], Counter]] = []
    dropped: list[dict[str, object]] = []
    protected = 0
    comparisons = 0
    for candidate in ranked:
        text = _normalize(candidate.text)
        grams = _shingles(text) if len(text) >= MIN_CHARS else frozenset()
        facts = Counter(value.casefold() for value in _FACTS.findall(text))
        duplicate = None
        coverage_protected = False
        if grams:
            for previous, previous_text, previous_grams, previous_facts in retained:
                if not previous_grams:
                    continue
                exact = text == previous_text
                similarity = 1.0 if exact else 0.0
                if not exact:
                    if threshold >= 1.0:
                        continue
                    same_scope = (candidate.document_id, candidate.document_version, candidate.section) == (
                        previous.document_id, previous.document_version, previous.section)
                    if (not same_scope or facts != previous_facts
                            or _preserve_layout(candidate.text) or _preserve_layout(previous.text)
                            or min(len(text), len(previous_text)) / max(len(text), len(previous_text)) < MIN_LENGTH_RATIO):
                        continue
                    comparisons += 1
                    similarity = len(grams & previous_grams) / len(grams | previous_grams)
                if similarity < threshold:
                    continue
                if not candidate.responsibilities <= previous.responsibilities:
                    coverage_protected = True
                    continue
                duplicate = {"chunk_id": candidate.chunk_id, "retained_chunk_id": previous.chunk_id,
                             "reason": "exact" if exact else "near", "similarity": round(similarity, 4)}
                break
        if duplicate is None:
            retained.append((candidate, text, grams, facts))
            protected += int(coverage_protected)
        else:
            dropped.append(duplicate)
    return [item[0].chunk_id for item in retained], {
        **config_payload(threshold), "status": "enabled", "input_count": len(ranked),
        "retained_count": len(retained), "dropped_count": len(dropped),
        "coverage_protected_count": protected, "near_comparison_count": comparisons,
        "dropped": dropped[:AUDIT_LIMIT], "audit_truncated": len(dropped) > AUDIT_LIMIT,
    }
