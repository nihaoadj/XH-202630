from sqlalchemy import create_engine, text

from app.db.migrations.p0_26_mastery_evidence_gate import apply_p0_26_mastery_evidence_gate_migration


def test_single_question_diagnosis_state_is_downgraded_without_deleting_evidence():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE knowledge_states (learner_id TEXT, knowledge_base_id TEXT, skill_node_id TEXT, mastery_score FLOAT, status TEXT, confidence TEXT, objective_evidence_count INTEGER, distinct_objective_source_count INTEGER, last_evidence_type TEXT, last_evidence_id TEXT, row_version INTEGER)"))
        connection.execute(text("CREATE TABLE ability_state_events (learner_id TEXT, knowledge_base_id TEXT, skill_node_id TEXT, source_type TEXT, verified BOOLEAN)"))
        connection.execute(text("CREATE TABLE diagnostic_answers (learner_id TEXT, knowledge_base_id TEXT, question_id TEXT)"))
        connection.execute(text("CREATE TABLE diagnostic_questions (question_id TEXT, skill_node_id TEXT, extra_metadata JSON)"))
        connection.execute(text("INSERT INTO knowledge_states VALUES ('learner','kb','node',1.0,'mastered','medium',1,1,'diagnosis','event',1)"))
        connection.execute(text("INSERT INTO ability_state_events VALUES ('learner','kb','node','diagnosis',1)"))
        connection.execute(text("INSERT INTO diagnostic_answers VALUES ('learner','kb','question')"))
        connection.execute(text("INSERT INTO diagnostic_questions VALUES ('question','node','{\"diagnostic_dimension\":\"concept\"}')"))

    apply_p0_26_mastery_evidence_gate_migration(engine)

    with engine.connect() as connection:
        state = connection.execute(text("SELECT mastery_score,status,objective_evidence_count FROM knowledge_states")).one()
        evidence_count = connection.execute(text("SELECT COUNT(*) FROM ability_state_events")).scalar_one()
    assert state == (None, "unassessed", 0)
    assert evidence_count == 1
