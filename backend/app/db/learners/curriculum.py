"""Durable curriculum-progression repositories for multi-round learning."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from sqlalchemy.orm import Session

from app.db.shared.models import LearnerCurriculumNodeORM
from app.models.learners.mastery import CurriculumNodeProgressV1, CurriculumProgressStatus


def _id(*parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return f"lcn_{hashlib.sha256(value.encode()).hexdigest()[:32]}"


def _to_model(row: LearnerCurriculumNodeORM) -> CurriculumNodeProgressV1:
    return CurriculumNodeProgressV1(
        learner_id=row.learner_id, knowledge_base_id=row.knowledge_base_id,
        skill_node_id=row.skill_node_id, progress_status=row.progress_status,
        wait_rounds=row.wait_rounds or 0, scheduled_run_id=row.scheduled_run_id,
        published_resource_count=row.published_resource_count or 0,
        verified_attempt_count=row.verified_attempt_count or 0,
        placement_exempt=bool(row.placement_exempt), placement_evidence_id=row.placement_evidence_id,
        last_scheduled_at=row.last_scheduled_at, last_published_at=row.last_published_at,
        last_verified_at=row.last_verified_at, row_version=row.row_version or 1,
        updated_at=row.updated_at,
    )


class BaseCurriculumRepository(ABC):
    @abstractmethod
    def ensure_nodes(self, learner_id: str, knowledge_base_id: str, node_ids: list[str]) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def list_nodes(self, learner_id: str, knowledge_base_id: str) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def schedule_round(self, learner_id: str, knowledge_base_id: str, *, run_id: str,
                       selected_node_ids: list[str], eligible_unplanned_ids: list[str],
                       now: datetime) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def reconcile_exposure(self, learner_id: str, knowledge_base_id: str,
                           published_counts: dict[str, int], now: datetime) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def record_verification(self, learner_id: str, knowledge_base_id: str, *, attempt_id: str,
                            scores: dict[str, float], now: datetime) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def set_placement_exemptions(self, learner_id: str, knowledge_base_id: str, *,
                                 node_ids: list[str], evidence_id: str, now: datetime) -> list[CurriculumNodeProgressV1]: ...

    @abstractmethod
    def release_failed_run(self, learner_id: str, knowledge_base_id: str, *, run_id: str,
                           now: datetime) -> list[CurriculumNodeProgressV1]: ...


class MemoryCurriculumRepository(BaseCurriculumRepository):
    def __init__(self):
        self._rows: dict[tuple[str, str, str], CurriculumNodeProgressV1] = {}
        self._attempts: set[tuple[str, str, str]] = set()
        self._lock = RLock()

    def ensure_nodes(self, learner_id, knowledge_base_id, node_ids):
        with self._lock:
            for node_id in sorted(set(node_ids)):
                key = (learner_id, knowledge_base_id, node_id)
                self._rows.setdefault(key, CurriculumNodeProgressV1(
                    learner_id=learner_id, knowledge_base_id=knowledge_base_id, skill_node_id=node_id,
                ))
            return self.list_nodes(learner_id, knowledge_base_id)

    def list_nodes(self, learner_id, knowledge_base_id):
        return [deepcopy(value) for key, value in sorted(self._rows.items()) if key[:2] == (learner_id, knowledge_base_id)]

    def _update(self, key, **changes):
        before = self._rows[key]
        self._rows[key] = before.model_copy(update={
            **changes, "row_version": before.row_version + 1,
            "updated_at": changes.get("updated_at") or datetime.now(timezone.utc),
        })

    def schedule_round(self, learner_id, knowledge_base_id, *, run_id, selected_node_ids, eligible_unplanned_ids, now):
        with self._lock:
            selected = set(selected_node_ids)
            for node_id in eligible_unplanned_ids:
                key = (learner_id, knowledge_base_id, node_id)
                if key not in self._rows:
                    continue
                row = self._rows[key]
                if node_id in selected:
                    self._update(key, progress_status=CurriculumProgressStatus.SCHEDULED,
                                 scheduled_run_id=run_id, wait_rounds=0, last_scheduled_at=now)
                elif row.progress_status == CurriculumProgressStatus.UNPLANNED:
                    self._update(key, wait_rounds=min(5, row.wait_rounds + 1))
            return self.list_nodes(learner_id, knowledge_base_id)

    def reconcile_exposure(self, learner_id, knowledge_base_id, published_counts, now):
        with self._lock:
            for node_id, count in published_counts.items():
                key = (learner_id, knowledge_base_id, node_id)
                if key not in self._rows:
                    continue
                row = self._rows[key]
                if count > row.published_resource_count:
                    # A follow-up resource is often published after feedback.
                    # Preserve a verified outcome instead of regressing a weak
                    # node from "reinforcement_due" to "exposed".
                    next_status = (
                        CurriculumProgressStatus.EXPOSED
                        if row.progress_status in {
                            CurriculumProgressStatus.UNPLANNED,
                            CurriculumProgressStatus.SCHEDULED,
                            CurriculumProgressStatus.EXPOSED,
                            CurriculumProgressStatus.VERIFICATION_PENDING,
                        }
                        else row.progress_status
                    )
                    self._update(key, published_resource_count=count,
                                 progress_status=next_status, last_published_at=now)
            return self.list_nodes(learner_id, knowledge_base_id)

    def record_verification(self, learner_id, knowledge_base_id, *, attempt_id, scores, now):
        with self._lock:
            for node_id, score in scores.items():
                key = (learner_id, knowledge_base_id, node_id)
                event_key = (learner_id, attempt_id, node_id)
                if key not in self._rows or event_key in self._attempts:
                    continue
                row = self._rows[key]
                if row.published_resource_count <= 0:
                    continue
                self._attempts.add(event_key)
                self._update(key, verified_attempt_count=row.verified_attempt_count + 1,
                             progress_status=(CurriculumProgressStatus.COMPLETED if score >= 0.86
                                              else CurriculumProgressStatus.REINFORCEMENT_DUE),
                             last_verified_at=now)
            return self.list_nodes(learner_id, knowledge_base_id)

    def set_placement_exemptions(self, learner_id, knowledge_base_id, *, node_ids, evidence_id, now):
        with self._lock:
            for node_id in sorted(set(node_ids)):
                key = (learner_id, knowledge_base_id, node_id)
                if key in self._rows and not self._rows[key].placement_exempt:
                    self._update(key, placement_exempt=True, placement_evidence_id=evidence_id, updated_at=now)
            return self.list_nodes(learner_id, knowledge_base_id)

    def release_failed_run(self, learner_id, knowledge_base_id, *, run_id, now):
        with self._lock:
            for key, row in list(self._rows.items()):
                if key[:2] == (learner_id, knowledge_base_id) and row.scheduled_run_id == run_id \
                        and row.published_resource_count == 0:
                    self._update(key, progress_status=CurriculumProgressStatus.UNPLANNED,
                                 scheduled_run_id=None, updated_at=now)
            return self.list_nodes(learner_id, knowledge_base_id)


class SQLCurriculumRepository(BaseCurriculumRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def ensure_nodes(self, learner_id, knowledge_base_id, node_ids):
        with self.session_factory() as db:
            existing = {row.skill_node_id for row in db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id).all()}
            for node_id in sorted(set(node_ids) - existing):
                db.add(LearnerCurriculumNodeORM(
                    curriculum_node_id=_id(learner_id, knowledge_base_id, node_id), learner_id=learner_id,
                    knowledge_base_id=knowledge_base_id, skill_node_id=node_id, progress_status="unplanned",
                    wait_rounds=0, published_resource_count=0, verified_attempt_count=0, row_version=1,
                ))
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)

    def list_nodes(self, learner_id, knowledge_base_id):
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).order_by(LearnerCurriculumNodeORM.skill_node_id).all()
            return [_to_model(row) for row in rows]

    def schedule_round(self, learner_id, knowledge_base_id, *, run_id, selected_node_ids, eligible_unplanned_ids, now):
        selected = set(selected_node_ids)
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).with_for_update().all()
            for row in rows:
                if row.skill_node_id not in eligible_unplanned_ids:
                    continue
                if row.skill_node_id in selected:
                    row.progress_status = "scheduled"; row.scheduled_run_id = run_id
                    row.wait_rounds = 0; row.last_scheduled_at = now; row.row_version += 1
                elif row.progress_status == "unplanned":
                    row.wait_rounds = min(5, (row.wait_rounds or 0) + 1); row.row_version += 1
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)

    def reconcile_exposure(self, learner_id, knowledge_base_id, published_counts, now):
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).with_for_update().all()
            for row in rows:
                count = published_counts.get(row.skill_node_id, 0)
                if count > (row.published_resource_count or 0):
                    row.published_resource_count = count
                    if row.progress_status in {"unplanned", "scheduled", "exposed", "verification_pending"}:
                        row.progress_status = "exposed"
                    row.last_published_at = now; row.row_version += 1
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)

    def record_verification(self, learner_id, knowledge_base_id, *, attempt_id, scores, now):
        # Feedback attempts are idempotently persisted before this projection is called.
        # Guard duplicate replays by recording the last attempt ID in a local, stable query.
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).with_for_update().all()
            for row in rows:
                score = scores.get(row.skill_node_id)
                if score is None or (row.published_resource_count or 0) <= 0:
                    continue
                if row.last_verified_attempt_id == attempt_id:
                    continue
                row.verified_attempt_count = (row.verified_attempt_count or 0) + 1
                row.progress_status = "completed" if score >= 0.86 else "reinforcement_due"
                row.last_verified_at = now; row.last_verified_attempt_id = attempt_id; row.row_version += 1
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)

    def set_placement_exemptions(self, learner_id, knowledge_base_id, *, node_ids, evidence_id, now):
        if not node_ids:
            return self.list_nodes(learner_id, knowledge_base_id)
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id,
            ).filter(LearnerCurriculumNodeORM.skill_node_id.in_(set(node_ids))).with_for_update().all()
            for row in rows:
                if not row.placement_exempt:
                    row.placement_exempt = True; row.placement_evidence_id = evidence_id
                    row.updated_at = now; row.row_version += 1
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)

    def release_failed_run(self, learner_id, knowledge_base_id, *, run_id, now):
        with self.session_factory() as db:
            rows = db.query(LearnerCurriculumNodeORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id,
                scheduled_run_id=run_id,
            ).with_for_update().all()
            for row in rows:
                if (row.published_resource_count or 0) == 0:
                    row.progress_status = "unplanned"; row.scheduled_run_id = None
                    row.updated_at = now; row.row_version += 1
            db.commit()
        return self.list_nodes(learner_id, knowledge_base_id)


def create_curriculum_repository(db_type: str, session_factory: Callable[[], Session]) -> BaseCurriculumRepository:
    return MemoryCurriculumRepository() if db_type == "memory" else SQLCurriculumRepository(session_factory)


__all__ = ["BaseCurriculumRepository", "MemoryCurriculumRepository", "SQLCurriculumRepository", "create_curriculum_repository"]
