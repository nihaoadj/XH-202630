"""Add private Claim budgets and an immutable run mode; no production backfill."""
from sqlalchemy import inspect, text

from app.db.shared.models import ClaimExtractionRunORM


def apply_p0_36_claim_extraction_migration(engine) -> None:
    if engine.dialect.name != "sqlite":
        # Preserve the existing optional non-SQLite initialization path.
        # This migration's additive legacy-column upgrade is SQLite specific.
        return
    with engine.begin() as db:
        tables = inspect(db).get_table_names()
        if "agent_runs" not in tables:
            return
        if "claim_extraction_mode" not in {c["name"] for c in inspect(db).get_columns("agent_runs")}:
            db.execute(text("ALTER TABLE agent_runs ADD COLUMN claim_extraction_mode VARCHAR(32) NOT NULL DEFAULT 'legacy_v3' CHECK (claim_extraction_mode IN ('legacy_v3', 'neutral_batch_v1'))"))
        ClaimExtractionRunORM.__table__.create(db, checkfirst=True)
        db.execute(text("CREATE TRIGGER IF NOT EXISTS trg_claim_extraction_mode_immutable BEFORE UPDATE OF claim_extraction_mode ON agent_runs WHEN NEW.claim_extraction_mode != OLD.claim_extraction_mode BEGIN SELECT RAISE(ABORT, 'immutable claim extraction mode'); END"))
        db.execute(text("CREATE TRIGGER IF NOT EXISTS trg_claim_extraction_mode_valid BEFORE INSERT ON agent_runs WHEN NEW.claim_extraction_mode NOT IN ('legacy_v3', 'neutral_batch_v1') BEGIN SELECT RAISE(ABORT, 'invalid claim extraction mode'); END"))


def rollback_p0_36_claim_extraction_migration(engine) -> None:
    """Isolated maintenance only; refuse to erase any neutral run or ledger."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as db:
        tables = inspect(db).get_table_names()
        if "claim_extraction_runs" in tables and db.execute(text("SELECT COUNT(*) FROM claim_extraction_runs")).scalar_one():
            raise ValueError("cannot roll back nonempty extraction ledger")
        columns = {c["name"] for c in inspect(db).get_columns("agent_runs")} if "agent_runs" in tables else set()
        if "claim_extraction_mode" in columns and db.execute(text("SELECT COUNT(*) FROM agent_runs WHERE claim_extraction_mode != 'legacy_v3'")).scalar_one():
            raise ValueError("cannot roll back neutral runs")
        db.execute(text("DROP TRIGGER IF EXISTS trg_claim_extraction_mode_immutable"))
        db.execute(text("DROP TRIGGER IF EXISTS trg_claim_extraction_mode_valid"))
        if "claim_extraction_runs" in tables:
            ClaimExtractionRunORM.__table__.drop(db)
        if "claim_extraction_mode" in columns:
            db.execute(text("ALTER TABLE agent_runs DROP COLUMN claim_extraction_mode"))
