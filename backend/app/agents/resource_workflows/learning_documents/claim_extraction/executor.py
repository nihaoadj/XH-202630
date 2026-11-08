"""Serial bounded extraction; no new workflow node or model merge/Judge call."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.llm.gateway import LLMGatewayError
from app.core.security.errors import ErrorCode
from app.models.reviews.claim_extraction import (
    ExtractionResult, content_digest, digest, result_identity_key,
)
from app.models.shared.llm import LLMCallContext

from .batching import plan_batches, subdivide
from .budget import ExtractionBudget, check_window, check_judge_capacity
from .contracts import select_contract
from .merge import validate_output_with_diagnostics, materialize_result, SourceLocatingRejected
from .prompts.builder import build_messages


def execute_extraction(state, resource, *, review_id, evidence, llm_gateway, repository, counter, step_id):
    budget = ExtractionBudget(state, repository, llm_gateway, counter)
    policy = budget.policy
    text = resource.content_text or ""
    if not text:
        raise ValueError("neutral extraction content unavailable")
    allowed_nodes = set(state.get("target_skill_nodes", []))
    new_result = ExtractionResult(resource_id=resource.resource_id, resource_version=resource.version, review_id=review_id,
        content_hash=content_digest(text), evidence_hash=digest([e.model_dump(mode="json") for e in evidence]),
        generation_attempt=state.get("generation_attempt", 1), created_at=datetime.now(timezone.utc))
    result_key = result_identity_key(new_result, budget.current.policy_hash)

    def messages(batch):
        return build_messages(text, resource, batch, policy, allowed_nodes)

    def fits(batch):
        try:
            count=check_window(policy,counter,messages(batch),contract.output_schema,policy.extractor_options)
            return count<=policy.target_tokens
        except ValueError:
            return False

    ledger = budget.current.state
    result = ledger.results.get(result_key)
    if result is not None and result.status == "completed":
        check_judge_capacity(policy, llm_gateway, counter, result.final_claims, evidence)
        return list(result.final_claims), dict(result_key=result_key, final_result_hash=result.final_result_hash), None
    if result is not None and result.status == "failed":
        raise ValueError("neutral extraction result already failed")
    # A completed result is an immutable read; extractor assets are only
    # relevant when this execution still needs to validate or send new output.
    contract = select_contract(policy)
    if result is None:
        try:
            batches = plan_batches(text, policy, counter, fits=fits)
            if len(batches) > policy.max_calls - ledger.calls:
                raise ValueError("neutral extraction batch count exceeds remaining run budget")
        except ValueError:
            failed = new_result.model_copy(update=dict(status="failed", failure="source_capacity_exceeded"))
            budget.commit(ledger.model_copy(update={"results": {**ledger.results, result_key: failed}}))
            raise
        result = new_result.model_copy(update={"batches": batches})
        budget.commit(ledger.model_copy(update={"results": {**ledger.results, result_key: result}}))

    last_observation = None

    def replace_result(updated):
        current = budget.current.state
        budget.commit(current.model_copy(update={"results": {**current.results, result_key: updated}}))

    try:
        while True:
            result = budget.current.state.results[result_key]
            pending = [b for b in result.batches if b.batch_id not in result.outputs]
            if not pending:
                break
            batch = pending[0]
            call_id=budget.begin(result_key,batch)
            observer=budget.observer(call_id)
            timeout=min(policy.attempt_timeout_seconds,budget.available()-0.01)
            if timeout<=0:
                raise ValueError("extraction time budget exhausted")
            options=policy.extractor_options.model_copy(update=dict(request_timeout_seconds=timeout,retry_request_timeout_seconds=timeout))
            invalid=False
            # Bypass LLM-call accounting (T41): one logical neutral-batch
            # extraction call, attributed to the resource and batch.
            from app.agents.shared.llm_accounting import stage_labeled_scope

            with stage_labeled_scope("claim_extract", labels=[resource.resource_id, batch.batch_id]):
                try:
                    observation=llm_gateway.invoke_structured(messages=messages(batch),output_schema=contract.output_schema,
                        context=LLMCallContext(run_id=state["run_id"],step_id=step_id,node_name="claim_extractor",
                            schema_name=contract.schema_name,generation_attempt=state.get("generation_attempt",1),
                            workflow_deadline_at=budget.deadline(),call_id=call_id),options=options,attempt_observer=observer)
                except LLMGatewayError as exc:
                    invalid=observer.context_rejected or exc.error.code in {
                        ErrorCode.LLM_OUTPUT_TRUNCATED,ErrorCode.LLM_OUTPUT_PARSE_FAILED,
                        ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,ErrorCode.LLM_OUTPUT_EMPTY}
                    budget.finish(call_id,"invalid" if invalid else "failed")
                    if not invalid:
                        raise ValueError("extraction transport/usage failed") from exc
                else:
                    last_observation=observation
                    try:
                        observer.verify_observation(observation,contract.output_schema)
                        if observation.finish_reason=="length":
                            raise ValueError("truncated extraction response is not complete")
                        if observation.model_name!=policy.model_name:
                            raise ValueError("extraction response model mismatch")
                        output=contract.output_schema.model_validate(observation.output)
                        _, diagnostics = validate_output_with_diagnostics(text,batch,output,resource=resource,
                            policy=policy,allowed_nodes=allowed_nodes)
                    except SourceLocatingRejected as exc:
                        invalid=True
                        budget.finish(call_id,"invalid",diagnostics=list(exc.diagnostics))
                    except ValueError:
                        invalid=True
                        budget.finish(call_id,"invalid")
                    else:
                        budget.finish(call_id,"completed",output,diagnostics)
            if invalid:
                result = budget.current.state.results[result_key]
                children = subdivide(text, batch, policy, counter, fits=fits)
                if len(children) > policy.max_calls - budget.current.state.calls:
                    raise ValueError("neutral extraction subdivision budget exhausted")
                active = []
                for previous in result.batches:
                    active.extend(children if previous.batch_id == batch.batch_id else [previous])
                replace_result(result.model_copy(update=dict(batches=active,
                    replaced_batches=[*result.replaced_batches, batch.batch_id])))

        result = budget.current.state.results[result_key]
        candidates = []
        for batch in result.batches:
            batch_candidates, diagnostics = validate_output_with_diagnostics(text, batch,
                result.outputs[batch.batch_id], resource=resource, policy=policy, allowed_nodes=allowed_nodes)
            if diagnostics is not None:
                stored = (result.location_diagnostics or {}).get(batch.batch_id)
                if stored is None or [d.model_dump(mode="json") for d in diagnostics] != [d.model_dump(mode="json") for d in stored]:
                    raise ValueError("extraction locating diagnostics drift")
            candidates.extend(batch_candidates)
        claims = materialize_result(candidates, text=text, resource=resource, review_id=review_id, run_id=state["run_id"],
                                    policy=policy, created_at=result.created_at)
        check_judge_capacity(policy, llm_gateway, counter, claims, evidence)
        result = result.model_copy(update=dict(status="completed", final_claims=claims, final_result_hash=digest(claims)))
        replace_result(result)
        return claims, dict(result_key=result_key, final_result_hash=result.final_result_hash), last_observation
    except ValueError:
        result = budget.current.state.results[result_key]
        if not any(t.status == "in_flight" for t in budget.current.state.tickets.values()):
            replace_result(result.model_copy(update=dict(status="failed", failure="extraction_incomplete")))
        raise
