"""Persist business artifacts at durable workflow merge boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.audit.base import BaseAuditRepository
from app.db.learning_documents.base import BaseResourceRepository
from app.db.claim.base import BaseClaimRepository
from app.models.reviews.claims import ClaimJudgement, ClaimRecord
from app.models.shared.persistence import WorkflowEventType, canonical_hash
from app.models.learning_documents.schemas import LearningResource
from app.agents.shared.validators import validate_resource_lineage
from app.db.audit.base import PersistenceConflict
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.db.shared.retry import run_with_sqlite_retry


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
        claim_repository: BaseClaimRepository | None = None,
    ) -> None:
        self.resource_repository = resource_repository
        self.audit_repository = audit_repository
        self.claim_repository = claim_repository

    def record(self, state: dict[str, Any], trace_item: dict[str, Any]) -> None:
        # A merge-boundary write may include several idempotent sub-writes
        # (Claim audit, metrics, events and execution projections). Retry the
        # whole boundary so a SQLite lock cannot leave only part of the audit
        # durable and strand the workflow before its next node.
        run_with_sqlite_retry(
            lambda: self._record_once(state, trace_item),
        )

    def _record_once(self, state: dict[str, Any], trace_item: dict[str, Any]) -> None:
        run_id = str(state["run_id"])
        for raw_spec in state.get("resource_specs", []):
            payload = dict(raw_spec)
            payload["run_id"] = run_id
            self.resource_repository.save_spec(ResourceSpecRecord.model_validate(payload))
        node_name = str(
            trace_item.get("node_name")
            or state.get("current_node")
            or trace_item.get("agent_name")
            or "unknown"
        )
        resources = {
            resource.resource_id: resource
            for resource in state.get("generated_resources", [])
            if isinstance(resource, LearningResource)
        }
        if node_name == "generator":
            immediate_resource_events = {
                event.event_id
                for event in self.audit_repository.list_events(run_id, limit=10_000)
                if event.event_type in {
                    WorkflowEventType.RESOURCE_GENERATED,
                    WorkflowEventType.RESOURCE_HUMAN_REVIEW_REQUESTED,
                }
            }
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
                        and (
                            stored.resource_spec_id == resource.resource_spec_id
                            and stored.representation == resource.representation
                            if resource.resource_spec_id
                            else stored.resource_spec_id is None
                            and stored.resource_type == resource.resource_type
                        )
                        and stored.version == resource.version
                ):
                        raise PersistenceConflict("duplicate resource version in run")
                self._save_resource(resource, state, trace_item)
                # Resource workers may have already persisted and announced this
                # exact resource while their peers were still running.  Keep the
                # merge-boundary write idempotent, but do not publish a second
                # "generated" event when that happened.
                already_announced = any(
                    event_id in immediate_resource_events
                    for event_id in (
                        _event_id(run_id, WorkflowEventType.RESOURCE_GENERATED.value, resource.resource_id),
                        _event_id(
                            run_id,
                            WorkflowEventType.RESOURCE_HUMAN_REVIEW_REQUESTED.value,
                            resource.resource_id,
                        ),
                    )
                )
                if already_announced:
                    continue
                self._append(
                    run_id,
                    WorkflowEventType.RESOURCE_VERSION_CREATED,
                    str(resource_id),
                    trace_item,
                    status=resource.review_status,
                    payload={
                        "resource_ids": [str(resource_id)],
                        "version": resource.version,
                        "parent_resource_id": resource.parent_resource_id,
                        **self._resource_event_payload(resource, state, "generated"),
                    },
                )
            self._persist_executions(state, run_id)
            return

        # LangGraph's topology uses ``review`` while older trace records used
        # ``reviewer``. Both identify the same reviewer Agent and must persist
        # the authoritative text review before finalization reconciles it.
        if node_name in {"review", "reviewer"}:
            review = state.get("review_result") or {}
            resource_reviews = state.get("resource_review_results") or {}
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
                item_review = dict(resource_reviews.get(str(resource_id)) or review)
                item_decision = str(item_review.get("decision") or decision)
                # Keep the review id allocated by the reviewer.  The per-resource
                # result normally does not carry the aggregate ``review_ids`` map,
                # so passing it as-is makes SQLAuditRepository generate a second,
                # random id and finalization cannot reconcile the recorder-owned
                # review.  Supplying the single-resource map makes persistence
                # idempotent.
                item_review["review_ids"] = {str(resource_id): str(review_id)}
                persisted_review_id = self.audit_repository.save_review(
                    str(resource_id), item_review, run_id
                )
                updated = resource.model_copy(
                    update={
                        "review_id": persisted_review_id,
                        "review_status": (
                            status_by_decision.get(item_decision, "human_review")
                        ),
                        "hallucination_rate": item_review.get("hallucination_score"),
                        "difficulty_match": item_review.get("difficulty_match"),
                    }
                )
                self._save_resource(updated, state, trace_item)
                self._append(
                    run_id,
                    WorkflowEventType.REVIEW_PERSISTED,
                    str(persisted_review_id),
                    trace_item,
                    status=item_decision,
                    payload={
                        "resource_ids": [str(resource_id)],
                        "review_ids": [str(persisted_review_id)],
                        "revision_count": int(review.get("revision_count", 0)),
                        **self._resource_event_payload(
                            updated,
                            state,
                            status_by_decision.get(item_decision, "human_review"),
                        ),
                    },
                )
                if updated.publication_status == "published":
                    self._append(
                        run_id,
                        WorkflowEventType.RESOURCE_PUBLISHED,
                        updated.resource_id,
                        trace_item,
                        status="published",
                        payload={
                            "resource_ids": [updated.resource_id],
                            "version": updated.version,
                            **self._resource_event_payload(updated, state, "approved"),
                        },
                    )
            self._persist_executions(state, run_id)
            return

        if node_name == "claim_extractor":
            claim_ids = [
                str(item.get("claim_id"))
                for item in state.get("extracted_claims", [])
                if isinstance(item, dict) and item.get("claim_id")
            ]
            event_type = (
                WorkflowEventType.CLAIM_EXTRACTION_COMPLETED
                if state.get("claim_check_status") == "pending"
                else WorkflowEventType.CLAIM_REVIEW_FAILED
            )
            self._append(
                run_id,
                WorkflowEventType.CLAIM_EXTRACTION_STARTED,
                str(trace_item.get("step_id")),
                trace_item,
                status="started",
                payload={"resource_ids": [str(value) for value in trace_item.get("resource_ids", [])]},
            )
            self._append(
                run_id,
                event_type,
                str(trace_item.get("step_id")),
                trace_item,
                status=str(state.get("claim_check_status")),
                payload={"claim_ids": claim_ids, "claim_count": len(claim_ids)},
            )
            self._persist_executions(state, run_id)
            return

        if node_name == "claim_judge":
            if state.get("claim_check_status") != "completed":
                self._append(
                    run_id,
                    WorkflowEventType.CLAIM_REVIEW_FAILED,
                    str(trace_item.get("step_id")),
                    trace_item,
                    status=str(state.get("claim_check_status")),
                    payload={"claim_count": len(state.get("extracted_claims", []))},
                )
                self._persist_executions(state, run_id)
                return
            claims = [ClaimRecord.model_validate(item) for item in state.get("extracted_claims", [])]
            judgements = [ClaimJudgement.model_validate(item) for item in state.get("claim_judgements", [])]
            if self.claim_repository is None:
                raise PersistenceConflict("claim repository is required for completed audit")
            self.claim_repository.save_audit(claims, judgements)
            verdict_counts: dict[str, int] = {}
            for item in judgements:
                verdict = item.verdict.value if item.verdict else "incomplete"
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            self._append(
                run_id,
                WorkflowEventType.CLAIM_JUDGEMENT_COMPLETED,
                str(trace_item.get("step_id")),
                trace_item,
                status="completed",
                payload={
                    "claim_ids": [item.claim_id for item in claims],
                    "claim_count": len(claims),
                    "verdict_counts": verdict_counts,
                },
            )
            self._append(
                run_id,
                WorkflowEventType.CLAIM_METRIC_COMPUTED,
                str(trace_item.get("step_id")),
                trace_item,
                status="completed",
                payload={"resource_metrics": state.get("claim_metrics", {})},
            )
            for resource_id, metric in state.get("claim_metrics", {}).items():
                resource = resources.get(str(resource_id))
                if resource is None or not isinstance(metric, dict):
                    continue
                factual_total = int(metric.get("factual_claim_total", 0) or 0)
                supported_total = int(metric.get("supported_claim_total", 0) or 0)
                self._append(
                    run_id,
                    WorkflowEventType.CLAIM_METRIC_COMPUTED,
                    f"resource:{resource_id}",
                    trace_item,
                    status="completed",
                    payload={
                        **self._resource_event_payload(resource, state, "claim_checking"),
                        "claim_metric_status": metric.get("metric_status"),
                        "claim_count": int(metric.get("claim_total", 0) or 0),
                        "factual_claim_total": factual_total,
                        "supported_claim_total": supported_total,
                        "contradicted_claim_total": int(metric.get("contradicted_claim_total", 0) or 0),
                        "not_in_evidence_claim_total": int(metric.get("not_in_evidence_claim_total", 0) or 0),
                        "claim_factual_pass_rate": (
                            supported_total / factual_total if factual_total else None
                        ),
                    },
                )
            self._persist_executions(state, run_id)
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
            self._persist_executions(state, run_id)
            return

        if node_name in {
            "decide",
            "finalize",
            "supervisor",
            "claim_supervisor",
            "finalize_draft",
            "finalize_evidence_insufficient",
        }:
            for resource in resources.values():
                self._save_resource(resource, state, trace_item)
                already_published = any(
                    event.event_type == WorkflowEventType.RESOURCE_PUBLISHED
                    and resource.resource_id in event.payload.get("resource_ids", [])
                    for event in self.audit_repository.list_events(run_id, limit=10000)
                )
                if resource.publication_status == "published" and not already_published:
                    self._append(
                        run_id,
                        WorkflowEventType.RESOURCE_PUBLISHED,
                        resource.resource_id,
                        trace_item,
                        status="published",
                        payload={
                            "resource_ids": [resource.resource_id],
                            "version": resource.version,
                            **self._resource_event_payload(resource, state, "approved"),
                        },
                    )
            self._persist_executions(state, run_id)

    def record_resource_queued(
        self,
        state: dict[str, Any],
        *,
        spec: ResourceSpecRecord,
        execution: dict[str, Any],
        trace_item: dict[str, Any],
    ) -> None:
        """Publish a durable queued event before an individual Worker runs."""

        run_id = str(state["run_id"])
        self.resource_repository.save_spec(spec)
        subject = f"{spec.resource_spec_id}:{execution.get('representation', 'text')}:{execution.get('attempt', 1)}"
        self._append(run_id, WorkflowEventType.RESOURCE_EXECUTION_QUEUED, subject, trace_item,
                     status="queued", payload={
                         "resource_spec_id": spec.resource_spec_id,
                         "resource_family_id": spec.resource_family_id,
                         "resource_type": spec.resource_type,
                         "representation": execution.get("representation", "text"),
                         "resource_execution_state": "queued",
                         "attempt": execution.get("attempt", 1),
                         "agent_name": execution.get("agent_name"),
                         "prompt_version": execution.get("prompt_version"),
                         "artifact_format": execution.get("artifact_format"),
                     })

    def record_resource_generated(
        self,
        state: dict[str, Any],
        *,
        resource: LearningResource,
        execution: dict[str, Any],
        trace_item: dict[str, Any],
    ) -> None:
        """Persist one completed resource and event before its peers finish."""

        run_id = str(state["run_id"])
        self._save_resource(resource, state, trace_item)
        self._upsert_execution(execution, run_id)
        execution_state = str(execution.get("resource_execution_state") or "generated")
        event_type = (WorkflowEventType.RESOURCE_HUMAN_REVIEW_REQUESTED
                      if execution_state == "human_review"
                      else WorkflowEventType.RESOURCE_GENERATED)
        event_state = "human_review" if execution_state == "human_review" else "generated"
        self._append(run_id, event_type, resource.resource_id, trace_item,
                     status=event_state,
                     payload=self._resource_event_payload(
                         resource, {**state, "resource_executions": [execution]}, event_state))

    def _persist_executions(self, state: dict[str, Any], run_id: str) -> None:
        """Persist execution projections only after their resource FK targets exist.

        ``resource_executions.resource_id`` references ``generated_resources``.
        A resource worker may return a degraded fallback, but that fallback is
        still a durable resource and must be saved before its execution record.
        Keeping this ordering at the workflow merge boundary makes SQLite's FK
        enforcement compatible with both successful and degraded generation.
        """

        for raw_execution in state.get("resource_executions", []):
            self._upsert_execution(raw_execution, run_id)

    def _upsert_execution(self, raw_execution: dict[str, Any], run_id: str) -> None:
        payload = dict(raw_execution)
        payload["run_id"] = run_id
        payload["state"] = payload.pop(
            "resource_execution_state",
            payload.get("state", "queued"),
        )
        self.resource_repository.upsert_execution(
            ResourceExecutionRecord.model_validate(payload)
        )

    @staticmethod
    def _resource_event_payload(
        resource: LearningResource,
        state: dict[str, Any],
        execution_state: str,
    ) -> dict[str, Any]:
        resource_representation = getattr(
            resource.representation,
            "value",
            resource.representation,
        )
        execution = next(
            (
                item
                for item in state.get("resource_executions", [])
                if str(item.get("resource_spec_id") or "") == str(resource.resource_spec_id or "")
                and str(item.get("representation") or "text") == str(resource_representation or "text")
            ),
            {},
        )
        return {
            "resource_id": resource.resource_id,
            "resource_spec_id": resource.resource_spec_id,
            "resource_family_id": resource.resource_family_id,
            "resource_type": resource.resource_type,
            "representation": resource_representation,
            "resource_execution_state": execution_state,
            "attempt": execution.get("attempt", 0),
            "agent_name": execution.get("agent_name"),
            "prompt_version": execution.get("prompt_version"),
            "artifact_format": execution.get("artifact_format"),
            "validation_status": execution.get("validation_status"),
            "publication_status": resource.publication_status,
            "review_id": resource.review_id,
            "claim_metric_status": resource.claim_metric_status,
            "claim_count": resource.claim_count,
            "claim_factual_pass_rate": resource.claim_factual_pass_rate,
            "claim_warning_publish": resource.claim_warning_publish,
            "claim_publish_decision_pending": resource.claim_publish_decision_pending,
            "claim_publish_decision": resource.claim_publish_decision,
        }

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
            batch_id=str(state.get("batch_id") or state["run_id"]),
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
