import json

from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_19_learner_mastery import (
    MIGRATION_ID,
    apply_p0_19_learner_mastery_migration,
)


def test_p0_19_is_additive_idempotent_and_prefers_canonical_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p0-19.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE knowledge_bases (knowledge_base_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE learner_profiles (learner_id VARCHAR(64) PRIMARY KEY, knowledge_base_id VARCHAR(128), "
            "knowledge_states JSON, theory_scores JSON, weak_points JSON, strong_points JSON, profile_version INTEGER)"
        ))
        connection.execute(text(
            "CREATE TABLE rag_skill_nodes (node_id VARCHAR(128) PRIMARY KEY, knowledge_base_id VARCHAR(128), name VARCHAR(256))"
        ))
        connection.execute(text(
            "CREATE TABLE knowledge_states (state_id VARCHAR(128) PRIMARY KEY, learner_id VARCHAR(64), "
            "knowledge_base_id VARCHAR(128), skill_node_id VARCHAR(128), mastery_score FLOAT, status VARCHAR(32), "
            "evidence JSON, attempt_count INTEGER DEFAULT 0, last_attempt_id VARCHAR(128), row_version INTEGER DEFAULT 1, "
            "last_updated DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE learning_attempts (attempt_id VARCHAR(128) PRIMARY KEY, submitted_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE knowledge_state_mutations (mutation_id VARCHAR(128) PRIMARY KEY, learner_id VARCHAR(64), "
            "knowledge_point_id VARCHAR(128), attempt_id VARCHAR(128), before_state JSON, after_state JSON)"
        ))
        connection.execute(text("INSERT INTO knowledge_bases VALUES ('kb')"))
        connection.execute(text("INSERT INTO rag_skill_nodes VALUES ('skill-a','kb','同名节点')"))
        connection.execute(text("INSERT INTO rag_skill_nodes VALUES ('skill-b','kb','同名节点')"))
        connection.execute(text(
            "INSERT INTO learner_profiles VALUES ('learner','kb',:states,'{}','[]','[]',1)"
        ), {"states": json.dumps({"同名节点": {"score": 0.1}, "skill-a": {"score": 0.9}})})
        connection.execute(text(
            "INSERT INTO knowledge_states VALUES ('state-a','learner','kb','skill-a',0.7,'learning','[]',0,NULL,4,NULL)"
        ))
        connection.execute(text("INSERT INTO learning_attempts VALUES ('attempt-old','2026-08-20 10:00:00')"))
        connection.execute(text(
            "INSERT INTO knowledge_state_mutations VALUES "
            "('mutation-old','learner','skill-a','attempt-old',:before_state,:after_state)"
        ), {
            "before_state": json.dumps({"mastery": 0.6, "status": "learning", "row_version": 3}),
            "after_state": json.dumps({
                "mastery": 0.75, "status": "learning", "objective_evidence_count": 1,
                "distinct_objective_source_count": 1, "attempt_count": 1, "row_version": 4,
            }),
        })

    apply_p0_19_learner_mastery_migration(engine)
    apply_p0_19_learner_mastery_migration(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("knowledge_states")}
    assert {
        "state_schema_version", "self_report_prior", "confidence",
        "objective_evidence_count", "distinct_objective_source_count",
        "last_evidence_type", "last_evidence_id",
    } <= columns
    with engine.begin() as connection:
        assert connection.execute(text("SELECT mastery_score FROM knowledge_states WHERE state_id='state-a'" )).scalar_one() == 0.7
        assert connection.execute(text("SELECT COUNT(*) FROM knowledge_states")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM ability_state_events")).scalar_one() == 1
        event = connection.execute(text(
            "SELECT source_type,verified,after_state FROM ability_state_events"
        )).one()
        assert event.source_type == "learning_attempt"
        assert event.verified == 1
        assert json.loads(event.after_state)["schema_version"] == "2.0"
        state_counts = connection.execute(text(
            "SELECT objective_evidence_count,distinct_objective_source_count,confidence,row_version "
            "FROM knowledge_states WHERE state_id='state-a'"
        )).one()
        assert tuple(state_counts) == (1, 1, "medium", 4)
        profile_cache = connection.execute(text(
            "SELECT knowledge_states,theory_scores,weak_points,strong_points FROM learner_profiles WHERE learner_id='learner'"
        )).one()
        assert set(json.loads(profile_cache.knowledge_states)) == {"skill-a"}
        assert json.loads(profile_cache.knowledge_states)["skill-a"]["score"] == 0.7
        assert json.loads(profile_cache.theory_scores) == {"skill-a": 70.0}
        assert json.loads(profile_cache.weak_points) == []
        assert json.loads(profile_cache.strong_points) == []
        report = connection.execute(text(
            "SELECT mapped_count,canonical_preserved_count,unmapped_count,unmapped_entries "
            "FROM learner_mastery_migration_reports WHERE migration_id=:migration_id"
        ), {"migration_id": MIGRATION_ID}).one()
        assert report.mapped_count == 0
        assert report.canonical_preserved_count == 1
        assert report.unmapped_count == 1
        assert json.loads(report.unmapped_entries)[0]["reason"] == "ambiguous_name"
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
