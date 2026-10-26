"""SQLite durable text claims and reconciliation, using short write transactions."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, text
from sqlalchemy.engine import Connection

from app.db.audit.sql_repository import SQLAuditRepository
from app.db.shared.models import AgentRunORM, GeneratedResourceORM, GenerationJobORM
from app.models.generation.dispatch import GenerationClaim


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def begin_write(db):
    bind = db.get_bind()
    if bind.dialect.name == "sqlite" and not (isinstance(bind, Connection) and bind.in_transaction()):
        db.execute(text("BEGIN IMMEDIATE"))


class GenerationDispatchMixin:
    supports_durable_dispatch = True

    def get_dispatch(self, run_id):
        with self.session_factory() as db:
            row = db.get(GenerationJobORM, run_id)
            if row is None:
                return None
            return {name: getattr(row, name) for name in (
                "dispatch_mode", "dispatch_snapshot", "submission_hash", "claim_owner", "claim_epoch",
                "claim_count", "lease_expires_at", "next_attempt_at", "retry_of_run_id")}

    def claim_next(self, owner, lease_seconds, now=None):
        now = now or datetime.now(timezone.utc)
        with self.session_factory() as db:
            begin_write(db)
            row = db.query(GenerationJobORM).filter(
                GenerationJobORM.status == "queued", GenerationJobORM.dispatch_mode == "worker",
                GenerationJobORM.dispatch_snapshot.is_not(None), GenerationJobORM.claim_count < 3,
                or_(GenerationJobORM.next_attempt_at.is_(None), GenerationJobORM.next_attempt_at <= now),
            ).order_by(GenerationJobORM.next_attempt_at, GenerationJobORM.created_at, GenerationJobORM.run_id).first()
            if row is None:
                db.commit()
                return None
            epoch = row.claim_epoch + 1
            expires = now + timedelta(seconds=lease_seconds)
            changed = db.query(GenerationJobORM).filter_by(run_id=row.run_id, status="queued", claim_epoch=row.claim_epoch).update({
                "status": "running", "claim_owner": owner, "claim_epoch": epoch,
                "claim_count": row.claim_count + 1, "lease_expires_at": expires,
                "started_at": now, "finished_at": None, "error_message": None,
            }, synchronize_session=False)
            if changed != 1:
                db.rollback()
                return None
            db.query(AgentRunORM).filter_by(run_id=row.run_id, status="created").update({
                "owner_instance_id": owner, "lease_expires_at": expires,
                "row_version": AgentRunORM.row_version + 1,
            }, synchronize_session=False)
            claim = GenerationClaim(row.run_id, owner, epoch, row.learner_id, row.batch_id or row.run_id,
                                    row.request_payload or {}, row.dispatch_snapshot, row.claim_count + 1)
            db.commit()
            return claim

    @staticmethod
    def _owned(db, claim, now):
        return db.query(GenerationJobORM).filter(
            GenerationJobORM.run_id == claim.run_id, GenerationJobORM.status == "running",
            GenerationJobORM.claim_owner == claim.owner, GenerationJobORM.claim_epoch == claim.epoch,
            GenerationJobORM.lease_expires_at > now,
        )

    def renew_claim(self, claim, lease_seconds, now=None):
        now = now or datetime.now(timezone.utc)
        with self.session_factory() as db:
            begin_write(db)
            run = db.get(AgentRunORM, claim.run_id)
            if run and run.status in {"failed", "interrupted"}:
                db.rollback()
                return False
            expires = now + timedelta(seconds=lease_seconds)
            if self._owned(db, claim, now).update({"lease_expires_at": expires}, synchronize_session=False) != 1:
                db.rollback()
                return False
            if run and run.status in {"created", "running", "finalizing"}:
                db.query(AgentRunORM).filter_by(run_id=claim.run_id, owner_instance_id=claim.owner).update({
                    "lease_expires_at": expires, "heartbeat_at": now,
                    "row_version": AgentRunORM.row_version + 1,
                }, synchronize_session=False)
            db.commit()
            return True

    def finish_claim(self, claim, *, resource_ids=None, error_code=None, now=None):
        now = now or datetime.now(timezone.utc)
        with self.session_factory() as db:
            begin_write(db)
            run = db.get(AgentRunORM, claim.run_id)
            if run and run.status in {"completed", "degraded", "human_review"}:
                # A response/transport failure after finalization cannot undo it.
                error_code = None
                resource_ids = [item[0] for item in db.query(GeneratedResourceORM.resource_id)
                                .filter_by(run_id=claim.run_id).order_by(GeneratedResourceORM.resource_id)]
            elif run and run.status in {"failed", "interrupted"}:
                error_code = error_code or "GENERATION_JOB_INTERRUPTED"
            values = {"status": "failed" if error_code else "completed", "finished_at": now,
                      "error_message": error_code, "claim_owner": None, "lease_expires_at": None}
            if resource_ids is not None:
                values["resource_ids"] = resource_ids
            changed = self._owned(db, claim, now).update(values, synchronize_session=False)
            db.commit()
            return changed == 1

    def create_retry(self, previous_run_id, *, run_id, learner_id, topic, knowledge_base_id,
                     request_payload, batch_id, dispatch_snapshot=None, submission_hash=None):
        with self.session_factory() as db:
            begin_write(db)
            previous = db.get(GenerationJobORM, previous_run_id)
            if previous is None or previous.status != "failed":
                raise ValueError("generation retry requires a failed predecessor")
            if previous.superseded_by_run_id:
                return previous.superseded_by_run_id
            existing = db.query(GenerationJobORM).filter_by(retry_of_run_id=previous_run_id).first()
            if existing:
                return existing.run_id
            changed = db.query(GenerationJobORM).filter_by(
                run_id=previous_run_id, status="failed", superseded_by_run_id=None,
            ).update({"superseded_by_run_id": run_id}, synchronize_session=False)
            if changed != 1:
                db.rollback()
                return self.get(previous_run_id).superseded_by_run_id
            db.add(GenerationJobORM(run_id=run_id, learner_id=learner_id, topic=topic,
                knowledge_base_id=knowledge_base_id, request_payload=request_payload,
                batch_id=batch_id or run_id, status="queued", resource_ids=[],
                dispatch_mode="worker" if dispatch_snapshot else "legacy", dispatch_snapshot=dispatch_snapshot,
                submission_hash=submission_hash, retry_of_run_id=previous_run_id))
            db.commit()
            return run_id

    def reconcile(self, *, now=None, queued_timeout_seconds=1260, limit=100):
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=queued_timeout_seconds)
        result = {"failed_run_ids": [], "requeued": 0, "completed": 0}
        with self.session_factory() as db:
            begin_write(db)
            job, run = GenerationJobORM, AgentRunORM
            rows = db.query(job, run).outerjoin(run, run.run_id == job.run_id).filter(
                job.status.in_(("queued", "running")),
                or_(
                    run.status.in_(("completed", "degraded", "human_review", "failed", "interrupted")),
                    and_(run.status.in_(("running", "finalizing")), run.lease_expires_at <= now),
                    and_(job.status == "running", job.dispatch_mode == "worker", job.lease_expires_at <= now,
                         or_(run.run_id.is_(None), run.status == "created")),
                    and_(job.dispatch_mode == "legacy", run.run_id.is_(None),
                         or_(job.created_at <= cutoff, job.created_at.is_(None))),
                ),
            ).order_by(job.created_at, job.run_id).limit(limit).all()
            audit = SQLAuditRepository(self.session_factory)
            for row, current_run in rows:
                if current_run and current_run.status in {"completed", "degraded", "human_review"}:
                    row.status = "completed"
                    row.resource_ids = [item[0] for item in db.query(GeneratedResourceORM.resource_id)
                                        .filter_by(run_id=row.run_id).order_by(GeneratedResourceORM.resource_id)]
                    row.error_message = None
                    result["completed"] += 1
                elif current_run and current_run.status in {"running", "finalizing"}:
                    if not audit.interrupt_expired_in_session(db, current_run, now):
                        continue
                    row.status = "failed"
                elif row.dispatch_mode == "worker" and (current_run is None or current_run.status == "created") and row.claim_count < 3:
                    row.status = "queued"
                    row.next_attempt_at = now + timedelta(seconds=min(2 ** row.claim_count, 30))
                    row.claim_owner = None
                    row.lease_expires_at = None
                    result["requeued"] += 1
                    continue
                else:
                    row.status = "failed"
                if row.status == "failed":
                    row.error_message = "GENERATION_JOB_INTERRUPTED"
                    result["failed_run_ids"].append(row.run_id)
                row.finished_at = now
                row.claim_owner = None
                row.lease_expires_at = None
            db.commit()
        return result
