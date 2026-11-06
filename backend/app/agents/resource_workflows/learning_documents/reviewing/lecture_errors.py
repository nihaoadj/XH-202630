"""Typed lecture review validation failures.

Correction decisions are made from these stable codes and fields, never from
exception text.  Only codes in ``CORRECTABLE_CODES`` describe a self-consistent
model output that contradicts another part of the same output; every other code
means the run must stop unpublished.
"""

from __future__ import annotations

CORRECTABLE_CODES = frozenset({
    "TARGET_SET_INCOMPLETE",
    "TARGET_LINK_MISSING",
    "COVERAGE_TARGET_INVALID",
    "DIMENSION_ISSUE_CONFLICT",
    "RISK_SCORE_CONFLICT",
    "RESOLUTION_SET_INCOMPLETE",
    "ISSUE_ID_DUPLICATED",
})

# Documents the boundary for readers; anything outside this tuple aborts.
NON_CORRECTABLE_CODES = (
    "BINDING_MISMATCH", "CONTENT_HASH_MISMATCH", "OMITTED_BLOCKING_ISSUES",
    "LOCATION_OUT_OF_BOUNDS", "EVIDENCE_REF_INVALID", "TEACHING_RULE_UNKNOWN",
    "UNCHANGED_FIXED", "REOPEN_INVALID", "ISSUE_ID_COLLISION", "OPEN_ISSUE_LIMIT",
    "TARGET_EMPTY", "ISSUE_LIMIT",
)


class LectureReviewValidationError(ValueError):
    """A stable, bounded description of one invalid lecture review result.

    Not a frozen dataclass: raising an exception sets ``__traceback__`` on the
    instance, which frozen instances reject.
    """

    def __init__(self, code: str, path: str, hint: str):
        self.code = code
        self.path = path
        self.hint = hint
        super().__init__(f"{code} at {path}: {hint}")

    @property
    def correctable(self) -> bool:
        return self.code in CORRECTABLE_CODES


def require(condition: bool, code: str, path: str, hint: str) -> None:
    """Raise unless ``condition`` holds; keeps validation free of string matching."""
    if not condition:
        raise LectureReviewValidationError(code=code, path=path, hint=hint)
