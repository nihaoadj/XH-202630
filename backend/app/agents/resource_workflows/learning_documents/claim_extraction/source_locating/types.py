"""Internal types and stable rejection codes for programmatic source locating.

These are private to the extraction pipeline: they never reach HTTP, trace,
SSE, the public frontend contract or ``ClaimRecord``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LocateCode(str, Enum):
    """Stable private rejection codes (T42 §4.4)."""

    ACCEPTED = "accepted"
    AMBIGUOUS_EXACT = "ambiguous_exact"
    AMBIGUOUS_NORMALIZED = "ambiguous_normalized"
    NO_CANDIDATE = "no_candidate"
    EDIT_NOT_ALLOWED = "edit_not_allowed"
    PROTECTED_CONTENT_CHANGED = "protected_content_changed"
    AMBIGUOUS_APPROXIMATE = "ambiguous_approximate"
    SOURCE_TOO_LONG = "source_too_long"
    WORK_LIMIT_EXCEEDED = "work_limit_exceeded"
    MAPPING_INVALID = "mapping_invalid"
    RULES_DRIFT = "rules_drift"


class WorkLimitExceeded(Exception):
    """Deterministic cell-budget exhaustion; never a provider retry signal."""


class LocateRejected(Exception):
    """A controlled locating rejection (not a programming error)."""

    def __init__(self, code: LocateCode):
        self.code = code
        super().__init__(code.value)


class WorkCounter:
    """Deterministic cell accounting shared by one batch's references."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def charge(self, cells: int) -> None:
        if cells < 0:
            raise ValueError("negative work charge")
        self.used += cells
        if self.used > self.limit:
            raise WorkLimitExceeded("locating cell budget exceeded")


@dataclass(frozen=True)
class LocateResult:
    """Outcome of locating one reference inside one target unit.

    ``start``/``end`` are full-text Python character indexes (half-open) and
    are only meaningful when ``accepted`` is true.
    """

    start: int | None
    end: int | None
    level: str
    code: str
    edits: int = 0
    score: float | None = None
    second_score: float | None = None
    second_gap: float | None = None
    edit_categories: tuple[str, ...] = ()
    work_cells: int = 0

    @property
    def accepted(self) -> bool:
        return self.code == LocateCode.ACCEPTED.value


@dataclass(frozen=True)
class EditOp:
    """One traceback edit: ``sub``/``ins``/``del`` with its positions."""

    op: str
    ref_index: int
    cand_index: int
    ref_char: str = ""
    cand_char: str = ""
