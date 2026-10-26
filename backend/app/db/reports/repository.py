"""SQLite metadata/keyset reads; never keeps a Session between calls."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learning_documents.sql_repository import _orm_to_pydantic
from app.db.shared.models import GeneratedResourceORM
from app.models.learning_documents.types import SUPPORTED_RESOURCE_TYPES
from app.db.reports.watermarks import PROTOCOL, TABLE, expected_triggers

_SUPPORTED_REPOSITORIES = {
    ("app.db.learning_documents.sql_repository", "SQLResourceRepository"),
    ("app.db.feedback.sql_repository", "SQLFeedbackRepository"),
    ("app.db.feedback.feedback_loop_sql_repository", "SQLFeedbackLoopRepository"),
    ("app.db.generation.sql_repository", "SQLGenerationJobRepository"),
    ("app.db.claim.sql_repository", "SQLClaimRepository"),
    ("app.db.audit.sql_repository", "SQLAuditRepository"),
    ("app.db.diagnosis.sql_repository", "SQLDiagnosisRepository"),
    ("app.db.learners.sql_repository", "SQLLearnerRepository"),
    ("app.db.learners.mastery", "SQLMasteryRepository"),
    ("app.db.learners.curriculum", "SQLCurriculumRepository"),
    ("app.db.learners.tier_progress", "SQLTierProgressRepository"),
    ("app.db.knowledge.catalog", "KnowledgeCatalogRepository"),
}


class SQLReportReadRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.profiles = SQLLearnerRepository(session_factory)
        self._triggers = expected_triggers()
        self._capabilities = None

    def supports(self, repositories) -> bool:
        # Check actual injected objects, never configuration alone. A Memory
        # override must not be validated using an unrelated SQL database.
        for repo in repositories:
            if repo is None:
                continue
            if (type(repo).__module__, type(repo).__name__) not in _SUPPORTED_REPOSITORIES or getattr(repo, "session_factory", None) is not self.session_factory:
                return False
        with self.session_factory() as db:
            if db.bind.dialect.name != "sqlite":
                return False
            if self._capabilities is None:
                try:
                    db.execute(text("SELECT json_array_length('[]'), row_number() OVER ()")).first()
                    self._capabilities = True
                except DBAPIError:
                    self._capabilities = False
            return self._capabilities

    def read_token(self):
        try:
            with self.session_factory() as db:
                row = db.execute(text(f'SELECT installation_id, protocol, epoch FROM "{TABLE}" WHERE source = \'global\'')).first()
                if row is None or row.protocol != PROTOCOL:
                    return None
                installed = dict(db.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_report_%'")).all())
                if installed != self._triggers:
                    return None
                return row.installation_id, row.protocol, row.epoch
        except DBAPIError:
            return None

    @staticmethod
    def _visible_cte(include_jobs: bool):
        published = """WITH published AS (
            SELECT resource_id, run_id, batch_id, resource_type, representation,
                   parent_resource_id, published_at
            FROM generated_resources WHERE learner_id = :learner AND publication_status = 'published'
        )"""
        if not include_jobs:
            return published + """, visible AS (
                SELECT p.* FROM published p WHERE NOT EXISTS (
                    SELECT 1 FROM published child WHERE child.parent_resource_id = p.resource_id)
            )"""
        return published + """, replacements AS (
            SELECT j.run_id, COALESCE(NULLIF(j.batch_id, ''), j.run_id) AS batch_key,
                   t.value AS resource_type,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(NULLIF(j.batch_id, ''), j.run_id), t.value
                       ORDER BY j.created_at DESC, j.rowid ASC) AS position
            FROM generation_jobs j, json_each(j.request_payload, '$.constraints.replacement_resource_types') t
            WHERE j.learner_id = :learner AND COALESCE(j.superseded_by_run_id, '') = ''
              AND json_type(j.request_payload, '$.constraints.replacement_resource_types') = 'array'
              AND EXISTS (SELECT 1 FROM published p WHERE p.run_id = j.run_id AND p.resource_type = t.value)
        ), visible AS (
            SELECT p.* FROM published p
            WHERE NOT EXISTS (SELECT 1 FROM published child WHERE child.parent_resource_id = p.resource_id)
              AND NOT EXISTS (SELECT 1 FROM generation_jobs j WHERE j.learner_id = :learner
                              AND j.run_id = p.run_id AND COALESCE(j.superseded_by_run_id, '') != '')
              AND NOT EXISTS (SELECT 1 FROM replacements r WHERE r.position = 1
                              AND r.batch_key = COALESCE(NULLIF(p.batch_id, ''), p.run_id)
                              AND r.resource_type = p.resource_type AND r.run_id != p.run_id)
        )"""

    def resource_page(self, learner_id, *, limit, boundary, include_jobs):
        params = {"learner": learner_id, "limit": limit + 1}
        eligible = ", eligible AS (SELECT * FROM visible WHERE COALESCE(NULLIF(representation, ''), 'text') = 'text' AND resource_type IN (" + ",".join(f":type{i}" for i in range(len(SUPPORTED_RESOURCE_TYPES))) + ")) "
        params.update({f"type{i}": kind for i, kind in enumerate(SUPPORTED_RESOURCE_TYPES)})
        cte = self._visible_cte(include_jobs) + eligible
        minimum = "0001-01-01 00:00:00.000000"
        order = f"COALESCE(published_at, '{minimum}')"
        with self.session_factory() as db:
            # sqlite3 legacy transaction mode does not BEGIN for SELECTs.
            # Keep anchor validation and page selection in one read snapshot.
            db.execute(text("BEGIN"))
            where = ""
            if boundary is not None:
                params["anchor_id"] = boundary["resource_id"]
                anchor = db.execute(text(cte + "SELECT resource_id, published_at FROM eligible WHERE resource_id = :anchor_id"), params).first()
                if anchor is None:
                    raise ValueError("cursor anchor is no longer visible")
                # Read through the mapped DateTime converter; SQLite's raw
                # string has a different separator from the public ISO cursor.
                stamp = db.query(GeneratedResourceORM.published_at).filter_by(resource_id=anchor.resource_id).scalar()
                if (stamp.isoformat() if stamp else None) != boundary["published_at"]:
                    raise ValueError("cursor publication time changed")
                params["anchor_time"] = (f"{stamp.year:04}-{stamp.month:02}-{stamp.day:02} {stamp.hour:02}:{stamp.minute:02}:{stamp.second:02}.{stamp.microsecond:06}" if stamp else minimum)
                where = f" WHERE ({order} < :anchor_time OR ({order} = :anchor_time AND resource_id > :anchor_id))"
            sql = cte + f"SELECT generated_resources.* FROM generated_resources JOIN (SELECT resource_id FROM eligible{where} ORDER BY {order} DESC, resource_id ASC LIMIT :limit) page USING(resource_id) ORDER BY COALESCE(generated_resources.published_at, '{minimum}') DESC, generated_resources.resource_id ASC"
            rows = db.query(GeneratedResourceORM).from_statement(text(sql)).params(**params).all()
            return [_orm_to_pydantic(row) for row in rows]
