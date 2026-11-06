"""P0-06 independent Claim extraction, judgement and deterministic routing."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.learning_documents.state import AgentState
from app.agents.shared.evidence_scope import evidence_for_resource, validate_payload_evidence, contract_error
from app.agents.shared.llm_accounting import stage_labeled_scope
from app.config import get_settings
from app.core.security.errors import ErrorCode
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.agent_contracts import build_trace_item, make_error_info, start_step
from app.models.reviews.claims import (
    ClaimExtractionLLMOutput,
    ClaimJudgementCandidate,
    ClaimJudgementLLMOutput,
    ClaimSourceRepairLLMOutput,
    ClaimType,
    ClaimMetricStatus,
    ClaimRecord,
    ClaimVerdict,
    compute_claim_metric,
    materialize_claims,
    materialize_judgements,
)
from app.models.shared.llm import LLMCallContext
from app.models.shared.workflow import ClaimCheckStatus, ReviewDecision, StepStatus


EXTRACTOR_PROMPT_VERSION = "p0-06-extract-v3"
JUDGE_PROMPT_VERSION = "p0-06-judge-v1"

def extractor_prompt(max_claims_per_resource: int) -> str:
    """Build the prompt from the same environment-backed Claim cap we enforce."""
    return f"""你是独立 Claim 抽取器。仅从给定资源原文抽取可单独判断的陈述。
resource_id 必须从输入中原样选择；source_text 必须是资源原文的连续精确子串。
source_start/source_end 请按 Python 字符下标填写且 end 为开区间；服务端会以精确 source_text
重新校验并确定最终位置。复习清单中的题干、选项和提示语不是 factual Claim；如需保留，
请标 instructional 或 non_factual。事实陈述标 factual，
教学动作标 instructional，主观/过渡表达标 non_factual。evidence_id 和 knowledge_point_id
只能从输入白名单选择，不能创造 ID。严格输出限制：每个非空资源输出 1–{max_claims_per_resource} 条 Claim；
claim_text 必须是单条简洁陈述；每条 source_text 必须是足以支持 Claim 的最短连续原文片段，且不得超过 200 字符。
关键约束：source_text 必须是资源原文的逐字连续片段。复制前先在原文中定位完整原句，再原样粘贴；
标点、空格、连词、代词、括号和引号都必须与原文完全一致，禁止改写、概括、合并、截断、补全或替换同义词。
反例（禁止）——原文“不能擅自扩写为‘事实为假’”，不得输出“不等于已证伪”；原文“之前，因为……”，不得输出“之前。”。
优先保留可由冻结 Evidence 独立验证的核心事实。只输出一个满足 schema 的 JSON 对象；禁止输出思考过程、解释、标题、Markdown、重复 Claim、重复 source_text 或任何 schema 外字段。"""

JUDGE_PROMPT = """你是独立 Claim 证据判定器。逐条且仅依据本次冻结 Evidence 判定。
每个 claim_id 必须恰好出现一次。事实 Claim 只能判 supported、contradicted、not_in_evidence；
instructional/non_factual Claim 必须判 non_factual。supported/contradicted 必须引用白名单
evidence_ids，not_in_evidence/non_factual 禁止引用证据。不能使用常识补全，不能创造 ID。
verdict 必须严格使用上述小写枚举值，不要输出 value、label、中文值或其它别名；
先逐条核对 claim_type 与 verdict/evidence_ids 的组合，再输出唯一 JSON 对象。"""


def _normalize_judgement_candidates(
    claims: list[ClaimRecord],
    candidates: list[ClaimJudgementCandidate],
) -> list[ClaimJudgementCandidate]:
    """Repair only deterministic, conservative Judge envelope mismatches."""
    claims_by_id = {claim.claim_id: claim for claim in claims}
    normalized: list[ClaimJudgementCandidate] = []
    for candidate in candidates:
        claim = claims_by_id.get(candidate.claim_id)
        if claim is None:
            normalized.append(candidate)
            continue

        if claim.claim_type != ClaimType.FACTUAL:
            # The extractor has already classified this claim. It is not
            # eligible for factual support metrics, so normalize provider
            # enum/evidence noise without creating factual support.
            if (
                candidate.verdict != ClaimVerdict.NON_FACTUAL
                or candidate.evidence_ids
            ):
                candidate = candidate.model_copy(
                    update={
                        "verdict": ClaimVerdict.NON_FACTUAL,
                        "evidence_ids": [],
                    }
                )
        elif candidate.verdict in {
            ClaimVerdict.NOT_IN_EVIDENCE,
            ClaimVerdict.NON_FACTUAL,
        } and candidate.evidence_ids:
            # A conservative absence/non-factual verdict cannot gain support
            # from an accidental evidence reference. Removing that reference
            # preserves the conservative verdict; the opposite direction is
            # never inferred here.
            candidate = candidate.model_copy(update={"evidence_ids": []})
        normalized.append(candidate)
    return normalized


def _claim_audit_content(resource) -> str:
    """Return canonical text so model spans and server validation share one source.

    Checklist masking previously changed the text sent to the model while
    ``materialize_claims`` validated against the unmasked resource. The
    extractor prompt now classifies checklist questions as non-factual or
    instructional instead.
    """
    return resource.content_text or ""


SOURCE_REPAIR_PROMPT = """你是 Claim 原文定位修复器。下面给出资源原文和若干条未通过“精确子串”校验的 Claim。
为每条 Claim 从 content_text 中逐字复制一段连续原文作为 source_text：
- 必须与原文完全一致，包括标点、空格、连词、代词、括号与引号；
- 不得改写、概括、合并、截断、补全或替换同义词；
- 长度 1–200 字符，且足以支持该 Claim；
- claim_index 必须原样返回，每条恰好出现一次，不得新增条目；
- 只输出一个 JSON 对象：{"claims":[{"claim_index":0,"source_text":"..."}]}，禁止解释、Markdown 或 schema 外字段。"""


def _repair_source_texts(
    *,
    resource,
    candidates: list,
    failed_indexes: list[int],
    llm_gateway: LLMGateway,
    state: AgentState,
    step_context: dict[str, Any],
    resource_deadline: datetime | None,
) -> dict[int, str]:
    """Ask once for verbatim copies of the spans that failed the substring gate.

    Repair never relaxes validation: it only gives the model a bounded second
    chance to copy the original sentence.  Any index it fails again is left
    untouched, so ``materialize_claims`` still rejects the resource.
    """
    payload = {
        "resource_id": resource.resource_id,
        "content_text": _claim_audit_content(resource),
        "claims": [
            {
                "claim_index": index,
                "claim_text": candidates[index].claim_text,
                "rejected_source_text": candidates[index].source_text,
            }
            for index in failed_indexes
        ],
    }
    options = llm_gateway.options_for(
        "claim_extractor",
        temperature=0.0,
    ).model_copy(update={
        # A repair is best-effort: one bounded call, no nested retry budget.
        "max_output_tokens": 4096,
        "max_attempts": 1,
        "allow_schema_repair": False,
        "allow_text_fallback": False,
    })
    # Bypass LLM-call accounting (T41): bounded source-repair call.
    with stage_labeled_scope("claim_extract", labels=[resource.resource_id, "source_repair"]):
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=SOURCE_REPAIR_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ],
            output_schema=ClaimSourceRepairLLMOutput,
            context=LLMCallContext(
                run_id=state.get("run_id", "direct-node-call"),
                step_id=step_context["step_id"],
                node_name="claim_extractor",
                schema_name=ClaimSourceRepairLLMOutput.__name__,
                generation_attempt=state.get("generation_attempt", 1),
                workflow_deadline_at=resource_deadline,
            ),
            options=options,
        )
    allowed = set(failed_indexes)
    return {
        item.claim_index: item.source_text
        for item in result.output.claims
        if item.claim_index in allowed
    }


def _with_resource_context(error, resource_id: str):
    detail = error.safe_detail or error.message
    return error.model_copy(update={
        "safe_detail": f"resource_id={resource_id}; {detail}"[:512],
    })


def _compact_error_summary(errors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "UNKNOWN")
        detail = str(item.get("safe_detail") or item.get("message") or "")
        parts.append(f"{code}({detail[:180]})")
    return "; ".join(parts)[:1000]


def _resource_deadline(
    workflow_deadline_at: Any,
    *,
    resources_left: int,
    now: datetime | None = None,
) -> Any:
    """Split the remaining run budget across the resources still to audit.

    Extraction and judgement each call the provider once per resource under a
    single workflow deadline.  Handing every resource the whole remaining
    budget let the first slow resource consume the time the later ones needed,
    which ends the run in manual review even though nothing was wrong with it.
    A fair share keeps one resource from starving its siblings and never
    extends the original deadline.
    """

    if not isinstance(workflow_deadline_at, datetime):
        return workflow_deadline_at
    deadline = workflow_deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    remaining = (deadline - current).total_seconds()
    if remaining <= 0:
        return deadline
    share = remaining / max(1, resources_left)
    return min(deadline, current + timedelta(seconds=share))


def claim_eligible_resource_ids(state: AgentState) -> list[str]:
    """Return current text resources that independently cleared ordinary review.

    Claim is a release gate for a resource version, not for a batch aggregate.
    A sibling awaiting revision or human review must neither be audited here nor
    prevent an already approved sibling from clearing its own Claim gate.
    """
    review = state.get("review_result", {})
    review_ids = review.get("review_ids", {})
    per_resource = state.get("resource_review_results", {})
    aggregate = str(review.get("decision") or review.get("status") or "")
    eligible: list[str] = []
    for resource in state.get("generated_resources", []):
        if (
            resource.representation.value != "text"
            or not (review_ids.get(resource.resource_id) or resource.review_id)
        ):
            continue
        result = per_resource.get(resource.resource_id, {})
        decision = str(result.get("decision") or result.get("status") or aggregate)
        if decision == ReviewDecision.APPROVE.value:
            eligible.append(resource.resource_id)
    return eligible


def _failure(
    state: AgentState,
    *,
    node_name: str,
    code: ErrorCode,
    detail: str,
    llm_error: LLMGatewayError | None = None,
    prior_errors: list[dict[str, Any]] | None = None,
    resource_ids: list[str] | None = None,
) -> dict[str, Any]:
    error = llm_error.error if llm_error else make_error_info(
        code,
        source=node_name,
        attempt=state.get("generation_attempt", 1),
        category="claim_audit",
        safe_detail=detail[:256],
    )
    review = dict(state.get("review_result", {}))
    review.update({
        "decision": ReviewDecision.HUMAN_REVIEW.value,
        "status": ReviewDecision.HUMAN_REVIEW.value,
        "passed": False,
        "claim_check_status": ClaimCheckStatus.FAILED.value,
        "claim_metric_status": ClaimMetricStatus.INCOMPLETE.value,
        "claim_hallucination_rate": None,
    })
    step_context = start_step(state)
    trace = build_trace_item(
        state,
        agent_name=node_name,
        action="Claim 级审核",
        status=StepStatus.HUMAN_REVIEW,
        input_summary=f"候选资源数：{len(resource_ids or state.get('claim_eligible_resource_ids', []))}",
        output_summary="Claim 审核失败，转人工复核",
        decision_reason="Claim 或 Evidence 的机器判定结果未通过确定性校验。",
        resource_ids=resource_ids or state.get("claim_eligible_resource_ids", []),
        review_ids=list(review.get("review_ids", {}).values()),
        error=error,
        step_context=step_context,
        llm_metadata=llm_error.trace_metadata() if llm_error else None,
    )
    persisted_errors = list(prior_errors or [])
    serialized_error = error.model_dump(mode="json")
    if serialized_error not in persisted_errors:
        persisted_errors.append(serialized_error)
    trace["error_message"] = _compact_error_summary(persisted_errors) or error.safe_detail or error.message
    return {
        "review_result": review,
        "claim_check_status": ClaimCheckStatus.FAILED.value,
        "current_node": node_name,
        "trace": [trace],
        "errors": persisted_errors,
    }


def _legacy_claim_extract_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
    max_claims_per_resource: int | None = None,
) -> dict[str, Any]:
    # HTML is a presentation derived from the canonical practice-guide text;
    # claim review, like normal review, assesses only canonical text.
    max_claims_per_resource = (
        max_claims_per_resource
        if max_claims_per_resource is not None
        else get_settings().claim_max_claims_per_resource
    )
    eligible_resource_ids = claim_eligible_resource_ids(state)
    all_resources = [
        item for item in state.get("generated_resources", [])
        if item.resource_id in eligible_resource_ids
    ]
    # Assessment answers and evidence are intentionally absent from public
    # Markdown. Their canonical JSON is already checked by the internal
    # resource reviewer, so generic substring-based Claim extraction would
    # audit the wrong (redacted) projection and must be skipped.
    assessment_resource_ids = {
        item.resource_id for item in all_resources
        if item.resource_type == "分阶测试题" and item.assessment_payload is not None
    }
    for resource in all_resources:
        resource_evidence = evidence_for_resource(state, resource)
        validate_payload_evidence(resource, resource_evidence)
    resources = [item for item in all_resources if item.resource_id not in assessment_resource_ids]
    evidence = state.get("retrieved_evidence", [])
    review_ids = {
        **{
            item.resource_id: item.review_id
            for item in state.get("generated_resources", [])
            if item.review_id
        },
        **state.get("review_result", {}).get("review_ids", {}),
    }
    step_context = start_step(state)
    if not all_resources or any(not item.content_text for item in resources):
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="resource content unavailable",
            resource_ids=eligible_resource_ids,
        )
    if not set(eligible_resource_ids) <= set(review_ids):
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="review/resource boundary mismatch",
            resource_ids=eligible_resource_ids,
        )
    claims: list[ClaimRecord] = []
    allowed_evidence = {item.evidence_id for item in evidence}
    allowed_nodes = set(state.get("target_skill_nodes", []))
    failed_resource_ids: list[str] = []
    errors: list[dict[str, Any]] = []
    last_result = None
    used_evidence_ids = set()
    repaired_claim_count = 0
    for index, resource in enumerate(resources):
        evidence = evidence_for_resource(state, resource)
        validate_payload_evidence(resource, evidence)
        allowed_evidence = {item.evidence_id for item in evidence}
        used_evidence_ids.update(allowed_evidence)
        resource_deadline = _resource_deadline(
            state.get("workflow_deadline_at"),
            resources_left=len(resources) - index,
        )
        try:
            payload = {
                "allowed_evidence": [
                    {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
                    for item in evidence
                ],
                "allowed_knowledge_point_ids": state.get("target_skill_nodes", []),
                "resources": [{
                    "resource_id": resource.resource_id,
                    "resource_version": resource.version,
                    "resource_type": resource.resource_type,
                    "content_text": _claim_audit_content(resource),
                }],
            }
            # Bypass LLM-call accounting (T41): legacy per-resource extraction.
            with stage_labeled_scope("claim_extract", labels=[resource.resource_id]):
                result = llm_gateway.invoke_structured(
                    messages=[
                        SystemMessage(content=extractor_prompt(max_claims_per_resource)),
                        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                    ],
                    output_schema=ClaimExtractionLLMOutput,
                    context=LLMCallContext(
                        run_id=state.get("run_id", "direct-node-call"),
                        step_id=step_context["step_id"],
                        node_name="claim_extractor",
                        schema_name=ClaimExtractionLLMOutput.__name__,
                        generation_attempt=state.get("generation_attempt", 1),
                        workflow_deadline_at=resource_deadline,
                    ),
                    options=llm_gateway.options_for("claim_extractor", temperature=0.0),
                )
            batches = result.output.resources
            if len(batches) != 1 or batches[0].resource_id != resource.resource_id:
                raise ValueError("extractor resource boundary mismatch")
            if not batches[0].claims:
                raise ValueError("each non-empty resource requires at least one claim")
            if len(batches[0].claims) > max_claims_per_resource:
                raise ValueError(
                    "claim count exceeds configured per-resource limit "
                    f"({max_claims_per_resource})"
                )
            candidates = list(batches[0].claims)
            audit_content = _claim_audit_content(resource)
            failed_indexes = [
                index for index, candidate in enumerate(candidates)
                if candidate.source_text not in audit_content
            ]
            if failed_indexes:
                # One bounded verbatim repair for rewritten spans.  Whatever
                # still misses the substring gate falls through to the strict
                # validator and fails the resource, never silently dropped.
                repaired = _repair_source_texts(
                    resource=resource,
                    candidates=candidates,
                    failed_indexes=failed_indexes,
                    llm_gateway=llm_gateway,
                    state=state,
                    step_context=step_context,
                    resource_deadline=resource_deadline,
                )
                repaired_claim_count += len(repaired)
                candidates = [
                    candidate.model_copy(update={"source_text": repaired[index]})
                    if index in repaired else candidate
                    for index, candidate in enumerate(candidates)
                ]
            claims.extend(materialize_claims(
                candidates=candidates,
                resource_content=resource.content_text or "",
                resource_id=resource.resource_id,
                resource_version=resource.version,
                review_id=review_ids[resource.resource_id],
                run_id=state.get("run_id", "direct-node-call"),
                allowed_evidence_ids=allowed_evidence,
                allowed_knowledge_point_ids=allowed_nodes,
                extractor_prompt_version=EXTRACTOR_PROMPT_VERSION,
                extractor_model=result.model_name,
            ))
            last_result = result
        except LLMGatewayError as exc:
            failed_resource_ids.append(resource.resource_id)
            errors.append(_with_resource_context(
                exc.error, resource.resource_id,
            ).model_dump(mode="json"))
        except (ValueError, KeyError) as exc:
            failed_resource_ids.append(resource.resource_id)
            errors.append(_with_resource_context(make_error_info(
                ErrorCode.CLAIM_EXTRACTION_INVALID,
                source="claim_extractor",
                attempt=state.get("generation_attempt", 1),
                category="claim_audit",
                safe_detail=str(exc)[:256],
            ), resource.resource_id).model_dump(mode="json"))
    if not claims and not assessment_resource_ids:
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="all resource claim extractions failed",
            prior_errors=errors,
            resource_ids=eligible_resource_ids,
        )
    error_summary = _compact_error_summary(errors)
    trace = build_trace_item(
        state,
        agent_name="claim_extractor",
        action="独立 Claim 抽取",
        status=StepStatus.DEGRADED if failed_resource_ids else StepStatus.SUCCESS,
        input_summary=f"Claim 候选资源数：{len(all_resources)}；冻结证据数：{len(evidence)}",
        output_summary=(f"已抽取 {len(claims)} 条 Claim；"
                        f"结构化测评专用审核 {len(assessment_resource_ids)} 个；失败资源 {len(failed_resource_ids)} 个"
                        + (f"；逐字修复 {repaired_claim_count} 条" if repaired_claim_count else "")
                        + (f"；逐资源错误：{error_summary}" if error_summary else "")),
        decision_reason="结构化测评由内部 JSON 审核；其余资源通过 Claim 白名单校验。",
        evidence_refs=[item.evidence_id for item in state.get("retrieved_evidence", []) if item.evidence_id in used_evidence_ids],
        resource_ids=[item.resource_id for item in all_resources],
        review_ids=list(review_ids.values()),
        step_context=step_context,
        error=(make_error_info(
            ErrorCode.CLAIM_EXTRACTION_INVALID,
            source="claim_extractor",
            attempt=state.get("generation_attempt", 1),
            category="claim_audit",
            safe_detail=error_summary,
        ) if errors else None),
        llm_metadata=last_result.trace_metadata() if last_result else None,
    )
    if error_summary:
        trace["error_message"] = error_summary
    return {
        "extracted_claims": [item.model_dump(mode="json") for item in claims],
        "assessment_claim_skipped_resource_ids": sorted(assessment_resource_ids),
        "claim_eligible_resource_ids": eligible_resource_ids,
        "claim_failed_resource_ids": failed_resource_ids,
        "claim_check_status": ClaimCheckStatus.PENDING.value,
        "current_node": "claim_extractor",
        "trace": [trace],
        "errors": errors,
    }


def claim_extract_node(state: AgentState, *, llm_gateway: LLMGateway,
                       max_claims_per_resource: int | None = None,
                       claim_extraction_repository=None, claim_extraction_counter=None) -> dict[str, Any]:
    from .claim_extraction.budget import validate_entry
    from app.db.audit.base import PersistenceError
    try:
        current = validate_entry(state, claim_extraction_repository)
    except (ValueError, PersistenceError):
        return _failure(state, node_name="claim_extractor", code=ErrorCode.CLAIM_EXTRACTION_INVALID,
                        detail="extraction policy or durable state invalid")
    if current is None:
        return _legacy_claim_extract_node(state, llm_gateway=llm_gateway, max_claims_per_resource=max_claims_per_resource)
    return _neutral_claim_extract_node(state, llm_gateway=llm_gateway, repository=claim_extraction_repository,
                                      counter=claim_extraction_counter)


def _neutral_claim_extract_node(state, *, llm_gateway, repository, counter):
    from .claim_extraction import execute_extraction
    from app.db.audit.base import PersistenceError
    eligible = claim_eligible_resource_ids(state)
    resources = [r for r in state.get("generated_resources", []) if r.resource_id in eligible]
    review_ids = {**{r.resource_id: r.review_id for r in resources if r.review_id},
                  **state.get("review_result", {}).get("review_ids", {})}
    if not resources or not set(eligible) <= set(review_ids):
        return _failure(state, node_name="claim_extractor", code=ErrorCode.CLAIM_EXTRACTION_INVALID,
                        detail="extraction review/resource boundary mismatch", resource_ids=eligible)
    step_context = start_step(state)
    claims, refs, failed, errors, assessments = [], [], [], [], []
    last_result = None
    for index, resource in enumerate(resources):
        evidence = evidence_for_resource(state, resource)
        validate_payload_evidence(resource, evidence)
        if resource.resource_type == "分阶测试题" and resource.assessment_payload is not None:
            assessments.append(resource.resource_id)
            continue
        # Give this resource its fair share of what is left; the extraction
        # budget reads the deadline from the state it receives.
        resource_state = {
            **state,
            "workflow_deadline_at": _resource_deadline(
                state.get("workflow_deadline_at"),
                resources_left=len(resources) - index,
            ),
        }
        try:
            items, reference, observation = execute_extraction(resource_state, resource, review_id=review_ids[resource.resource_id],
                evidence=evidence, llm_gateway=llm_gateway, repository=repository, counter=counter, step_id=step_context["step_id"])
            claims.extend(items)
            refs.append(reference)
            last_result = observation or last_result
        except (ValueError, KeyError, PersistenceError):
            failed.append(resource.resource_id)
            errors.append(_with_resource_context(make_error_info(ErrorCode.CLAIM_EXTRACTION_INVALID,
                source="claim_extractor", attempt=state.get("generation_attempt", 1), category="claim_audit",
                safe_detail="neutral extraction incomplete; private audit retained"), resource.resource_id).model_dump(mode="json"))
    if not claims and not assessments:
        return _failure(state, node_name="claim_extractor", code=ErrorCode.CLAIM_EXTRACTION_INVALID,
                        detail="all resource claim extractions failed", prior_errors=errors, resource_ids=eligible)
    trace = build_trace_item(state, agent_name="claim_extractor", action="独立 Claim 抽取",
        status=StepStatus.DEGRADED if failed else StepStatus.SUCCESS,
        input_summary=f"Claim 候选资源数：{len(resources)}；输入为正文及文内上下文",
        output_summary=f"已抽取 {len(claims)} 条 Claim；结构化测评专用审核 {len(assessments)} 个；失败资源 {len(failed)} 个",
        decision_reason="正文范围处理及候选校验完成；处理清单不代表全部事实召回。",
        evidence_refs=[], resource_ids=eligible, review_ids=list(review_ids.values()), step_context=step_context,
        llm_metadata=last_result.trace_metadata() if last_result else None)
    return dict(extracted_claims=[c.model_dump(mode="json") for c in claims], claim_extraction_refs=refs,
        assessment_claim_skipped_resource_ids=sorted(assessments), claim_eligible_resource_ids=eligible,
        claim_failed_resource_ids=failed, claim_check_status=ClaimCheckStatus.PENDING.value,
        current_node="claim_extractor", trace=[trace], errors=errors)


def claim_judge_node(state: AgentState, *, llm_gateway: LLMGateway,
                     claim_extraction_repository=None, claim_extraction_counter=None) -> dict[str, Any]:
    from .claim_extraction.budget import validate_entry, GuardedJudgeGateway
    from app.db.audit.base import PersistenceError
    try:
        current = validate_entry(state, claim_extraction_repository)
    except (ValueError, PersistenceError):
        return _failure(state, node_name="claim_judge", code=ErrorCode.CLAIM_JUDGEMENT_INVALID,
                        detail="extraction policy or durable state invalid")
    if current is not None:
        llm_gateway = GuardedJudgeGateway(state, llm_gateway, claim_extraction_repository, claim_extraction_counter)
    return _judge_claims_node(state, llm_gateway=llm_gateway)


def _judge_claims_node(state: AgentState, *, llm_gateway: LLMGateway) -> dict[str, Any]:
    step_context = start_step(state)
    try:
        claims = [ClaimRecord.model_validate(item) for item in state.get("extracted_claims", [])]
    except ValueError as exc:
        return _failure(state, node_name="claim_judge",
                        code=ErrorCode.CLAIM_JUDGEMENT_INVALID, detail=str(exc))
    assessment_resource_ids = set(state.get("assessment_claim_skipped_resource_ids", []))
    if not claims and not assessment_resource_ids:
        return _failure(state, node_name="claim_judge",
                        code=ErrorCode.CLAIM_JUDGEMENT_INVALID, detail="no validated claims",
                        resource_ids=state.get("claim_eligible_resource_ids", []))
    for resource in state.get("generated_resources", []):
        if resource.resource_id in assessment_resource_ids:
            validate_payload_evidence(resource, evidence_for_resource(state, resource))
    evidence = state.get("retrieved_evidence", [])
    claims_by_resource: dict[str, list[ClaimRecord]] = defaultdict(list)
    for item in claims:
        claims_by_resource[item.resource_id].append(item)
    judgements = []
    failed_resource_ids = set(state.get("claim_failed_resource_ids", []))
    errors: list[dict[str, Any]] = []
    last_result = None
    used_evidence_ids = set()
    resource_by_id = {item.resource_id: item for item in state.get("generated_resources", [])}
    judge_items = list(claims_by_resource.items())
    for index, (resource_id, resource_claims) in enumerate(judge_items):
        if resource_id not in resource_by_id:
            raise contract_error()
        evidence = evidence_for_resource(state, resource_by_id[resource_id])
        used_evidence_ids.update(item.evidence_id for item in evidence)
        judge_deadline = _resource_deadline(
            state.get("workflow_deadline_at"),
            resources_left=len(judge_items) - index,
        )
        try:
            payload = {
                "allowed_evidence": [
                    {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
                    for item in evidence
                ],
                "claims": [
                    {
                        "claim_id": item.claim_id,
                        "claim_type": item.claim_type.value,
                        "claim_text": item.claim_text,
                        "resource_id": item.resource_id,
                        "resource_version": item.resource_version,
                    }
                    for item in resource_claims
                ],
            }
            # Bypass LLM-call accounting (T41): per-resource Judge call.
            with stage_labeled_scope("claim_judge", labels=[resource_id]):
                result = llm_gateway.invoke_structured(
                    messages=[SystemMessage(content=JUDGE_PROMPT), HumanMessage(content=json.dumps(payload, ensure_ascii=False))],
                    output_schema=ClaimJudgementLLMOutput,
                    context=LLMCallContext(
                        run_id=state.get("run_id", "direct-node-call"),
                        step_id=step_context["step_id"],
                        node_name="claim_judge",
                        schema_name=ClaimJudgementLLMOutput.__name__,
                        generation_attempt=state.get("generation_attempt", 1),
                        workflow_deadline_at=judge_deadline,
                    ),
                    options=llm_gateway.options_for("claim_judge", temperature=0.0),
                )
            normalized_candidates = _normalize_judgement_candidates(
                resource_claims,
                result.output.judgements,
            )
            judgements.extend(materialize_judgements(
                claims=resource_claims,
                candidates=normalized_candidates,
                allowed_evidence_ids={item.evidence_id for item in evidence},
                judge_prompt_version=JUDGE_PROMPT_VERSION,
                judge_model=result.model_name,
            ))
            last_result = result
        except LLMGatewayError as exc:
            failed_resource_ids.add(resource_id)
            errors.append(_with_resource_context(
                exc.error, resource_id,
            ).model_dump(mode="json"))
        except (ValueError, KeyError) as exc:
            failed_resource_ids.add(resource_id)
            errors.append(_with_resource_context(make_error_info(
                ErrorCode.CLAIM_JUDGEMENT_INVALID,
                source="claim_judge",
                attempt=state.get("generation_attempt", 1),
                category="claim_audit",
                safe_detail=str(exc)[:256],
            ), resource_id).model_dump(mode="json"))
    judgements_by_resource: dict[str, list] = defaultdict(list)
    for item in judgements:
        judgements_by_resource[item.resource_id].append(item)
    metrics = {
        resource_id: compute_claim_metric(items, judgements_by_resource[resource_id])
        for resource_id, items in claims_by_resource.items()
    }
    for resource_id in assessment_resource_ids:
        metrics[resource_id] = {
            "metric_status": ClaimMetricStatus.NOT_APPLICABLE.value,
            "claim_hallucination_rate": None,
            "claim_total": 0,
            "factual_claim_total": 0,
            "supported_claim_total": 0,
            "contradicted_claim_total": 0,
            "not_in_evidence_claim_total": 0,
            "non_factual_claim_total": 0,
            "incomplete_claim_total": 0,
            "audit_mode": "structured_assessment_internal",
        }
    for resource_id in failed_resource_ids:
        if resource_id not in metrics:
            metrics[resource_id] = {
                "metric_status": ClaimMetricStatus.INCOMPLETE.value,
                "claim_hallucination_rate": None,
                "claim_total": 0,
                "factual_claim_total": 0,
                "supported_claim_total": 0,
                "contradicted_claim_total": 0,
                "not_in_evidence_claim_total": 0,
                "non_factual_claim_total": 0,
                "incomplete_claim_total": 1,
            }
    error_summary = _compact_error_summary(errors)
    trace = build_trace_item(
        state,
        agent_name="claim_judge",
        action="冻结证据 Claim 判定",
        status=StepStatus.DEGRADED if failed_resource_ids else StepStatus.SUCCESS,
        input_summary=f"Claim 数：{len(claims)}；结构化测评专用审核 {len(assessment_resource_ids)} 个；冻结证据数：{len(evidence)}",
        output_summary=(f"完成 {len(judgements)} 条独立判定；"
                        f"失败资源 {len(failed_resource_ids)} 个"
                        + (f"；逐资源错误：{error_summary}" if error_summary else "")),
        decision_reason="成功资源完成冻结证据判定；失败资源被隔离并转人工复核。",
        evidence_refs=[item.evidence_id for item in state.get("retrieved_evidence", []) if item.evidence_id in used_evidence_ids],
        resource_ids=sorted(claims_by_resource),
        review_ids=sorted({item.review_id for item in claims}),
        step_context=step_context,
        error=(make_error_info(
            ErrorCode.CLAIM_JUDGEMENT_INVALID,
            source="claim_judge",
            attempt=state.get("generation_attempt", 1),
            category="claim_audit",
            safe_detail=error_summary,
        ) if errors else None),
        llm_metadata=last_result.trace_metadata() if last_result else None,
    )
    if error_summary:
        trace["error_message"] = error_summary
    return {
        "claim_judgements": [item.model_dump(mode="json") for item in judgements],
        "claim_metrics": {
            key: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value)
            for key, value in metrics.items()
        },
        "claim_failed_resource_ids": sorted(failed_resource_ids),
        "claim_check_status": ClaimCheckStatus.COMPLETED.value,
        "current_node": "claim_judge",
        "trace": [trace],
        "errors": errors,
    }


def claim_decide_node(state: AgentState) -> dict[str, Any]:
    step_context = start_step(state)
    review = dict(state.get("review_result", {}))
    ordinary_decision = ReviewDecision(
        review.get("decision", review.get("status", ReviewDecision.HUMAN_REVIEW.value))
    )
    failed_resource_ids = set(state.get("claim_failed_resource_ids", []))
    if state.get("claim_check_status") != ClaimCheckStatus.COMPLETED.value:
        review.update({
            "decision": ReviewDecision.HUMAN_REVIEW.value,
            "status": ReviewDecision.HUMAN_REVIEW.value,
            "passed": False,
            "claim_check_status": ClaimCheckStatus.FAILED.value,
            "claim_hallucination_rate": None,
            "claim_metric_status": ClaimMetricStatus.INCOMPLETE.value,
        })
        decision = ReviewDecision.HUMAN_REVIEW
        bad = []
    else:
        claims = {item["claim_id"]: item for item in state.get("extracted_claims", [])}
        bad = [
            item for item in state.get("claim_judgements", [])
            if item.get("verdict") in {ClaimVerdict.CONTRADICTED.value, ClaimVerdict.NOT_IN_EVIDENCE.value}
        ]
        metrics = state.get("claim_metrics", {})
        incomplete = bool(failed_resource_ids) or any(
            item.get("metric_status") == ClaimMetricStatus.INCOMPLETE.value
            for item in metrics.values()
        )
        total_factual = sum(item.get("factual_claim_total", 0) for item in metrics.values())
        total_bad = sum(
            item.get("contradicted_claim_total", 0) + item.get("not_in_evidence_claim_total", 0)
            for item in metrics.values()
        )
        micro_rate = (total_bad / total_factual) if total_factual else 0.0
        metric_status = (
            ClaimMetricStatus.INCOMPLETE if incomplete else
            ClaimMetricStatus.NOT_APPLICABLE if not total_factual else
            ClaimMetricStatus.COMPLETE
        )
        review.update({
            "claim_check_status": ClaimCheckStatus.COMPLETED.value,
            "claim_total": len(claims),
            "claim_metric_status": metric_status.value,
            "claim_hallucination_rate": None if incomplete else micro_rate,
            "legacy_reviewer_score": review.get("hallucination_score"),
        })
        resources = {item.resource_id: item for item in state.get("generated_resources", [])}
        existing_issue_resources = {
            str(item.get("resource_id"))
            for item in review.get("issues", [])
            if isinstance(item, dict) and item.get("resource_id")
        }
        for resource_id in sorted(failed_resource_ids - existing_issue_resources):
            resource = resources.get(resource_id)
            if resource is None:
                continue
            review.setdefault("issues", []).append({
                "issue_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{state.get('run_id')}:claim-audit-failed:{resource_id}",
                )),
                "code": "evidence_gap",
                "severity": "high",
                "resource_type": resource.resource_type,
                "resource_id": resource.resource_id,
                "resource_version": resource.version,
                "claim_ids": [],
                "knowledge_point": None,
                "description": "该资源的 Claim 审核未完成，需要人工复核。",
            })
        if incomplete:
            decision = ReviewDecision.HUMAN_REVIEW
        elif bad:
            decision = ReviewDecision.REVISE
            for index, judgement in enumerate(bad, start=1):
                claim = claims[judgement["claim_id"]]
                resource = resources[claim["resource_id"]]
                code = "factual_risk" if judgement["verdict"] == ClaimVerdict.CONTRADICTED.value else "evidence_gap"
                review.setdefault("issues", []).append({
                    "issue_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state.get('run_id')}:claim-issue:{judgement['claim_id']}")),
                    "code": code,
                    "severity": "high",
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "resource_version": resource.version,
                    "claim_ids": [judgement["claim_id"]],
                    "knowledge_point": claim.get("knowledge_point_id"),
                    "description": judgement["reason"],
                })
                review.setdefault("revision_instructions", []).append({
                    "instruction_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state.get('run_id')}:claim-instruction:{judgement['claim_id']}")),
                    "issue_codes": [code],
                    "target_resource_type": resource.resource_type,
                    "target_claim_ids": [judgement["claim_id"]],
                    "action": "依据冻结 Evidence 修正或删除该事实陈述，并重新进行 Claim 抽取与判定。",
                    "priority": index,
                })
        else:
            # Claim approval only clears the Claim gate for eligible resources.
            # It must not overwrite a sibling's ordinary-review hold.
            decision = ordinary_decision
        review.update({
            "decision": decision.value,
            "status": decision.value,
            "passed": decision == ReviewDecision.APPROVE,
            "claim_check_status": (
                ClaimCheckStatus.FAILED.value
                if failed_resource_ids
                else ClaimCheckStatus.COMPLETED.value
            ),
        })
    trace = build_trace_item(
        state,
        agent_name="claim_supervisor",
        action="Claim 确定性决策",
        status=StepStatus.HUMAN_REVIEW if decision == ReviewDecision.HUMAN_REVIEW else StepStatus.SUCCESS,
        input_summary=f"Claim 数：{len(state.get('extracted_claims', []))}",
        output_summary=f"决策：{decision.value}；问题 Claim：{len(bad)}",
        decision_reason="自动发布要求所有事实 Claim 完整判定且不存在 contradicted/not_in_evidence。",
        resource_ids=[item.resource_id for item in state.get("generated_resources", [])],
        review_ids=list(review.get("review_ids", {}).values()),
        step_context=step_context,
    )
    return {
        "review_result": review,
        "claim_check_status": review.get(
            "claim_check_status", state.get("claim_check_status")
        ),
        "current_node": "claim_supervisor",
        "trace": [trace],
        "errors": [],
    }
