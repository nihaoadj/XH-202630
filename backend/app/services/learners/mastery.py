"""Single policy surface for learner ability state, priorities and projections."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.db.learners.mastery import BaseMasteryRepository
from app.db.learners.curriculum import BaseCurriculumRepository
from app.db.learners.tier_progress import BaseTierProgressRepository
from app.core.learning_tiers import (
    MAX_TIER, TIER_POLICY_VERSION, difficulty_for_tier, label_for_tier, tier_for_level,
)
from app.db.learning_documents.base import BaseResourceRepository
from app.models.learners.mastery import (
    MASTERY_CONFIRMATION_THRESHOLD,
    AbilityConfidence,
    AbilityEvidenceSource,
    AbilityEvidenceV1,
    AbilityNodeProjectionV1,
    AbilityNodesResponseV1,
    AbilityNodeSummaryV1,
    AbilityStatus,
    CurriculumNodeProgressV1,
    CurriculumProgressStatus,
    CurriculumProgressSummaryV1,
    LearnerFocusSkippedV1,
    LearnerFocusSnapshotV1,
    LearnerTierProgressV1,
    LearningIntent,
    NextGenerationCandidateV1,
    NextGenerationOptionsV1,
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
    def __init__(
        self,
        repository: BaseMasteryRepository,
        knowledge_service: KnowledgeService,
        resource_repo: BaseResourceRepository | None = None,
        curriculum_repo: BaseCurriculumRepository | None = None,
        tier_progress_repo: BaseTierProgressRepository | None = None,
    ):
        self.repository = repository
        self.knowledge_service = knowledge_service
        self.resource_repo = resource_repo
        self.curriculum_repo = curriculum_repo
        self.tier_progress_repo = tier_progress_repo

    def _nodes(self, knowledge_base_id: str):
        return self.knowledge_service.list_skill_nodes(knowledge_base_id)

    @staticmethod
    def _node_tier(node: object) -> int:
        value = getattr(node, "tier", None)
        if value is not None:
            return int(value)
        # Catalog imports reject missing tiers.  This only keeps legacy in-memory
        # projections (created before the migration) deterministic.
        level = getattr(node, "level", None)
        return tier_for_level(level) if level is not None else 1

    def _published_node_counts(
        self,
        learner_id: str,
        names: dict[str, str],
    ) -> dict[str, int]:
        """Return durable curriculum exposure counts from published resources.

        New resource specs persist graph node IDs.  Older resources may contain
        the display name instead, so normalize both representations here rather
        than losing historical coverage when a learner continues their plan.
        Names that are not unique in a graph are intentionally not guessed.
        """
        counts = {node_id: 0 for node_id in names}
        if self.resource_repo is None:
            return counts
        ids_by_unique_name: dict[str, str | None] = {}
        for node_id, name in names.items():
            ids_by_unique_name[name] = (
                node_id if name not in ids_by_unique_name else None
            )
        for resource in self.resource_repo.list_by_learner(learner_id):
            if resource.publication_status != "published":
                continue
            resource_nodes: set[str] = set()
            for point in resource.knowledge_points or []:
                raw_value = str(point).strip()
                node_id = raw_value if raw_value in counts else ids_by_unique_name.get(raw_value)
                if node_id:
                    resource_nodes.add(node_id)
            for node_id in resource_nodes:
                counts[node_id] += 1
        return counts

    def _curriculum_nodes(
        self, profile: LearnerProfile, names: dict[str, str],
    ) -> list[CurriculumNodeProgressV1]:
        """Ensure the full graph is tracked, then reconcile durable publication facts."""
        if self.curriculum_repo is None or not profile.knowledge_base_id:
            return []
        self.curriculum_repo.ensure_nodes(profile.learner_id, profile.knowledge_base_id, list(names))
        return self.curriculum_repo.reconcile_exposure(
            profile.learner_id, profile.knowledge_base_id,
            self._published_node_counts(profile.learner_id, names), datetime.now(timezone.utc),
        )

    def _tier_progress(self, profile: LearnerProfile) -> LearnerTierProgressV1 | None:
        if self.tier_progress_repo is None or not profile.knowledge_base_id:
            return None
        tier = tier_for_level(profile.skill_level)
        state = self.tier_progress_repo.get_or_create(
            profile.learner_id, profile.knowledge_base_id,
            placement_tier=tier, profile_version=profile.profile_version,
        )
        self._apply_placement_exemptions(profile, state)
        return state

    def initialize_tier_progress(self, profile: LearnerProfile) -> LearnerTierProgressV1 | None:
        """Public onboarding hook; safe to call repeatedly."""
        return self._tier_progress(profile)

    def finalize_initial_placement(self, profile: LearnerProfile, *, tier: int) -> LearnerTierProgressV1 | None:
        """Commit the calibrated tier only after the initial diagnostic flow ends."""
        if not self.tier_progress_repo or not profile.knowledge_base_id:
            return None
        state = self.tier_progress_repo.get_or_create(
            profile.learner_id, profile.knowledge_base_id,
            placement_tier=tier, profile_version=profile.profile_version,
        )
        state = state.model_copy(update={
            "placement_tier": tier,
            "active_tier": tier,
            "highest_unlocked_tier": tier,
            "remediation_return_tier": None,
            "profile_version": profile.profile_version,
        })
        saved = self.tier_progress_repo.save(state)
        self._apply_placement_exemptions(profile, saved)
        return saved

    def _apply_placement_exemptions(self, profile: LearnerProfile, state: LearnerTierProgressV1) -> None:
        """Record placement as unverified self-report, never as objective completion."""
        if self.curriculum_repo is None or not profile.knowledge_base_id or state.placement_tier <= 1:
            return
        graph = self._nodes(profile.knowledge_base_id)
        exempt_ids = [node.node_id for node in graph if self._node_tier(node) < state.placement_tier]
        if not exempt_ids:
            return
        source_id = _stable_id("placement", profile.learner_id, profile.knowledge_base_id, state.placement_tier)
        names = {node.node_id: node.name for node in graph}
        evidence = [AbilityEvidenceV1(
            evidence_id=_stable_id("abe", source_id, node_id), learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id, skill_node_id=node_id,
            source_type=AbilityEvidenceSource.ONBOARDING_SELF_REPORT, source_id=source_id,
            source_hash=_canonical_hash({"placement_tier": state.placement_tier, "node_id": node_id}),
            observed_score=1.0, verified=False,
        ) for node_id in exempt_ids]
        self.repository.apply_evidence(evidence, names, increment_profile_version=False)
        self.curriculum_repo.ensure_nodes(profile.learner_id, profile.knowledge_base_id, list(names))
        self.curriculum_repo.set_placement_exemptions(
            profile.learner_id, profile.knowledge_base_id, node_ids=exempt_ids,
            evidence_id=source_id, now=datetime.now(timezone.utc),
        )

    @staticmethod
    def _curriculum_summary(nodes: list[CurriculumNodeProgressV1]) -> CurriculumProgressSummaryV1:
        counts = {status: 0 for status in CurriculumProgressStatus}
        for node in nodes:
            counts[node.progress_status] += 1
        return CurriculumProgressSummaryV1(
            total_count=len(nodes), unplanned_count=counts[CurriculumProgressStatus.UNPLANNED],
            scheduled_count=counts[CurriculumProgressStatus.SCHEDULED],
            exposed_count=counts[CurriculumProgressStatus.EXPOSED],
            verification_pending_count=counts[CurriculumProgressStatus.VERIFICATION_PENDING],
            completed_count=counts[CurriculumProgressStatus.COMPLETED],
            reinforcement_due_count=counts[CurriculumProgressStatus.REINFORCEMENT_DUE],
        )

    def curriculum_progress(self, profile: LearnerProfile) -> tuple[list[CurriculumNodeProgressV1], CurriculumProgressSummaryV1 | None]:
        if not profile.knowledge_base_id:
            return [], None
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        nodes = self._curriculum_nodes(profile, names)
        return nodes, self._curriculum_summary(nodes) if nodes else None

    def classify_generation_selection(
        self, profile: LearnerProfile, selected_node_ids: list[str], *, intent: LearningIntent | None = None,
    ) -> tuple[str, int]:
        """Return the explicit selection type and effective resource tier."""
        if not profile.knowledge_base_id or not selected_node_ids:
            raise ValueError("generation selection requires target nodes")
        nodes = {node.node_id: node for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(selected_node_ids) - set(nodes))
        if unknown:
            raise ValueError(f"target nodes outside knowledge base: {', '.join(unknown)}")
        tiers = {self._node_tier(nodes[node_id]) for node_id in selected_node_ids}
        state = self._tier_progress(profile)
        active = state.active_tier if state else tier_for_level(profile.skill_level)
        if len(tiers) == 1:
            target_tier = int(next(iter(tiers)))
            if target_tier == active:
                return ("same_tier_prerequisite" if intent == LearningIntent.DOWNGRADE_LEARNING else "same_tier", target_tier)
            if target_tier == active - 1 and intent == LearningIntent.DOWNGRADE_LEARNING:
                return "lower_tier_selection", target_tier
            raise ValueError("selected nodes are outside the current learning tier")
        if intent != LearningIntent.LEARN_NEW_AND_REINFORCE or len(selected_node_ids) != 2:
            raise ValueError("selected nodes must belong to one learning tier")
        high = max(tiers); low = min(tiers)
        if low != high - 1 or high not in {active, active + 1}:
            raise ValueError("cross-tier selection is not available")
        if high == active + 1 and (
            state is None or state.highest_unlocked_tier < high or not self._is_tier_completed(profile, active)
        ):
            raise ValueError("higher tier is not unlocked")
        published = self._published_node_counts(
            profile.learner_id, {node_id: node.name for node_id, node in nodes.items()}
        )
        high_id = next(node_id for node_id in selected_node_ids if self._node_tier(nodes[node_id]) == high)
        low_id = next(node_id for node_id in selected_node_ids if self._node_tier(nodes[node_id]) == low)
        if published.get(high_id, 0) > 0 or published.get(low_id, 0) <= 0:
            raise ValueError("cross-tier selection requires a new higher node and a learned prerequisite")
        ancestors = set()
        frontier = [high_id]
        while frontier:
            current = frontier.pop()
            for prerequisite in nodes[current].prerequisites:
                if prerequisite not in ancestors:
                    ancestors.add(prerequisite)
                    if prerequisite in nodes:
                        frontier.append(prerequisite)
        if low_id not in ancestors:
            raise ValueError("cross-tier review node must be a prerequisite")
        return "cross_tier_prerequisite_review", high

    def schedule_generation(
        self, profile: LearnerProfile, *, run_id: str, selected_node_ids: list[str], selection_type: str | None = None,
    ) -> None:
        """Atomically settle curriculum wait debt and lock a confirmed batch."""
        if self.curriculum_repo is None or not profile.knowledge_base_id or not selected_node_ids:
            return
        graph = self._nodes(profile.knowledge_base_id)
        if selection_type == "correction_package":
            # Correction targets are the just-assessed node and are allowed
            # even when a recommendation points to another tier.
            pass
        elif selection_type in {"lower_tier_selection", "cross_tier_prerequisite_review"}:
            intent = (
                LearningIntent.DOWNGRADE_LEARNING
                if selection_type == "lower_tier_selection"
                else LearningIntent.LEARN_NEW_AND_REINFORCE
            )
            self.classify_generation_selection(profile, selected_node_ids, intent=intent)
        else:
            self.validate_generation_targets(profile, selected_node_ids)
        names = {node.node_id: node.name for node in graph}
        current = {item.skill_node_id: item for item in self._curriculum_nodes(profile, names)}
        covered = {node_id for node_id, item in current.items()
                   if item.placement_exempt or item.progress_status == CurriculumProgressStatus.COMPLETED}
        selected = set(selected_node_ids)
        eligible = [node.node_id for node in graph if (
            node.node_id in selected or (
            current.get(node.node_id, CurriculumNodeProgressV1(
                learner_id=profile.learner_id, knowledge_base_id=profile.knowledge_base_id,
                skill_node_id=node.node_id,
            )).progress_status in {CurriculumProgressStatus.UNPLANNED, CurriculumProgressStatus.REINFORCEMENT_DUE}
            and all(prerequisite in covered for prerequisite in node.prerequisites if prerequisite in names)
            )
        )]
        prior_tier_state = self._tier_progress(profile)
        try:
            self.curriculum_repo.schedule_round(
                profile.learner_id, profile.knowledge_base_id, run_id=run_id,
                selected_node_ids=list(dict.fromkeys(selected_node_ids))[:2],
                eligible_unplanned_ids=eligible, now=datetime.now(timezone.utc),
            )
            if selection_type in {"lower_tier_selection", "cross_tier_prerequisite_review"}:
                state = prior_tier_state
                if state is not None:
                    nodes = {node.node_id: node for node in graph}
                    target_tier = max(self._node_tier(nodes[node_id]) for node_id in selected_node_ids)
                    if selection_type == "lower_tier_selection":
                        target_tier = min(self._node_tier(nodes[node_id]) for node_id in selected_node_ids)
                    self.tier_progress_repo.save(state.model_copy(update={
                        "active_tier": target_tier,
                        "remediation_return_tier": None,
                        "profile_version": profile.profile_version,
                    }))
        except Exception:
            # A failed task must not leave a scheduled curriculum node or a
            # changed active tier visible to the report.
            self.curriculum_repo.release_failed_run(
                profile.learner_id, profile.knowledge_base_id, run_id=run_id,
                now=datetime.now(timezone.utc),
            )
            if prior_tier_state is not None and self.tier_progress_repo is not None:
                self.tier_progress_repo.save(prior_tier_state)
            raise

    def validate_generation_targets(self, profile: LearnerProfile, selected_node_ids: list[str]) -> int | None:
        """Hard gate for every entry point that creates node-targeted resources."""
        if not selected_node_ids:
            return None
        if len(selected_node_ids) > 2:
            raise ValueError("at most two target skill nodes are allowed")
        if not profile.knowledge_base_id:
            raise ValueError("learner knowledge base is required")
        metadata = profile.learning_preferences.metadata if profile.learning_preferences else {}
        initial_flow = metadata.get("initial_diagnostic_flow", {}) if isinstance(metadata, dict) else {}
        initial_node_id = initial_flow.get("initial_recommended_node_id") if isinstance(initial_flow, dict) else None
        if initial_flow.get("status") == "final" and initial_node_id and not any(
            item.publication_status == "published" for item in (self.resource_repo.list_by_learner(profile.learner_id) if self.resource_repo else [])
        ) and list(dict.fromkeys(selected_node_ids)) != [initial_node_id]:
            raise ValueError("首轮资源必须使用初始诊断推荐的单一能力节点")
        nodes = {node.node_id: node for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(selected_node_ids) - set(nodes))
        if unknown:
            raise ValueError(f"target nodes outside knowledge base: {', '.join(unknown)}")
        tiers = {self._node_tier(nodes[node_id]) for node_id in selected_node_ids}
        if len(tiers) != 1:
            raise ValueError("target skill nodes must belong to one learning tier")
        state = self._tier_progress(profile)
        target_tier = int(next(iter(tiers)))
        if state is not None and target_tier != state.active_tier:
            raise ValueError("target skill nodes are outside the active learning tier")
        return target_tier

    def validate_correction_targets(
        self,
        profile: LearnerProfile,
        selected_node_ids: list[str],
        correction_snapshot: dict[str, Any],
    ) -> int | None:
        """Validate a correction pack without applying the active-tier gate.

        A remedial feedback decision can lower ``active_tier`` before the
        learner chooses a correction pack. The pack repairs the just-assessed
        node, so it must remain allowed even when that node is now above the
        temporary remedial tier. Its immutable snapshot is the authority for
        the target set and prevents this exception from becoming a generic
        cross-tier generation bypass.
        """
        if not profile.knowledge_base_id or not selected_node_ids:
            raise ValueError("correction targets require a learner knowledge base")
        ordered = correction_snapshot.get("ordered_target_nodes")
        snapshot_ids = [
            str(item.get("skill_node_id") or "")
            for item in ordered
            if isinstance(item, dict)
        ] if isinstance(ordered, list) else []
        selected = list(dict.fromkeys(selected_node_ids))
        if not 1 <= len(selected) <= 2 or selected != snapshot_ids:
            raise ValueError("correction targets do not match the feedback snapshot")
        nodes = {node.node_id: node for node in self._nodes(profile.knowledge_base_id)}
        if set(selected) - set(nodes):
            raise ValueError("correction targets outside knowledge base")
        tiers = {self._node_tier(nodes[node_id]) for node_id in selected}
        if len(tiers) != 1:
            raise ValueError("correction targets must belong to one learning tier")
        return int(next(iter(tiers)))

    def apply_tier_feedback(
        self, profile: LearnerProfile, *, point_scores: dict[str, float],
    ) -> LearnerTierProgressV1 | None:
        """Apply the auditable low/practice/high tier transition after formal scoring."""
        state = self._tier_progress(profile)
        if state is None or not point_scores:
            return state
        graph = {node.node_id: node for node in self._nodes(profile.knowledge_base_id or "")}
        assessed_tiers = {self._node_tier(graph[node_id]) for node_id in point_scores if node_id in graph}
        if len(assessed_tiers) != 1:
            return state
        assessed_tier = int(next(iter(assessed_tiers)))
        low = any(score < 0.60 for score in point_scores.values())
        high = bool(point_scores) and all(
            score >= MASTERY_CONFIRMATION_THRESHOLD for score in point_scores.values()
        )
        updated = state
        if low and assessed_tier > 1:
            targets, _, _ = self.recommend_feedback_targets(
                profile, action="remediate", point_scores=point_scores,
            )
            if self.curriculum_repo is not None:
                self.curriculum_repo.require_placement_verification(
                    profile.learner_id, profile.knowledge_base_id or "", node_ids=targets,
                    now=datetime.now(timezone.utc),
                )
            # A feedback result only creates a recommendation. The learner
            # must explicitly choose a lower-tier target before active_tier changes.
            updated = state
        elif high and state.remediation_return_tier and assessed_tier == state.active_tier:
            # Legacy states may still contain a return tier from the old
            # automatic downgrade behavior. Do not auto-promote them either.
            updated = state
        elif high and self._is_tier_completed(profile, assessed_tier) and assessed_tier < MAX_TIER:
            next_tier = assessed_tier + 1
            updated = state.model_copy(update={
                "active_tier": next_tier,
                "highest_unlocked_tier": max(state.highest_unlocked_tier, next_tier),
                "profile_version": profile.profile_version,
            })
        if updated != state:
            return self.tier_progress_repo.save(updated) if self.tier_progress_repo else updated
        return state

    def recommend_feedback_targets(
        self, profile: LearnerProfile, *, action: str, point_scores: dict[str, float],
    ) -> tuple[list[str], int | None, int | None]:
        """Return same-tier targets or the closest lower-tier prerequisites."""
        if not profile.knowledge_base_id or not point_scores:
            return list(point_scores), None, None
        graph = {node.node_id: node for node in self._nodes(profile.knowledge_base_id)}
        assessed = [node_id for node_id in point_scores if node_id in graph]
        tiers = {self._node_tier(graph[node_id]) for node_id in assessed}
        if len(tiers) != 1:
            return assessed[:2], None, None
        assessed_tier = int(next(iter(tiers)))
        if action != "remediate" or assessed_tier == 1:
            return assessed[:2], assessed_tier, None
        weak = [node_id for node_id in assessed if point_scores[node_id] < 0.60]
        candidates: list[str] = []
        queue = list(weak)
        visited = set(queue)
        while queue:
            child_id = queue.pop(0)
            for parent_id in graph[child_id].prerequisites:
                parent = graph.get(parent_id)
                if parent is None or parent_id in visited:
                    continue
                visited.add(parent_id)
                if self._node_tier(parent) == assessed_tier - 1:
                    candidates.append(parent_id)
                else:
                    queue.append(parent_id)
        # The graph traversal is deterministic because metadata order is frozen;
        # node ID finishes tie-breaking across branches.
        selected = sorted(set(candidates))[:2]
        return (selected or weak[:2]), assessed_tier - 1, assessed_tier

    def _is_tier_completed(self, profile: LearnerProfile, tier: int) -> bool:
        graph = self._nodes(profile.knowledge_base_id or "")
        records, _ = self.curriculum_progress(profile)
        by_id = {item.skill_node_id: item for item in records}
        tier_nodes = [item for item in graph if self._node_tier(item) == tier]
        return bool(tier_nodes) and all(
            by_id.get(node.node_id) and by_id[node.node_id].progress_status == CurriculumProgressStatus.COMPLETED
            for node in tier_nodes
        )

    def record_curriculum_verification(
        self, profile: LearnerProfile, *, attempt_id: str, point_scores: dict[str, float], occurred_at: datetime,
    ) -> None:
        if self.curriculum_repo is None or not profile.knowledge_base_id:
            return
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        self._curriculum_nodes(profile, names)
        self.curriculum_repo.record_verification(
            profile.learner_id, profile.knowledge_base_id, attempt_id=attempt_id,
            scores={node_id: score for node_id, score in point_scores.items() if node_id in names}, now=occurred_at,
        )

    def release_failed_generation(self, profile: LearnerProfile, *, run_id: str) -> None:
        if self.curriculum_repo is None or not profile.knowledge_base_id:
            return
        self.curriculum_repo.release_failed_run(
            profile.learner_id, profile.knowledge_base_id, run_id=run_id,
            now=datetime.now(timezone.utc),
        )

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
        assessment_metadata: dict[str, dict[str, Any]] | None = None,
    ):
        if not profile.knowledge_base_id:
            raise ValueError("learner knowledge_base_id is required")
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(node_scores) - set(names))
        if unknown:
            raise ValueError(f"diagnosis nodes outside knowledge base: {', '.join(unknown)}")
        if not node_scores:
            # A partial diagnostic still needs a complete unassessed graph
            # projection so the report can distinguish "not measured" from
            # "weak" and expose the missing dimensions.
            states = self.repository.ensure_states(
                profile.learner_id, profile.knowledge_base_id, names,
            )
            return states, profile.profile_version, False
        metadata_by_node = assessment_metadata or {}
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
            assessment_kind="initial_diagnosis",
            assessment_session_id=metadata_by_node.get(node_id, {}).get("assessment_session_id") or source_id,
            assessment_form_id=metadata_by_node.get(node_id, {}).get("assessment_form_id") or "initial-diagnostic-v1",
            question_ids=list(metadata_by_node.get(node_id, {}).get("question_ids", [])),
            covered_dimensions=list(metadata_by_node.get(node_id, {}).get("covered_dimensions", [])),
            scoring_audit_status="single_pass",
            occurred_at=occurred_at,
        ) for node_id, score in sorted(node_scores.items())]
        return self.repository.apply_evidence(evidence, names, increment_profile_version=True)

    def apply_learning_attempt(
        self,
        profile: LearnerProfile,
        *,
        attempt_id: str,
        point_scores: dict[str, float],
        occurred_at: datetime,
        assessment_metadata: dict[str, Any] | None = None,
    ):
        """Project a server-scored feedback attempt without incrementing profile twice."""
        if not profile.knowledge_base_id:
            return [], profile.profile_version, False
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(point_scores) - set(names))
        if unknown:
            raise ValueError(f"attempt nodes outside knowledge base: {', '.join(unknown)}")
        source_hash = _canonical_hash({"attempt_id": attempt_id, "scores": point_scores})
        metadata = assessment_metadata or {}
        question_trace = metadata.get("question_trace", []) if isinstance(metadata, dict) else []
        trace_by_point: dict[str, list[dict[str, Any]]] = {}
        for item in question_trace:
            if isinstance(item, dict):
                trace_by_point.setdefault(str(item.get("skill_node_id") or item.get("knowledge_point") or ""), []).append(item)
        scoring_audit = metadata.get("scoring_audit", {}) if isinstance(metadata, dict) else {}
        evidence = [AbilityEvidenceV1(
            evidence_id=_stable_id("abe", attempt_id, node_id), learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id, skill_node_id=node_id,
            source_type=AbilityEvidenceSource.LEARNING_ATTEMPT, source_id=attempt_id,
            source_hash=source_hash, observed_score=score, verified=True,
            assessment_kind=metadata.get("assessment_kind", "learning_check"),
            assessment_session_id=metadata.get("assessment_session_id") or attempt_id,
            assessment_form_id=metadata.get("assessment_form_id") or source_hash,
            question_ids=[str(item.get("question_id")) for item in trace_by_point.get(node_id, []) if item.get("question_id")],
            covered_dimensions=list(dict.fromkeys(
                str(item.get("diagnostic_dimension")) for item in trace_by_point.get(node_id, [])
                if item.get("diagnostic_dimension") in {"concept", "scenario", "misconception", "practice"}
            )),
            scoring_audit_status=str(scoring_audit.get(node_id, "single_pass")),
            # Later formal attempts remain valid evidence even when their
            # question blueprint covers only one dimension. Dimension
            # coverage is accumulated for promotion instead of rejecting the
            # entire attempt.
            evidence_eligible=str(scoring_audit.get(node_id, "single_pass")) not in {"double_disagreement", "failed"},
            occurred_at=occurred_at,
        ) for node_id, score in sorted(point_scores.items())]
        return self.repository.apply_evidence(evidence, names, increment_profile_version=False)

    def assessment_eligibility(
        self, profile: LearnerProfile, *, point_ids: list[str], metadata: dict[str, Any]
    ) -> dict[str, bool]:
        """Check whether a formal attempt can add objective evidence.

        The answer remains auditable even when a repeated question set is
        submitted: the attempt is retained, but it cannot promote mastery.
        """
        trace = metadata.get("question_trace", []) if isinstance(metadata, dict) else []
        traces: dict[str, list[dict[str, Any]]] = {}
        for item in trace:
            if isinstance(item, dict):
                key = str(item.get("skill_node_id") or item.get("knowledge_point") or "")
                traces.setdefault(key, []).append(item)
        session_id = metadata.get("assessment_session_id") or metadata.get("source_run_id")
        audit = metadata.get("scoring_audit", {}) if isinstance(metadata, dict) else {}
        result = {}
        for point_id in point_ids:
            # Dimension coverage is not an eligibility gate for later
            # attempts. It is evaluated cumulatively by assessment_dimension_ready.
            eligible = str(audit.get(point_id, "single_pass")) not in {"double_disagreement", "failed"}
            question_ids = {str(item.get("question_id")) for item in traces.get(point_id, []) if item.get("question_id")}
            if eligible and session_id and question_ids:
                for event in self.repository.list_events(profile.learner_id, profile.knowledge_base_id or ""):
                    if event.skill_node_id != point_id or not event.verified or not event.evidence_eligible:
                        continue
                    prior_session = event.assessment_session_id or event.source_id
                    if prior_session != session_id and question_ids.intersection(event.question_ids):
                        eligible = False
                        break
            result[point_id] = eligible
        return result

    def assessment_dimension_ready(
        self, profile: LearnerProfile, *, point_ids: list[str], metadata: dict[str, Any]
    ) -> dict[str, bool]:
        """Return whether each node has initial or cumulative dimension coverage."""
        required = {"concept", "scenario", "misconception"}
        trace = metadata.get("question_trace", []) if isinstance(metadata, dict) else []
        current: dict[str, set[str]] = {}
        for item in trace:
            if not isinstance(item, dict):
                continue
            point_id = str(item.get("skill_node_id") or item.get("knowledge_point") or "")
            dimension = item.get("diagnostic_dimension")
            if point_id and dimension in required:
                current.setdefault(point_id, set()).add(str(dimension))
        events = self.repository.list_events(profile.learner_id, profile.knowledge_base_id or "")
        result = {}
        for point_id in point_ids:
            node_events = [
                event for event in events
                if event.skill_node_id == point_id and event.verified and event.evidence_eligible
            ]
            cumulative = set(current.get(point_id, set()))
            initial_calibrated = False
            for event in node_events:
                dimensions = set(event.covered_dimensions)
                cumulative.update(dimensions & required)
                if event.source_type == AbilityEvidenceSource.DIAGNOSIS and required.issubset(dimensions):
                    initial_calibrated = True
            result[point_id] = initial_calibrated or required.issubset(cumulative)
        return result

    def apply_courseware_self_report(
        self, profile: LearnerProfile, *, source_id: str, node_scores: dict[str, float],
    ):
        """Record review-courseware self reports without creating objective evidence."""
        if not profile.knowledge_base_id or not node_scores:
            return [], profile.profile_version, False
        names = {node.node_id: node.name for node in self._nodes(profile.knowledge_base_id)}
        unknown = sorted(set(node_scores) - set(names))
        if unknown:
            raise ValueError(f"courseware self-report nodes outside knowledge base: {', '.join(unknown)}")
        source_hash = _canonical_hash({"source_id": source_id, "scores": node_scores})
        evidence = [AbilityEvidenceV1(
            evidence_id=_stable_id("abe", source_id, node_id), learner_id=profile.learner_id,
            knowledge_base_id=profile.knowledge_base_id, skill_node_id=node_id,
            source_type=AbilityEvidenceSource.COURSEWARE_SELF_REPORT, source_id=source_id,
            source_hash=source_hash, observed_score=score, verified=False,
            occurred_at=datetime.now(timezone.utc),
        ) for node_id, score in sorted(node_scores.items())]
        return self.repository.apply_evidence(evidence, names, increment_profile_version=False)

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
        curriculum_nodes, curriculum_summary = self.curriculum_progress(profile)
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
                tier=self._node_tier(node),
                tier_label=label_for_tier(self._node_tier(node)),
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
            curriculum_progress=curriculum_summary,
            curriculum_nodes=curriculum_nodes,
        )

    def weakness_priorities(self, profile: LearnerProfile) -> list[WeaknessPriorityV1]:
        """Rank every graph node for the learner's durable curriculum.

        The legacy name is retained for API compatibility.  Unlike the former
        exception-only queue, this projection deliberately includes every node:
        a node that is not urgent is still visible as uncovered or maintained,
        so it cannot silently disappear from a multi-round learning journey.
        """
        if not profile.knowledge_base_id:
            return []
        nodes = self._nodes(profile.knowledge_base_id)
        names = {node.node_id: node.name for node in nodes}
        states = self.repository.ensure_states(profile.learner_id, profile.knowledge_base_id, names)
        state_by_id = {item.skill_node_id: item for item in states}
        published_counts = self._published_node_counts(profile.learner_id, names)
        covered = {node_id for node_id, count in published_counts.items() if count > 0}
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
            "ready_uncovered": 2, "low_self_report": 3,
            "blocked_uncovered": 4, "maintain_mastery": 5,
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
            elif node.node_id not in covered and all(
                prerequisite in covered for prerequisite in node.prerequisites if prerequisite in names
            ):
                group, reasons = "ready_uncovered", ["CURRICULUM_COVERAGE_PENDING", "PREREQUISITES_COVERED"]
            elif state.status == AbilityStatus.SELF_REPORTED and (state.self_report_prior or 0) < 0.60:
                group, reasons = "low_self_report", ["LOW_CONFIDENCE_SELF_REPORT_BELOW_0_60"]
            elif node.node_id not in covered:
                missing = [prerequisite for prerequisite in node.prerequisites if prerequisite in names and prerequisite not in covered]
                group, reasons = "blocked_uncovered", ["CURRICULUM_COVERAGE_PENDING", "PREREQUISITE_REQUIRED", *missing]
            else:
                group, reasons = "maintain_mastery", ["CURRICULUM_NODE_COVERED"]
            candidates.append((group_order[group], -downstream(node.node_id),
                               state.mastery_score is None, state.mastery_score or 0.0,
                               sort_time(state.last_updated),
                               node.node_id, group, reasons, state))
        candidates.sort(key=lambda item: item[:6])
        return [WeaknessPriorityV1(
            skill_node_id=item[5], rank=index, priority_group=item[6], reason_codes=item[7],
            mastery_score=item[8].mastery_score, confidence=item[8].confidence,
            downstream_count=-item[1],
            coverage_status="covered" if item[5] in covered else "uncovered",
            published_resource_count=published_counts[item[5]],
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
            adopted = list(dict.fromkeys(explicit_node_ids))[:2]
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
            remediation = [
                item for item in priorities
                if item.priority_group in {"confirmed_weak", "regressing_learning"}
            ]
            ready_uncovered = [
                item for item in priorities if item.priority_group == "ready_uncovered"
            ]
            # Reserve one slot for a ready, uncovered node whenever possible.
            # This makes coverage progress even while a learner needs repeated
            # remediation, instead of allowing weak nodes to monopolize every
            # subsequent resource batch.
            adopted = [item.skill_node_id for item in remediation[:1]]
            if ready_uncovered and len(adopted) < 2:
                adopted.append(ready_uncovered[0].skill_node_id)
            for item in [*remediation[1:], *ready_uncovered[1:]]:
                if len(adopted) >= 2:
                    break
                adopted.append(item.skill_node_id)
            skipped = [LearnerFocusSkippedV1(
                skill_node_id=item.skill_node_id, reason_code="MAX_FOCUS_NODES_REACHED"
            ) for item in priorities if item.skill_node_id not in adopted]
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

    def next_generation_options(self, profile: LearnerProfile) -> NextGenerationOptionsV1:
        """Return learner-selectable reinforcement and new-knowledge candidates.

        A published resource is the durable learning-exposure fact in the current
        data model.  It is deliberately kept separate from objective mastery:
        an unassessed exposed node is not silently classified as weak.
        """
        if not profile.knowledge_base_id:
            raise ValueError("learner knowledge base is required")
        tier_state = self._tier_progress(profile)
        nodes = self._nodes(profile.knowledge_base_id)
        names = {node.node_id: node.name for node in nodes}
        curriculum_nodes = {item.skill_node_id: item for item in self._curriculum_nodes(profile, names)}
        states = self.repository.ensure_states(profile.learner_id, profile.knowledge_base_id, names)
        state_by_id = {state.skill_node_id: state for state in states}
        published_counts = self._published_node_counts(profile.learner_id, names)
        exposed = {node_id for node_id, count in published_counts.items() if count > 0}
        active_tier = tier_state.active_tier if tier_state else tier_for_level(profile.skill_level)
        snapshot_hash = _canonical_hash({
            "states": [item.model_dump(mode="json") for item in states],
            "exposed": sorted(exposed),
            "profile_version": profile.profile_version,
            "tier_progress": tier_state.model_dump(mode="json") if tier_state else None,
        })
        # Downgrade is a learner choice surface. Expose active-tier nodes and
        # the immediately lower tier without changing active_tier.
        downgrade_selection = True

        def prerequisite_blockers(node) -> list[str]:
            blocked: list[str] = []
            for prerequisite in node.prerequisites:
                if prerequisite not in names:
                    continue
                record = curriculum_nodes.get(prerequisite)
                prerequisite_tier = next((self._node_tier(item) for item in nodes if item.node_id == prerequisite), None)
                satisfied = bool(record and (
                    record.progress_status == CurriculumProgressStatus.COMPLETED
                    or (prerequisite_tier is not None and prerequisite_tier < active_tier
                        and record.placement_exempt and not record.placement_verification_required)
                ))
                if not satisfied:
                    blocked.append(prerequisite)
            return blocked

        def candidate(node, group: str, rank: int) -> NextGenerationCandidateV1:
            state = state_by_id[node.node_id]
            missing_prerequisites = prerequisite_blockers(node)
            # During downgrade learning the learner is explicitly repairing a
            # prerequisite tier. Every node in that tier is a valid choice;
            # requiring the learner to unlock those same-tier prerequisites in
            # sequence would make the choice UI contradictory to the fallback
            # path and is what caused the disabled-node screen.
            if downgrade_selection and self._node_tier(node) in {active_tier, active_tier - 1}:
                missing_prerequisites = []
            reasons = (
                ["LEARNED_OBJECTIVELY_NOT_MASTERED"]
                if group == "learned_not_mastered"
                else ["ALREADY_EXPOSED"]
                if group == "learned"
                else ["NOT_YET_EXPOSED", "PREREQUISITE_REQUIRED"]
                if missing_prerequisites else ["NOT_YET_EXPOSED"]
            )
            return NextGenerationCandidateV1(
                skill_node_id=node.node_id, name=node.name, priority_group=group,
                rank=rank, reason_codes=reasons, mastery_score=state.mastery_score,
                confidence=state.confidence, prerequisite_ids=list(node.prerequisites),
                blocked_by_node_ids=missing_prerequisites,
                tier=self._node_tier(node), tier_label=label_for_tier(self._node_tier(node)),
                eligibility_status=("placement_exempt" if curriculum_nodes.get(node.node_id, CurriculumNodeProgressV1(
                    learner_id=profile.learner_id, knowledge_base_id=profile.knowledge_base_id,
                    skill_node_id=node.node_id,
                )).placement_exempt else "blocked" if missing_prerequisites else "available"),
            )

        reinforce_nodes = [
            node for node in nodes
            if self._node_tier(node) == active_tier
            and node.node_id in exposed
            and state_by_id[node.node_id].objective_evidence_count > 0
            and state_by_id[node.node_id].status in {AbilityStatus.WEAK, AbilityStatus.LEARNING}
        ]
        reinforce_nodes.sort(key=lambda node: (
            state_by_id[node.node_id].mastery_score is None,
            state_by_id[node.node_id].mastery_score if state_by_id[node.node_id].mastery_score is not None else 1.0,
            node.node_id,
        ))
        new_nodes = [node for node in nodes if self._node_tier(node) == active_tier and node.node_id not in exposed]
        new_nodes.sort(key=lambda node: (
            -(curriculum_nodes.get(node.node_id).wait_rounds if node.node_id in curriculum_nodes else 0),
            bool(prerequisite_blockers(node)), node.node_id))
        learned_nodes = [node for node in nodes if node.node_id in exposed]
        if downgrade_selection:
            learned_nodes = [node for node in learned_nodes if self._node_tier(node) == active_tier]
        learned_nodes.sort(key=lambda node: (
            state_by_id[node.node_id].status not in {AbilityStatus.WEAK, AbilityStatus.LEARNING},
            state_by_id[node.node_id].mastery_score is None,
            state_by_id[node.node_id].mastery_score if state_by_id[node.node_id].mastery_score is not None else 1.0,
            self._node_tier(node), node.node_id,
        ))
        learning_nodes = []
        seen_learning_ids: set[str] = set()
        downgrade_nodes = [node for node in nodes if self._node_tier(node) in {active_tier, active_tier - 1}]
        for node in ([*downgrade_nodes] if downgrade_selection else [*new_nodes, *learned_nodes]):
            if node.node_id in seen_learning_ids:
                continue
            seen_learning_ids.add(node.node_id)
            learning_nodes.append(node)
        recommended_reinforcement = [node.node_id for node in reinforce_nodes[:1]]
        recommended_new = [node.node_id for node in new_nodes if not candidate(node, "unlearned", 1).blocked_by_node_ids]
        # Do not use another tier to fill the remaining slots; one or two nodes is valid.
        recommended = [*recommended_reinforcement, *recommended_new[:max(0, 2 - len(recommended_reinforcement))]]
        tier_completed = self._is_tier_completed(profile, active_tier)
        cross_new_nodes = []
        cross_review_nodes = []
        cross_high_tiers = {active_tier}
        if tier_completed and tier_state and tier_state.highest_unlocked_tier >= active_tier + 1:
            cross_high_tiers.add(active_tier + 1)
        if tier_state:
            exposed_lower = {
                node_id for node_id, count in published_counts.items()
                if count > 0 and self._node_tier(next(node for node in nodes if node.node_id == node_id)) < active_tier + 1
            }
            for node in nodes:
                node_tier = self._node_tier(node)
                if node_tier not in cross_high_tiers or node.node_id in exposed:
                    continue
                ancestors: set[str] = set()
                frontier = list(node.prerequisites)
                while frontier:
                    ancestor = frontier.pop()
                    if ancestor in ancestors:
                        continue
                    ancestors.add(ancestor)
                    if ancestor in names:
                        parent = next((item for item in nodes if item.node_id == ancestor), None)
                        if parent:
                            frontier.extend(parent.prerequisites)
                reviews = sorted(
                    exposed_lower & ancestors & {
                        item.node_id for item in nodes if self._node_tier(item) == node_tier - 1
                    }
                )
                if reviews:
                    cross_new_nodes.append(node)
                    cross_review_nodes.extend(reviews)
        recommendation_type = (
            "remedial" if tier_state and tier_state.remediation_return_tier else
            "complete" if tier_completed and active_tier == MAX_TIER else
            "advance" if tier_completed else
            "practice" if recommended_reinforcement else "current_tier"
        )
        return NextGenerationOptionsV1(
            learner_id=profile.learner_id, knowledge_base_id=profile.knowledge_base_id,
            profile_version=profile.profile_version, snapshot_hash=snapshot_hash,
            reinforce_weakness=[candidate(node, "learned_not_mastered", index)
                                for index, node in enumerate(reinforce_nodes, start=1)],
            learn_new_knowledge=[candidate(node, "unlearned", index)
                                 for index, node in enumerate(new_nodes, start=1)],
            cross_tier_new_knowledge=[candidate(node, "unlearned", index)
                                      for index, node in enumerate(cross_new_nodes, start=1)],
            cross_tier_prerequisite_review=[candidate(
                next(node for node in nodes if node.node_id == node_id), "learned", index,
            ) for index, node_id in enumerate(dict.fromkeys(cross_review_nodes), start=1)],
            learning_candidates=[candidate(
                node,
                "unlearned" if node.node_id not in exposed else "learned",
                index,
            ) for index, node in enumerate(learning_nodes, start=1)],
            recommended_node_ids=recommended[:2],
            curriculum_progress=self._curriculum_summary(list(curriculum_nodes.values())) if curriculum_nodes else None,
            tier_progress=tier_state, tier_completion=tier_completed,
            recommendation_type=recommendation_type,
        )

    def confirm_next_generation_intent(
        self,
        profile: LearnerProfile,
        *,
        intent: LearningIntent,
        selected_node_ids: list[str],
        snapshot_hash: str | None = None,
    ) -> tuple[NextGenerationOptionsV1, list[str]]:
        options = self.next_generation_options(profile)
        # A feedback decision remains actionable until the learner selects a
        # follow-up.  The hash is returned to let clients correlate the view
        # they acted on, not to turn an unselected decision into an expired
        # one after a reload or an unrelated profile refresh.  Candidate,
        # prerequisite, and tier checks below remain authoritative.
        selected = list(dict.fromkeys(selected_node_ids))
        if not selected or len(selected) > 2:
            raise ValueError("selected nodes are not available for this learning intent")
        if intent in {LearningIntent.DOWNGRADE_LEARNING, LearningIntent.UPGRADE_LEARNING}:
            expected_type = (
                "remedial" if intent == LearningIntent.DOWNGRADE_LEARNING else "advance"
            )
            if intent == LearningIntent.DOWNGRADE_LEARNING:
                if not options.learning_candidates:
                    raise ValueError("selected tier learning intent is not available")
            elif options.recommendation_type != expected_type:
                raise ValueError("selected tier learning intent is not available")
            allowed = {item.skill_node_id: item for item in options.learning_candidates}
            if set(selected) - set(allowed):
                raise ValueError("selected tier learning nodes are not available")
            blocked = [node_id for node_id in selected if allowed[node_id].blocked_by_node_ids]
            if blocked:
                raise ValueError("selected tier learning has unlearned prerequisites")
            return options, selected
        if intent == LearningIntent.LEARN_NEW_AND_REINFORCE:
            if len(selected) != 2:
                raise ValueError("mixed learning requires one new and one reinforcement node")
            node_tiers = {
                self._node_tier(node)
                for node in self._nodes(profile.knowledge_base_id or "")
                if node.node_id in selected
            }
            if len(node_tiers) > 1:
                self.classify_generation_selection(
                    profile, selected, intent=LearningIntent.LEARN_NEW_AND_REINFORCE,
                )
                cross_new_ids = {item.skill_node_id for item in options.cross_tier_new_knowledge}
                cross_review_ids = {item.skill_node_id for item in options.cross_tier_prerequisite_review}
                if len(set(selected) & cross_new_ids) != 1 or len(set(selected) & cross_review_ids) != 1:
                    raise ValueError("cross-tier learning requires one new node and one learned prerequisite")
                return options, selected
            reinforce_ids = {item.skill_node_id for item in options.reinforce_weakness}
            new_by_id = {item.skill_node_id: item for item in options.learn_new_knowledge}
            selected_reinforce = [node_id for node_id in selected if node_id in reinforce_ids]
            selected_new = [node_id for node_id in selected if node_id in new_by_id]
            if len(selected_reinforce) != 1 or len(selected_new) != 1:
                raise ValueError("mixed learning requires one new and one reinforcement node")
            if new_by_id[selected_new[0]].blocked_by_node_ids:
                raise ValueError("selected new knowledge has unlearned prerequisites")
            return options, selected
        candidates = (options.reinforce_weakness if intent == LearningIntent.REINFORCE_WEAKNESS
                      else options.learn_new_knowledge)
        allowed = {item.skill_node_id: item for item in candidates}
        if set(selected) - set(allowed):
            raise ValueError("selected nodes are not available for this learning intent")
        blocked = [node_id for node_id in selected if allowed[node_id].blocked_by_node_ids]
        if blocked:
            raise ValueError("selected new knowledge has unlearned prerequisites")
        return options, selected

    def confirm_correction_targets(
        self,
        profile: LearnerProfile,
        *,
        selected_node_ids: list[str],
        snapshot_hash: str | None = None,
        allowed_target_ids: list[str] | None = None,
    ) -> tuple[NextGenerationOptionsV1, list[str]]:
        """Validate optional correction-pack targets without changing curriculum intent."""
        options = self.next_generation_options(profile)
        # See ``confirm_next_generation_intent``: an unselected feedback
        # option must remain available when the learner returns later.
        selected = list(dict.fromkeys(selected_node_ids))
        if not selected or len(selected) > 2:
            raise ValueError("correction targets must contain one or two nodes")
        allowed = {str(item) for item in (allowed_target_ids or [])}
        if not allowed or set(selected) - allowed:
            raise ValueError("correction targets are not available")
        return options, selected


__all__ = ["MasteryService"]
