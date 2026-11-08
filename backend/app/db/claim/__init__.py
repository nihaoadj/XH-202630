"""Claim persistence package.

Names are resolved lazily (PEP 562) because the SQL/memory repositories import
the audit repository, which imports the shared database module.  Eager imports
here made every metadata-only consumer (report watermarks, migrations) part of
that cycle.  The public API stays identical while the import graph stops
closing on itself.

Each branch imports one module with a literal name, so the architecture check can
verify the boundary statically instead of treating the import as unresolvable.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BaseClaimRepository",
    "MemoryClaimExtractionRepository",
    "MemoryClaimRepository",
    "SQLClaimExtractionRepository",
    "SQLClaimRepository",
    "create_claim_repository",
    "get_claim_repository",
]


def __getattr__(name: str) -> Any:
    value: Any
    if name == "BaseClaimRepository":
        from app.db.claim.base import BaseClaimRepository

        value = BaseClaimRepository
    elif name == "MemoryClaimRepository":
        from app.db.claim.memory import MemoryClaimRepository

        value = MemoryClaimRepository
    elif name == "SQLClaimRepository":
        from app.db.claim.sql_repository import SQLClaimRepository

        value = SQLClaimRepository
    elif name == "MemoryClaimExtractionRepository":
        from app.db.claim.extraction import MemoryClaimExtractionRepository

        value = MemoryClaimExtractionRepository
    elif name == "SQLClaimExtractionRepository":
        from app.db.claim.extraction import SQLClaimExtractionRepository

        value = SQLClaimExtractionRepository
    elif name == "get_claim_repository":
        from app.db.claim.repository import get_claim_repository

        value = get_claim_repository
    elif name == "create_claim_repository":
        from app.db.claim.repository import create_claim_repository

        value = create_claim_repository
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
