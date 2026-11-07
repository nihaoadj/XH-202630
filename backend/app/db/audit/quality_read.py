"""Consistent, read-only source packets for the resource quality projection.

The quality query needs one coherent view of a Run's audit ledger, frozen
resource specs, generated resources and Claim rows.  Two repository families
exist, and each needs its own proof of a common read boundary:

* Native SQL — one call-local connection with an explicit ``BEGIN`` (and
  ``PRAGMA query_only`` on SQLite).  Shallow repository copies are bound to
  that connection with ``join_transaction_mode="create_savepoint"`` so every
  read inside the region observes the same snapshot and no repository can
  commit or write.  The global repositories' ``session_factory`` is never
  mutated.
* Native memory — the four repositories already use (or now use) a re-entrant
  instance lock.  They are acquired in the fixed order generation-job → audit →
  resource → claim, the needed values are deep-copied, and all locks are
  released before the caller computes anything.  No lock is held across an
  ``await``, a model call or a request boundary.

A mixed or custom repository set has no provable common boundary, so it is
reported as unsupported instead of being stitched together from two reads that
look successful but are not atomic.
"""

from __future__ import annotations

import copy
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.audit.base import (
    StepReviewAudit,
)
from app.models.learning_documents.schemas import LearningResource
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.reviews.claims import ClaimJudgement, ClaimRecord
from app.models.shared.persistence import (
    AgentRunRecord,
    AgentStepRecord,
    WorkflowCheckpoint,
)


NATIVE_SQL = "native_sql"
NATIVE_MEMORY = "native_memory"
UNSUPPORTED = "unsupported"

CONSISTENT_READ_UNSUPPORTED = "CONSISTENT_READ_UNSUPPORTED"
CONSISTENT_READ_FAILED = "CONSISTENT_READ_FAILED"

_SQL_REPOSITORIES = {
    ("app.db.audit.sql_repository", "SQLAuditRepository"),
    ("app.db.learning_documents.sql_repository", "SQLResourceRepository"),
    ("app.db.claim.sql_repository", "SQLClaimRepository"),
    ("app.db.generation.sql_repository", "SQLGenerationJobRepository"),
}
_MEMORY_REPOSITORIES = {
    ("app.db.audit.memory", "MemoryAuditRepository"),
    ("app.db.learning_documents.memory", "MemoryResourceRepository"),
    ("app.db.claim.memory", "MemoryClaimRepository"),
    ("app.db.generation.memory", "MemoryGenerationJobRepository"),
}


def repository_identity(repository) -> tuple[str, str]:
    return type(repository).__module__, type(repository).__name__


@dataclass(frozen=True)
class QualitySourceBundle:
    """Detached facts copied out of one consistent read region."""

    run_id: str
    read_mode: str
    run: AgentRunRecord | None = None
    request_snapshot: dict[str, Any] | None = None
    job_request_payload: dict[str, Any] | None = None
    steps: tuple[AgentStepRecord, ...] = ()
    checkpoints: tuple[WorkflowCheckpoint, ...] = ()
    audits: tuple[StepReviewAudit, ...] = ()
    specs: tuple[ResourceSpecRecord, ...] = ()
    executions: tuple[ResourceExecutionRecord, ...] = ()
    resources: tuple[LearningResource, ...] = ()
    claims: tuple[ClaimRecord, ...] = ()
    judgements: tuple[ClaimJudgement, ...] = ()
    reviews: tuple[tuple[str, Any], ...] = ()
    failure_code: str | None = None

    @property
    def supported(self) -> bool:
        return self.read_mode != UNSUPPORTED and self.failure_code is None


def read_quality_sources(
    run_id: str,
    *,
    audit_repository,
    resource_repository,
    claim_repository,
    generation_job_repository=None,
) -> QualitySourceBundle:
    """Return one consistent, detached source packet for ``run_id``."""
    repositories = [audit_repository, resource_repository, claim_repository]
    if generation_job_repository is not None:
        repositories.append(generation_job_repository)
    mode = _read_mode(repositories)
    if mode == NATIVE_SQL:
        return _read_sql(run_id, repositories=repositories)
    if mode == NATIVE_MEMORY:
        return _read_memory(run_id, repositories=repositories)
    return QualitySourceBundle(
        run_id=run_id, read_mode=UNSUPPORTED, failure_code=CONSISTENT_READ_UNSUPPORTED,
    )


def _read_mode(repositories) -> str:
    identities = [repository_identity(repository) for repository in repositories]
    if all(item in _SQL_REPOSITORIES for item in identities):
        factories = {id(repository.session_factory) for repository in repositories}
        return NATIVE_SQL if len(factories) == 1 else UNSUPPORTED
    if all(item in _MEMORY_REPOSITORIES for item in identities):
        return NATIVE_MEMORY
    return UNSUPPORTED


def _bound_copy(repository, session_factory):
    clone = copy.copy(repository)
    clone.session_factory = session_factory
    return clone


def _read_sql(run_id: str, *, repositories) -> QualitySourceBundle:
    audit_repository, resource_repository, claim_repository = repositories[:3]
    job_repository = repositories[3] if len(repositories) > 3 else None
    engine = audit_repository.session_factory.kw["bind"]
    connection = engine.connect()
    dbapi = connection.connection.dbapi_connection
    query_only = False
    explicit = False
    try:
        if engine.dialect.name == "sqlite":
            # SQLAlchemy already autobegins on the first statement, so the
            # explicit transaction is opened on the raw DBAPI connection.
            # query_only makes "read the packet, never write" a hard property
            # of this connection rather than a review convention.
            cursor = dbapi.cursor()
            try:
                cursor.execute("PRAGMA query_only = ON")
                query_only = True
                cursor.execute("BEGIN")
            finally:
                cursor.close()
        else:
            connection.exec_driver_sql("BEGIN")
        explicit = True

        def bound():
            return Session(
                bind=connection, join_transaction_mode="create_savepoint",
                autoflush=False, expire_on_commit=False,
            )

        audit = _bound_copy(audit_repository, bound)
        resource = _bound_copy(resource_repository, bound)
        claim = _bound_copy(claim_repository, bound)
        job_repo = _bound_copy(job_repository, bound) if job_repository is not None else None
        run = audit.get_run(run_id)
        job = job_repo.get(run_id) if job_repo is not None and run is not None else None
        if run is None:
            return QualitySourceBundle(
                run_id=run_id, read_mode=NATIVE_SQL, failure_code="RUN_NOT_FOUND",
            )
        resources = tuple(resource.list_by_run(run_id))
        return QualitySourceBundle(
            run_id=run_id,
            read_mode=NATIVE_SQL,
            run=run,
            request_snapshot=dict(audit.get_run_creation_snapshot(run_id)),
            job_request_payload=dict(job.request_payload) if job is not None else None,
            steps=tuple(audit.list_steps(run_id)),
            checkpoints=tuple(audit.list_checkpoints(run_id)),
            audits=tuple(audit.get_review_audits_by_runs([run_id])),
            specs=tuple(resource.list_specs_by_run(run_id)),
            executions=tuple(resource.list_executions_by_run(run_id)),
            resources=resources,
            claims=tuple(claim.list_claims_by_runs([run_id])),
            judgements=tuple(claim.list_judgements_by_runs([run_id])),
            reviews=tuple(audit.get_reviews_by_resources(
                [item.resource_id for item in resources],
            ).items()) if resources else (),
        )
    finally:
        if explicit:
            try:
                dbapi.rollback()
            except Exception:  # noqa: BLE001 - connection is closing anyway
                pass
        if query_only:
            try:
                cursor = dbapi.cursor()
                try:
                    cursor.execute("PRAGMA query_only = OFF")
                finally:
                    cursor.close()
            except Exception:  # noqa: BLE001 - connection is closing anyway
                pass
        connection.close()


def _read_memory(run_id: str, *, repositories) -> QualitySourceBundle:
    audit_repository, resource_repository, claim_repository = repositories[:3]
    job_repository = repositories[3] if len(repositories) > 3 else None
    # Fixed acquisition order; no other repository nests these locks.
    ordered = [repository for repository in (job_repository, audit_repository,
                                             resource_repository, claim_repository)
               if repository is not None]
    with ExitStack() as stack:
        for repository in ordered:
            stack.enter_context(repository._lock)
        run = audit_repository.get_run(run_id)
        if run is None:
            return QualitySourceBundle(
                run_id=run_id, read_mode=NATIVE_MEMORY, failure_code="RUN_NOT_FOUND",
            )
        job = job_repository.get(run_id) if job_repository is not None else None
        resources = tuple(resource_repository.list_by_run(run_id))
        return QualitySourceBundle(
            run_id=run_id,
            read_mode=NATIVE_MEMORY,
            run=run,
            request_snapshot=dict(audit_repository.get_run_creation_snapshot(run_id)),
            job_request_payload=dict(job.request_payload) if job is not None else None,
            steps=tuple(audit_repository.list_steps(run_id)),
            checkpoints=tuple(audit_repository.list_checkpoints(run_id)),
            audits=tuple(audit_repository.get_review_audits_by_runs([run_id])),
            specs=tuple(resource_repository.list_specs_by_run(run_id)),
            executions=tuple(resource_repository.list_executions_by_run(run_id)),
            resources=resources,
            claims=tuple(claim_repository.list_claims_by_runs([run_id])),
            judgements=tuple(claim_repository.list_judgements_by_runs([run_id])),
            reviews=tuple(audit_repository.get_reviews_by_resources(
                [item.resource_id for item in resources],
            ).items()) if resources else (),
        )


__all__ = [
    "CONSISTENT_READ_FAILED",
    "CONSISTENT_READ_UNSUPPORTED",
    "NATIVE_MEMORY",
    "NATIVE_SQL",
    "QualitySourceBundle",
    "UNSUPPORTED",
    "read_quality_sources",
    "repository_identity",
]
