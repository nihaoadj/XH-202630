"""Review orchestration: selection, deterministic gates and state aggregation."""

import uuid
from datetime import datetime, timezone

from app.agents.resource_workflows.learning_documents.state import AgentState
from app.agents.shared.evidence_scope import evidence_for_resource, validate_payload_evidence
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.core.retrieval.evidence import source_refs_are_scoped
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import ReviewerInput, build_trace_item, make_error_info, start_step
from app.models.shared.llm import LLMCallContext
from app.models.shared.workflow import ResourceStatus, ReviewDecision, StepStatus
from app.models.reviews.review_audit import (ReviewAuditRecordV2, ReviewAuditRecordV3, ReviewAuditRecordV4,
    ReviewPolicySnapshotV1, ReviewResourceAuditV1, review_audit_envelope)
from app.agents.shared.policies import decide_review, locked_human_review_resource_ids
from app.agents.shared.validators import revision_instructions_are_valid
from app.agents.resource_workflows.learning_documents.generator_agent import progress_summary
from app.agents.resource_workflows.learning_documents.reviewing import (
    ReviewAuditInput, ReviewCallCollector, ReviewInputBudgetError, build_review_audit,
    build_review_prompt, build_review_request, check_resource_structure, invoke_review,
    normalize_review_result, resolve_review_profile, select_specialties,
)
from app.agents.resource_workflows.learning_documents.reviewing.checks import node_tier_difficulty_review
from app.agents.resource_workflows.learning_documents.reviewing.results import decorate_review_items, normalize_node_tier_review
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import issue_locations
from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import assert_review_entry_allowed
from app.agents.resource_workflows.learning_documents.specialized_reviews.assessment_scope import (
    review_assessment_scope, review_assessment_combined,
)


def _fail_closed_review_error(error):
    return error


def review_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
    review_repository=None,
) -> dict:
    """Review canonical text resources independently and aggregate deterministically."""
    node_input = ReviewerInput.model_validate(state)
    policy = ReviewPolicySnapshotV1.model_validate(node_input.review_policy or {})
    collector = ReviewCallCollector()
    resource_audits = []
    lecture_ledgers = dict(state.get("lecture_ledgers") or {})
    current_lecture_ledgers = []
    lecture_stop_reasons = dict(state.get("lecture_stop_reasons") or {})
    lecture_repairs = []
    lecture_contract_version = state.get("lecture_review_contract_version")
    resource_ledgers = dict(state.get("resource_ledgers") or {})
    current_resource_ledgers = []
    resource_stop_reasons = dict(state.get("resource_stop_reasons") or {})
    resource_repairs = []
    resource_contract_version = state.get("resource_review_contract_version")
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
        None,
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
    results: dict[str, dict] = {}
    errors = []
    trace_error = None
    last_llm_result = None

    if not resources:
        try:
            profile = resolve_review_profile(resource_type="__empty_resource__", phase="empty_resource_compat_v1", policy=policy)
            request = build_review_request(profile=profile, prompt_bundle=build_review_prompt(profile=profile),
                                            audit_input=ReviewAuditInput())
            last_llm_result = invoke_review(
                request=request, llm_gateway=llm_gateway, collector=collector,
                call_context=LLMCallContext(run_id=node_input.run_id, step_id=step_context["step_id"],
                    node_name="reviewer", schema_name=profile.output_schema.__name__,
                    generation_attempt=node_input.generation_attempt,
                    workflow_deadline_at=state.get("workflow_deadline_at")))
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

    used_evidence_ids = set()
    for resource in resources:
        evidence = evidence_for_resource(state, resource)
        validate_payload_evidence(resource, evidence)
        used_evidence_ids.update(item.evidence_id for item in evidence)
        invalid_source_refs = not source_refs_are_scoped(resource.source_refs, evidence)
        error = None
        specialized_review = None
        structure_status = "not_checked"
        error_category = None
        calls_before = len(collector.calls)
        tier_contract = node_input.constraints.get("target_tier")
        expected_difficulty = node_input.difficulty_preference
        node_tier_review = node_tier_difficulty_review(resource, state)
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
        elif node_tier_review is not None:
            raw = node_tier_review
        elif tier_contract is not None and resource.difficulty != expected_difficulty:
            raw = {
                "decision": "revise", "hallucination_score": 0.0,
                "issues": [{"code": "other", "severity": "high", "resource_type": resource.resource_type,
                            "resource_id": resource.resource_id, "knowledge_point": None,
                            "description": "资源难度与冻结的能力节点阶级不一致。"}],
                "difficulty_match": False, "coverage_rate": 1.0,
                "suggestion": "按冻结阶级重建资源规格。",
                "revision_instructions": [{"target_resource_type": resource.resource_type,
                                           "instruction": "将资源难度调整为冻结目标阶级。"}],
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
        elif state.get("resource_review_policy"):
            structure_status = "passed"
            try:
                call_context = LLMCallContext(
                    run_id=node_input.run_id, step_id=step_context["step_id"], node_name="reviewer",
                    schema_name=("ResourceReviewRecheckV1" if resource.resource_spec_id in resource_ledgers
                                 else "ResourceReviewInitialV1"),
                    generation_attempt=node_input.generation_attempt,
                    workflow_deadline_at=state.get("workflow_deadline_at"))

                def resource_guard(*, step_id, generation_attempt):
                    assert_review_entry_allowed(
                        repository=review_repository, run_id=node_input.run_id,
                        step_id=step_id, generation_attempt=generation_attempt)

                from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import (
                    review_resource_v1,
                )
                outcome = review_resource_v1(
                    state=state, resource=resource, evidence=evidence,
                    step_id=step_context["step_id"], context=call_context,
                    gateway=llm_gateway, collector=collector,
                    review_id=review_ids[resource.resource_id], step_guard=resource_guard)
                raw, last_llm_result = outcome.raw, outcome.last_llm_result
                stop_reason = outcome.stop_reason
                if outcome.repair is not None:
                    resource_repairs.append(outcome.repair)
                if outcome.ledger is not None:
                    resource_ledgers[resource.resource_spec_id] = outcome.ledger.model_dump(mode="json")
                    current_resource_ledgers.append(outcome.ledger)
                if stop_reason:
                    resource_stop_reasons[resource.resource_spec_id] = stop_reason
                    if stop_reason == "program_gate_failed":
                        structure_status = "failed"
            except (LLMGatewayError, ValueError) as exc:
                if isinstance(exc, LLMGatewayError):
                    error = _fail_closed_review_error(exc.error)
                    last_llm_result = exc
                    error_category = exc.error.category
                else:
                    error_category = "input_budget" if isinstance(exc, ReviewInputBudgetError) else "review_validation"
                    error = _fail_closed_review_error(make_error_info(
                        ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, source="reviewer",
                        attempt=node_input.generation_attempt, category=error_category))
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "审核能力不可用或结果无效，无法安全完成自动审核。"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "保持未发布。", "revision_instructions": []}
        elif structured_review := check_resource_structure(resource=resource, context=state):
            raw = structured_review
        else:
            structure_status = "passed"
            try:
                if resource.resource_type == "分阶测试题" and resource.assessment_payload is not None:
                    combined = policy.assessment_strategy == "combined_v2"
                    assessment_review = review_assessment_combined if combined else review_assessment_scope
                    specialized_review = assessment_review(
                        resource=resource, evidence=evidence,
                        target_skill_nodes=list(state.get("target_skill_nodes", [])),
                        llm_gateway=llm_gateway, collector=collector,
                        review_id=review_ids[resource.resource_id], policy=policy,
                        context=LLMCallContext(
                            run_id=node_input.run_id, step_id=step_context["step_id"],
                            node_name="reviewer" if combined else "assessment_scope_reviewer",
                            schema_name="AssessmentCombinedReviewV2" if combined else "AssessmentScopeReviewV1",
                            generation_attempt=node_input.generation_attempt,
                            workflow_deadline_at=state.get("workflow_deadline_at")))
                    if combined or not specialized_review.passed:
                        raw = specialized_review.summary
                        if combined:
                            last_llm_result = specialized_review.llm_result
                    else:
                        raw = None
                else:
                    raw = None
                if raw is None and resource.resource_type == "讲义" and state.get("lecture_review_policy"):
                    call_context = LLMCallContext(
                        run_id=node_input.run_id, step_id=step_context["step_id"], node_name="reviewer",
                        schema_name=("LectureRecheckReviewV2" if lecture_contract_version == "2.0"
                                     else "LectureRecheckReviewV1")
                        if resource.resource_spec_id in lecture_ledgers else
                        ("LectureInitialReviewV2" if lecture_contract_version == "2.0"
                         else "LectureInitialReviewV1"),
                        generation_attempt=node_input.generation_attempt,
                        workflow_deadline_at=state.get("workflow_deadline_at"))
                    if lecture_contract_version == "2.0":
                        from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine_v2 import review_lecture_v2

                        def guard(*, step_id, generation_attempt):
                            # Fail closed: a V2 sendable entry must have a durable
                            # repository and a fenced owner/lease.  Passing None here
                            # raises inside assert_review_entry_allowed, never silently
                            # skipping the guard.
                            assert_review_entry_allowed(
                                repository=review_repository, run_id=node_input.run_id,
                                step_id=step_id, generation_attempt=generation_attempt)
                        outcome = review_lecture_v2(
                            state=state, resource=resource, evidence=evidence,
                            step_id=step_context["step_id"], context=call_context,
                            gateway=llm_gateway, collector=collector,
                            review_id=review_ids[resource.resource_id], step_guard=guard)
                        raw, last_llm_result = outcome.raw, outcome.last_llm_result
                        stop_reason = outcome.stop_reason
                        if outcome.repair is not None:
                            lecture_repairs.append(outcome.repair)
                        if outcome.ledger is not None:
                            lecture_ledgers[resource.resource_spec_id] = outcome.ledger.model_dump(mode="json")
                            current_lecture_ledgers.append(outcome.ledger)
                    else:
                        from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine import review_lecture
                        raw, ledger, last_llm_result, stop_reason = review_lecture(
                            state=state, resource=resource, evidence=evidence, step_id=step_context["step_id"],
                            context=call_context, gateway=llm_gateway, collector=collector,
                            review_id=review_ids[resource.resource_id])
                        lecture_ledgers[resource.resource_spec_id] = ledger.model_dump(mode="json")
                        current_lecture_ledgers.append(ledger)
                    if stop_reason:
                        lecture_stop_reasons[resource.resource_spec_id] = stop_reason
                if raw is None:
                    phase = ("practice_semantic_v2" if resource.resource_type == "实操指南" else
                             "assessment_package_v1" if resource.resource_type == "分阶测试题" else "content_v2")
                    profile = resolve_review_profile(resource_type=resource.resource_type, phase=phase, policy=policy)
                    bundle = build_review_prompt(profile=profile, enabled_specialties=select_specialties(profile=profile, resource=resource))
                    request = build_review_request(profile=profile, prompt_bundle=bundle, audit_input=ReviewAuditInput(
                        resource=resource, evidence=tuple(evidence), difficulty=node_input.difficulty_preference,
                        constraints=node_input.constraints, policy=policy))
                    last_llm_result = invoke_review(request=request, llm_gateway=llm_gateway, collector=collector,
                        review_id=review_ids[resource.resource_id],
                        call_context=LLMCallContext(run_id=node_input.run_id, step_id=step_context["step_id"],
                            node_name="reviewer", schema_name=profile.output_schema.__name__,
                            generation_attempt=node_input.generation_attempt,
                            workflow_deadline_at=state.get("workflow_deadline_at")))
                    try:
                        raw = normalize_review_result(output=last_llm_result.output, resource_context=resource)
                    except ValueError:
                        collector.invalid_result(call_id=last_llm_result.call_id)
                        raise
            except (LLMGatewayError, ValueError) as exc:
                if isinstance(exc, LLMGatewayError):
                    error = _fail_closed_review_error(exc.error)
                    last_llm_result = exc
                    error_category = exc.error.category
                else:
                    error_category = "input_budget" if isinstance(exc, ReviewInputBudgetError) else "review_validation"
                    error_source = "reviewer"
                    if (resource.resource_type == "分阶测试题" and resource.assessment_payload is not None
                            and policy.assessment_strategy == "two_stage_v1"):
                        error_category, error_source = "assessment_scope", "assessment_scope_reviewer"
                    error = _fail_closed_review_error(make_error_info(
                        ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, source=error_source,
                        attempt=node_input.generation_attempt, category=error_category))
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "审核能力不可用或结果无效，无法安全完成自动审核。"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "保持未发布。", "revision_instructions": []}
        if (state.get("lecture_review_policy") and resource.resource_type == "讲义"
                and not any(l.binding.resource_id == resource.resource_id for l in current_lecture_ledgers)
                and raw.get("decision") == "revise"):
            raw = {**raw, "decision": "human_review", "revision_instructions": []}
            lecture_stop_reasons[resource.resource_spec_id] = "program_gate_failed"
        raw = normalize_node_tier_review(raw, resource, state)
        decorated = decorate_review_items(raw, run_id=f"{node_input.run_id}:{resource.resource_id}",
                                           generation_attempt=node_input.generation_attempt)
        if specialized_review is not None:
            decorated["specialized_reviews"] = {
                "assessment_combined" if policy.assessment_strategy == "combined_v2" else "assessment_scope": {
                    "passed": specialized_review.passed, "findings": specialized_review.findings,
                }
            }
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
        calls = collector.calls[calls_before:]
        resource_audits.append(ReviewResourceAuditV1(
            resource_id=resource.resource_id, review_id=review_ids[resource.resource_id],
            resource_spec_id=resource.resource_spec_id, resource_type=resource.resource_type,
            structure_status=structure_status if structure_status == "passed" or resource.resource_id in locked_resource_ids else "failed",
            semantic_status=("unavailable" if error and structure_status == "passed" else
                             "passed" if structure_status == "passed" and decision == ReviewDecision.APPROVE else
                             "failed" if structure_status == "passed" else "not_run"),
            decision=decision.value, profiles=[c.phase for c in calls],
            prompt_fingerprints=[c.prompt_fingerprint for c in calls],
            findings=specialized_review.findings if specialized_review is not None else [],
            issue_locations=issue_locations(review=decorated, resource=resource),
            error_category=error_category,
        ))
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
            and not (state.get("lecture_review_policy") and resource.resource_type == "讲义")
            and not state.get("resource_review_policy")
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
        evidence_refs=[item.evidence_id for item in node_input.retrieved_evidence if item.evidence_id in used_evidence_ids],
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review_ids.values()),
        error=trace_error,
        attempt=node_input.generation_attempt,
        step_context=step_context,
        llm_metadata=last_llm_result.trace_metadata() if last_llm_result else None,
    )

    audit = build_review_audit(collector=collector, run_id=node_input.run_id, step_id=step_context["step_id"],
        generation_attempt=node_input.generation_attempt, revision_count=node_input.revision_count,
        policy=policy, decision=aggregate_decision.value, resources=resource_audits)
    if state.get("lecture_review_policy") and lecture_contract_version == "2.0":
        audit = ReviewAuditRecordV3.model_validate({**audit.model_dump(mode="json"), "schema_version": "3.0",
            "lecture_review_policy": state["lecture_review_policy"],
            "lecture_review_policy_hash": state["lecture_review_policy_hash"],
            "lecture_ledgers": [ledger.model_dump(mode="json") for ledger in current_lecture_ledgers],
            "repairs": [repair.as_dict() | {"review_id": review_ids[repair.resource_id]}
                        for repair in lecture_repairs]})
    elif state.get("lecture_review_policy"):
        audit = ReviewAuditRecordV2.model_validate({**audit.model_dump(mode="json"), "schema_version": "2.0",
            "lecture_review_policy": state["lecture_review_policy"],
            "lecture_review_policy_hash": state["lecture_review_policy_hash"],
            "lecture_ledgers": [ledger.model_dump(mode="json") for ledger in current_lecture_ledgers]})
    elif state.get("resource_review_policy"):
        audit = ReviewAuditRecordV4.model_validate({**audit.model_dump(mode="json"), "schema_version": "4.0",
            "resource_review_policy": state["resource_review_policy"],
            "resource_review_policy_hash": state["resource_review_policy_hash"],
            "resource_ledgers": [ledger.model_dump(mode="json") for ledger in current_resource_ledgers],
            "repairs": [repair.as_dict() | {"review_id": review_ids[repair.resource_id]}
                        for repair in resource_repairs]})
    envelope = review_audit_envelope(audit, run_id=node_input.run_id, step_id=step_context["step_id"])
    audit_ref = {"step_id": step_context["step_id"], "audit_hash": envelope["audit_hash"],
                 "review_ids": [item.review_id for item in resource_audits]}
    if state.get("lecture_review_policy"):
        audit_ref.update({"schema_version": "3.0" if lecture_contract_version == "2.0" else "2.0", "lecture_resources": [
            {"resource_id": l.binding.resource_id, "resource_spec_id": l.binding.resource_spec_id,
             "version": l.binding.version, "content_hash": l.binding.content_hash,
             "lineage_id": l.binding.lineage_id} for l in current_lecture_ledgers]})
    elif state.get("resource_review_policy"):
        audit_ref.update({"schema_version": "4.0", "resource_ledgers": [
            {"resource_id": l.binding.resource_id, "resource_spec_id": l.binding.resource_spec_id,
             "version": l.binding.version, "artifact_exact_hash": l.binding.artifact_exact_hash,
             "lineage_id": l.binding.lineage_id} for l in current_resource_ledgers]})
    return {
        **({"lecture_ledgers": lecture_ledgers, "lecture_stop_reasons": lecture_stop_reasons} if state.get("lecture_review_policy") else {}),
        **({"resource_ledgers": resource_ledgers, "resource_stop_reasons": resource_stop_reasons} if state.get("resource_review_policy") else {}),
        "review_audit": audit.model_dump(mode="json"),
        "review_audit_refs": [*state.get("review_audit_refs", []), audit_ref],
        "review_result": review,
        # A targeted revision reviews only the newly generated resource types.
        # Preserve decisions for untouched siblings so the final aggregation
        # cannot turn a previously approved lecture into human review merely
        # because another resource still needs revision.
        "resource_review_results": {
            **state.get("resource_review_results", {}),
            **results,
        },
        "generated_resources": reviewed_resources,
        "resource_executions": executions,
        "resource_progress_summary": progress_summary(executions),
        "current_node": "reviewer",
        "trace": [trace_item],
        "errors": errors,
    }
