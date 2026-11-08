"""Versioned edit whitelist, protected-content table and frozen rules asset.

The rules asset is a static JSON in this package. Its canonical hash is frozen
into every new Run's ``SourceLocatingPolicy`` so a modified rules file can be
detected before any locating executes (``rules_drift``).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .types import EditOp

RULES_PATH = Path(__file__).resolve().parent / "rules_v1.json"

_NUMBER = re.compile(
    r"[0-9]+(?:\.[0-9]+)?%?|[0-9]+(?:\.[0-9]+)?\s*[-~～]\s*[0-9]+(?:\.[0-9]+)?"
    r"|[〇零一二三四五六七八九十百千万亿两]+"
)
_HSPACE = re.compile(r"[ \t]")


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def rules_digest(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


@dataclass(frozen=True)
class Thresholds:
    max_edits: int
    max_edit_ratio: float
    min_effective_chars: int
    min_score_margin: float
    max_unit_chars: int
    max_candidate_chars: int
    max_dp_cells_per_ref: int
    max_distinct_intervals: int
    max_work_cells_per_batch: int


@dataclass(frozen=True)
class Rules:
    version: str
    hash: str
    thresholds: Thresholds
    function_words: frozenset
    typo_pairs: frozenset
    protected: dict  # category -> tuple of words

    @property
    def protected_words(self):
        return frozenset(w for words in self.protected.values() for w in words)


def load_rules(path: Path = RULES_PATH) -> Rules:
    """Load and validate the frozen rules asset."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != "rules-v1":
        raise ValueError("unknown rules asset version")
    th = raw["thresholds"]
    thresholds = Thresholds(
        max_edits=th["max_edits"],
        max_edit_ratio=th["max_edit_ratio"],
        min_effective_chars=th["min_effective_chars"],
        min_score_margin=th["min_score_margin"],
        max_unit_chars=th["max_unit_chars"],
        max_candidate_chars=th["max_candidate_chars"],
        max_dp_cells_per_ref=th["max_dp_cells_per_ref"],
        max_distinct_intervals=th["max_distinct_intervals"],
        max_work_cells_per_batch=th["max_work_cells_per_batch"],
    )
    if not 1 <= thresholds.max_edits <= 2:
        raise ValueError("max_edits out of range")
    typo_pairs = frozenset(
        (a, b) for a, b in raw["controlled_typo_pairs"]
    )
    protected = {k: tuple(v) for k, v in raw["protected"].items()}
    rules = Rules(
        version=raw["version"],
        hash=rules_digest(raw),
        thresholds=thresholds,
        function_words=frozenset(raw["function_words"]),
        typo_pairs=typo_pairs,
        protected=protected,
    )
    return rules


def _word_spans(text: str, start: int, end: int, words) -> list[tuple[int, int, str]]:
    """Longest-match spans for a set of protected words within [start, end)."""
    spans: list[tuple[int, int, str]] = []
    i = start
    while i < end:
        for word in sorted(words, key=len, reverse=True):
            if text.startswith(word, i):
                spans.append((i, i + len(word), word))
                i += len(word)
                break
        else:
            i += 1
    return spans


def protected_fragments(text: str, start: int, end: int, rules: Rules) -> list[tuple[int, int, str]]:
    """Ordered protected fragments: numbers plus protected words."""
    fragments: list[tuple[int, int, str]] = []
    for match in _NUMBER.finditer(text[start:end]):
        fragments.append((start + match.start(), start + match.end(), "number"))
    for category, words in rules.protected.items():
        for s, e, _ in _word_spans(text, start, end, words):
            fragments.append((s, e, category))
    fragments.sort()
    return fragments


def protected_signature(text: str, start: int, end: int, rules: Rules) -> tuple[tuple[str, str], ...]:
    """Ordered (category, value) of protected fragments for comparison."""
    return tuple((kind, text[s:e]) for s, e, kind in protected_fragments(text, start, end, rules))


def _inside_fragments(index: int, fragments) -> bool:
    for s, e, _ in fragments:
        if s <= index < e:
            return True
    return False


def classify_edit(op: EditOp, ref: str, cand: str, rules: Rules,
                  *, strict_duplicates: bool = False) -> str | None:
    """Return the allowed edit category id, or None if the edit is not allowed.

    Only three narrow categories exist in v1: the model omitting a whitelisted
    function word ("ins" of a function word), the model duplicating an adjacent
    character ("del" of a repeated char), or a controlled confusable-typo
    substitution. Anything else (synonym swaps, reordering, subject/object
    replacement) is refused by design.
    """
    if op.op == "sub":
        pair = (op.ref_char, op.cand_char)
        if pair in rules.typo_pairs or (op.cand_char, op.ref_char) in rules.typo_pairs:
            return "controlled_typo"
        return None
    if op.op == "ins":
        # The model omitted a character that the candidate text contains.
        return "omitted_function_word" if op.cand_char in rules.function_words else None
    if op.op == "del":
        # The model added a spurious character; allowed only when it repeats a
        # neighbour (an accidental duplication), never an unrelated insertion.
        prev = ref[op.ref_index - 1] if 0 <= op.ref_index - 1 < len(ref) else ""
        nxt = ref[op.ref_index + 1] if 0 <= op.ref_index + 1 < len(ref) else ""
        if op.ref_char and op.ref_char in (prev, nxt):
            if strict_duplicates:
                neighbours = cand[max(0, op.cand_index - 1):op.cand_index + 1]
                if op.ref_char not in neighbours:
                    return None
            return "duplicated_char"
        return None
    return None


def edits_allowed(ops: list[EditOp], ref: str, cand: str, rules: Rules,
                  *, strict_duplicates: bool = False):
    """Return ``(categories, all_allowed, protected_violation)``.

    ``all_allowed`` is False when any edit is outside the whitelist (an unknown
    edit such as a synonym swap). ``protected_violation`` is True when protected
    content (numbers, negation, quantifiers, conditionals, relations, units/
    versions) changed value, order or boundary, or when an otherwise-allowed
    edit touches a protected fragment. These are independent: a synonym swap is
    not-allowed but not protected, while a changed number is both unknown and
    protected. Callers report ``protected_content_changed`` over
    ``edit_not_allowed`` when both hold.
    """
    categories: list[str] = []
    all_allowed = True
    ref_fragments = protected_fragments(ref, 0, len(ref), rules)
    cand_fragments = protected_fragments(cand, 0, len(cand), rules)
    for op in ops:
        category = classify_edit(op, ref, cand, rules, strict_duplicates=strict_duplicates)
        if category is None:
            all_allowed = False
            continue
        if op.op in ("sub", "del") and _inside_fragments(op.ref_index, ref_fragments):
            return tuple(categories), all_allowed, True
        if op.op in ("sub", "ins") and _inside_fragments(op.cand_index, cand_fragments):
            return tuple(categories), all_allowed, True
        if category not in categories:
            categories.append(category)
    # Whole-fragment value/order/boundary comparison as a final guard.
    if protected_signature(ref, 0, len(ref), rules) != protected_signature(cand, 0, len(cand), rules):
        return tuple(categories), all_allowed, True
    return tuple(categories), all_allowed, False
