"""Language-aware selection scores, separate from model relevance scores."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SELECTION_VERSION = "english-relevance-bonus-v1"
LANGUAGE_PATH_VERSION = "canonical-reference-path-v1"


@dataclass(frozen=True)
class SelectionScore:
    language: str
    bonus: float
    score: float


def source_language(source_path: object) -> str:
    """Recognize the KB's canonical relative layout, never guess from text."""
    if not isinstance(source_path, str) or ":" in source_path or "\x00" in source_path:
        return "unknown"
    parts = source_path.replace("\\", "/").split("/")
    if len(parts) < 3 or any(part in {"", ".", ".."} for part in parts):
        return "unknown"
    prefix = [part.casefold() for part in parts[:2]]
    if prefix == ["references", "en"]:
        return "en"
    if prefix in (["references", "zh"], ["teaching", "zh"]):
        return "zh"
    return "unknown"


def selection_score(
    relevance: float,
    source_path: object,
    settings: Any,
    *,
    verified: bool,
    minimum_score: float | None = None,
) -> SelectionScore:
    """Only verified, relevance-qualified English evidence receives a bonus.

    Callers still enforce the original relevance threshold. This score is a
    bounded selection preference, not a probability or an Evidence score.
    Legacy injected settings without the new field keep their old ordering.
    """
    language = source_language(source_path) if verified else "unknown"
    floor = float(getattr(settings, "retrieval_min_normalized_score", 0.35))
    if minimum_score is not None:
        floor = max(floor, minimum_score)
    configured_bonus = float(getattr(settings, "retrieval_english_score_bonus", 0.0))
    value = relevance
    if verified and language == "en" and relevance >= floor:
        value = min(1.0, relevance + configured_bonus)
    return SelectionScore(language=language, bonus=value - relevance, score=value)
