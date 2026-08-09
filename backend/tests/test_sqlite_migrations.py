"""SQLite 历史表结构迁移测试。"""

from sqlalchemy import create_engine, text

from app.db.database import (
    _migrate_sqlite_feedback_records,
    _migrate_sqlite_generated_resources,
)


def _columns(engine, table_name: str) -> set[str]:
    with engine.begin() as conn:
        return {
            row[1]
            for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
        }


def test_generated_resources_and_feedback_records_migrations_fill_legacy_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE generated_resources (
                    resource_id VARCHAR(64) PRIMARY KEY,
                    learner_id VARCHAR(64) NOT NULL,
                    topic VARCHAR(256) NOT NULL,
                    resource_type VARCHAR(32) NOT NULL,
                    difficulty VARCHAR(16) NOT NULL,
                    knowledge_points JSON,
                    source_refs JSON,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE feedback_records (
                    feedback_id VARCHAR(64) PRIMARY KEY,
                    learner_id VARCHAR(64) NOT NULL,
                    resource_id VARCHAR(64) NOT NULL,
                    correct_rate FLOAT NOT NULL,
                    decision VARCHAR(32) NOT NULL,
                    answers JSON,
                    created_at DATETIME
                )
                """
            )
        )

    _migrate_sqlite_generated_resources(engine)
    _migrate_sqlite_feedback_records(engine)

    generated_columns = _columns(engine, "generated_resources")
    feedback_columns = _columns(engine, "feedback_records")

    assert {
        "storage_type",
        "content_text",
        "file_path",
        "file_size",
        "mime_type",
        "learning_path_node",
        "review_status",
        "review_id",
        "claim_count",
        "hallucination_rate",
        "difficulty_match",
        "run_id",
        "version",
        "parent_resource_id",
        "exercise_items",
    }.issubset(generated_columns)

    assert {
        "feedback_type",
        "time_spent_seconds",
        "completed",
        "self_rating",
        "practice_result",
        "decision_reason",
        "next_action",
        "recommended_topics",
        "updated_knowledge_states",
        "regenerate_suggestion",
    }.issubset(feedback_columns)
