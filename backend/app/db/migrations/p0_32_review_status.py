"""Normalize legacy resource review decision values to canonical statuses."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260827_p0_32_review_status"


def apply_p0_32_review_status_migration(engine: Engine) -> None:
    """Make persisted review statuses agree with resource/report contracts."""

    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        tables = set(inspect(engine).get_table_names())
        if "resource_reviews" in tables:
            conn.execute(text(
                """
                UPDATE resource_reviews
                SET status = CASE lower(trim(status))
                    WHEN 'approve' THEN 'approved'
                    WHEN 'approved' THEN 'approved'
                    WHEN 'passed' THEN 'approved'
                    WHEN 'revise' THEN 'revision_requested'
                    WHEN 'revision_required' THEN 'revision_requested'
                    WHEN 'revision_requested' THEN 'revision_requested'
                    WHEN 'reject' THEN 'rejected'
                    WHEN 'rejected' THEN 'rejected'
                    WHEN 'needs_review' THEN 'human_review'
                    ELSE status
                END
                WHERE status IS NOT NULL
                """
            ))
        if "generated_resources" in tables:
            conn.execute(text(
                """
                UPDATE generated_resources
                SET review_status = CASE lower(trim(review_status))
                    WHEN 'approve' THEN 'approved'
                    WHEN 'approved' THEN 'approved'
                    WHEN 'passed' THEN 'approved'
                    WHEN 'revise' THEN 'revision_requested'
                    WHEN 'revision_required' THEN 'revision_requested'
                    WHEN 'revision_requested' THEN 'revision_requested'
                    WHEN 'reject' THEN 'rejected'
                    WHEN 'rejected' THEN 'rejected'
                    WHEN 'needs_review' THEN 'human_review'
                    ELSE review_status
                END
                WHERE review_status IS NOT NULL
                """
            ))
        if "schema_migrations" in tables and not conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"),
            {"id": MIGRATION_ID},
        ).first():
            conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["MIGRATION_ID", "apply_p0_32_review_status_migration"]
