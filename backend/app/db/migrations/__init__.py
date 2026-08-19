"""Small versioned migrations required for additive schema upgrades."""

from app.db.migrations.p0_04 import apply_p0_04_migration
from app.db.migrations.p0_05 import apply_p0_05_migration
from app.db.migrations.p0_06 import apply_p0_06_migration
from app.db.migrations.p0_07 import apply_p0_07_migration
from app.db.migrations.p0_07_feedback import apply_p0_07_feedback_migration
from app.db.migrations.p0_09 import apply_p0_09_migration
from app.db.migrations.p0_10 import apply_p0_10_migration
from app.db.migrations.p0_11_resource_batches import apply_p0_11_resource_batches_migration
from app.db.migrations.p0_12_superseded_generation_jobs import apply_p0_12_superseded_generation_jobs_migration

__all__ = [
    "apply_p0_04_migration",
    "apply_p0_05_migration",
    "apply_p0_06_migration",
    "apply_p0_07_migration",
    "apply_p0_07_feedback_migration",
    "apply_p0_09_migration",
    "apply_p0_10_migration",
    "apply_p0_11_resource_batches_migration",
    "apply_p0_12_superseded_generation_jobs_migration",
]
