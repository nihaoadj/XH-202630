"""One generic resource review round: gate -> semantic call -> one ledger commit.

Order of operations is fixed and shared across all six text resources:

    freeze policy/spec/targets/evidence -> build material + binding
      -> run the deterministic program gate
        -> gate fails: append a program-gate observation (zero model calls)
        -> gate passes: one gateway call (frozen M) -> full validation
           -> one model-observation commit -> derived decision

A whitelisted self-contradiction may consume the remaining physical attempt as
a single bounded correction; nothing else is retried here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.gateway import LLMGatewayError
from app.models.reviews.evidence_context import build_carry_over, context_fields
from app.models.reviews.resource_review import (
    ResourceGateKeyV1,
    ResourceIssueHistoryV1,
    ResourceIssueV1,
    ResourceLedgerV1,
    ResourceLocationV1,
    ResourceProgramGateResultV1,
    ResourceReviewBindingV1,
    ResourceReviewOutputV1,
    program_issue_id,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash, validate_execution_identity

from .adapters.base import ResourceMaterial, text_hash
from .decisions import project_public_summary, public_code
from .ledger import (
    append_model_observation_v1,
    append_program_gate_observation_v1,
)
from .persistence import verify_binding_hashes
from .prompts import CORRECTION_RULES
from .registry import adapter_for, output_schema, profile_fragments
from .validation import ValidationError

from app.models.shared.persistence import canonical_hash
from ..prompts.builder import build_review_prompt
from ..types import ReviewProfile, ReviewRequest
from ..payloads import estimate_review_input
from ..executor import ReviewInputBudgetError, invoke_review
from ..lecture_correction import CorrectionPlan, CorrectionRecord, correction_fits
from ..checks import check_resource_structure


STRUCTURE_GATE_RULE = "resource_structure_v1"
PROJECTION_GATE_RULE = "resource_projection_v1"
GATE_RULE_VERSION = "resource-gate-v1"


@dataclass(frozen=True)
class ResourceReviewOutcome:
    raw: dict
    ledger: ResourceLedgerV1 | None
    last_llm_result: object
    stop_reason: str | None
    repair: CorrectionRecord | None = None


def _validate_first_attempts(*, result, policy: ResourceReviewPolicyV1) -> int:
    detail = list(result.attempts)
    if not detail:
        raise ValidationError("ATTEMPT_DETAIL_MISSING", "attempts",
                              "attempt detail list is empty; cannot verify how many requests were sent")
    if len(detail) != result.attempt_count:
        raise ValidationError("ATTEMPT_COUNT_MISMATCH", "attempts",
                              f"detail count {len(detail)} != attempt_count {result.attempt_count}")
    if result.attempt_count > policy.max_physical_attempts:
        raise ValidationError("ATTEMPT_CAP_EXCEEDED", "attempts",
                              f"{result.attempt_count} physical attempts exceed frozen M")
    ordinals = [item.attempt for item in detail]
    if sorted(ordinals) != list(range(1, result.attempt_count + 1)):
        raise ValidationError("ATTEMPT_ORDINAL_INVALID", "attempts",
                              "attempt ordinals are not the contiguous 1..N sequence")
    return len(detail)


def _freeze_inputs(*, state, resource, evidence):
    policy = ResourceReviewPolicyV1.model_validate(state["resource_review_policy"])
    if policy_hash(policy.model_dump(mode="json")) != state.get("resource_review_policy_hash"):
        raise ValueError("resource review policy hash mismatch")
    spec_id = resource.resource_spec_id
    if not spec_id or not resource.resource_family_id:
        raise ValueError("resource identity missing")
    specs = [spec for spec in state.get("resource_specs", [])
             if (spec.get("resource_spec_id") if isinstance(spec, dict) else spec.resource_spec_id) == spec_id]
    if len(specs) != 1:
        raise ValueError("frozen resource specification missing or duplicated")
    spec = specs[0] if isinstance(specs[0], dict) else specs[0].model_dump(mode="json")
    targets = list(spec["knowledge_points"])
    if spec["resource_family_id"] != resource.resource_family_id or spec["difficulty"] != resource.difficulty:
        raise ValueError("frozen resource specification mismatch")
    frozen_evidence = [{"evidence_id": e.evidence_id, "excerpt_hash": text_hash(e.excerpt), "excerpt": e.excerpt}
                       for e in sorted(evidence, key=lambda item: item.evidence_id)]
    return policy, spec_id, targets, frozen_evidence


def _binding(*, state, resource, spec_id, frozen_evidence, material,
             previous_binding=None) -> ResourceReviewBindingV1:
    identity = {
        "run_id": state["run_id"], "resource_spec_id": spec_id,
        "lineage_id": resource.resource_family_id, "resource_id": resource.resource_id,
        "resource_type": resource.resource_type, "version": resource.version,
        "text_exact_hash": material.text_exact_hash,
        "structured_payload_hash": material.structured_payload_hash,
        "artifact_exact_hash": material.artifact_exact_hash,
        "comparison_hash": material.comparison_hash,
        "evidence_snapshot_hash": _evidence_hash(frozen_evidence),
        "policy_hash": state["resource_review_policy_hash"]}
    identity.update(context_fields(previous_binding, identity))
    return ResourceReviewBindingV1(**identity)


def _evidence_hash(frozen_evidence: list[dict]) -> str:
    return canonical_hash({"evidence": sorted(
        ({"evidence_id": item["evidence_id"], "excerpt_hash": item["excerpt_hash"]}
         for item in frozen_evidence), key=lambda item: item["evidence_id"])})


def _profile(resource_type: str, phase: str, policy: ResourceReviewPolicyV1) -> ReviewProfile:
    schema = output_schema(resource_type, recheck=phase == "resource_issue_recheck_v1")
    return ReviewProfile(resource_type, phase, "1.0", profile_fragments(resource_type),
                         (), schema, "reviewer", policy.max_output_tokens)


def _gate_issue(binding: ResourceReviewBindingV1, gate_rule_id: str, scope_locator: str,
                failure_code: str, requirement: str) -> ResourceIssueV1:
    return ResourceIssueV1(
        issue_id=program_issue_id(run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
                                  gate_rule_id=gate_rule_id, scope_locator=scope_locator,
                                  failure_code=failure_code),
        origin="program_gate", code=failure_code, severity="high", blocking=True,
        blocking_rule=gate_rule_id, dimension="self_contained",
        location=ResourceLocationV1(kind="root"),
        impact="结构或投影不满足硬门，本轮语义审核被跳过。",
        requirement=requirement,
        acceptance="固定规则版本不变，重新运行结构/投影硬门通过。",
        criteria_version=1, path="reorganize_existing", executability="executable",
        rationale=requirement)


def run_program_gate(*, resource, material: ResourceMaterial,
                     binding: ResourceReviewBindingV1) -> ResourceProgramGateResultV1:
    """Deterministic structure + projection gates, zero model calls."""
    keys = []
    new_issues = []
    structure = check_resource_structure(resource=resource)
    if structure is not None:
        issue = structure["issues"][0]
        code = issue.get("code") or "structure_quality"
        keys.append(ResourceGateKeyV1(gate_rule_id=STRUCTURE_GATE_RULE,
                                      scope_locator="root", failure_code=code))
        new_issues.append(_gate_issue(binding, STRUCTURE_GATE_RULE, "root", code,
                                      issue.get("description") or "结构硬门未通过。"))
    if not material.projection_consistent:
        keys.append(ResourceGateKeyV1(gate_rule_id=PROJECTION_GATE_RULE,
                                      scope_locator="root", failure_code="projection_inconsistent"))
        new_issues.append(_gate_issue(binding, PROJECTION_GATE_RULE, "root",
                                      "projection_inconsistent",
                                      "结构化包与公开 Markdown 投影不一致，需按原 renderer 重建。"))
    passed = not keys
    blocked_reason = "" if passed else "；".join(item.requirement for item in new_issues)
    return ResourceProgramGateResultV1(rule_version=GATE_RULE_VERSION, passed=passed,
                                       keys=keys, new_issues=new_issues,
                                       blocked_reason=blocked_reason)


def migrate_program_gate(gate: ResourceProgramGateResultV1, previous: ResourceLedgerV1 | None):
    """Complete the prior program-issue migration for a gate result."""
    if previous is None:
        return gate
    prior_program_open = [item.issue for item in previous.issues
                          if item.status == "open" and item.issue.origin == "program_gate"]
    prior_by_key = {}
    for issue in prior_program_open:
        prior_by_key[(issue.blocking_rule, _scope_of(issue), issue.code)] = issue.issue_id
    resolved = []
    still_open = []
    new_keys = {(key.gate_rule_id, key.scope_locator, key.failure_code) for key in gate.keys}
    for key_tuple, issue_id in prior_by_key.items():
        if key_tuple in new_keys:
            still_open.append(issue_id)
        else:
            resolved.append(issue_id)
    carry = [item.issue.issue_id for item in previous.issues
             if item.status == "open" and item.issue.origin == "model_review"]
    return gate.model_copy(update={
        "resolved_program_issues": resolved,
        "still_open_program_issues": still_open,
        "carry_forward_model_issues": carry,
    })


def _scope_of(issue: ResourceIssueV1) -> str:
    if issue.location.kind == "root":
        return "root"
    return issue.location.unit_id or issue.location.paragraph_id or "root"


def _gate_summary(*, gate: ResourceProgramGateResultV1, material: ResourceMaterial,
                  resource_id, resource_spec_id) -> dict:
    ordered = sorted(gate.new_issues, key=lambda item: item.code)
    issues = [{"code": public_code(item), "severity": item.severity,
               "resource_type": material.resource_type, "resource_id": resource_id,
               "knowledge_point": None,
               "description": "结构或投影硬门未通过，需按固定规则重建。"}
              for item in ordered[:3]]
    codes = list(dict.fromkeys(public_code(item) for item in ordered))
    return {
        "decision": "revise", "hallucination_score": 0.0, "coverage_rate": 0.0,
        "difficulty_match": True, "issues": issues,
        "suggestion": "结构或投影硬门未通过，按定向工作单重建后再审核。",
        "revision_instructions": [{"issue_codes": codes or ["structure_quality"],
                                    "target_resource_type": material.resource_type,
                                    "resource_spec_id": resource_spec_id,
                                    "action": gate.blocked_reason or "恢复结构或投影一致性。", "priority": 1}],
    }


def _payload(*, material: ResourceMaterial, binding: ResourceReviewBindingV1, targets,
             frozen_evidence, previous: ResourceLedgerV1 | None, parent_text: str | None,
             parent_material=None) -> dict:
    payload = {
        "binding": binding.model_dump(mode="json"),
        "resource_type": material.resource_type,
        "difficulty": material.difficulty,
        "targets": list(dict.fromkeys(targets)),
        "evidence": frozen_evidence,
        "teaching_rule_ids": list(material.rule_ids),
        "location_index": {
            "paragraph_ids": sorted(material.index.paragraph_ids),
            "unit_ids": sorted(material.index.unit_ids),
            "root_allowed": material.index.root_allowed,
        },
        "text": material.text,
    }
    if material.structured_payload is not None:
        payload["structured_payload"] = material.structured_payload
    if previous is not None:
        payload["previous_content"] = parent_text
        payload["previous_structured_payload"] = parent_material.structured_payload
        payload["previous_location_index"] = {"paragraph_ids": sorted(parent_material.index.paragraph_ids),
                                              "unit_ids": sorted(parent_material.index.unit_ids)}
        payload["old_issues"] = [item.model_dump(mode="json") for item in previous.issues]
        payload["previous_binding"] = previous.binding.model_dump(mode="json")
    return payload


def _plan_correction(*, error: ValidationError, remaining_attempts: int,
                     remaining_seconds: float | None, output_reserve_ok: bool) -> CorrectionPlan:
    if not error.correctable:
        return CorrectionPlan(False, f"not_correctable:{error.code}")
    if remaining_attempts < 1:
        return CorrectionPlan(False, "no_physical_attempt_left")
    if remaining_seconds is not None and remaining_seconds <= 0:
        return CorrectionPlan(False, "workflow_deadline_reached")
    if not output_reserve_ok:
        return CorrectionPlan(False, "context_window_insufficient")
    return CorrectionPlan(True, None)


def _build_correction_request(*, request: ReviewRequest, first_output: dict,
                              errors: list[ValidationError]) -> ReviewRequest:
    system = request.messages[0]
    original = request.messages[1]
    if not isinstance(system, SystemMessage) or not isinstance(original, HumanMessage):
        raise ValueError("resource correction expects the frozen system/human pair")
    payload = json.loads(original.content)
    payload["previous_review_under_check"] = first_output
    payload["review_consistency_errors"] = [
        {"code": item.code, "field": item.path, "relationship": item.hint} for item in errors]
    body = json.dumps(payload, ensure_ascii=False)
    return ReviewRequest(
        request.profile, request.prompt_bundle,
        (SystemMessage(content=system.content + "\n\n" + CORRECTION_RULES.text),
         HumanMessage(content=body)),
        request.resource_id, request.max_output_tokens, request.context_tokens)


def _record(*, resource, attempted: bool, stop_reason: str | None, errors, first_attempts: int,
            correction_attempts: int, first, correction, corrected: bool,
            final_hash: str | None) -> CorrectionRecord:
    payload = first.output.model_dump(mode="json") if hasattr(first, "output") else None
    return CorrectionRecord(
        resource_id=resource.resource_id, attempted=attempted, stop_reason=stop_reason,
        error_codes=tuple(item.code for item in errors),
        error_paths=tuple(item.path for item in errors),
        first_attempts=first_attempts, correction_attempts=correction_attempts,
        first_call_id=first.call_id, correction_call_id=correction.call_id if correction else None,
        first_output=payload,
        first_output_hash=canonical_hash(payload) if payload is not None else "",
        corrected=corrected, final_output_hash=final_hash)


def _blocked(*, reason: str, error: ValidationError, result, repair: CorrectionRecord,
             resource) -> ResourceReviewOutcome:
    raw = {"decision": "human_review", "hallucination_score": 1.0, "coverage_rate": 0.0,
           "difficulty_match": False,
           "issues": [{"code": "evidence_gap", "severity": "critical",
                       "resource_type": resource.resource_type, "knowledge_point": None,
                       "description": "审核结果内部不一致且未能在允许范围内纠正，保持未发布。"}],
           "suggestion": f"停止原因：{reason}；错误代码：{error.code}。",
           "revision_instructions": []}
    return ResourceReviewOutcome(raw=raw, ledger=None, last_llm_result=result,
                                 stop_reason=reason, repair=repair)


def review_resource_v1(*, state, resource, evidence, step_id, context, gateway, collector,
                       review_id, step_guard=None) -> ResourceReviewOutcome:
    policy, spec_id, targets, frozen_evidence = _freeze_inputs(
        state=state, resource=resource, evidence=evidence)
    adapter = adapter_for(resource.resource_type)
    material = adapter.build_material(resource=resource, evidence=evidence, spec=None, targets=targets)

    previous_data = (state.get("resource_ledgers") or {}).get(spec_id)
    previous = ResourceLedgerV1.model_validate(previous_data) if previous_data else None
    binding = _binding(state=state, resource=resource, spec_id=spec_id,
                       frozen_evidence=frozen_evidence, material=material,
                       previous_binding=previous.binding if previous else None)
    verify_binding_hashes(binding=binding, material=material, evidence=evidence)
    carry_over = None
    if previous is not None and previous.binding.evidence_snapshot_hash != binding.evidence_snapshot_hash:
        carry_over = build_carry_over(previous, history_model=ResourceIssueHistoryV1)
    revision = (state.get("resource_revision") or {}).get(spec_id) or {}
    parent_text = revision.get("previous_text") if previous else None
    parent_material = None
    if previous is not None:
        if parent_text is None:
            raise ValueError("resource revision requires verified parent text")
        fields = {"content_text": parent_text}
        payload_field = {"实操指南": "practice_guide_payload", "分阶测试题": "assessment_payload",
                         "复习清单": "review_practice_payload"}.get(resource.resource_type)
        if payload_field:
            if "previous_structured_payload" not in revision:
                raise ValueError("resource revision requires the complete parent package")
            fields[payload_field] = revision["previous_structured_payload"]
        parent_resource = resource.model_copy(update=fields)
        parent_material = adapter.build_material(resource=parent_resource, evidence=evidence, spec=None, targets=targets)
        if parent_material.artifact_exact_hash != previous.binding.artifact_exact_hash:
            raise ValueError("resource revision parent artifact hash mismatch")
    revision_kind = "claim" if revision.get("claim_only") else "ordinary"

    gate = run_program_gate(resource=resource, material=material, binding=binding)
    gate = migrate_program_gate(gate, previous)
    if not gate.passed:
        ledger = append_program_gate_observation_v1(
            previous=previous, binding=binding, step_id=step_id, gate=gate, material=material,
            parent_comparison_hash=previous.observations[-1].comparison_hash if previous else None,
            carry_over=carry_over)
        raw = _gate_summary(gate=gate, material=material, resource_id=resource.resource_id,
                            resource_spec_id=spec_id)
        return ResourceReviewOutcome(raw=raw, ledger=ledger, last_llm_result=None,
                                     stop_reason="program_gate_failed", repair=None)

    phase = "resource_issue_recheck_v1" if previous else "resource_issue_initial_v1"
    profile = _profile(resource.resource_type, phase, policy)
    bundle = build_review_prompt(profile=profile)
    request = ReviewRequest(profile, bundle,
                            (SystemMessage(content=bundle.system_text),
                             HumanMessage(content=json.dumps(
                                 _payload(material=material, binding=binding, targets=targets,
                                          frozen_evidence=frozen_evidence, previous=previous,
                                          parent_text=parent_text, parent_material=parent_material), ensure_ascii=False))),
                            resource.resource_id, policy.max_output_tokens, policy.context_tokens)
    if estimate_review_input(request=request) + policy.max_output_tokens > policy.context_tokens:
        from ..executor import ReviewInputBudgetError
        raise ReviewInputBudgetError("resource review context window exceeded")

    guard = step_guard or state.get("resource_review_entry_guard")
    if not callable(guard):
        raise ValidationError("DURABLE_GUARD_MISSING", "guard",
                              "resource review requires a durable step guard before any request")
    validate_execution_identity(state=state, gateway=gateway)
    guard(step_id=step_id, generation_attempt=context.generation_attempt)

    result = invoke_review(request=request, llm_gateway=gateway, collector=collector,
                           review_id=review_id, call_context=context,
                           options_override={"max_attempts": policy.max_physical_attempts})
    try:
        first_attempts = _validate_first_attempts(result=result, policy=policy)
    except ValidationError as attempt_error:
        collector.invalid_result(call_id=result.call_id)
        repair = _record(resource=resource, attempted=False, stop_reason=f"attempt_unknown:{attempt_error.code}",
                         errors=(attempt_error,), first_attempts=0, correction_attempts=0,
                         first=result, correction=None, corrected=False, final_hash=None)
        return _blocked(reason=f"attempt_unknown:{attempt_error.code}", error=attempt_error,
                        result=result, repair=repair, resource=resource)
    used = first_attempts
    repair: CorrectionRecord | None = None
    try:
        schema = profile.output_schema
        output = schema.model_validate(result.output.model_dump(mode="json"))
        ledger = append_model_observation_v1(
            previous=previous, binding=binding, step_id=step_id, output=output,
            material=material, adapter=adapter, parent_text=parent_text, parent_material=parent_material,
            parent_comparison_hash=previous.observations[-1].comparison_hash if previous else None,
            revision_kind=revision_kind, coverage_threshold=policy.coverage_threshold,
            max_consecutive_unchanged=policy.max_consecutive_unchanged, gate=gate,
            carry_over=carry_over)
    except ValidationError as error:
        collector.invalid_result(call_id=result.call_id)
        remaining = policy.max_physical_attempts - used
        correction = _build_correction_request(request=request,
                                               first_output=result.output.model_dump(mode="json"),
                                               errors=[error])
        remaining_seconds = (gateway.remaining_seconds(context)
                             if hasattr(gateway, "remaining_seconds") else None)
        plan = _plan_correction(error=error, remaining_attempts=remaining,
                                remaining_seconds=remaining_seconds,
                                output_reserve_ok=correction_fits(
                                    request=correction, max_output_tokens=policy.max_output_tokens,
                                    context_tokens=policy.context_tokens))
        if not plan.allowed:
            repair = _record(resource=resource, attempted=False, stop_reason=plan.stop_reason,
                             errors=(error,), first_attempts=first_attempts, correction_attempts=0,
                             first=result, correction=None, corrected=False, final_hash=None)
            return _blocked(reason=plan.stop_reason or error.code, error=error, result=result,
                            repair=repair, resource=resource)
        validate_execution_identity(state=state, gateway=gateway)
        guard(step_id=step_id, generation_attempt=context.generation_attempt)
        correction_context = context.model_copy(update={"call_id": str(uuid4()),
                                                        "schema_name": profile.output_schema.__name__})
        try:
            second = invoke_review(
                request=correction, llm_gateway=gateway, collector=collector, review_id=review_id,
                call_context=correction_context,
                options_override={"max_attempts": 1, "allow_schema_repair": False, "schema_repair_attempts": 0})
        except LLMGatewayError as gateway_error:
            repair = _record(resource=resource, attempted=True,
                             stop_reason=f"correction_gateway_error:{getattr(gateway_error.error, 'code', 'unknown')}",
                             errors=(error,), first_attempts=first_attempts,
                             correction_attempts=0, first=result, correction=None,
                             corrected=False, final_hash=None)
            return _blocked(reason=repair.stop_reason, error=error, result=result,
                            repair=repair, resource=resource)
        try:
            output = schema.model_validate(second.output.model_dump(mode="json"))
            ledger = append_model_observation_v1(
                previous=previous, binding=binding, step_id=step_id, output=output,
                material=material, adapter=adapter, parent_text=parent_text, parent_material=parent_material,
                parent_comparison_hash=previous.observations[-1].comparison_hash if previous else None,
                revision_kind=revision_kind, coverage_threshold=policy.coverage_threshold,
                max_consecutive_unchanged=policy.max_consecutive_unchanged, gate=gate,
                carry_over=carry_over)
        except ValidationError as second_error:
            collector.invalid_result(call_id=second.call_id)
            repair = _record(resource=resource, attempted=True,
                             stop_reason=f"correction_failed:{second_error.code}",
                             errors=(error, second_error), first_attempts=first_attempts,
                             correction_attempts=len(second.attempts), first=result,
                             correction=second, corrected=False, final_hash=None)
            return _blocked(reason=f"correction_failed:{second_error.code}", error=second_error,
                            result=second, repair=repair, resource=resource)
        repair = _record(resource=resource, attempted=True, stop_reason=None, errors=(error,),
                         first_attempts=first_attempts, correction_attempts=len(second.attempts),
                         first=result, correction=second, corrected=True,
                         final_hash=ledger.observations[-1].output_hash)
        result = second

    observation = ledger.observations[-1]
    decision = observation.decision
    stop_reason = None
    if decision == "human_review":
        stop_reason = ("revision_no_progress" if observation.consecutive_unchanged >= policy.max_consecutive_unchanged
                       else "evidence_insufficient")
    if decision == "revise" and state.get("revision_count", 0) >= state.get("max_iterations", 2):
        decision, stop_reason = "human_review", "revision_budget_exhausted"
    open_issues = tuple(item.issue for item in ledger.issues if item.status == "open")
    raw = project_public_summary(decision=decision, output=observation.output, material=material,
                                 resource_id=resource.resource_id, resource_spec_id=spec_id,
                                 open_issues=open_issues)
    return ResourceReviewOutcome(raw=raw, ledger=ledger, last_llm_result=result,
                                 stop_reason=stop_reason, repair=repair)
