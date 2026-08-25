"""Downgrade legacy one-shot diagnosis projections without deleting evidence."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260825_p0_26_mastery_evidence_gate"


def apply_p0_26_mastery_evidence_gate_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    required = {"knowledge_states", "ability_state_events", "diagnostic_answers", "diagnostic_questions"}
    if not required.issubset(tables):
        return
    with engine.begin() as connection:
        if "schema_migrations" in tables and connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
        ).first():
            return
        # Only downgrade a state whose *sole* objective source is diagnosis.
        # Later formal attempts remain authoritative, while the original
        # answer/event rows are retained for audit.
        dimension_count = (
            "COUNT(DISTINCT json_extract(q.extra_metadata, '$.diagnostic_dimension'))"
            if engine.url.get_backend_name() == "sqlite" else "COUNT(DISTINCT q.question_id)"
        )
        connection.execute(text(f"""
            UPDATE knowledge_states
            SET mastery_score=NULL, status='unassessed', confidence='none',
                objective_evidence_count=0, distinct_objective_source_count=0,
                last_evidence_type=NULL, last_evidence_id=NULL,
                row_version=COALESCE(row_version, 1) + 1
            WHERE EXISTS (
                SELECT 1 FROM ability_state_events e
                WHERE e.learner_id=knowledge_states.learner_id
                  AND e.knowledge_base_id=knowledge_states.knowledge_base_id
                  AND e.skill_node_id=knowledge_states.skill_node_id
                  AND e.source_type='diagnosis' AND e.verified=1
            )
              AND 1=(SELECT COUNT(*) FROM ability_state_events e
                     WHERE e.learner_id=knowledge_states.learner_id
                       AND e.knowledge_base_id=knowledge_states.knowledge_base_id
                       AND e.skill_node_id=knowledge_states.skill_node_id AND e.verified=1)
              AND ((SELECT COUNT(DISTINCT a.question_id) FROM diagnostic_answers a
                   JOIN diagnostic_questions q ON q.question_id=a.question_id
                   WHERE a.learner_id=knowledge_states.learner_id
                     AND a.knowledge_base_id=knowledge_states.knowledge_base_id
                     AND q.skill_node_id=knowledge_states.skill_node_id) < 3
                   OR (SELECT {dimension_count} FROM diagnostic_answers a
                       JOIN diagnostic_questions q ON q.question_id=a.question_id
                       WHERE a.learner_id=knowledge_states.learner_id
                         AND a.knowledge_base_id=knowledge_states.knowledge_base_id
                         AND q.skill_node_id=knowledge_states.skill_node_id) < 3)
        """))
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["apply_p0_26_mastery_evidence_gate_migration"]
