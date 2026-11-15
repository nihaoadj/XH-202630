"""Deterministic ability projections over facts already read by MasteryService.

These functions do not read repositories, initialize learner state, or own a
transaction. Input order and legacy node shapes remain part of the service contract.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from app.core.learning_tiers import label_for_tier
from app.models.learners.mastery import (
    AbilityConfidence, AbilityEvidenceSource, AbilityMasteryStateV2,
    AbilityNodeProjectionV1, AbilityNodeSummaryV1, AbilityStateEventV1, AbilityStatus,
    CurriculumNodeProgressV1, CurriculumProgressStatus, CurriculumProgressSummaryV1,
    LearnerFocusSkippedV1, WeaknessPriorityV1,
)
from app.models.learning_documents.schemas import SkillNode


def summarize_curriculum(nodes: list[CurriculumNodeProgressV1]) -> CurriculumProgressSummaryV1:
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


def objective_mastery_history(events: list[AbilityStateEventV1]) -> dict[str, list[float]]:
    objective_after: dict[str, list[float]] = {}
    for event in events:
        if event.verified and event.source_type in {
            AbilityEvidenceSource.DIAGNOSIS, AbilityEvidenceSource.LEARNING_ATTEMPT,
        } and event.after_state.mastery_score is not None:
            objective_after.setdefault(event.skill_node_id, []).append(event.after_state.mastery_score)
    return objective_after


def project_ability_nodes(
    nodes: list[SkillNode],
    states: list[AbilityMasteryStateV2],
    objective_after: dict[str, list[float]],
    priorities: list[WeaknessPriorityV1],
    *,
    get_node_tier: Callable[[object], int],
) -> tuple[list[AbilityNodeProjectionV1], AbilityNodeSummaryV1]:
    state_by_id = {item.skill_node_id: item for item in states}
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
            tier=get_node_tier(node),
            tier_label=label_for_tier(get_node_tier(node)),
            prerequisites=node.prerequisites,
            children=node.children,
            mastery=state_by_id[node.node_id],
            trend_delta=trend_delta,
            priority=priority_by_id.get(node.node_id),
        ))
    counts = {status: 0 for status in AbilityStatus}
    for state in states:
        counts[state.status] += 1
    return projected, AbilityNodeSummaryV1(
        total_count=len(states),
        mastered_count=counts[AbilityStatus.MASTERED],
        learning_count=counts[AbilityStatus.LEARNING],
        weak_count=counts[AbilityStatus.WEAK],
        self_reported_count=counts[AbilityStatus.SELF_REPORTED],
        unassessed_count=counts[AbilityStatus.UNASSESSED],
        medium_or_high_confidence_count=sum(
            item.confidence in {AbilityConfidence.MEDIUM, AbilityConfidence.HIGH} for item in states
        ),
    )


def rank_weakness_priorities(
    nodes: list[SkillNode],
    states: list[AbilityMasteryStateV2],
    published_counts: dict[str, int],
    events: list[AbilityStateEventV1],
) -> list[WeaknessPriorityV1]:
    """Rank the full curriculum, preserving group and stable tie-break order."""
    names = {node.node_id: node.name for node in nodes}
    state_by_id = {item.skill_node_id: item for item in states}
    covered = {node_id for node_id, count in published_counts.items() if count > 0}
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


def select_focus_nodes(
    priorities: list[WeaknessPriorityV1], *, mode: str, explicit_node_ids: list[str],
) -> tuple[Literal["auto", "off", "explicit"], list[str], list[LearnerFocusSkippedV1]]:
    """Choose focus from validated targets and an already-ranked snapshot."""
    focus_mode: Literal["auto", "off", "explicit"]
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
    return focus_mode, adopted, skipped
