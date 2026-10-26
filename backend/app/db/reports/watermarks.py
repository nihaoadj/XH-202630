"""Explicit source closure for the report projection; bump protocol on changes."""
from app.db.shared.models import Base
from app.db.shared import extended_models as _extended_models  # noqa: F401

PROTOCOL = "report-read/1"
TABLE = "report_read_watermarks"
WATCHED_TABLES = (
    "learner_profiles", "generated_resources", "generation_jobs", "feedback_records",
    "learning_attempts", "learning_attempt_point_results", "feedback_decisions",
    "knowledge_state_mutations", "learner_profile_versions", "learning_paths",
    "learning_path_nodes", "learning_path_mutations", "feedback_followup_runs",
    "diagnostic_runs", "knowledge_states", "ability_state_events", "learner_curriculum_nodes",
    "learner_tier_progress", "resource_reviews", "resource_claims", "claim_judgements",
    "claim_evidence", "rag_skill_nodes", "skill_node_relations", "knowledge_bases",
    "learning_tracks", "learning_domains",
)
JOB_COLUMNS = {
    "run_id", "batch_id", "learner_id", "knowledge_base_id", "topic", "status",
    "request_payload", "resource_ids", "error_message", "superseded_by_run_id",
    "created_at", "started_at", "finished_at",
}
INDEXES = {
    "ix_report_resources_page": ('generated_resources', 'learner_id, publication_status, published_at DESC, resource_id ASC'),
    "ix_report_resources_parent": ('generated_resources', 'learner_id, publication_status, parent_resource_id'),
    "ix_report_resources_run_type": ('generated_resources', 'learner_id, publication_status, run_id, resource_type'),
    "ix_report_attempts_order": ('learning_attempts', 'learner_id, submitted_at DESC, attempt_id DESC'),
    "ix_report_reviews_latest": ('resource_reviews', 'resource_id, created_at DESC'),
}


def source_columns(source):
    columns = list(Base.metadata.tables[source].columns.keys())
    return [column for column in columns if source != "generation_jobs" or column in JOB_COLUMNS]


def trigger_definitions(source, columns=None):
    columns = source_columns(source) if columns is None else columns
    for operation in ("INSERT", "UPDATE", "DELETE"):
        name = f"trg_report_{source}_{operation.lower()}"
        condition = ""
        if operation == "UPDATE":
            condition = " WHEN " + " OR ".join(f'OLD."{column}" IS NOT NEW."{column}"' for column in columns)
        sql = (f'CREATE TRIGGER "{name}" AFTER {operation} ON "{source}"{condition} '
               f'BEGIN UPDATE "{TABLE}" SET epoch = epoch + 1 WHERE source = \'global\'; END')
        yield name, sql


def expected_triggers():
    return dict(item for source in WATCHED_TABLES for item in trigger_definitions(source))
