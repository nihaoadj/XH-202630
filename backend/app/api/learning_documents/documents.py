from pathlib import Path

from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import Response

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.core.storage.file_storage import load_resource_file
from app.core.health import build_health_report
from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
    GenerateRequest,
    GenerationJobCreateResponse,
    ResourceListResponse,
    ResourceDetailResponse,
)
from app.services.generation.jobs import GenerationJobService
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from app.models.shared.persistence import WorkflowEventType

router = APIRouter()


class ClaimPublicationDecisionRequest(BaseModel):
    publish: bool


@router.post("/items/{resource_id}/claim-publication-decision")
def decide_claim_publication(resource_id: str, payload: ClaimPublicationDecisionRequest, request: Request):
    service: ResourceService = request.app.container.resource_service()
    resource = service.get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id or "")
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    if not resource.claim_publish_decision_pending:
        if resource.claim_publish_decision == ("published_by_user" if payload.publish else "rejected_by_user"):
            return {"resource": resource}
        raise HTTPException(status_code=409, detail="该资源当前不处于待用户决策状态")
    if resource.claim_metric_status != "complete":
        raise HTTPException(status_code=409, detail="Claim 审核尚未完成")
    if (resource.claim_factual_pass_rate is None or resource.claim_factual_pass_rate < get_settings().claim_user_review_min_factual_pass_rate):
        raise HTTPException(status_code=409, detail="事实 Claim 通过率未达到用户决策阈值")
    claims_response = request.app.container.run_query_service().get_claims(resource.run_id or "")
    metric = claims_response.resource_metrics.get(resource_id)
    if metric is None or metric.contradicted_claim_total > 0:
        raise HTTPException(status_code=409, detail="存在矛盾事实 Claim，禁止发布")
    updated = service.update_publication_decision(resource_id, publish=payload.publish)
    if updated is not None and updated.run_id:
        request.app.container.audit_repository().append_event(
            updated.run_id,
            WorkflowEventType.RESOURCE_PUBLICATION_DECIDED,
            payload={
                "resource_id": updated.resource_id,
                "resource_type": updated.resource_type,
                "publication_status": updated.publication_status,
                "claim_publish_decision": updated.claim_publish_decision,
            },
            occurred_at=datetime.now(timezone.utc),
            status=updated.publication_status,
        )
    return {"resource": updated}


def _resource_context(resources: list) -> list[dict]:
    """Keep the continuation prompt bounded while retaining batch context."""
    summaries = []
    for resource in resources[-12:]:
        content = " ".join((resource.content_text or "").split())
        summaries.append(
            {
                "resource_type": resource.resource_type,
                "difficulty": resource.difficulty,
                "knowledge_points": resource.knowledge_points[:8],
                "content_summary": content[:600],
            }
        )
    return summaries


@router.post("/batches/{batch_id}/continuations", response_model=GenerationJobCreateResponse)
def continue_resource_batch(
    batch_id: str,
    payload: ContinueResourceBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Create a new auditable Run in an existing batch.

    A full-batch retry supersedes its source run. A single-resource retry only
    replaces that resource's visible version inside the batch.
    """
    report = build_health_report(get_settings())
    if report.status == "not_ready":
        detail = "生成依赖未就绪"
        if report.error_codes:
            detail = f"{detail}：{', '.join(report.error_codes)}"
        raise HTTPException(status_code=503, detail=detail)

    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    learner = ensure_profile_access(request, profile_service.get(payload.learner_id))
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_job_service: GenerationJobService = container.generation_job_service()
    batch_jobs = [
        item
        for item in generation_job_service.list_jobs(learner.learner_id).items
        if (item.batch_id or item.run_id) == batch_id
    ]
    source_job = next(
        (item for item in batch_jobs if item.run_id == payload.source_run_id),
        None,
    ) if payload.source_run_id else next(iter(batch_jobs), None)
    if source_job is None:
        detail = "指定的源任务不属于该资源批次" if payload.source_run_id else "资源批次不存在"
        raise HTTPException(status_code=404, detail=detail)

    try:
        source_request = GenerateRequest.model_validate(source_job.request_payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="资源批次的原始生成参数不可用") from exc

    resource_service: ResourceService = container.resource_service()
    batch_resources = [
        item
        for item in resource_service.list_by_learner(learner.learner_id)
        if (item.batch_id or item.run_id) == batch_id
    ]
    constraints = dict(source_request.constraints)
    constraints["continuation_context"] = _resource_context(batch_resources)
    if payload.instructions and payload.instructions.strip():
        constraints["continuation_instructions"] = payload.instructions.strip()
    if payload.replace_existing_types:
        # Keep prior artifacts auditable, while allowing the learner-facing
        # batch projection to use this run as the latest version of each type.
        constraints["replacement_resource_types"] = list(payload.resource_types)
    request_updates = {
        "resource_types": payload.resource_types,
        "constraints": constraints,
    }
    if payload.include_claim_check is not None:
        request_updates["include_claim_check"] = payload.include_claim_check
    try:
        # Revalidate the copied request so an explicit Claim option cannot
        # bypass the invariant that Claim review requires normal review.
        generation_request = GenerateRequest.model_validate(
            {**source_request.model_dump(mode="python"), **request_updates}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = generation_job_service.create_job(
        learner,
        generation_request,
        batch_id=batch_id,
    )
    feedback_attempt_id = constraints.get("feedback_attempt_id")
    feedback_decision_id = constraints.get("feedback_decision_id")
    if feedback_attempt_id and feedback_decision_id:
        relation_type = "retry" if payload.replace_existing_types and "重新生成" in (payload.instructions or "") else "continuation"
        source_relation_id = None
        if relation_type == "retry" and payload.source_run_id:
            source_relation = request.app.container.feedback_service().feedback_loop_repo.get_followup_relation(
                payload.source_run_id
            )
            source_relation_id = source_relation.get("relation_id") if source_relation else None
        request.app.container.feedback_service().feedback_loop_repo.attach_followup(
            attempt_id=str(feedback_attempt_id), decision_id=str(feedback_decision_id),
            parent_run_id=payload.source_run_id or source_job.run_id,
            child_run_id=job.run_id, trigger_type="resource_append",
            status="queued", relation_type=relation_type,
            source_relation_id=source_relation_id,
            source_child_run_id=payload.source_run_id if relation_type == "retry" else None,
        )
    if payload.source_run_id and payload.replace_source_run:
        generation_job_service.mark_superseded(payload.source_run_id, job.run_id)
    background_tasks.add_task(
        generation_job_service.run_job,
        learner,
        generation_request,
        job.run_id,
        job.batch_id,
    )
    return job


@router.get("/file/{resource_id}")
def download_resource(resource_id: str, request: Request):
    """通过资源 ID 下载受控目录中的生成文件，拒绝任意路径访问。"""
    resource_service: ResourceService = request.app.container.resource_service()
    resource = resource_service.get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id or "")
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    if resource.publication_status != "published":
        raise HTTPException(status_code=404, detail="资源不存在")
    if not resource.file_path:
        raise HTTPException(status_code=404, detail="该资源没有可下载文件")
    try:
        content = load_resource_file(resource.file_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="资源文件不存在或路径不安全") from None
    filename = Path(resource.file_path).name
    return Response(
        content=content,
        media_type=resource.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _authorized_published_resource(resource_id: str, request: Request):
    service: ResourceService = request.app.container.resource_service()
    resource = service.get(resource_id)
    if resource is None or resource.publication_status != "published":
        raise HTTPException(status_code=404, detail="资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id or "")
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return resource


@router.get("/items/{resource_id}", response_model=ResourceDetailResponse)
def get_resource_detail(resource_id: str, request: Request):
    _authorized_published_resource(resource_id, request)
    service: ResourceService = request.app.container.resource_service()
    detail = service.get_published_detail(resource_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return {"resource": detail}


@router.get("/{learner_id}", response_model=ResourceListResponse)
def list_resources(
    learner_id: str,
    request: Request,
    resource_type: str | None = None,
    difficulty: str | None = None,
    run_id: str | None = None,
    batch_id: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    summary_only: bool = False,
):
    """查询学习者生成资源历史"""
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    resource_service: ResourceService = container.resource_service()
    if page is None:
        resources = resource_service.list_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id)
        total = len(resources)
    else:
        resources, total = resource_service.list_page_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id,
            page=page, page_size=page_size)
    if summary_only:
        resources = [item.model_copy(update={"content_text": None, "file_path": None})
                     for item in resources]
    return {
        "learner_id": learner_id,
        "total": total,
        "resources": resources,
        "page": page,
        "page_size": page_size if page is not None else None,
        "has_next": bool(page is not None and page * page_size < total),
        "summary_only": summary_only,
    }
