"""Add the optional Claim evidence retrieval side tables.

The migration is purely additive: no existing table, row, unique constraint or
Claim ID material is rewritten.  The rollback only removes the new tables from a
maintenance copy that still has no fact rows, so history is never traded for a
successful downgrade.
"""

from __future__ import annotations

from sqlalchemy import inspect, select


def apply_p0_39_claim_evidence_retrieval_migration(engine) -> None:
    # Imported inside the function: the Claim package imports the audit
    # repository, which imports the database module that calls this migration.
    from app.db.claim.supplement_models import SUPPLEMENT_MODELS
    from app.db.migrations.p0_38_learning_rounds import apply_p0_38_learning_rounds_migration
    from app.db.shared.models import Base
    from app.db.shared import extended_models as _extended_models  # noqa: F401

    with engine.begin() as connection:
        for model in SUPPLEMENT_MODELS:
            if model.__tablename__ not in Base.metadata.tables:
                Base.metadata.tables[model.__tablename__] = model.__table__
            model.__table__.create(connection, checkfirst=True)
    # Keep legacy upgrades ordered: the round tables this feature reads must
    # exist before any supplement row can reference the same runs/resources.
    apply_p0_38_learning_rounds_migration(engine)


def rollback_p0_39_claim_evidence_retrieval_migration(engine) -> None:
    from app.db.claim.supplement_models import SUPPLEMENT_MODELS

    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        for model in SUPPLEMENT_MODELS:
            if model.__tablename__ in existing and connection.execute(
                select(model.__table__).limit(1)
            ).first():
                raise ValueError("CLAIM_EVIDENCE_RETRIEVAL_ROLLBACK_HAS_FACTS")
        for model in reversed(SUPPLEMENT_MODELS):
            model.__table__.drop(connection, checkfirst=True)


__all__ = [
    "apply_p0_39_claim_evidence_retrieval_migration",
    "rollback_p0_39_claim_evidence_retrieval_migration",
]
