"""Durable access state for the three-tier learner curriculum."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from sqlalchemy.orm import Session

from app.db.shared.models import LearnerTierProgressORM
from app.models.learners.mastery import LearnerTierProgressV1


def _id(*parts: object) -> str:
    raw = "\x1f".join(str(item) for item in parts)
    return f"ltp_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _model(row: LearnerTierProgressORM) -> LearnerTierProgressV1:
    return LearnerTierProgressV1(
        learner_id=row.learner_id, knowledge_base_id=row.knowledge_base_id,
        placement_tier=row.placement_tier, active_tier=row.active_tier,
        highest_unlocked_tier=row.highest_unlocked_tier,
        remediation_return_tier=row.remediation_return_tier,
        profile_version=row.profile_version, row_version=row.row_version,
        updated_at=row.updated_at,
    )


class BaseTierProgressRepository(ABC):
    @abstractmethod
    def get_or_create(self, learner_id: str, knowledge_base_id: str, *, placement_tier: int,
                      profile_version: int) -> LearnerTierProgressV1: ...

    @abstractmethod
    def save(self, state: LearnerTierProgressV1) -> LearnerTierProgressV1: ...


class MemoryTierProgressRepository(BaseTierProgressRepository):
    def __init__(self):
        self._states: dict[tuple[str, str], LearnerTierProgressV1] = {}
        self._lock = RLock()

    def get_or_create(self, learner_id, knowledge_base_id, *, placement_tier, profile_version):
        with self._lock:
            key = (learner_id, knowledge_base_id)
            self._states.setdefault(key, LearnerTierProgressV1(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id,
                placement_tier=placement_tier, active_tier=placement_tier,
                highest_unlocked_tier=placement_tier, profile_version=profile_version,
            ))
            return deepcopy(self._states[key])

    def save(self, state):
        with self._lock:
            key = (state.learner_id, state.knowledge_base_id)
            prior = self._states.get(key)
            updated = state.model_copy(update={
                "row_version": (prior.row_version if prior else state.row_version) + 1,
                "updated_at": datetime.now(timezone.utc),
            })
            self._states[key] = updated
            return deepcopy(updated)


class SQLTierProgressRepository(BaseTierProgressRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get_or_create(self, learner_id, knowledge_base_id, *, placement_tier, profile_version):
        with self.session_factory() as db:
            row = db.query(LearnerTierProgressORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id,
            ).one_or_none()
            if row is None:
                row = LearnerTierProgressORM(
                    tier_progress_id=_id(learner_id, knowledge_base_id), learner_id=learner_id,
                    knowledge_base_id=knowledge_base_id, placement_tier=placement_tier,
                    active_tier=placement_tier, highest_unlocked_tier=placement_tier,
                    profile_version=profile_version, row_version=1,
                )
                db.add(row); db.commit(); db.refresh(row)
            return _model(row)

    def save(self, state):
        with self.session_factory() as db:
            row = db.query(LearnerTierProgressORM).filter_by(
                learner_id=state.learner_id, knowledge_base_id=state.knowledge_base_id,
            ).with_for_update().one()
            for field in ("placement_tier", "active_tier", "highest_unlocked_tier",
                          "remediation_return_tier", "profile_version"):
                setattr(row, field, getattr(state, field))
            row.row_version += 1
            db.commit(); db.refresh(row)
            return _model(row)


def create_tier_progress_repository(db_type: str, session_factory: Callable[[], Session]) -> BaseTierProgressRepository:
    return MemoryTierProgressRepository() if db_type == "memory" else SQLTierProgressRepository(session_factory)


__all__ = ["BaseTierProgressRepository", "create_tier_progress_repository"]
