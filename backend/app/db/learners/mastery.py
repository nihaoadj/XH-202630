"""Canonical mastery repository with identical memory and SQLite transitions."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from sqlalchemy.orm import Session

from app.db.learners.base import BaseLearnerRepository
from app.db.shared.models import AbilityStateEventORM, KnowledgeStateORM, LearnerProfileORM
from app.models.learners.mastery import (
    AbilityConfidence,
    AbilityEvidenceSource,
    AbilityEvidenceV1,
    AbilityMasteryStateV2,
    AbilityStateEventV1,
    AbilityStatus,
)
from app.models.learning_documents.schemas import KnowledgeState


class MasteryEvidenceConflict(ValueError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:32]}"


def _confidence(count: int, distinct_sources: int, prior: float | None) -> AbilityConfidence:
    if count >= 3 and distinct_sources >= 2:
        return AbilityConfidence.HIGH
    if count >= 2:
        return AbilityConfidence.MEDIUM
    return AbilityConfidence.LOW if count >= 1 or prior is not None else AbilityConfidence.NONE


def _objective_status(score: float, objective_count: int) -> AbilityStatus:
    if score < 0.60:
        return AbilityStatus.WEAK
    # A single strong observation is useful evidence, but it is not enough to
    # claim durable mastery.  The second independent server-scored source is
    # enforced by the append-only evidence count.
    if score <= 0.85 or objective_count < 2:
        return AbilityStatus.LEARNING
    return AbilityStatus.MASTERED


def _transition(
    before: AbilityMasteryStateV2,
    evidence: AbilityEvidenceV1,
    distinct_source_count: int,
) -> AbilityMasteryStateV2:
    prior = before.self_report_prior
    mastery = before.mastery_score
    status = before.status
    objective_count = before.objective_evidence_count
    attempt_count = before.attempt_count

    if evidence.source_type in {AbilityEvidenceSource.ONBOARDING_SELF_REPORT, AbilityEvidenceSource.COURSEWARE_SELF_REPORT}:
        prior = evidence.observed_score
        if objective_count == 0:
            mastery = prior
            status = AbilityStatus.SELF_REPORTED if prior is not None else AbilityStatus.UNASSESSED
    elif evidence.verified and evidence.source_type in {
        AbilityEvidenceSource.DIAGNOSIS,
        AbilityEvidenceSource.LEARNING_ATTEMPT,
    }:
        observed = float(evidence.observed_score or 0.0)
        if objective_count == 0:
            mastery = observed if prior is None else 0.2 * prior + 0.8 * observed
        else:
            mastery = 0.7 * float(mastery or 0.0) + 0.3 * observed
        mastery = round(mastery, 6)
        objective_count += 1
        status = _objective_status(mastery, objective_count)
        if evidence.source_type == AbilityEvidenceSource.LEARNING_ATTEMPT:
            attempt_count += 1

    return before.model_copy(update={
        "mastery_score": mastery,
        "self_report_prior": prior,
        "status": status,
        "confidence": _confidence(objective_count, distinct_source_count, prior),
        "objective_evidence_count": objective_count,
        "distinct_objective_source_count": distinct_source_count,
        "attempt_count": attempt_count,
        "last_evidence_type": evidence.source_type,
        "last_evidence_id": evidence.evidence_id,
        "row_version": before.row_version + 1,
        "last_updated": evidence.occurred_at,
    })


def _empty_state(learner_id: str, knowledge_base_id: str, node_id: str) -> AbilityMasteryStateV2:
    return AbilityMasteryStateV2(
        learner_id=learner_id,
        knowledge_base_id=knowledge_base_id,
        skill_node_id=node_id,
    )


def _legacy_caches(states: list[AbilityMasteryStateV2], node_names: dict[str, str]) -> dict:
    duplicate_names = {
        name for name in node_names.values() if list(node_names.values()).count(name) > 1
    }

    def label(node_id: str) -> str:
        name = node_names.get(node_id, node_id)
        return f"{name}（{node_id}）" if name in duplicate_names else name

    ordered = sorted(states, key=lambda item: item.skill_node_id)
    knowledge_states = {
        item.skill_node_id: {
            "score": item.mastery_score,
            "status": item.status.value,
            "evidence": [item.last_evidence_id] if item.last_evidence_id else [],
            "last_updated": item.last_updated.isoformat() if item.last_updated else None,
            "self_report_prior": item.self_report_prior,
            "confidence": item.confidence.value,
            "objective_evidence_count": item.objective_evidence_count,
            "distinct_objective_source_count": item.distinct_objective_source_count,
            "attempt_count": item.attempt_count,
            "last_evidence_type": item.last_evidence_type.value if item.last_evidence_type else None,
            "last_evidence_id": item.last_evidence_id,
            "row_version": item.row_version,
        }
        for item in ordered
    }
    objective = [item for item in ordered if item.objective_evidence_count > 0]
    return {
        "knowledge_states": knowledge_states,
        "theory_scores": {
            item.skill_node_id: round(float(item.mastery_score or 0.0) * 100, 1)
            for item in objective if item.mastery_score is not None
        },
        "weak_points": [label(item.skill_node_id) for item in objective if item.status == AbilityStatus.WEAK],
        "strong_points": [label(item.skill_node_id) for item in objective if item.status == AbilityStatus.MASTERED],
    }


class BaseMasteryRepository(ABC):
    @abstractmethod
    def ensure_states(
        self, learner_id: str, knowledge_base_id: str, node_names: dict[str, str]
    ) -> list[AbilityMasteryStateV2]: ...

    @abstractmethod
    def apply_evidence(
        self,
        evidences: list[AbilityEvidenceV1],
        node_names: dict[str, str],
        *,
        increment_profile_version: bool,
    ) -> tuple[list[AbilityMasteryStateV2], int, bool]: ...

    @abstractmethod
    def list_states(self, learner_id: str, knowledge_base_id: str) -> list[AbilityMasteryStateV2]: ...

    @abstractmethod
    def list_events(self, learner_id: str, knowledge_base_id: str) -> list[AbilityStateEventV1]: ...


class MemoryMasteryRepository(BaseMasteryRepository):
    def __init__(self, learner_repository: BaseLearnerRepository):
        self.learner_repository = learner_repository
        self._states: dict[tuple[str, str, str], AbilityMasteryStateV2] = {}
        self._events: dict[tuple[str, str, str, str], AbilityStateEventV1] = {}
        self._node_names: dict[str, dict[str, str]] = {}
        self._lock = RLock()

    def ensure_states(self, learner_id, knowledge_base_id, node_names):
        with self._lock:
            self._node_names.setdefault(knowledge_base_id, {}).update(node_names)
            node_names = self._node_names[knowledge_base_id]
            for node_id in node_names:
                self._states.setdefault(
                    (learner_id, knowledge_base_id, node_id),
                    _empty_state(learner_id, knowledge_base_id, node_id),
                )
            states = self.list_states(learner_id, knowledge_base_id)
            self._sync_profile(learner_id, states, node_names, increment=False)
            return states

    def apply_evidence(self, evidences, node_names, *, increment_profile_version):
        if not evidences:
            return [], 1, False
        with self._lock:
            first = evidences[0]
            self._node_names.setdefault(first.knowledge_base_id, {}).update(node_names)
            node_names = self._node_names[first.knowledge_base_id]
            self.ensure_states(first.learner_id, first.knowledge_base_id, node_names)
            changed = False
            for evidence in evidences:
                event_key = (
                    evidence.learner_id,
                    evidence.source_type.value,
                    evidence.source_id,
                    evidence.skill_node_id,
                )
                existing = self._events.get(event_key)
                if existing:
                    if existing.source_hash != evidence.source_hash:
                        raise MasteryEvidenceConflict("ability evidence source payload conflict")
                    continue
                state_key = (evidence.learner_id, evidence.knowledge_base_id, evidence.skill_node_id)
                before = self._states.get(state_key) or _empty_state(*state_key)
                objective_sources = {
                    event.source_id
                    for event in self._events.values()
                    if event.learner_id == evidence.learner_id
                    and event.knowledge_base_id == evidence.knowledge_base_id
                    and event.skill_node_id == evidence.skill_node_id
                    and event.verified
                    and event.source_type in {
                        AbilityEvidenceSource.DIAGNOSIS,
                        AbilityEvidenceSource.LEARNING_ATTEMPT,
                    }
                }
                if evidence.verified and evidence.source_type in {
                    AbilityEvidenceSource.DIAGNOSIS,
                    AbilityEvidenceSource.LEARNING_ATTEMPT,
                }:
                    objective_sources.add(evidence.source_id)
                after = _transition(before, evidence, len(objective_sources))
                event = AbilityStateEventV1(
                    **evidence.model_dump(), before_state=before, after_state=after
                )
                self._events[event_key] = event
                self._states[state_key] = after
                changed = True
            states = self.list_states(first.learner_id, first.knowledge_base_id)
            version = self._sync_profile(
                first.learner_id,
                states,
                node_names,
                increment=bool(changed and increment_profile_version),
            )
            return states, version, changed

    def _sync_profile(self, learner_id, states, node_names, *, increment):
        profile = self.learner_repository.get(learner_id)
        if profile is None:
            raise ValueError("learner profile not found")
        caches = _legacy_caches(states, node_names)
        profile.knowledge_states = {
            key: KnowledgeState(**value) for key, value in caches["knowledge_states"].items()
        }
        profile.theory_scores = caches["theory_scores"]
        profile.weak_points = caches["weak_points"]
        profile.strong_points = caches["strong_points"]
        if increment:
            profile.profile_version += 1
        self.learner_repository.save(profile)
        return profile.profile_version

    def list_states(self, learner_id, knowledge_base_id):
        return [
            deepcopy(value)
            for key, value in sorted(self._states.items())
            if key[:2] == (learner_id, knowledge_base_id)
        ]

    def list_events(self, learner_id, knowledge_base_id):
        values = [
            deepcopy(value) for value in self._events.values()
            if value.learner_id == learner_id and value.knowledge_base_id == knowledge_base_id
        ]
        return sorted(values, key=lambda item: (item.occurred_at, item.evidence_id))


class SQLMasteryRepository(BaseMasteryRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    @staticmethod
    def _to_state(row: KnowledgeStateORM) -> AbilityMasteryStateV2:
        return AbilityMasteryStateV2(
            learner_id=row.learner_id,
            knowledge_base_id=row.knowledge_base_id,
            skill_node_id=row.skill_node_id,
            mastery_score=row.mastery_score,
            self_report_prior=row.self_report_prior,
            status=row.status or "unassessed",
            confidence=row.confidence or "none",
            objective_evidence_count=row.objective_evidence_count or 0,
            distinct_objective_source_count=row.distinct_objective_source_count or 0,
            attempt_count=row.attempt_count or 0,
            last_evidence_type=row.last_evidence_type,
            last_evidence_id=row.last_evidence_id,
            row_version=row.row_version or 1,
            last_updated=row.last_updated,
        )

    def _ensure(self, db: Session, learner_id: str, knowledge_base_id: str, node_names: dict[str, str]):
        existing = {
            row.skill_node_id for row in db.query(KnowledgeStateORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).all()
        }
        for node_id in sorted(set(node_names) - existing):
            db.add(KnowledgeStateORM(
                state_id=_stable_id("kst", learner_id, knowledge_base_id, node_id),
                learner_id=learner_id,
                knowledge_base_id=knowledge_base_id,
                skill_node_id=node_id,
                state_schema_version="2.0",
                status="unassessed",
                confidence="none",
                evidence=[],
                row_version=1,
            ))
        db.flush()

    def ensure_states(self, learner_id, knowledge_base_id, node_names):
        with self.session_factory() as db:
            self._ensure(db, learner_id, knowledge_base_id, node_names)
            rows = db.query(KnowledgeStateORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).order_by(KnowledgeStateORM.skill_node_id).all()
            states = [self._to_state(row) for row in rows]
            self._sync_profile(db, learner_id, states, node_names, increment=False)
            db.commit()
            return states

    def apply_evidence(self, evidences, node_names, *, increment_profile_version):
        if not evidences:
            return [], 1, False
        first = evidences[0]
        with self.session_factory() as db:
            self._ensure(db, first.learner_id, first.knowledge_base_id, node_names)
            changed = False
            for evidence in evidences:
                existing = db.query(AbilityStateEventORM).filter_by(
                    learner_id=evidence.learner_id,
                    source_type=evidence.source_type.value,
                    source_id=evidence.source_id,
                    skill_node_id=evidence.skill_node_id,
                ).first()
                if existing:
                    if existing.source_hash != evidence.source_hash:
                        raise MasteryEvidenceConflict("ability evidence source payload conflict")
                    continue
                row = db.query(KnowledgeStateORM).filter_by(
                    learner_id=evidence.learner_id,
                    knowledge_base_id=evidence.knowledge_base_id,
                    skill_node_id=evidence.skill_node_id,
                ).with_for_update().one()
                before = self._to_state(row)
                objective_sources = {
                    value[0] for value in db.query(AbilityStateEventORM.source_id).filter_by(
                        learner_id=evidence.learner_id,
                        knowledge_base_id=evidence.knowledge_base_id,
                        skill_node_id=evidence.skill_node_id,
                        verified=True,
                    ).distinct().all()
                }
                if evidence.verified and evidence.source_type in {
                    AbilityEvidenceSource.DIAGNOSIS,
                    AbilityEvidenceSource.LEARNING_ATTEMPT,
                }:
                    objective_sources.add(evidence.source_id)
                after = _transition(before, evidence, len(objective_sources))
                row.mastery_score = after.mastery_score
                row.self_report_prior = after.self_report_prior
                row.status = after.status.value
                row.confidence = after.confidence.value
                row.objective_evidence_count = after.objective_evidence_count
                row.distinct_objective_source_count = after.distinct_objective_source_count
                row.attempt_count = after.attempt_count
                row.last_attempt_id = evidence.source_id if evidence.source_type == AbilityEvidenceSource.LEARNING_ATTEMPT else row.last_attempt_id
                row.last_evidence_type = evidence.source_type.value
                row.last_evidence_id = evidence.evidence_id
                row.row_version = after.row_version
                row.last_updated = evidence.occurred_at
                row.evidence = list(dict.fromkeys([*(row.evidence or []), evidence.evidence_id]))[-20:]
                db.add(AbilityStateEventORM(
                    event_id=evidence.evidence_id,
                    schema_version=evidence.schema_version,
                    learner_id=evidence.learner_id,
                    knowledge_base_id=evidence.knowledge_base_id,
                    skill_node_id=evidence.skill_node_id,
                    source_type=evidence.source_type.value,
                    source_id=evidence.source_id,
                    source_hash=evidence.source_hash,
                    observed_score=evidence.observed_score,
                    verified=evidence.verified,
                    before_state=before.model_dump(mode="json"),
                    after_state=after.model_dump(mode="json"),
                    occurred_at=evidence.occurred_at,
                ))
                changed = True
            rows = db.query(KnowledgeStateORM).filter_by(
                learner_id=first.learner_id, knowledge_base_id=first.knowledge_base_id
            ).order_by(KnowledgeStateORM.skill_node_id).all()
            states = [self._to_state(row) for row in rows]
            version = self._sync_profile(
                db, first.learner_id, states, node_names,
                increment=bool(changed and increment_profile_version),
            )
            db.commit()
            return states, version, changed

    @staticmethod
    def _sync_profile(db, learner_id, states, node_names, *, increment):
        profile = db.query(LearnerProfileORM).filter_by(learner_id=learner_id).with_for_update().one()
        caches = _legacy_caches(states, node_names)
        profile.knowledge_states = caches["knowledge_states"]
        profile.theory_scores = caches["theory_scores"]
        profile.weak_points = caches["weak_points"]
        profile.strong_points = caches["strong_points"]
        if increment:
            profile.profile_version = (profile.profile_version or 1) + 1
        db.flush()
        return profile.profile_version or 1

    def list_states(self, learner_id, knowledge_base_id):
        with self.session_factory() as db:
            rows = db.query(KnowledgeStateORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).order_by(KnowledgeStateORM.skill_node_id).all()
            return [self._to_state(row) for row in rows]

    def list_events(self, learner_id, knowledge_base_id):
        with self.session_factory() as db:
            rows = db.query(AbilityStateEventORM).filter_by(
                learner_id=learner_id, knowledge_base_id=knowledge_base_id
            ).order_by(AbilityStateEventORM.occurred_at, AbilityStateEventORM.event_id).all()
            return [AbilityStateEventV1(
                evidence_id=row.event_id,
                learner_id=row.learner_id,
                knowledge_base_id=row.knowledge_base_id,
                skill_node_id=row.skill_node_id,
                source_type=row.source_type,
                source_id=row.source_id,
                source_hash=row.source_hash,
                observed_score=row.observed_score,
                verified=row.verified,
                occurred_at=row.occurred_at,
                before_state=row.before_state,
                after_state=row.after_state,
            ) for row in rows]


def create_mastery_repository(
    db_type: str,
    session_factory: Callable[[], Session],
    learner_repository: BaseLearnerRepository,
) -> BaseMasteryRepository:
    if db_type == "memory":
        return MemoryMasteryRepository(learner_repository)
    return SQLMasteryRepository(session_factory)


__all__ = [
    "BaseMasteryRepository",
    "MasteryEvidenceConflict",
    "MemoryMasteryRepository",
    "SQLMasteryRepository",
    "create_mastery_repository",
]
