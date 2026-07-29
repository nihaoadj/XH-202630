import uuid
from datetime import datetime, timedelta, timezone
from typing import List

from app.core.file_storage import save_text_resource
from app.core.errors import ApplicationError, ErrorCode
from app.core.health import ensure_generation_ready
from app.config import get_settings
from app.db.resource.base import BaseResourceRepository
from app.db.audit.base import BaseAuditRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.schemas import GenerateRequest, GenerateResponse, LearnerProfile, LearningResource
from app.models.workflow import (
    ClaimCheckStatus,
    ReviewDecision,
    WorkflowConstraints,
    WorkflowState,
    WorkflowStateSnapshot,
    WorkflowStatus,
)


def build_workflow_state(
    learner: LearnerProfile,
    req: GenerateRequest,
    *,
    run_id: str | None = None,
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
        snapshot = WorkflowStateSnapshot(
            run_id=run_id or str(uuid.uuid4()),
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
            generated_resources=[],
            review_result={},
            final_decision="",
            trace=[],
            errors=[],
            iteration=0,
        )
    except ValueError as exc:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422) from exc
    return snapshot.as_state()


def _build_report(learner: LearnerProfile, diagnosis: dict, review: dict, learning_plan: dict) -> dict:
    """构建生成报告摘要"""
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
        "coverage_rate": review.get("coverage_rate", 0.0),
        "difficulty_match": review.get("difficulty_match", False),
        "retrieval_hit_rate": review.get("retrieval_hit_rate", 0.0),
        "revision_count": review.get("revision_count", 0),
        "next_suggestions": weak_points[:3],
    }


def _persist_resources(
    resources: List[LearningResource],
    learner_id: str,
    topic: str,
    resource_repo: BaseResourceRepository,
) -> List[LearningResource]:
    """将生成的资源持久化到文件系统与数据库"""
    persisted = []
    for resource in resources:
        resource.learner_id = learner_id
        resource.topic = topic

        if resource.storage_type == "text" and resource.content_text:
            file_path, file_size, mime_type = save_text_resource(
                learner_id=learner_id,
                resource_type=resource.resource_type,
                text=resource.content_text,
                resource_id=resource.resource_id,
            )
            resource.file_path = file_path
            resource.file_size = file_size
            resource.mime_type = mime_type

        resource_repo.save(resource, learner_id, topic)
        persisted.append(resource)
    return persisted


class GenerationService:
    """个性化资源生成业务服务
    
    通过构造函数注入依赖。
    """

    def __init__(
        self,
        resource_repo: BaseResourceRepository,
        workflow,
        audit_repo: BaseAuditRepository | None = None,
        knowledge_catalog: KnowledgeCatalogRepository | None = None,
    ):
        """初始化服务
        
        Args:
            resource_repo: 资源仓库（通过DI容器注入）
            workflow: Agent工作流（通过DI容器注入）
        """
        self.resource_repo = resource_repo
        self.workflow = workflow
        self.audit_repo = audit_repo
        self.knowledge_catalog = knowledge_catalog

    def generate(self, learner: LearnerProfile, req: GenerateRequest) -> GenerateResponse:
        """生成个性化学习资源"""
        readiness = (
            ensure_generation_ready(
                index_status_provider=self.knowledge_catalog.get_index_status
            )
            if self.knowledge_catalog is not None
            else ensure_generation_ready()
        )
        initial_state = build_workflow_state(learner, req)
        run_id = initial_state["run_id"]

        result = self.workflow.invoke(initial_state)
        trace = result.get("trace", [])
        raw_resources = result.get("generated_resources", [])
        persisted_resources = _persist_resources(
            raw_resources,
            req.learner_id,
            req.topic,
            self.resource_repo,
        )
        review = result.get("review_result", {})
        if self.audit_repo:
            self.audit_repo.save_run(
                learner_id=req.learner_id,
                knowledge_base_id=req.knowledge_base_id or learner.knowledge_base_id,
                topic=req.topic,
                trace=result.get("trace", []),
                input_payload=req.model_dump(mode="json"),
                output_payload={
                    "schema_version": initial_state["schema_version"],
                    "run_id": run_id,
                    "workflow_status": result.get("workflow_status", WorkflowStatus.COMPLETED.value),
                    "final_decision": result.get("final_decision", ""),
                },
                status=result.get("workflow_status", WorkflowStatus.COMPLETED.value),
                run_id=run_id,
            )
            if review.get("decision") != ReviewDecision.NOT_REQUESTED.value:
                for resource in persisted_resources:
                    review_id = self.audit_repo.save_review(resource.resource_id, review, run_id)
                    resource.review_id = review_id
                    resource.claim_count = review.get("claim_total", len(review.get("claims", [])))
                    resource.hallucination_rate = review.get(
                        "hallucination_rate", review.get("hallucination_score")
                    )
                    resource.difficulty_match = review.get("difficulty_match")
                    self.resource_repo.save(resource, req.learner_id, req.topic)

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
