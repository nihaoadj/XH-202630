"""Resource-level generation router retained under the historical filename."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from app.agents.shared.policies import target_resource_types
from app.agents.resource_agents.registry import get_resource_agent, normalize_resource_type
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.agents.resource_workflows.learning_documents.state import AgentState
from app.core.security.errors import ApplicationError, ErrorCode
from app.core.retrieval.evidence import source_refs_from_evidence
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.config import get_settings
from app.models.shared.agent_contracts import (
    GeneratedArtifact,
    GeneratorInput,
    ResourceGenerationContext,
    ResourceSpec,
    build_trace_item,
    make_error_info,
    require_agent_fallback,
    start_step,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.workflow import ResourceStatus, StepStatus
from app.db.learning_documents.models import ResourceSpecRecord


class ResourceProgressRecorder(Protocol):
    def record_resource_queued(self, state: dict[str, Any], *, spec: ResourceSpecRecord,
                               execution: dict[str, Any], trace_item: dict[str, Any]) -> None: ...

    def record_resource_generated(self, state: dict[str, Any], *, resource: LearningResource,
                                  execution: dict[str, Any], trace_item: dict[str, Any]) -> None: ...


# Compatibility symbol. Content prompts now live exclusively in resource_agents/.
GENERATION_PROMPT = "Resource routing is deterministic; specialized prompts own content generation."


def _specs_for_state(state: AgentState, node_input: GeneratorInput) -> list[ResourceSpec]:
    stored = state.get("resource_specs") or []
    if stored:
        specs = [ResourceSpec.model_validate(item) for item in stored]
    else:
        specs = build_resource_specs(
            run_id=node_input.run_id,
            resource_types=node_input.resource_types,
            topic=node_input.topic,
            difficulty=(node_input.difficulty_preference
                or node_input.diagnosis.get("recommended_difficulty")
                or node_input.learner.skill_level or "中级"),
            learning_plan={
                **node_input.learning_plan,
                **({"correction_focus_snapshot": node_input.constraints["correction_focus_snapshot"]}
                   if node_input.constraints.get("correction_focus_snapshot") else {}),
            },
            evidence=node_input.retrieved_evidence,
            target_skill_nodes=node_input.target_skill_nodes,
        )
    expected = [normalize_resource_type(item) for item in node_input.resource_types]
    if [item.resource_type for item in specs] != expected:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
    return specs


def _context(node_input: GeneratorInput, state: AgentState, step_id: str) -> ResourceGenerationContext:
    learner = node_input.learner
    return ResourceGenerationContext(
        run_id=node_input.run_id,
        batch_id=node_input.batch_id,
        step_id=step_id,
        topic=node_input.topic,
        learner_profile_summary={
            "skill_level": learner.skill_level,
            "weak_points": learner.weak_points[:20],
            "strong_points": learner.strong_points[:20],
            "learning_goal": learner.learning_goal,
        },
        learning_path=list(node_input.learning_plan.get("learning_path", []))[:50],
        evidence=node_input.retrieved_evidence,
        continuation_context=list(node_input.constraints.get("continuation_context", []))[:12],
        constraints=node_input.constraints,
        generation_attempt=node_input.generation_attempt,
        workflow_deadline_at=state.get("workflow_deadline_at"),
    )


def _worker_step_id(node_input: GeneratorInput, spec: ResourceSpec, representation: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{node_input.run_id}:resource-worker:{spec.resource_spec_id}:{representation}:{node_input.generation_attempt}",
    ))


def _previous(resources: list[LearningResource]) -> dict[tuple[str, str], LearningResource]:
    return {
        (item.resource_spec_id, item.representation.value): item
        for item in resources if item.resource_spec_id
    }


def _materialize(
    artifact: GeneratedArtifact,
    node_input: GeneratorInput,
    previous: LearningResource | None,
    spec: ResourceSpec,
) -> LearningResource:
    metadata = artifact.metadata
    data = artifact.artifact_data
    return LearningResource(
        resource_id=str(uuid.uuid4()), learner_id=node_input.learner.learner_id,
        topic=node_input.topic, run_id=node_input.run_id, batch_id=node_input.batch_id,
        resource_spec_id=metadata.resource_spec_id,
        resource_family_id=metadata.resource_family_id,
        representation=metadata.representation, resource_type=metadata.resource_type,
        difficulty=artifact.difficulty, storage_type=artifact.storage_type,
        content_text=artifact.content_text, mime_type=artifact.mime_type,
        # The frozen spec is the authoritative curriculum scope. Preserve any
        # agent-added subpoints, but never allow an artifact to drop a selected
        # target node before publication and curriculum accounting.
        knowledge_points=list(dict.fromkeys([*spec.knowledge_points, *artifact.knowledge_points])),
        source_refs=source_refs_from_evidence(node_input.retrieved_evidence),
        review_status=(ResourceStatus.PENDING_REVIEW.value if node_input.include_review
                       else ResourceStatus.UNREVIEWED_DRAFT.value),
        version=(previous.version + 1) if previous else 1,
        parent_resource_id=previous.resource_id if previous else None,
        exercise_items=list(data.get("exercise_items") or []),
        assessment_payload=data.get("assessment_package"),
        assessment_payload_hash=(data.get("assessment_package") or {}).get("payload_hash"),
    )


def _fallback(spec: ResourceSpec, node_input: GeneratorInput, previous: LearningResource | None) -> LearningResource:
    return LearningResource(
        resource_id=str(uuid.uuid4()), learner_id=node_input.learner.learner_id,
        topic=node_input.topic, run_id=node_input.run_id, batch_id=node_input.batch_id,
        resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
        representation="text", resource_type=spec.resource_type, difficulty=spec.difficulty,
        content_text=(f"# {node_input.topic} - {spec.resource_type}\n\n## 学习目标\n"
                      f"{spec.learning_objective}\n\n## 资源状态\n模型调用未完成，等待人工复核。\n"),
        knowledge_points=spec.knowledge_points,
        source_refs=source_refs_from_evidence(node_input.retrieved_evidence),
        review_status=ResourceStatus.HUMAN_REVIEW.value,
        version=(previous.version + 1) if previous else 1,
        parent_resource_id=previous.resource_id if previous else None,
    )


def _execution(spec: ResourceSpec, resource: LearningResource, agent: Any, *, attempt: int,
               worker_step_id: str,
               state: str, validation_status: str, error_code: str | None = None) -> dict[str, Any]:
    return {
        "resource_spec_id": spec.resource_spec_id, "resource_type": spec.resource_type,
        "representation": resource.representation.value, "resource_execution_state": state,
        "worker_step_id": worker_step_id,
        "attempt": attempt, "resource_id": resource.resource_id, "review_id": resource.review_id,
        "error_code": error_code, "agent_name": agent.agent_name,
        "prompt_version": agent.prompt_version, "artifact_format": agent.artifact_format,
        "validation_status": validation_status,
    }


def progress_summary(executions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in executions:
        value = str(item["resource_execution_state"])
        counts[value] = counts.get(value, 0) + 1
    # Each resource spec has one user-facing text representation.
    logical: dict[str, list[str]] = {}
    for item in executions:
        logical.setdefault(str(item.get("resource_spec_id") or id(item)), []).append(
            str(item.get("resource_execution_state") or "queued")
        )
    total = len(logical)
    terminal = sum(
        all(value in {"approved", "human_review", "failed"} for value in values)
        for values in logical.values()
    )
    return {"schema_version": "1.0", "total": total, "counts": counts,
            "approved": counts.get("approved", 0), "human_review": counts.get("human_review", 0),
            "failed": counts.get("failed", 0), "can_finalize": bool(total and terminal == total),
            "executions": executions}



def _error_code_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def generate_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
    resource_progress_recorder: ResourceProgressRecorder | None = None,
) -> dict[str, Any]:
    """Generate one canonical text artifact per spec using an exact registry route."""
    node_input = GeneratorInput.model_validate(state)
    if not node_input.retrieved_evidence:
        raise ApplicationError(ErrorCode.EVIDENCE_INSUFFICIENT, status_code=422)
    specs = _specs_for_state(state, node_input)
    revision_targets = target_resource_types(node_input.review_result.get("revision_instructions", []))
    revision_targets.update(
        item.get("resource_type")
        for item in state.get("resource_executions", [])
        if isinstance(item, dict)
        and item.get("validation_status") == "failed"
        and item.get("resource_type")
    )
    active_types = (revision_targets if node_input.revision_count and node_input.generated_resources
                    else {item.resource_type for item in specs})
    if not active_types:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
    step_context = start_step(state, attempt=node_input.generation_attempt)
    previous = _previous(node_input.generated_resources)
    resources = [item for item in node_input.generated_resources
                 if item.resource_type not in active_types]
    generated_now: list[LearningResource] = []
    executions = [item for item in state.get("resource_executions", [])
                  if item.get("resource_type") not in active_types]
    errors: list[dict[str, Any]] = []
    llm_metadata = None
    work_items = [
        (
            spec,
            get_resource_agent(spec.resource_type),
            previous.get((spec.resource_spec_id, "text")),
            _context(node_input, state, _worker_step_id(node_input, spec, "text")),
        )
        for spec in specs
        if spec.resource_type in active_types
    ]
    progress_trace = {
        "run_id": node_input.run_id,
        "step_id": step_context["step_id"],
        "sequence": step_context["sequence"],
        "attempt": node_input.generation_attempt,
        "agent_name": "generator",
        "node_name": "generate",
    }
    if resource_progress_recorder is not None:
        for spec, agent, _, context in work_items:
            queued_execution = {
                "resource_spec_id": spec.resource_spec_id,
                "resource_type": spec.resource_type,
                "representation": "text",
                "resource_execution_state": "queued",
                "worker_step_id": context.step_id,
                "attempt": node_input.generation_attempt,
                "agent_name": agent.agent_name,
                "prompt_version": agent.prompt_version,
                "artifact_format": agent.artifact_format,
                "validation_status": "pending",
            }
            payload = spec.model_dump(mode="json")
            payload["run_id"] = node_input.run_id
            resource_progress_recorder.record_resource_queued(
                state,
                spec=ResourceSpecRecord.model_validate(payload),
                execution=queued_execution,
                trace_item=progress_trace,
            )
    max_workers = min(get_settings().resource_worker_max_concurrency, len(work_items))
    futures = {}
    executor = None
    if max_workers > 1:
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="resource-worker")
        futures = {
            spec.resource_spec_id: executor.submit(
                agent.generate,
                spec,
                context,
                llm_gateway=llm_gateway,
            )
            for spec, agent, _, context in work_items
        }
    def consume(spec, agent, old, context, artifact=None, worker_error=None) -> None:
        nonlocal llm_metadata
        try:
            if worker_error is not None:
                raise worker_error
            if artifact is None:
                artifact = agent.generate(spec, context, llm_gateway=llm_gateway)
            resource = _materialize(artifact, node_input, old, spec)
            llm_metadata = artifact.llm_metadata
            execution = _execution(spec, resource, agent, attempt=node_input.generation_attempt,
                                   worker_step_id=context.step_id,
                                   state="generated", validation_status=artifact.metadata.validation_status)
        except LLMGatewayError as exc:
            try:
                error = require_agent_fallback(state, exc.error)
            except ApplicationError:
                error = exc.error
            errors.append(error.model_dump(mode="json"))
            resource = _fallback(spec, node_input, old)
            execution = _execution(spec, resource, agent, attempt=node_input.generation_attempt,
                                   worker_step_id=context.step_id,
                                   state="human_review", validation_status="failed",
                                   error_code=_error_code_value(error.code))
        except ApplicationError as exc:
            error = make_error_info(exc.code, source=agent.agent_name,
                                    attempt=node_input.generation_attempt,
                                    category="resource_validation")
            errors.append(error.model_dump(mode="json"))
            resource = _fallback(spec, node_input, old)
            execution = _execution(spec, resource, agent, attempt=node_input.generation_attempt,
                                   worker_step_id=context.step_id, state="human_review",
                                   validation_status="failed",
                                   error_code=_error_code_value(error.code))
        if resource_progress_recorder is not None:
            resource_progress_recorder.record_resource_generated(
                state, resource=resource, execution=execution, trace_item=progress_trace
            )
        resources.append(resource)
        generated_now.append(resource)
        executions.append(execution)

    try:
        if executor is not None:
            future_items = {
                future: (spec, agent, old, context)
                for spec, agent, old, context in work_items
                for future in [futures[spec.resource_spec_id]]
            }
            for future in as_completed(future_items):
                spec, agent, old, context = future_items[future]
                try:
                    artifact = future.result()
                except Exception as exc:
                    # ``Future.result`` re-raises failures from the resource
                    # worker.  Feed those back through ``consume`` so the
                    # normal per-resource fallback policy is applied instead
                    # of aborting every other resource in this generation run.
                    consume(spec, agent, old, context, worker_error=exc)
                else:
                    consume(spec, agent, old, context, artifact=artifact)
        else:
            for spec, agent, old, context in work_items:
                consume(spec, agent, old, context)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    order = {item.resource_spec_id: item.display_order for item in specs}
    resources.sort(key=lambda item: order.get(item.resource_spec_id or "", 999))
    executions.sort(key=lambda item: (
        order.get(str(item.get("resource_spec_id") or ""), 999),
    ))
    status = StepStatus.DEGRADED if errors else StepStatus.SUCCESS
    trace_item = build_trace_item(
        state, agent_name="generator", action="按资源类型路由专用 Agent", status=status,
        input_summary=f"资源 Spec：{len(specs)}；本轮生成：{len(generated_now)}",
        output_summary=f"已生成文本表示：{[item.resource_type for item in generated_now]}",
        decision_reason="resource_type 经受控别名规范化后精确路由，仅生成文本表示并进入审核。",
        evidence_refs=[item.evidence_id for item in node_input.retrieved_evidence],
        resource_ids=[item.resource_id for item in generated_now], attempt=node_input.generation_attempt,
        step_context=step_context, llm_metadata=llm_metadata)
    return {"resource_specs": [item.model_dump(mode="json") for item in specs],
            "resource_executions": executions, "resource_progress_summary": progress_summary(executions),
            "generated_resources": resources, "current_node": "generator", "trace": [trace_item],
            "errors": errors, "generation_attempt": node_input.generation_attempt,
            "iteration": node_input.generation_attempt}
