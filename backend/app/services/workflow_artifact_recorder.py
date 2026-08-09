"""Persist business artifacts at durable workflow merge boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.audit.base import BaseAuditRepository
from app.db.resource.base import BaseResourceRepository
from app.models.persistence import WorkflowEventType, canonical_hash
from app.models.schemas import LearningResource
from app.agents.validators import validate_resource_lineage
from app.db.audit.base import PersistenceConflict


def _event_id(run_id: str, event_type: str, subject_id: str) -> str:
    return f"evt_{canonical_hash({'run_id': run_id, 'event_type': event_type, 'subject_id': subject_id})[:32]}"


class WorkflowArtifactRecorder:
    """Idempotent P0-05 resource/review recorder.

    It is called before the checkpoint is accepted so replay never points at a
    resource version or review round that has not been persisted.
    """

    def __init__(
        self,
        resource_repository: BaseResourceRepository,
        audit_repository: BaseAuditRepository,
    ) -> None:
        self.resource_repository = resource_repository
        self.audit_repository = audit_repository

    def record(self, state: dict[str, Any], trace_item: dict[str, Any]) -> None:
        run_id = str(state["run_id"])
        node_name = str(
            state.get("current_node")
            or trace_item.get("node_name")
            or trace_item.get("agent_name")
            or "unknown"
        )
        resources = {
            resource.resource_id: resource
            for resource in state.get("generated_resources", [])
            if isinstance(resource, LearningResource)
        }
        if node_name == "generator":
            for resource_id in trace_item.get("resource_ids", []):
                resource = resources.get(str(resource_id))
                if resource is None:
                    continue
                previous = (
                    self.resource_repository.get(resource.parent_resource_id)
                    if resource.parent_resource_id
                    else None
                )
                validate_resource_lineage(resource, previous)
                for stored in self.resource_repository.list_by_run(run_id):
                    if (
                        stored.resource_id != resource.resource_id
                        and stored.resource_type == resource.resource_type
                        and stored.version == resource.version
                    ):
                        raise PersistenceConflict("duplicate resource version in run")
                self._save_resource(resource, state, trace_item)
                self._append(
                    run_id,
                    WorkflowEventType.RESOURCE_VERSION_CREATED,
                    str(resource_id),
                    trace_item,
                    status=resource.review_status,
                    payload={
                        "resource_ids": [str(resource_id)],
                        "resource_type": resource.resource_type,
                        "version": resource.version,
                        "parent_resource_id": resource.parent_resource_id,
                    },
                )
            return

        if node_name == "reviewer":
            review = state.get("review_result") or {}
            decision = str(review.get("decision") or "human_review")
            status_by_decision = {
                "approve": "approved",
                "revise": "revision_requested",
                "reject": "rejected",
                "human_review": "human_review",
            }
            revision_targets = {
                str(item.get("target_resource_type"))
                for item in review.get("revision_instructions", [])
                if isinstance(item, dict) and item.get("target_resource_type")
            }
            for resource_id, review_id in (review.get("review_ids") or {}).items():
                resource = resources.get(str(resource_id))
                if resource is None:
                    continue
                review_id = self.audit_repository.save_review(str(resource_id), review, run_id)
                updated = resource.model_copy(
                    update={
                        "review_id": review_id,
                        "review_status": (
                            "revision_requested"
                            if decision == "revise" and resource.resource_type in revision_targets
                            else "pending_review"
                            if decision == "revise"
                            else status_by_decision.get(decision, "human_review")
                        ),
                        "hallucination_rate": review.get("hallucination_score"),
                        "difficulty_match": review.get("difficulty_match"),
                    }
                )
                self._save_resource(updated, state, trace_item)
                self._append(
                    run_id,
                    WorkflowEventType.REVIEW_PERSISTED,
                    str(review_id),
                    trace_item,
                    status=decision,
                    payload={
                        "resource_ids": [str(resource_id)],
                        "review_ids": [str(review_id)],
                        "revision_count": int(review.get("revision_count", 0)),
                    },
                )
            return

        if node_name == "prepare_revision":
            self._append(
                run_id,
                WorkflowEventType.REVISION_REQUESTED,
                str(trace_item.get("step_id")),
                trace_item,
                status="revision_requested",
                payload={
                    "resource_ids": [str(value) for value in trace_item.get("resource_ids", [])],
                    "revision_count": int(state.get("revision_count", 0)),
                },
            )
            return

        if node_name in {
            "supervisor",
            "finalize_draft",
            "claim_check",
            "finalize_evidence_insufficient",
        }:
            for resource in resources.values():
                self._save_resource(resource, state, trace_item)
                if resource.publication_status == "published":
                    self._append(
                        run_id,
                        WorkflowEventType.RESOURCE_PUBLISHED,
                        resource.resource_id,
                        trace_item,
                        status="published",
                        payload={"resource_ids": [resource.resource_id], "version": resource.version},
                    )

    def _save_resource(
        self,
        resource: LearningResource,
        state: dict[str, Any],
        trace_item: dict[str, Any],
    ) -> None:
        self.resource_repository.save(
            resource,
            str(state["learner_id"]),
            str(state["topic"]),
            run_id=str(state["run_id"]),
            generation_step_id=(
                str(trace_item["step_id"])
                if trace_item.get("agent_name") == "generator"
                else None
            ),
        )

    def _append(
        self,
        run_id: str,
        event_type: WorkflowEventType,
        subject_id: str,
        trace_item: dict[str, Any],
        *,
        status: str | None,
        payload: dict[str, Any],
    ) -> None:
        self.audit_repository.append_event(
            run_id,
            event_type,
            payload=payload,
            occurred_at=datetime.now(timezone.utc),
            step_id=str(trace_item.get("step_id")) if trace_item.get("step_id") else None,
            step_sequence=int(trace_item["sequence"]) if trace_item.get("sequence") else None,
            node_name=str(trace_item.get("node_name") or trace_item.get("agent_name") or "unknown"),
            status=status,
            event_id=_event_id(run_id, event_type.value, subject_id),
        )
