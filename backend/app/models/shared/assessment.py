"""Shared contract constants for structured, staged assessments."""

from typing import Final


ASSESSMENT_QUESTION_QUOTAS: Final[dict[str, int]] = {
    "single_choice": 2,
    "multiple_choice": 2,
    "short_answer": 2,
}

ASSESSMENT_SCORE_BY_TYPE: Final[dict[str, float]] = {
    "single_choice": 15.0,
    "multiple_choice": 20.0,
    "short_answer": 15.0,
}

ASSESSMENT_TOTAL_SCORE: Final[float] = 100.0
ASSESSMENT_SCORE_DECIMAL_PLACES: Final[int] = 1
