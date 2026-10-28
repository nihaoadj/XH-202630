"""Validate and freeze one failed resource without re-diagnosing the learner."""
from __future__ import annotations

import json

from app.config import get_settings
from app.core.retrieval.knowledge_ids import query_hash
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.generation.dispatch import TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION
from app.models.generation.resource_retry import ResourceRetryContext
from app.models.knowledge.knowledge import EvidenceAllocation, RESOURCE_AWARE_STRATEGY
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.shared.agent_contracts import ResourceSpec
from app.models.shared.persistence import WorkflowCheckpoint, canonical_hash


def retry_conflict(detail="原任务冻结上下文不完整，无法从资源生成处重试；请明确选择批次完整重新生成"):
    return ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, public_message=detail, status_code=409)


def prepare_resource_retry(service, learner, run_id, spec_id, representation):
    """Read-only preparation. Only the dedicated authorized use case calls this."""
    if representation != "text":
        raise ApplicationError(ErrorCode.REQUEST_VALIDATION_ERROR, status_code=422)
    source = service.job_repo.get(run_id)
    if source is None or source.learner_id != learner.learner_id:
        raise ApplicationError(ErrorCode.WORKFLOW_RUN_NOT_FOUND, status_code=404)
    if source.job_status not in {"completed", "failed"}:
        raise retry_conflict("原任务尚未结束，不能单独重新生成资料")
    generation = service.generation_service
    repo, audit = generation.resource_repo, generation.audit_repo
    spec_record = repo.get_spec(spec_id)
    if spec_record is None or spec_record.run_id != run_id:
        raise ApplicationError(ErrorCode.WORKFLOW_RUN_NOT_FOUND, status_code=404)
    execution = repo.get_execution(run_id, spec_id, representation)
    if execution is None or execution.state not in {"failed", "human_review", "revision_requested"}:
        raise retry_conflict("仅可重新生成已失败或未通过审核的资源")
    parent = repo.get(execution.resource_id) if execution.resource_id else None
    if execution.resource_id and parent is None:
        raise retry_conflict("原资料版本记录缺失，不能安全重建版本关系")
    if parent is not None and parent.publication_status == "published":
        raise retry_conflict("该资源已经发布，不能通过失败资源重试入口覆盖")
    try:
        dispatch = service.job_repo.get_dispatch(run_id) or {}
        source_snapshot = dispatch.get("dispatch_snapshot") or {}
        if source_snapshot.get("workflow_version") not in {TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION}:
            raise ValueError("unsupported source dispatch version")
        frozen_learner = LearnerProfile.model_validate(source_snapshot["learner"])
        original = GenerateRequest.model_validate(source.request_payload)
        if (frozen_learner.learner_id != learner.learner_id
                or original.learner_id != learner.learner_id
                or (frozen_learner.user_id and frozen_learner.user_id != learner.user_id)):
            raise ValueError("source learner mismatch")
        if source_snapshot.get("request_hash") != canonical_hash(original.model_dump(mode="json")):
            raise ValueError("source request fingerprint mismatch")
        checkpoints = audit.list_checkpoints(run_id)
        if not checkpoints:
            raise ValueError("source checkpoint missing")
        checkpoint = max(checkpoints, key=lambda item: (item.step_sequence, item.event_sequence, item.checkpoint_id))
        checkpoint = WorkflowCheckpoint.model_validate(checkpoint.model_dump(mode="json"))
        projection = checkpoint.state_projection
        if (projection.get("run_id") != run_id or projection.get("learner_id") != learner.learner_id
                or projection.get("knowledge_base_id") != source.knowledge_base_id):
            raise ValueError("checkpoint ownership mismatch")
        spec = ResourceSpec.model_validate(spec_record.model_dump(mode="json", exclude={"run_id", "created_at"}))
        frozen_spec = next(item for item in projection["resource_specs"] if item["resource_spec_id"] == spec_id)
        if ResourceSpec.model_validate(frozen_spec) != spec or spec.dependencies:
            raise ValueError("spec mismatch or unsupported cross-resource dependencies")
        if spec.resource_type not in original.resource_types:
            raise ValueError("resource type outside original request")
        evidence = audit.list_evidence(run_id)
        by_id = {item.evidence_id: item for item in evidence}
        strategy = projection.get("retrieval_strategy_version", "legacy")
        allocation = None
        selected_ids = list(spec.evidence_ids)
        if strategy == RESOURCE_AWARE_STRATEGY:
            allocation = EvidenceAllocation.model_validate(projection["evidence_allocation"])
            selected_ids = allocation.available_ids(spec.resource_type)
            if selected_ids != spec.evidence_ids:
                raise ValueError("spec differs from frozen allocation")
        if not selected_ids or set(selected_ids) - set(projection["evidence_ids"]):
            raise ValueError("missing checkpoint evidence")
        selected = [by_id[ident] for ident in (allocation.evidence_ids if allocation else selected_ids)]
        source_reviews = [item for item in audit.list_reviews_by_run(run_id)
                          if parent is not None and str(item.get("resource_id")) == parent.resource_id]
        source_reviews.sort(key=lambda item: (int(item.get("revision_count") or 0),
                                              str(item.get("created_at") or ""), str(item.get("review_id") or "")))
        own_review = source_reviews[-1] if source_reviews else {}
        aggregate = projection.get("review", {})

        def is_selected(item, field):
            if not isinstance(item, dict):
                return len(original.resource_types) == 1
            resource_type = item.get(field) or item.get("resource_type")
            resource_id = item.get("resource_id") or item.get("target_resource_id")
            return ((resource_type is None or resource_type == spec.resource_type)
                    and (resource_id is None or parent is not None and resource_id == parent.resource_id)
                    and (resource_type is not None or resource_id is not None or len(original.resource_types) == 1))

        def distinct(items):
            seen, result = set(), []
            for item in items:
                fingerprint = canonical_hash(item)
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    result.append(item)
            return result

        feedback = {
            "issues": distinct([*own_review.get("issues", []),
                                *(item for item in aggregate.get("issues", []) if is_selected(item, "target_resource_type"))]),
            "revision_instructions": distinct([
                *(item for item in own_review.get("revision_instructions", [])
                  if isinstance(item, dict) and item.get("target_resource_type") in {None, spec.resource_type}),
                *(item for item in aggregate.get("revision_instructions", [])
                  if isinstance(item, dict) and is_selected(item, "target_resource_type")),
            ]),
        }
        if own_review.get("suggestion"):
            feedback["suggestion"] = own_review["suggestion"]
        elif len(original.resource_types) == 1 and aggregate.get("suggestion"):
            feedback["suggestion"] = aggregate["suggestion"]
        if execution.error_code:
            feedback["execution_error_code"] = execution.error_code
        constraints = {**original.constraints, "replacement_resource_types": [spec.resource_type],
                       "resource_retry_lineage": {"source_run_id": run_id, "source_spec_id": spec_id,
                                                  "source_checkpoint_hash": checkpoint.state_hash}}
        request = GenerateRequest.model_validate({**original.model_dump(mode="python"),
                                                  "resource_types": [spec.resource_type], "constraints": constraints})
        texts = {}
        for ref in parent.source_refs if parent is not None else []:
            if ref.evidence_id in selected_ids and ref.retrieval_query and query_hash(ref.retrieval_query) == by_id[ref.evidence_id].query_hash:
                texts[ref.evidence_id] = ref.retrieval_query
        payload = {"schema_version": "1.0", "source_run_id": run_id, "source_spec_id": spec_id,
                   "source_checkpoint_hash": checkpoint.state_hash, "learner": frozen_learner.model_dump(mode="json"),
                   "request": request.model_dump(mode="json"), "diagnosis": projection["diagnosis"],
                   "learning_plan": projection["learning_plan"], "spec": spec.model_dump(mode="json"),
                   "evidence": [item.model_dump(mode="json") for item in selected], "query_texts": texts,
                   "evidence_allocation": allocation.model_dump(mode="json") if allocation else None,
                   "retrieval_strategy_version": strategy, "retrieval_config_hash": projection["retrieval_config_hash"],
                   "source_resource": parent.model_dump(mode="json") if parent else None,
                   "revision_feedback": feedback}
        context = ResourceRetryContext.from_snapshot({**payload, "context_hash": canonical_hash(payload)})
        if len(json.dumps(context.model_dump(mode="json"), ensure_ascii=False).encode()) > get_settings().workflow_checkpoint_max_bytes:
            raise ValueError("retry context exceeds checkpoint budget")
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        raise retry_conflict() from exc
    return context
