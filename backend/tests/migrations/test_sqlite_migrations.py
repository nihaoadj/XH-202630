"""SQLite 历史表结构迁移测试。"""

from sqlalchemy import create_engine, text

from app.db.shared.database import (
    _migrate_sqlite_feedback_records,
    _migrate_sqlite_generated_resources,
    _migrate_sqlite_learner_profiles,
    _migrate_sqlite_users,
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


def test_auth_columns_and_learner_owner_are_migrated(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-auth.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    user_id VARCHAR(64) PRIMARY KEY,
                    display_name VARCHAR(128) NOT NULL,
                    identity VARCHAR(64) NOT NULL,
                    education VARCHAR(64) NOT NULL,
                    major VARCHAR(128) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE learner_profiles (
                    learner_id VARCHAR(64) PRIMARY KEY,
                    learner_type VARCHAR(64) NOT NULL,
                    education VARCHAR(32) NOT NULL,
                    major VARCHAR(64) NOT NULL,
                    learning_goal VARCHAR(512) NOT NULL,
                    learning_preferences JSON
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (user_id, display_name, identity, education, major) "
                "VALUES ('user_1', 'alice', '其他', '未填写', '未填写')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO learner_profiles "
                "(learner_id, learner_type, education, major, learning_goal, learning_preferences) "
                "VALUES ('learner_1', '测试', '本科', '计算机', '学习', "
                "'{\"metadata\": {\"user_id\": \"user_1\"}}')"
            )
        )

    _migrate_sqlite_users(engine)
    _migrate_sqlite_learner_profiles(engine)

    assert {"username", "password_hash", "is_active", "last_login_at"}.issubset(
        _columns(engine, "users")
    )
    assert "user_id" in _columns(engine, "learner_profiles")
    with engine.begin() as conn:
        owner = conn.execute(
            text("SELECT user_id FROM learner_profiles WHERE learner_id = 'learner_1'")
        ).scalar_one()
    assert owner == "user_1"
