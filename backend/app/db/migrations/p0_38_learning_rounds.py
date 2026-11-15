"""Add learning-round facts without rewriting existing jobs or attempts."""

from __future__ import annotations

from sqlalchemy import inspect, select

from app.db.feedback.round_models import ROUND_MODELS


def apply_p0_38_learning_rounds_migration(engine) -> None:
    from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration

    with engine.begin() as connection:
        for model in ROUND_MODELS:
            model.__table__.create(connection, checkfirst=True)
    apply_p0_35_report_read_model_migration(engine)


def rollback_p0_38_learning_rounds_migration(engine) -> None:
    """Only empty maintenance copies can physically remove the new tables."""
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        for model in ROUND_MODELS:
            if model.__tablename__ in existing and connection.execute(select(model.__table__).limit(1)).first():
                raise ValueError("ROUND_ROLLBACK_HAS_FACTS")
        for model in reversed(ROUND_MODELS):
            model.__table__.drop(connection, checkfirst=True)
