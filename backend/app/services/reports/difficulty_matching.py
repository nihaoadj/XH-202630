"""Deterministic, versioned resource-difficulty matching helpers."""

from __future__ import annotations

from dataclasses import dataclass


STRATEGY_VERSION = "declared-band/v1"
_BANDS = {
    "初级": 0.35,
    "beginner": 0.35,
    "基础": 0.35,
    "中级": 0.65,
    "intermediate": 0.65,
    "高级": 0.85,
    "advanced": 0.85,
}


@dataclass(frozen=True)
class DifficultyMatch:
    score: float | None
    source: str
    gap: float | None
    status: str
    reason_codes: tuple[str, ...]


def normalize_declared_difficulty(value: str | None) -> tuple[float | None, str]:
    """Return a conservative score; unknown labels are intentionally unmeasured."""
    if not value:
        return None, "unavailable"
    score = _BANDS.get(str(value).strip().casefold())
    return (score, "declared_band") if score is not None else (None, "unavailable")


def match_difficulty(*, learner_readiness: float | None, declared_difficulty: str | None) -> DifficultyMatch:
    score, source = normalize_declared_difficulty(declared_difficulty)
    if learner_readiness is None:
        return DifficultyMatch(score, source, None, "not_measured", ("LEARNER_READINESS_NOT_MEASURED",))
    if score is None:
        return DifficultyMatch(None, source, None, "not_measured", ("RESOURCE_DIFFICULTY_UNAVAILABLE",))
    gap = round(score - learner_readiness, 6)
    if gap < -0.15:
        status = "too_easy"
    elif gap <= 0.10:
        status = "matched"
    elif gap <= 0.25:
        status = "challenging"
    else:
        status = "too_hard"
    return DifficultyMatch(score, source, gap, status, (f"DIFFICULTY_{status.upper()}",))


__all__ = ["DifficultyMatch", "STRATEGY_VERSION", "match_difficulty", "normalize_declared_difficulty"]
