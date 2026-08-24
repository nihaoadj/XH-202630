"""Single policy surface for learner ability state, priorities and projections."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.db.learners.mastery import BaseMasteryRepository
from app.models.learners.mastery import (
    AbilityConfidence,
    AbilityEvidenceSource,
    AbilityEvidenceV1,
    AbilityNodeProjectionV1,
    AbilityNodesResponseV1,
    AbilityNodeSummaryV1,
    AbilityStatus,
    LearnerFocusSkippedV1,
    LearnerFocusSnapshotV1,
    WeaknessPriorityV1,
)
from app.models.learning_documents.schemas import LearnerProfile
from app.services.knowledge.knowledge import KnowledgeService


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{_canonical_hash(parts)[:32]}"


class MasteryService:
    def __init__(self, repository: BaseMasteryRepository, knowledge_service: KnowledgeService):
        self.repository = repository
        self.knowledge_service = knowledge_service

    def _nodes(self, knowledge_base_id: str):
        return self.knowledge_service.list_skill_nodes(knowledge_base_id)

    def ensure_profile_projection(self, profile: LearnerProfile):
        if not profile.knowledge_base_id:
            return []
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        return self.repository.ensure_states(profile.learner_id, profile.knowledge_base_id, names)

    @staticmethod
    def normalize_self_report_score(value: object) -> float | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        number = float(value)
        if 0 <= number <= 1:
            return number
        if 1 < number <= 100:
            return number / 100
        return None

    def apply_onboarding_answers(
        self,
        profile: LearnerProfile,
        questions: dict[str, dict[str, Any]],
        answers: dict[str, Any],
    ) -> tuple[list, int, bool]:
        knowledge_base_id = profile.knowledge_base_id
        if not knowledge_base_id:
            return [], profile.profile_version, False
        nodes = self._nodes(knowledge_base_id)
        names = {node.node_id: node.name for node in nodes}
        self.repository.ensure_states(profile.learner_id, knowledge_base_id, names)
        last_scores: dict[str, float] = {}
        answer_ids: dict[str, list[str]] = {}
        for question_id, question in questions.items():
            raw_answer = answers.get(question_id)
            values = raw_answer if isinstance(raw_answer, list) else [raw_answer]
            for value in values:
                option = next((item for item in question.get("options", []) if isinstance(item, dict)
                               and item.get("value", item.get("label")) == value), None)
                if not option:
                    continue
                score = self.normalize_self_report_score(option.get("self_report_score"))
                node_ids = [item for item in option.get("diagnostic_scope_add", []) if item in names]
                if score is None:
                    continue
                for node_id in node_ids:
                    last_scores[node_id] = score
                    answer_ids.setdefault(node_id, []).append(question_id)
        source_hash = _canonical_hash({"answers": answers, "knowledge_base_id": knowledge_base_id})
        source_id = _stable_id("onboarding", profile.learner_id, source_hash)
        occurred_at = datetime.now(timezone.utc)
        evidence = [AbilityEvidenceV1(
            evidence_id=_stable_id("abe", source_id, node_id),
            learner_id=profile.learner_id,
            knowledge_base_id=knowledge_base_id,
            skill_node_id=node_id,
            source_type=AbilityEvidenceSource.ONBOARDING_SELF_REPORT,
            source_id=source_id,
            source_hash=_canonical_hash({"source_hash": source_hash, "answer_ids": answer_ids[node_id]}),
            observed_score=score,
            verified=False,
            occurred_at=occurred_at,
        ) for node_id, score in sorted(last_scores.items())]
        if not evidence:
            return self.repository.list_states(profile.learner_id, knowledge_base_id), profile.profile_version, False
        return self.repository.apply_evidence(evidence, names, increment_profile_version=False)

    def apply_diagnosis(
        self,
        profile: LearnerProfile,
        node_scores: dict[str, float],
        *,
        source_id: str,
        source_hash: str,
        occurred_at: datetime,
    ):
        if not profile.knowledge_base_id:
            raise ValueError("learner knowledge_base_id is required")
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(node_scores) - set(names))
        if unknown:
            raise ValueError(f"diagnosis nodes outside knowledge base: {', '.join(unknown)}")
        evidence = [AbilityEvidenceV1(
            evidence_id=_stable_id("abe", source_id, node_id),
            learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id,
            skill_node_id=node_id,
            source_type=AbilityEvidenceSource.DIAGNOSIS,
            source_id=source_id,
            source_hash=source_hash,
            observed_score=score,
            verified=True,
            occurred_at=occurred_at,
        ) for node_id, score in sorted(node_scores.items())]
        return self.repository.apply_evidence(evidence, names, increment_profile_version=True)

    def ability_nodes(self, profile: LearnerProfile) -> AbilityNodesResponseV1:
        if not profile.knowledge_base_id:
            return AbilityNodesResponseV1(
                learner_id=profile.learner_id,
                knowledge_base_id=None,
                as_of_profile_version=profile.profile_version,
                summary=AbilityNodeSummaryV1(
                    total_count=0, mastered_count=0, learning_count=0, weak_count=0,
                    self_reported_count=0, unassessed_count=0, medium_or_high_confidence_count=0,
                ),
                data_warnings=["KNOWLEDGE_BASE_UNAVAILABLE"],
            )
        nodes = self._nodes(profile.knowledge_base_id)
        names = {node.node_id: node.name for node in nodes}
        states = self.repository.ensure_states(profile.learner_id, profile.knowledge_base_id, names)
        state_by_id = {item.skill_node_id: item for item in states}
        events = self.repository.list_events(profile.learner_id, profile.knowledge_base_id)
        objective_after: dict[str, list[float]] = {}
        for event in events:
            if event.verified and event.source_type in {
                AbilityEvidenceSource.DIAGNOSIS, AbilityEvidenceSource.LEARNING_ATTEMPT,
            } and event.after_state.mastery_score is not None:
                objective_after.setdefault(event.skill_node_id, []).append(event.after_state.mastery_score)
        priorities = self.weakness_priorities(profile)
        priority_by_id = {item.skill_node_id: item.rank for item in priorities}
        projected = []
        for node in nodes:
            values = objective_after.get(node.node_id, [])
            trend_delta = round(values[-1] - values[-2], 6) if len(values) >= 2 else None
            projected.append(AbilityNodeProjectionV1(
                skill_node_id=node.node_id,
                name=node.name,
                description=node.description,
                level=node.level,
                prerequisites=node.prerequisites,
                children=node.children,
                mastery=state_by_id[node.node_id],
                trend_delta=trend_delta,
                priority=priority_by_id.get(node.node_id),
            ))
        counts = {status: 0 for status in AbilityStatus}
        for state in states:
            counts[state.status] += 1
        return AbilityNodesResponseV1(
            learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id,
            as_of_profile_version=profile.profile_version,
            summary=AbilityNodeSummaryV1(
                total_count=len(states),
                mastered_count=counts[AbilityStatus.MASTERED],
                learning_count=counts[AbilityStatus.LEARNING],
                weak_count=counts[AbilityStatus.WEAK],
                self_reported_count=counts[AbilityStatus.SELF_REPORTED],
                unassessed_count=counts[AbilityStatus.UNASSESSED],
                medium_or_high_confidence_count=sum(
                    item.confidence in {AbilityConfidence.MEDIUM, AbilityConfidence.HIGH} for item in states
                ),
            ),
            nodes=projected,
            edges=[
                {"from": prerequisite, "to": node.node_id}
                for node in nodes for prerequisite in node.prerequisites
            ],
            weakness_priorities=priorities,
        )

    def weakness_priorities(self, profile: LearnerProfile) -> list[WeaknessPriorityV1]:
        if not profile.knowledge_base_id:
            return []
        nodes = self._nodes(profile.knowledge_base_id)
        names = {node.node_id: node.name for node in nodes}
        states = self.repository.ensure_states(profile.learner_id, profile.knowledge_base_id, names)
        state_by_id = {item.skill_node_id: item for item in states}
        events = self.repository.list_events(profile.learner_id, profile.knowledge_base_id)
        observed: dict[str, list[float]] = {}
        for event in events:
            if event.verified and event.source_type in {
                AbilityEvidenceSource.DIAGNOSIS, AbilityEvidenceSource.LEARNING_ATTEMPT,
            } and event.observed_score is not None:
                observed.setdefault(event.skill_node_id, []).append(event.observed_score)
        children = {node.node_id: list(node.children) for node in nodes}

        def downstream(node_id: str) -> int:
            seen: set[str] = set()
            stack = list(children.get(node_id, []))
            while stack:
                candidate = stack.pop()
                if candidate in seen:
                    continue
                seen.add(candidate)
                stack.extend(children.get(candidate, []))
            return len(seen)

        candidates = []
        group_order = {
            "confirmed_weak": 0, "regressing_learning": 1,
            "low_self_report": 2, "unassessed_prerequisite": 3,
        }
        def sort_time(value: datetime | None) -> datetime:
            if value is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        for node in nodes:
            state = state_by_id[node.node_id]
            group = None
            reasons: list[str] = []
            if state.status == AbilityStatus.WEAK and state.objective_evidence_count > 0:
                group, reasons = "confirmed_weak", ["OBJECTIVE_SCORE_BELOW_0_60"]
            elif state.status == AbilityStatus.LEARNING and len(observed.get(node.node_id, [])) >= 2 \
                    and observed[node.node_id][-1] < observed[node.node_id][-2]:
                group, reasons = "regressing_learning", ["RECENT_OBJECTIVE_SCORE_REGRESSED"]
            elif state.status == AbilityStatus.SELF_REPORTED and (state.self_report_prior or 0) < 0.60:
                group, reasons = "low_self_report", ["LOW_CONFIDENCE_SELF_REPORT_BELOW_0_60"]
            elif state.status == AbilityStatus.UNASSESSED and downstream(node.node_id) > 0:
                group, reasons = "unassessed_prerequisite", ["UNASSESSED_BLOCKING_PREREQUISITE"]
            if group:
                candidates.append((group_order[group], -downstream(node.node_id),
                                   state.mastery_score is None, state.mastery_score or 0.0,
                                   sort_time(state.last_updated),
                                   node.node_id, group, reasons, state))
        candidates.sort(key=lambda item: item[:6])
        return [WeaknessPriorityV1(
            skill_node_id=item[5], rank=index, priority_group=item[6], reason_codes=item[7],
            mastery_score=item[8].mastery_score, confidence=item[8].confidence,
            downstream_count=-item[1],
        ) for index, item in enumerate(candidates, start=1)]

    def focus_snapshot(
        self,
        profile: LearnerProfile,
        *,
        mode: str,
        explicit_node_ids: list[str],
        created_at: datetime | None = None,
    ) -> LearnerFocusSnapshotV1:
        if not profile.knowledge_base_id:
            raise ValueError("learner knowledge base is required")
        nodes = {node.node_id for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(explicit_node_ids) - nodes)
        if unknown:
            raise ValueError(f"target nodes outside knowledge base: {', '.join(unknown)}")
        priorities = self.weakness_priorities(profile)
        states = self.repository.list_states(profile.learner_id, profile.knowledge_base_id)
        snapshot_hash = _canonical_hash([item.model_dump(mode="json") for item in states])
        skipped: list[LearnerFocusSkippedV1] = []
        if explicit_node_ids:
            focus_mode = "explicit"
            adopted = list(dict.fromkeys(explicit_node_ids))[:3]
            skipped = [LearnerFocusSkippedV1(
                skill_node_id=item.skill_node_id, reason_code="EXPLICIT_TARGETS_SELECTED"
            ) for item in priorities if item.skill_node_id not in adopted]
        elif mode == "off":
            focus_mode = "off"
            adopted = []
            skipped = [LearnerFocusSkippedV1(
                skill_node_id=item.skill_node_id, reason_code="PROFILE_FOCUS_DISABLED"
            ) for item in priorities]
        else:
            focus_mode = "auto"
            adopted = [item.skill_node_id for item in priorities[:3]]
            skipped = [LearnerFocusSkippedV1(
                skill_node_id=item.skill_node_id, reason_code="MAX_FOCUS_NODES_REACHED"
            ) for item in priorities[3:]]
            if not priorities:
                skipped = [LearnerFocusSkippedV1(skill_node_id="*", reason_code="NO_ELIGIBLE_WEAKNESS")]
        return LearnerFocusSnapshotV1(
            learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id,
            profile_version=profile.profile_version,
            mastery_snapshot_hash=snapshot_hash,
            focus_mode=focus_mode,
            ranked_priorities=priorities,
            adopted_node_ids=adopted,
            skipped=skipped,
            created_at=created_at or datetime.now(timezone.utc),
        )


__all__ = ["MasteryService"]
