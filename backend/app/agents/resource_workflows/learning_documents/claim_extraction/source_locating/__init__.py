"""Programmatic source locating (T42). Single public entry, no executor/Service imports."""
from .api import locate
from .rules import load_rules, rules_digest
from .types import LocateCode, LocateResult, WorkCounter, WorkLimitExceeded

__all__ = ["locate", "load_rules", "rules_digest", "LocateCode", "LocateResult", "WorkCounter", "WorkLimitExceeded"]
