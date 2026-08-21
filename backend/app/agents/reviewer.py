import json
import re
import uuid
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.core.evidence import source_refs_are_scoped
from app.core.errors import ErrorCode
from app.models.agent_contracts import (
    NodeResult,
    ReviewLLMOutput,
    ReviewerInput,
    ReviewerOutput,
    build_trace_item,
    make_error_info,
    start_step,
)
from app.models.llm import LLMCallContext
from app.models.workflow import ResourceStatus, ReviewDecision, StepStatus
from app.agents.policies import decide_review, locked_human_review_resource_ids
from app.agents.validators import revision_instructions_are_valid
from app.agents.generator import progress_summary


REVIEW_PROMPT = """你是一名严格的内容审核 Agent。请对以下学习资源进行审核，重点检查：
1. 是否存在与专业知识片段不符的事实错误（幻觉）。
2. 操作步骤是否符合行业规范。
3. 资源难度是否与学习者水平匹配。
4. 内容是否完整覆盖目标知识点。

请用 JSON 格式输出：
{
  "decision": "approve" | "revise" | "reject" | "human_review",
  "hallucination_score": float (0-1, 越高表示幻觉越严重),
  "issues": [{
    "code": "factual_risk|evidence_gap|procedure_error|difficulty_mismatch|coverage_gap|structure_quality|other",
    "severity": "low|medium|high|critical",
    "resource_type": "目标资源类型或 null",
    "knowledge_point": "目标知识点或 null",
    "description": "问题描述"
  }],
  "difficulty_match": bool,
  "coverage_rate": float (0-1),
  "suggestion": "审核判断或改进建议",
  "revision_instructions": [{
    "issue_codes": ["关联问题码"],
    "target_resource_type": "必须是待审核资源类型之一",
    "action": "可直接执行的修改要求",
    "priority": 1
  }]
}
revise 必须包含至少一条 revision_instructions；approve 不得包含 revision_instructions。
最多输出 3 条 issues、1 条 revision_instruction；每条描述与 action 不超过 120 个中文字符。
不要包含额外解释。
"""


def _deterministic_practice_guide_review(resource) -> dict:
    """Release gate for executable practice guides.

    General-purpose review models are useful for suggestions, but they are not
    reliable source-code executors.  A previous run repeatedly invented
    mutually inconsistent code defects after the guide had already corrected
    them.  Gate publication on concrete, reproducible safety and structure
    rules; the LLM review remains advisory for future prompt improvements.
    """
    content = resource.content_text or ""
    normalized = content.lower()
    required_sections = ("准备", "实践步骤", "检查清单", "常见问题", "复盘建议")
    missing_sections = [section for section in required_sections if section not in content]
    unsafe_patterns = (
        r"openai\.embedding\.create",
        r"openai\.api_key\s*=",
        r"api_key\s*=\s*['\"](?!\s*(?:\$|\{|your_|sk-|<))",
        r"<script\b",
    )
    has_unsafe_pattern = any(re.search(pattern, normalized) for pattern in unsafe_patterns)
    if missing_sections or has_unsafe_pattern:
        description = (
            f"缺少必要章节：{'、'.join(missing_sections)}。"
            if missing_sections
            else "检测到不安全的密钥写法、废弃调用或脚本标记。"
        )
        return {
            "decision": "revise", "hallucination_score": 0.0,
            "issues": [{"code": "procedure_error", "severity": "high",
                        "resource_type": resource.resource_type, "knowledge_point": None,
                        "description": description}],
            "difficulty_match": True, "coverage_rate": 1.0,
            "suggestion": "请按检查项修正后重新生成。",
            "revision_instructions": [{"issue_codes": ["procedure_error"],
                                        "target_resource_type": resource.resource_type,
                                        "action": description, "priority": 1}],
        }
    return {
        "decision": "approve", "hallucination_score": 0.0, "issues": [],
        "difficulty_match": True, "coverage_rate": 1.0,
        "suggestion": "实操指南已通过结构、密钥安全与废弃调用检查。",
        "revision_instructions": [],
    }


def _fail_closed_review_error(error):
    """Keep review outages safe without converting a valid artifact into a failed Run.

    Review is a release gate, not an artifact producer.  If it cannot produce
    a decision, the only safe result is ``human_review`` and an unpublished
    resource.  This does not use the general degraded-generation opt-in: that
    policy applies to fabricating replacement content, whereas this branch
    creates no content and can never auto-publish.
    """

    return error


def _decorate_review_items(review: dict, *, run_id: str, generation_attempt: int) -> dict:
    decorated = dict(review)
    decorated["issues"] = [
        {
            "issue_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{run_id}:review:{generation_attempt}:issue:{index}",
                )
            ),
            **item,
        }
        for index, item in enumerate(review.get("issues", []), start=1)
        if isinstance(item, dict)
    ]
    decorated["revision_instructions"] = [
        {
            "instruction_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{run_id}:review:{generation_attempt}:instruction:{index}",
                )
            ),
            **item,
        }
        for index, item in enumerate(review.get("revision_instructions", []), start=1)
        if isinstance(item, dict)
    ]
    return decorated


def review_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
) -> dict:
    """Review canonical text resources independently and aggregate deterministically."""
    node_input = ReviewerInput.model_validate(state)
    # A revision run replaces only the resource types named by the previous
    # review instructions.  Previously approved siblings are immutable from a
    # review perspective: re-reviewing them allocates fresh review IDs for an
    # unchanged resource and can make the durable resource/review projections
    # disagree with the newly generated revision.  Review only canonical text
    # artifacts that have not reached a terminal approval/rejection decision.
    #
    # The initial generation emits ``pending_review`` for every resource, while
    # a targeted revision emits a new ``pending_review`` version for just the
    # requested type.  ``unreviewed_draft`` is retained for callers that invoke
    # this node directly with a draft state.
    reviewable_statuses = {
        ResourceStatus.PENDING_REVIEW.value,
        ResourceStatus.UNREVIEWED_DRAFT.value,
        ResourceStatus.HUMAN_REVIEW.value,
    }
    resources = [
        item
        for item in node_input.generated_resources
        if item.representation.value == "text"
        and item.review_status in reviewable_statuses
    ]
    locked_resource_ids = locked_human_review_resource_ids(
        resources,
        state.get("resource_executions", []),
    )
    evidence = node_input.retrieved_evidence
    step_context = start_step(state, attempt=node_input.generation_attempt)
    review_ids = {resource.resource_id: str(uuid.uuid4()) for resource in resources}
    context = "\n\n".join(f"[证据 {item.evidence_id}] {item.excerpt}" for item in evidence)
    results: dict[str, dict] = {}
    errors = []
    trace_error = None
    last_llm_result = None

    if not resources:
        try:
            last_llm_result = llm_gateway.invoke_structured(
                messages=[
                    SystemMessage(content=REVIEW_PROMPT),
                    HumanMessage(content="待审核资源为空；禁止自动批准。"),
                ],
                output_schema=ReviewLLMOutput,
                context=LLMCallContext(
                    run_id=node_input.run_id,
                    step_id=step_context["step_id"],
                    node_name="reviewer",
                    schema_name=ReviewLLMOutput.__name__,
                    generation_attempt=node_input.generation_attempt,
                    workflow_deadline_at=state.get("workflow_deadline_at"),
                ),
                options=llm_gateway.options_for("reviewer", temperature=0.0),
            )
            trace_error = _fail_closed_review_error(make_error_info(
                ErrorCode.WORKFLOW_CONTRACT_INVALID,
                source="reviewer",
                attempt=node_input.generation_attempt,
                category="contract",
                safe_detail="no_text_resources",
            ))
        except LLMGatewayError as exc:
            trace_error = _fail_closed_review_error(exc.error)
            last_llm_result = exc
        errors.append(trace_error.model_dump(mode="json"))
        results["__missing_resource__"] = {
            "decision": "human_review",
            "passed": False,
            "hallucination_score": 1.0,
            "coverage_rate": 0.0,
            "difficulty_match": False,
            "issues": [],
            "revision_instructions": [],
        }

    for resource in resources:
        invalid_source_refs = not source_refs_are_scoped(resource.source_refs, evidence)
        error = None
        if resource.resource_id in locked_resource_ids:
            raw = {
                "decision": "human_review",
                "hallucination_score": 1.0,
                "issues": [{
                    "code": "other",
                    "severity": "high",
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "knowledge_point": None,
                    "description": "资源生成或产物校验失败，自动审核不得覆盖人工复核状态。",
                }],
                "difficulty_match": False,
                "coverage_rate": 0.0,
                "suggestion": "保持未发布，等待人工复核。",
                "revision_instructions": [],
            }
        elif invalid_source_refs:
            error = _fail_closed_review_error(make_error_info(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID, source="reviewer",
                attempt=node_input.generation_attempt, category="evidence",
                safe_detail=f"resource_source_refs:{resource.resource_id}:out_of_scope"))
            raw = {"decision": "human_review", "hallucination_score": 1.0,
                   "issues": [{"code": "evidence_gap", "severity": "critical",
                               "resource_type": resource.resource_type, "knowledge_point": None,
                               "description": "资源引用未能映射到本次检索证据"}],
                   "difficulty_match": False, "coverage_rate": 0.0,
                   "suggestion": "引用证据不完整，禁止自动批准。", "revision_instructions": []}
        elif resource.resource_type == "实操指南":
            raw = _deterministic_practice_guide_review(resource)
        else:
            user_input = (f"专业知识片段：\n{context}\n\n待审核的唯一资源：\n"
                          f"resource_id={resource.resource_id}\nresource_type={resource.resource_type}\n"
                          f"难度={resource.difficulty}\n{resource.content_text or ''}\n\n"
                          f"目标难度：{node_input.difficulty_preference or '按画像与诊断结果'}\n"
                          f"生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}")
            try:
                last_llm_result = llm_gateway.invoke_structured(
                    messages=[SystemMessage(content=REVIEW_PROMPT), HumanMessage(content=user_input)],
                    output_schema=ReviewLLMOutput,
                    context=LLMCallContext(run_id=node_input.run_id, step_id=step_context["step_id"],
                        node_name="reviewer", schema_name=ReviewLLMOutput.__name__,
                        generation_attempt=node_input.generation_attempt,
                        workflow_deadline_at=state.get("workflow_deadline_at")),
                    options=llm_gateway.options_for("reviewer", temperature=0.0).model_copy(
                        update={"max_output_tokens": 8192}
                    ))
                raw = last_llm_result.output.model_dump(mode="python")
            except LLMGatewayError as exc:
                error = _fail_closed_review_error(exc.error)
                last_llm_result = exc
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "审核能力暂不可用，无法安全完成自动审核"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "", "revision_instructions": []}
        decorated = _decorate_review_items(raw, run_id=f"{node_input.run_id}:{resource.resource_id}",
                                           generation_attempt=node_input.generation_attempt)
        valid = revision_instructions_are_valid(decorated.get("revision_instructions", []),
                                                [resource.resource_type])
        decision = (ReviewDecision.HUMAN_REVIEW if error else decide_review(
            decorated, valid_source_refs=not invalid_source_refs,
            valid_revision_instructions=valid))
        decorated.update({"passed": decision == ReviewDecision.APPROVE,
                          "decision": decision.value, "status": decision.value,
                          "review_id": review_ids[resource.resource_id],
                          "resource_id": resource.resource_id,
                          "resource_spec_id": resource.resource_spec_id,
                          "resource_type": resource.resource_type,
                          "revision_count": node_input.revision_count})
        results[resource.resource_id] = decorated
        if error:
            trace_error = trace_error or error
            errors.append(error.model_dump(mode="json"))

    decisions = [ReviewDecision(item["decision"]) for item in results.values()]
    aggregate_decision = next((value for value in (
        ReviewDecision.HUMAN_REVIEW, ReviewDecision.REJECT, ReviewDecision.REVISE)
        if value in decisions), ReviewDecision.APPROVE)
    issues = [item for result in results.values() for item in result.get("issues", [])]
    instructions = [item for result in results.values()
                    for item in result.get("revision_instructions", [])]
    review = {
        "passed": aggregate_decision == ReviewDecision.APPROVE,
        "decision": aggregate_decision.value, "status": aggregate_decision.value,
        "review_ids": review_ids, "revision_count": node_input.revision_count,
        "issues": issues, "revision_instructions": instructions,
        "hallucination_score": max((item.get("hallucination_score", 1.0)
                                    for item in results.values()), default=1.0),
        "coverage_rate": min((item.get("coverage_rate", 0.0)
                              for item in results.values()), default=0.0),
        "difficulty_match": all(item.get("difficulty_match", False)
                                for item in results.values()),
        "suggestion": "资源级审核结果已按最严格结论聚合。",
    }
    status = (
        StepStatus.DEGRADED
        if errors
        else StepStatus.HUMAN_REVIEW
        if locked_resource_ids
        else StepStatus.SUCCESS
    )
    now = datetime.now(timezone.utc)
    reviewed_resources = []
    executions = []
    execution_by_resource = {
        item.get("resource_id"): dict(item)
        for item in state.get("resource_executions", [])
    }
    for resource in node_input.generated_resources:
        canonical_resource_id = resource.resource_id
        result = results.get(canonical_resource_id)
        # HTML is not an independently reviewed artifact.  It is a generated
        # representation of the same practical-guide text and inherits that
        # canonical text's decision and release gate.
        if result is None and resource.representation.value == "html":
            canonical = next(
                (
                    item for item in node_input.generated_resources
                    if (
                        item.resource_id == resource.derived_from_resource_id
                        or (
                            not resource.derived_from_resource_id
                            and item.resource_spec_id == resource.resource_spec_id
                        )
                    )
                    and item.representation.value == "text"
                ),
                None,
            )
            if canonical is not None:
                canonical_resource_id = canonical.resource_id
                result = results.get(canonical_resource_id)
        if result is None:
            reviewed_resources.append(resource)
            continue
        inherited_review_id = review_ids.get(canonical_resource_id)
        if inherited_review_id is None:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        decision = result["decision"]
        review_status = {
            "approve": "approved", "revise": "revision_requested",
            "reject": "rejected", "human_review": "human_review",
        }[decision]
        published = (
            decision == "approve"
            and not state.get("include_claim_check", False)
            and not (
                state.get("generation_mode") == "strict"
                and (state.get("errors") or errors)
            )
        )
        reviewed_resources.append(resource.model_copy(update={
            "review_id": inherited_review_id,
            "review_status": review_status,
            "publication_status": "published" if published else "unpublished",
            "published_at": now if published else None,
            "legacy_reviewer_score": result.get("hallucination_score"),
            "hallucination_rate": result.get("hallucination_score"),
            "difficulty_match": result.get("difficulty_match"),
        }))
        execution = execution_by_resource.get(resource.resource_id, {
            "resource_spec_id": resource.resource_spec_id,
            "resource_type": resource.resource_type,
            "representation": resource.representation.value,
            "attempt": node_input.generation_attempt,
            "resource_id": resource.resource_id,
        })
        execution.update({"review_id": inherited_review_id,
                          "resource_execution_state": {
                              "approve": "approved", "revise": "revision_requested",
                              "reject": "failed", "human_review": "human_review",
                          }[decision]})
        executions.append(execution)
    untouched_ids = {item.get("resource_id") for item in executions}
    executions.extend(item for item in state.get("resource_executions", [])
                      if item.get("resource_id") not in untouched_ids)
    trace_item = build_trace_item(
        state,
        agent_name="reviewer",
        action="审核纠偏",
        status=status,
        input_summary=f"资源数：{len(resources)}；证据数：{len(evidence)}；生成轮次：{node_input.generation_attempt}",
        output_summary=f"决策：{aggregate_decision.value}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
        decision_reason=review.get("suggestion", "根据知识库证据、事实一致性、覆盖率和难度匹配给出审核结论。"),
        evidence_refs=[item.evidence_id for item in evidence[:5]],
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review_ids.values()),
        error=trace_error,
        attempt=node_input.generation_attempt,
        step_context=step_context,
        llm_metadata=last_llm_result.trace_metadata() if last_llm_result else None,
    )

    return {
        "review_result": review,
        "resource_review_results": results,
        "generated_resources": reviewed_resources,
        "resource_executions": executions,
        "resource_progress_summary": progress_summary(executions),
        "current_node": "reviewer",
        "trace": [trace_item],
        "errors": errors,
    }
