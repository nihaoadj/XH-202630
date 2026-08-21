import uuid
import os
import socket
from datetime import datetime, timedelta, timezone
import logging
from typing import List

from app.core.errors import ApplicationError, ErrorCode
from app.core.file_storage import save_text_resource
from app.core.health import ensure_generation_ready
from app.config import get_settings
from app.db.resource.base import BaseResourceRepository
from app.db.audit.base import BaseAuditRepository
from app.db.audit.base import PersistenceConflict
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.base import BaseClaimRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.schemas import GenerateRequest, GenerateResponse, LearnerProfile, LearningResource
from app.models.persistence import (
    CreateRunCommand,
    RunStatus,
    WorkflowEventType,
    canonical_hash,
)
from app.models.workflow import (
    ClaimCheckStatus,
    ReviewDecision,
    WorkflowConstraints,
    WorkflowState,
    WorkflowStateSnapshot,
    WorkflowStatus,
)
from app.services.durable_workflow_runner import DurableWorkflowRunner
from app.services.workflow_artifact_recorder import WorkflowArtifactRecorder


def build_workflow_state(
    learner: LearnerProfile,
    req: GenerateRequest,
    *,
    run_id: str | None = None,
    batch_id: str | None = None,
) -> WorkflowState:
    """Validate and map every public request control into workflow channels."""
    if learner.learner_id != req.learner_id:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)

    try:
        settings = get_settings()
        workflow_started_at = datetime.now(timezone.utc)
        constraints = WorkflowConstraints.model_validate(req.constraints).model_dump(
            mode="python",
            exclude_none=True,
        )
        effective_run_id = run_id or str(uuid.uuid4())
        snapshot = WorkflowStateSnapshot(
            run_id=effective_run_id,
            batch_id=batch_id or effective_run_id,
            learner_id=req.learner_id,
            learner=learner,
            topic=req.topic,
            knowledge_base_id=req.knowledge_base_id or learner.knowledge_base_id,
            diagnostic_result_id=req.diagnostic_result_id,
            target_skill_nodes=req.target_skill_nodes,
            resource_types=req.resource_types,
            difficulty_preference=req.difficulty_preference,
            generation_mode=req.generation_mode or "standard",
            include_review=req.include_review,
            include_claim_check=req.include_claim_check,
            max_iterations=req.max_iterations,
            constraints=constraints,
            workflow_status=WorkflowStatus.RUNNING,
            current_node="pending",
            generation_attempt=1,
            revision_count=0,
            workflow_started_at=workflow_started_at,
            workflow_deadline_at=workflow_started_at + timedelta(
                seconds=settings.llm_workflow_timeout_seconds
            ),
            claim_check_status=(
                ClaimCheckStatus.PENDING
                if req.include_claim_check
                else ClaimCheckStatus.NOT_REQUESTED
            ),
            retrieval_status="pending",
            retrieval_config_hash=None,
            retrieval_query_hashes=[],
            retrieval_candidate_count=0,
            retrieval_dropped_candidate_count=0,
            retrieval_partial_failure_count=0,
            diagnosis={},
            retrieved_evidence=[],
            retrieved_chunks=[],
            learning_plan={},
            resource_specs=[],
            resource_executions=[],
            resource_progress_summary={},
            generated_resources=[],
            review_result={},
            resource_review_results={},
            final_decision="",
            trace=[],
            errors=[],
            iteration=0,
        )
    except ValueError as exc:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422) from exc
    return snapshot.as_state()


def _build_report(learner: LearnerProfile, diagnosis: dict, review: dict, learning_plan: dict) -> dict:
    hallucination_rate = review.get("hallucination_rate", review.get("hallucination_score", 0.0))
    weak_points = diagnosis.get("weak_points", learner.weak_points)
    return {
        "learner_id": learner.learner_id,
        "ability_level": diagnosis.get("recommended_difficulty", learner.skill_level),
        "ability_tags": diagnosis.get("ability_tags", []),
        "weak_points": weak_points,
        "recommended_difficulty": diagnosis.get("recommended_difficulty", learner.skill_level),
        "learning_plan": learning_plan,
        "review_summary": {
            "status": review.get("status", "pending"),
            "issues": review.get("issues", []),
            "claim_total": review.get("claim_total", 0),
            "claim_supported": review.get("claim_supported", 0),
            "claim_unsupported": review.get("claim_unsupported", 0),
        },
        "hallucination_rate": hallucination_rate,
        "legacy_reviewer_score": review.get("hallucination_score"),
        "claim_hallucination_rate": review.get("claim_hallucination_rate"),
        "claim_metric_status": review.get("claim_metric_status"),
        "coverage_rate": review.get("coverage_rate", 0.0),
        "difficulty_match": review.get("difficulty_match", False),
        "retrieval_hit_rate": review.get("retrieval_hit_rate", 0.0),
        "revision_count": review.get("revision_count", 0),
        "next_suggestions": weak_points[:3],
    }


logger = logging.getLogger(__name__)


def _materialize_resources(
    resources: List[LearningResource],
    learner_id: str,
    topic: str,
    resource_repo: BaseResourceRepository,
    *,
    run_id: str,
    batch_id: str | None = None,
    generation_steps: dict[str, str],
    audit_repo: BaseAuditRepository,
) -> List[LearningResource]:
    """Materialize files and reconcile storage metadata on recorder-owned rows."""
    persisted = []
    for resource in resources:
        resource.learner_id = learner_id
        resource.topic = topic
        resource.run_id = run_id
        resource.batch_id = batch_id or run_id

        existing = resource_repo.get(resource.resource_id)
        if existing is None:
            raise PersistenceConflict("recorder-owned resource is missing")
        if (
            resource.publication_status == "published"
            and resource.storage_type == "text"
            and resource.content_text
        ):
            file_path, file_size, mime_type = save_text_resource(
                learner_id=learner_id,
                resource_type=resource.resource_type,
                text=resource.content_text,
                resource_id=resource.resource_id,
            )
            resource.file_path = file_path
            resource.file_size = file_size
            resource.mime_type = mime_type

        materialized = existing.model_copy(update={
            "file_path": resource.file_path,
            "file_size": resource.file_size,
            "mime_type": resource.mime_type,
        })
        generation_step_id = generation_steps.get(resource.resource_id)
        resource_repo.save(
            materialized,
            learner_id,
            topic,
            run_id=run_id,
            batch_id=batch_id or run_id,
            generation_step_id=generation_step_id,
        )
        audit_repo.append_event(
            run_id,
            WorkflowEventType.RESOURCE_PERSISTED,
            payload={"resource_ids": [resource.resource_id]},
            occurred_at=datetime.now(timezone.utc),
            step_id=generation_step_id,
            status=materialized.review_status,
            event_id=_event_id(
                run_id,
                WorkflowEventType.RESOURCE_PERSISTED.value,
                resource.resource_id,
            ),
        )
        persisted.append(materialized)
    return persisted


def _reconcile_reviews(
    resources: List[LearningResource],
    review: dict,
    *,
    run_id: str,
    audit_repo: BaseAuditRepository,
) -> None:
    """Verify recorder-owned review links without creating a second Review."""

    if not review or review.get("decision") == ReviewDecision.NOT_REQUESTED.value:
        return
    expected = {str(key): str(value) for key, value in (review.get("review_ids") or {}).items()}
    persisted = {
        str(item.get("resource_id")): str(item.get("review_id"))
        for item in audit_repo.list_reviews_by_run(run_id)
        if item.get("resource_id") and item.get("review_id")
    }
    for resource in resources:
        expected_id = expected.get(resource.resource_id)
        # A failed/degraded resource is intentionally sent to human review
        # without a completed automated review record. It must not make the
        # already-terminal workflow fail during finalization.
        if expected_id is None and resource.publication_status != "published":
            continue
        if expected_id is None or persisted.get(resource.resource_id) != expected_id:
            raise PersistenceConflict("recorder-owned review is missing")


def _request_snapshot(req: GenerateRequest, state: WorkflowState) -> dict:
    constraints = state.get("constraints", {})
    allowed_constraint_keys = {
        "must_include_citations",
        "language",
        "max_length",
        "retrieval_top_k",
    }
    return {
        "learner_id": req.learner_id,
        "topic": req.topic,
        "knowledge_base_id": state.get("knowledge_base_id"),
        "diagnostic_result_id": req.diagnostic_result_id,
        "target_skill_nodes": list(req.target_skill_nodes),
        "resource_types": list(req.resource_types),
        "difficulty_preference": req.difficulty_preference,
        "generation_mode": req.generation_mode or "standard",
        "include_review": req.include_review,
        "include_claim_check": req.include_claim_check,
        "max_iterations": req.max_iterations,
        "constraints": {
            key: constraints[key]
            for key in allowed_constraint_keys
            if key in constraints
        },
    }


def _generation_step_map(trace: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in trace:
        if not isinstance(item, dict) or item.get("agent_name") != "generator":
            continue
        step_id = item.get("step_id")
        if not step_id:
            continue
        for resource_id in item.get("resource_ids", []):
            result[str(resource_id)] = str(step_id)
    return result


def _event_id(run_id: str, event_type: str, subject_id: str) -> str:
    material = {
        "run_id": run_id,
        "event_type": event_type,
        "subject_id": subject_id,
    }
    return f"evt_{canonical_hash(material)[:32]}"


def _run_status(workflow_status: str) -> RunStatus:
    return {
        WorkflowStatus.COMPLETED.value: RunStatus.COMPLETED,
        WorkflowStatus.DEGRADED.value: RunStatus.DEGRADED,
        WorkflowStatus.HUMAN_REVIEW.value: RunStatus.HUMAN_REVIEW,
        WorkflowStatus.FAILED.value: RunStatus.FAILED,
    }[workflow_status]


class GenerationService:
    """Generate learning resources by orchestrating the workflow and persistence."""

    def __init__(
        self,
        resource_repo: BaseResourceRepository,
        workflow,
        audit_repo: BaseAuditRepository | None = None,
        knowledge_catalog: KnowledgeCatalogRepository | None = None,
        claim_repo: BaseClaimRepository | None = None,
    ):
        self.resource_repo = resource_repo
        self.workflow = workflow
        self.audit_repo = audit_repo or MemoryAuditRepository()
        self.knowledge_catalog = knowledge_catalog
        self.claim_repo = claim_repo or MemoryClaimRepository()

    def generate(self, learner: LearnerProfile, req: GenerateRequest) -> GenerateResponse:
        return self.generate_with_run_id(learner, req)

    def generate_with_run_id(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
        run_id: str | None = None,
        batch_id: str | None = None,
    ) -> GenerateResponse:
        """Generate with a caller-owned Run ID while preserving durable lifecycle semantics."""
        readiness = (
            ensure_generation_ready(
                index_status_provider=self.knowledge_catalog.get_index_status
            )
            if self.knowledge_catalog is not None
            else ensure_generation_ready()
        )
        initial_state = build_workflow_state(learner, req, run_id=run_id, batch_id=batch_id)
        run_id = initial_state["run_id"]
        started_at = datetime.now(timezone.utc)
        lease_expires_at = started_at + timedelta(
            seconds=get_settings().workflow_run_lease_seconds
        )
        request_snapshot = _request_snapshot(req, initial_state)
        try:
            self.audit_repo.create_run(
                CreateRunCommand(
                    run_id=run_id,
                    learner_id=req.learner_id,
                    knowledge_base_id=initial_state.get("knowledge_base_id"),
                    topic=req.topic,
                    request_snapshot=request_snapshot,
                    request_hash=canonical_hash(request_snapshot),
                    owner_instance_id=f"{socket.gethostname()}:{os.getpid()}",
                    lease_expires_at=lease_expires_at,
                    occurred_at=started_at,
                )
            )
            self.audit_repo.start_run(
                run_id,
                occurred_at=started_at,
                lease_expires_at=lease_expires_at,
            )
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE) from exc

        try:
            result = DurableWorkflowRunner(
                self.workflow,
                self.audit_repo,
                WorkflowArtifactRecorder(self.resource_repo, self.audit_repo, self.claim_repo),
            ).invoke(initial_state)
        except Exception as exc:
            error_code = (
                exc.code.value if isinstance(exc, ApplicationError) else ErrorCode.INTERNAL_ERROR.value
            )
            try:
                self.audit_repo.fail_run(
                    run_id,
                    error_code=error_code,
                    occurred_at=datetime.now(timezone.utc),
                )
            except Exception as persistence_exc:
                raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE) from persistence_exc
            if isinstance(exc, ApplicationError):
                raise
            raise ApplicationError(ErrorCode.INTERNAL_ERROR, status_code=500) from exc

        trace = result.get("trace", [])
        review = result.get("review_result", {})

        trace_error_codes = [
            item.get("error_code")
            for item in trace
            if isinstance(item, dict) and item.get("error_code")
        ]
        state_error_codes = [
            item.get("code")
            for item in result.get("errors", [])
            if isinstance(item, dict) and item.get("code")
        ]
        error_codes = list(dict.fromkeys(readiness.error_codes + trace_error_codes + state_error_codes))
        workflow_status = result.get("workflow_status", WorkflowStatus.COMPLETED.value)
        if workflow_status == WorkflowStatus.COMPLETED.value and readiness.status == "degraded":
            workflow_status = WorkflowStatus.DEGRADED.value
        execution_status = {
            WorkflowStatus.COMPLETED.value: "success",
            WorkflowStatus.DEGRADED.value: "degraded",
            WorkflowStatus.HUMAN_REVIEW.value: "human_review",
            WorkflowStatus.FAILED.value: "failed",
            WorkflowStatus.RUNNING.value: "running",
        }[workflow_status]

        finalization_stage = "mark_finalizing"
        try:
            existing_run = self.audit_repo.get_run(run_id)
            target_status = _run_status(workflow_status)
            # A completed retry must not transition a terminal Run backwards.
            if existing_run is None or existing_run.status != target_status:
                self.audit_repo.mark_finalizing(
                    run_id,
                    workflow_status=workflow_status,
                    current_node=result.get("current_node"),
                    generation_attempt=int(result.get("generation_attempt", 1)),
                    revision_count=int(result.get("revision_count", 0)),
                    retrieval_status=result.get("retrieval_status"),
                    final_decision=result.get("final_decision"),
                    occurred_at=datetime.now(timezone.utc),
                )
            finalization_stage = "materialize_resources"
            raw_resources = result.get("generated_resources", [])
            persisted_resources = _materialize_resources(
                raw_resources,
                req.learner_id,
                req.topic,
                self.resource_repo,
                run_id=run_id,
                batch_id=str(initial_state["batch_id"]),
                generation_steps=_generation_step_map(trace),
                audit_repo=self.audit_repo,
            )
            finalization_stage = "reconcile_review"
            _reconcile_reviews(
                persisted_resources,
                review,
                run_id=run_id,
                audit_repo=self.audit_repo,
            )
            finalization_stage = "complete_run"
            self.audit_repo.complete_run(
                run_id,
                status=_run_status(workflow_status),
                workflow_status=workflow_status,
                execution_status=execution_status,
                final_decision=result.get("final_decision"),
                occurred_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error(
                "Workflow finalization failed run_id=%s finalization_stage=%s exception_type=%s",
                run_id,
                finalization_stage,
                type(exc).__name__,
            )
            try:
                self.audit_repo.append_event(
                    run_id,
                    WorkflowEventType.WORKFLOW_FINALIZATION_FAILED,
                    payload={
                        "finalization_stage": finalization_stage,
                        "exception_type": type(exc).__name__,
                        "safe_message": "finalization_stage_failed",
                    },
                    occurred_at=datetime.now(timezone.utc),
                    status="failed",
                    error_code=ErrorCode.WORKFLOW_FINALIZATION_FAILED.value,
                    event_id=_event_id(
                        run_id,
                        WorkflowEventType.WORKFLOW_FINALIZATION_FAILED.value,
                        finalization_stage,
                    ),
                )
                self.audit_repo.fail_run(
                    run_id,
                    error_code=ErrorCode.WORKFLOW_FINALIZATION_FAILED.value,
                    occurred_at=datetime.now(timezone.utc),
                )
            except Exception as persistence_exc:
                raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE) from persistence_exc
            raise ApplicationError(ErrorCode.WORKFLOW_FINALIZATION_FAILED) from exc

        return GenerateResponse(
            schema_version=initial_state["schema_version"],
            run_id=run_id,
            workflow_status=workflow_status,
            learner_id=req.learner_id,
            topic=req.topic,
            resources=persisted_resources,
            trace=trace,
            report=_build_report(
                learner,
                result.get("diagnosis", {}),
                result.get("review_result", {}),
                result.get("learning_plan", {}),
            ),
            execution_status=execution_status,
            error_codes=error_codes,
        )
