"""Small versioned migrations required for additive schema upgrades."""

from app.db.migrations.p0_04 import apply_p0_04_migration

__all__ = ["apply_p0_04_migration"]
