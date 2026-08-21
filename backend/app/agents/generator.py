"""Resource-level generation router retained under the historical filename."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from app.agents.policies import target_resource_types
from app.agents.resource_agents.registry import get_resource_agent, normalize_resource_type
from app.agents.resource_spec_builder import build_resource_specs
from app.agents.state import AgentState
from app.core.errors import ApplicationError, ErrorCode
from app.core.evidence import source_refs_from_evidence
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.config import get_settings
from app.models.agent_contracts import (
    GeneratedArtifact,
    GeneratorInput,
    ResourceGenerationContext,
    ResourceSpec,
    build_trace_item,
    make_error_info,
    require_agent_fallback,
    start_step,
)
from app.models.schemas import LearningResource
from app.models.workflow import ResourceStatus, StepStatus
from app.db.resource.models import ResourceSpecRecord


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
            learning_plan=node_input.learning_plan,
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
        knowledge_points=artifact.knowledge_points,
        source_refs=source_refs_from_evidence(node_input.retrieved_evidence),
        review_status=(ResourceStatus.PENDING_REVIEW.value if node_input.include_review
                       else ResourceStatus.UNREVIEWED_DRAFT.value),
        version=(previous.version + 1) if previous else 1,
        parent_resource_id=previous.resource_id if previous else None,
        canonical_text_hash=metadata.canonical_text_hash,
        guide_manifest=data.get("guide_manifest") or {},
        derived_from_resource_id=data.get("derived_from_resource_id"),
        source_resource_version=data.get("source_resource_version"),
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
    # A practice guide's canonical text and HTML are two representations of
    # one user-facing resource.  Keep the API summary resource-oriented too.
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
            resource = _materialize(artifact, node_input, old)
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
    resources.sort(key=lambda item: (order.get(item.resource_spec_id or "", 999),
                                     0 if item.representation.value == "text" else 1))
    executions.sort(key=lambda item: (
        order.get(str(item.get("resource_spec_id") or ""), 999),
        0 if item.get("representation") == "text" else 1,
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


def derive_html_node(state: AgentState, *, llm_gateway: LLMGateway) -> dict[str, Any]:
    """Derive HTML from the current validated canonical practice guide."""

    step_context = start_step(state, attempt=state.get("generation_attempt", 1))
    resources = list(state.get("generated_resources", []))
    canonical = next((item for item in resources
                       if item.resource_type == "实操指南"
                       and item.representation.value == "text"
                       and item.review_status in {
                           ResourceStatus.PENDING_REVIEW.value,
                           ResourceStatus.UNREVIEWED_DRAFT.value,
                           ResourceStatus.APPROVED.value,
                       }
                       and item.content_text
                       and item.canonical_text_hash
                       and item.guide_manifest), None)
    if canonical is None:
        trace = build_trace_item(
            state, agent_name="html_practice_deriver", action="派生互动 HTML",
            status=StepStatus.SKIPPED, input_summary="未找到可派生的规范文本",
            output_summary="跳过 HTML 派生", decision_reason="只有已通过文本技术校验、尚未进入返工或拒绝状态的规范指南可以派生 HTML。",
            step_context=step_context)
        return {"current_node": "html_practice_deriver", "trace": [trace], "errors": []}

    specs = [ResourceSpec.model_validate(item) for item in state.get("resource_specs", [])]
    spec = next((item for item in specs if item.resource_spec_id == canonical.resource_spec_id), None)
    if spec is None or not canonical.canonical_text_hash or not canonical.guide_manifest:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
    node_input = GeneratorInput.model_validate(state)
    context = _context(
        node_input,
        state,
        _worker_step_id(node_input, spec, "html"),
    )
    source = ApprovedPracticeGuideSource(
        resource_id=canonical.resource_id,
        resource_spec_id=spec.resource_spec_id,
        resource_family_id=spec.resource_family_id,
        resource_version=canonical.version,
        review_status=canonical.review_status,
        publication_status=canonical.publication_status,
        difficulty=canonical.difficulty, markdown_content=canonical.content_text or "",
        guide_manifest=canonical.guide_manifest,
        canonical_text_hash=canonical.canonical_text_hash,
        knowledge_points=canonical.knowledge_points,
        source_evidence_ids=spec.evidence_ids,
    )
    agent = get_resource_agent("实操指南")
    executions = [item for item in state.get("resource_executions", [])
                  if not (item.get("resource_spec_id") == spec.resource_spec_id
                          and item.get("representation") == "html")]
    derivation_error = None
    try:
        artifact = agent.generate(spec, context, llm_gateway=llm_gateway,
                                  stage="html", approved_text=source)
        html_resource = _materialize(artifact, node_input, None).model_copy(update={
            # HTML is generated immediately after the canonical text. It is
            # never independently reviewed and therefore mirrors the source's
            # provisional status until the text review supplies its review ID.
            "review_id": canonical.review_id,
            "review_status": canonical.review_status,
            "publication_status": canonical.publication_status,
            "published_at": canonical.published_at,
        })
        resources.append(html_resource)
        executions.append(_execution(spec, html_resource, agent,
                                     attempt=state.get("generation_attempt", 1),
                                     worker_step_id=context.step_id,
                                     state="generated",
                                     validation_status=artifact.metadata.validation_status))
        status = StepStatus.SUCCESS
        errors: list[dict[str, Any]] = []
        output_summary = "互动 HTML 已从规范文本派生并通过最小技术准入"
        llm_metadata = artifact.llm_metadata
        resource_ids = [html_resource.resource_id]
    except LLMGatewayError as exc:
        # Provider truncation must not turn a valid canonical guide into a
        # failed resource. Render the same reviewed Markdown deterministically
        # and keep the model failure only as trace metadata.
        if exc.error.code == ErrorCode.LLM_OUTPUT_TRUNCATED.value:
            fallback_html, warnings = sanitize_html_fragment(
                _deterministic_html_from_markdown(
                    source.markdown_content, source.guide_manifest
                )
            )
            metadata = agent.metadata(
                spec=spec,
                representation="html",
                source_evidence_ids=list(source.source_evidence_ids),
                canonical_text_hash=source.canonical_text_hash,
                validation_status="validated_with_repairs",
            ).model_copy(update={
                "prompt_version": agent.html_prompt_version,
                "artifact_format": "html",
            })
            artifact = GeneratedArtifact(
                metadata=metadata,
                difficulty=source.difficulty,
                content_text=fallback_html,
                knowledge_points=list(source.knowledge_points),
                artifact_data={
                    "derived_from_resource_id": source.resource_id,
                    "source_resource_version": source.resource_version,
                    "source_section_ids": [item.section_id for item in source.guide_manifest.sections],
                    "source_step_ids": [item.step_id for item in source.guide_manifest.steps],
                    "source_code_ids": list(source.guide_manifest.code_ids),
                    "source_checklist_ids": list(source.guide_manifest.checklist_ids),
                    "source_quiz_ids": list(source.guide_manifest.quiz_ids),
                    "interactive_component_counts": {
                        "steps": fallback_html.count("data-practice-step"),
                        "checklists": fallback_html.count("data-practice-checklist"),
                        "quizzes": fallback_html.count("data-practice-quiz"),
                    },
                },
                storage_type="file", mime_type="text/html",
                sanitization_warnings=[*warnings, "deterministic_renderer_fallback"],
                llm_metadata={"fallback": "deterministic_html_renderer", "fallback_reason": exc.error.code},
            )
            html_resource = _materialize(artifact, node_input, None).model_copy(update={
                "review_id": canonical.review_id,
                "review_status": canonical.review_status,
                "publication_status": canonical.publication_status,
                "published_at": canonical.published_at,
            })
            resources.append(html_resource)
            executions.append(_execution(spec, html_resource, agent,
                                         attempt=state.get("generation_attempt", 1),
                                         worker_step_id=context.step_id,
                                         state="generated",
                                         validation_status=artifact.metadata.validation_status))
            status = StepStatus.SUCCESS
            errors = [exc.error.model_dump(mode="json")]
            output_summary = "模型 HTML 截断，已使用规范文本确定性渲染并通过准入"
            llm_metadata = artifact.llm_metadata
            resource_ids = [html_resource.resource_id]
        else:
            derivation_error = exc.error
            executions.append({
                "resource_spec_id": spec.resource_spec_id, "resource_type": spec.resource_type,
                "representation": "html", "resource_execution_state": "failed",
                "worker_step_id": context.step_id,
                "attempt": state.get("generation_attempt", 1), "resource_id": None,
                "review_id": None, "error_code": _error_code_value(exc.error.code),
                "agent_name": agent.agent_name, "prompt_version": agent.html_prompt_version,
                "artifact_format": "html", "validation_status": "failed",
            })
            status = StepStatus.DEGRADED
            errors = [exc.error.model_dump(mode="json")]
            output_summary = "HTML 派生失败；规范文本指南保持可用"
            llm_metadata = exc.trace_metadata()
            resource_ids = []
    except ApplicationError as exc:
        derivation_error = make_error_info(
            exc.code,
            source="html_practice_deriver",
            category="validation",
        )
        executions.append({
            "resource_spec_id": spec.resource_spec_id, "resource_type": spec.resource_type,
            "representation": "html", "resource_execution_state": "failed",
            "worker_step_id": context.step_id,
            "attempt": state.get("generation_attempt", 1), "resource_id": None,
            "review_id": None, "error_code": _error_code_value(exc.code),
            "agent_name": agent.agent_name, "prompt_version": agent.html_prompt_version,
            "artifact_format": "html", "validation_status": "failed",
        })
        status = StepStatus.DEGRADED
        errors = [derivation_error.model_dump(mode="json")]
        output_summary = "HTML 派生结果未通过技术准入；规范文本指南保持可用"
        llm_metadata = None
        resource_ids = []
    trace = build_trace_item(
        state, agent_name="generator", action="派生互动 HTML", status=status,
        input_summary=f"规范文本：{canonical.resource_id} v{canonical.version}",
        output_summary=output_summary,
        decision_reason="HTML 仅使用规范文本、manifest 与服务端 hash 作为内容来源，并在审核阶段继承文本结论。",
        evidence_refs=spec.evidence_ids, resource_ids=resource_ids,
        error=derivation_error,
        step_context=step_context, llm_metadata=llm_metadata)
    return {"generated_resources": resources, "resource_executions": executions,
            "resource_progress_summary": progress_summary(executions),
            "workflow_status": ("degraded" if status == StepStatus.DEGRADED
                                and state.get("workflow_status") == "completed"
                                else state.get("workflow_status")),
            "current_node": "html_practice_deriver", "trace": [trace], "errors": errors}
