"""Validated deterministic mutations for the minimal P0-07 learning path."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.agents.learning_agents.feedback_policy_agent import FeedbackPolicyDecision
from app.models.feedback.feedback_loop import (
    FeedbackAction,
    LearningAttempt,
    LearningPath,
    LearningPathNode,
    PathMutation,
    PathMutationType,
    PathNodeStatus,
    PathNodeType,
)


def _stable_id(prefix: str, *parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def ensure_learning_path(attempt: LearningAttempt, existing: LearningPath | None) -> LearningPath:
    if existing is not None:
        return existing.model_copy(deep=True)
    path_id = _stable_id("path", attempt.learner_id)
    nodes: list[LearningPathNode] = []
    previous_id: str | None = None
    for index, item in enumerate(attempt.knowledge_point_results, start=1):
        node_id = _stable_id("node", path_id, "core", item.knowledge_point_id)
        nodes.append(LearningPathNode(
            node_id=node_id,
            path_id=path_id,
            knowledge_point_id=item.knowledge_point_id,
            node_type=PathNodeType.CORE,
            sequence=index,
            status=PathNodeStatus.IN_PROGRESS if index == 1 else PathNodeStatus.LOCKED,
            prerequisite_ids=[previous_id] if previous_id else [],
            source="feedback",
        ))
        previous_id = node_id
    return LearningPath(path_id=path_id, learner_id=attempt.learner_id, version=1, nodes=nodes)


def mutate_learning_path(
    *,
    attempt: LearningAttempt,
    decision_id: str,
    policy: FeedbackPolicyDecision,
    existing: LearningPath | None,
    advance_knowledge_point_id: str | None = None,
) -> tuple[LearningPath, PathMutation]:
    path = ensure_learning_path(attempt, existing)
    before_version = path.version
    node_by_id = {item.node_id: item for item in path.nodes}
    if attempt.path_node_id:
        current = node_by_id.get(attempt.path_node_id)
        if current is None:
            raise ValueError("attempt path_node_id does not exist in current path")
    else:
        current = next(
            (item for item in path.nodes if item.status == PathNodeStatus.IN_PROGRESS),
            next((item for item in path.nodes if item.status == PathNodeStatus.AVAILABLE), None),
        )
    now = datetime.now(timezone.utc)
    inserted: list[str] = []
    unlocked: list[str] = []
    completed: list[str] = []
    mutation_type = PathMutationType.HOLD

    if policy.action in {FeedbackAction.REMEDIATE, FeedbackAction.PRACTICE}:
        node_type = (
            PathNodeType.REMEDIAL
            if policy.action == FeedbackAction.REMEDIATE
            else PathNodeType.PRACTICE
        )
        mutation_type = (
            PathMutationType.INSERT_REMEDIAL
            if node_type == PathNodeType.REMEDIAL
            else PathMutationType.INSERT_PRACTICE
        )
        for point_id in policy.target_knowledge_point_ids:
            duplicate = next(
                (
                    item for item in path.nodes
                    if item.node_type == node_type
                    and item.knowledge_point_id == point_id
                    and item.status not in {PathNodeStatus.COMPLETED, PathNodeStatus.SKIPPED}
                ),
                None,
            )
            if duplicate is not None:
                continue
            node_id = _stable_id("node", path.path_id, node_type.value, point_id)
            node = LearningPathNode(
                node_id=node_id,
                path_id=path.path_id,
                knowledge_point_id=point_id,
                node_type=node_type,
                sequence=max((item.sequence for item in path.nodes), default=0) + 1,
                status=PathNodeStatus.AVAILABLE,
                prerequisite_ids=[],
                parent_node_id=current.node_id if current else None,
                source="feedback",
                difficulty="基础" if node_type == PathNodeType.REMEDIAL else None,
                created_at=now,
                updated_at=now,
            )
            path.nodes.append(node)
            inserted.append(node_id)
        if not inserted:
            mutation_type = PathMutationType.HOLD

    elif policy.action == FeedbackAction.ADVANCE:
        mutation_type = PathMutationType.ADVANCE
        if current is None:
            raise ValueError("advance requires a current path node")
        current.status = PathNodeStatus.COMPLETED
        current.updated_at = now
        completed.append(current.node_id)
        completed_ids = {
            item.node_id for item in path.nodes if item.status == PathNodeStatus.COMPLETED
        }
        for node in path.nodes:
            if node.status == PathNodeStatus.LOCKED and set(node.prerequisite_ids) <= completed_ids:
                node.status = PathNodeStatus.AVAILABLE
                node.updated_at = now
                unlocked.append(node.node_id)
        if not unlocked and advance_knowledge_point_id and (
            advance_knowledge_point_id != current.knowledge_point_id
        ):
            point_id = advance_knowledge_point_id
            node_id = _stable_id("node", path.path_id, "challenge", point_id, before_version)
            challenge = LearningPathNode(
                node_id=node_id,
                path_id=path.path_id,
                knowledge_point_id=point_id,
                node_type=PathNodeType.CHALLENGE,
                sequence=max(item.sequence for item in path.nodes) + 1,
                status=PathNodeStatus.AVAILABLE,
                prerequisite_ids=[current.node_id],
                parent_node_id=current.node_id,
                source="feedback",
                difficulty="高级",
                created_at=now,
                updated_at=now,
            )
            path.nodes.append(challenge)
            inserted.append(node_id)
            unlocked.append(node_id)

    _validate_path(path)
    changed = bool(inserted or unlocked or completed)
    if changed:
        path.version += 1
        path.updated_at = now
    mutation = PathMutation(
        mutation_id=_stable_id("mut", attempt.attempt_id, decision_id),
        learner_id=attempt.learner_id,
        path_id=path.path_id,
        attempt_id=attempt.attempt_id,
        decision_id=decision_id,
        mutation_type=mutation_type,
        target_node_id=current.node_id if current else None,
        inserted_node_ids=inserted,
        unlocked_node_ids=unlocked,
        completed_node_ids=completed,
        reason_codes=list(policy.reason_codes),
        path_version_before=before_version,
        path_version_after=path.version,
        created_at=now,
    )
    return path, mutation


def _validate_path(path: LearningPath) -> None:
    ids = [item.node_id for item in path.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("learning path contains duplicate node_id")
    known = set(ids)
    graph: dict[str, list[str]] = {}
    for node in path.nodes:
        if node.node_id in node.prerequisite_ids:
            raise ValueError("learning path self-loop is forbidden")
        if set(node.prerequisite_ids) - known:
            raise ValueError("learning path prerequisite does not exist")
        graph[node.node_id] = node.prerequisite_ids

    def visit(node_id: str, active: set[str], done: set[str]) -> None:
        if node_id in active:
            raise ValueError("learning path cycle is forbidden")
        if node_id in done:
            return
        active.add(node_id)
        for parent in graph[node_id]:
            visit(parent, active, done)
        active.remove(node_id)
        done.add(node_id)

    completed: set[str] = set()
    for node_id in graph:
        visit(node_id, set(), completed)
