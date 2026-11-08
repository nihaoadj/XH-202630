"""Frozen heuristic policy and persistent per-physical-attempt accounting."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math
import time
from urllib.parse import urlsplit

from app.core.execution import current_execution_session, current_execution_fence
from app.core.llm.counting import CharacterEstimator
from app.models.reviews.claim_extraction import (
    LEGACY, ESTIMATE, PRIVATE_FIELDS, EstimatePolicy, AttemptTicket, LogicalExtraction,
    DensityBatchingPolicy, SourceLocatingPolicy, BatchOutputV2, PROMPT_VERSION_V2,
    digest, policy_from_input,
)


def gateway_model(gateway):
    return getattr(getattr(gateway, "transport", gateway), "model_name", None)


def gateway_identity(gateway):
    settings = getattr(getattr(gateway, "transport", None), "settings", None)
    return (digest(str(getattr(settings, "llm_base_url", "offline")).rstrip("/")),
            getattr(settings, "llm_thinking_mode", "auto"))


def validate_counter(counter, gateway, frozen_policy=None):
    from app.models.reviews.claim_extraction import OfflineClaimCounter
    from app.core.llm.transport import LangChainChatTransport
    if not isinstance(counter, CharacterEstimator) or gateway is None:
        raise ValueError("neutral estimate requires a character estimator")
    if isinstance(counter,OfflineClaimCounter) and isinstance(getattr(gateway,"transport",None),LangChainChatTransport):
        raise ValueError("synthetic estimator cannot be used with production transport")
    if frozen_policy is not None and counter.parameters != frozen_policy.estimator_parameters:
        raise ValueError("frozen estimator parameters drift")
    return counter.parameters


def freeze_policy(settings, gateway, counter):
    from .profiles import load_counter
    from ..claim_review_agent import JUDGE_PROMPT
    from app.models.reviews.claims import ClaimJudgementLLMOutput
    from .prompts.extract_v2 import PROMPT as PROMPT_V2
    from .source_locating.rules import load_rules
    counter = counter if counter is not None else load_counter(settings, gateway)
    parameters = validate_counter(counter, gateway)
    judge = gateway.options_for("claim_judge", temperature=0.0)
    base = gateway.options_for("claim_extractor", temperature=0.0)
    timeout = min(settings.claim_extraction_attempt_timeout_seconds, base.request_timeout_seconds,
                  base.retry_request_timeout_seconds or base.request_timeout_seconds)
    cap = settings.claim_extraction_output_tokens
    extractor = base.model_copy(update=dict(max_output_tokens=cap, truncated_retry_output_tokens=cap,
        request_timeout_seconds=timeout, retry_request_timeout_seconds=timeout,
        schema_repair_attempts=min(base.schema_repair_attempts, base.max_attempts-1)))
    endpoint, thinking = gateway_identity(gateway)
    if thinking != "disabled":
        # Thinking tokens are outside the frozen character estimator; running
        # neutral extraction with thinking enabled would silently break the
        # reserved token budget and the attempt timeout contract (T36).
        raise ValueError("neutral extraction requires LLM_THINKING_MODE=disabled")
    source_locating = None
    prompt_version = None
    if settings.claim_extraction_source_locating_mode in {"exact_v1", "tolerant_v1"}:
        rules = load_rules()
        source_locating = SourceLocatingPolicy(
            locator_algorithm_version="locator-v2",
            mode=settings.claim_extraction_source_locating_mode,
            extractor_prompt_hash=digest(PROMPT_V2),
            output_schema_hash=digest(BatchOutputV2.model_json_schema()),
            rules_hash=rules.hash,
            max_edits=rules.thresholds.max_edits,
            max_edit_ratio=rules.thresholds.max_edit_ratio,
            min_effective_chars=rules.thresholds.min_effective_chars,
            min_score_margin=rules.thresholds.min_score_margin,
            max_unit_chars=rules.thresholds.max_unit_chars,
            max_candidate_chars=rules.thresholds.max_candidate_chars,
            max_dp_cells_per_ref=rules.thresholds.max_dp_cells_per_ref,
            max_distinct_intervals=rules.thresholds.max_distinct_intervals,
            max_work_cells_per_batch=rules.thresholds.max_work_cells_per_batch,
        )
        prompt_version = PROMPT_VERSION_V2
    values = dict(estimator_parameters=parameters.model_dump(),
        model_name=gateway_model(gateway),
        endpoint_hash=endpoint, thinking_mode=thinking, context_limit=settings.claim_extraction_context_limit,
        judge_options=judge, judge_prompt_hash=digest(JUDGE_PROMPT),
        judge_schema_hash=digest(ClaimJudgementLLMOutput.model_json_schema()),
        target_tokens=settings.claim_extraction_target_tokens, context_tokens=settings.claim_extraction_context_tokens,
        batch_claims=settings.claim_extraction_batch_claims, resource_claims=settings.claim_extraction_resource_claims,
        output_tokens=cap, max_calls=settings.claim_extraction_max_calls, max_attempts=settings.claim_extraction_max_attempts,
        max_tokens=settings.claim_extraction_max_tokens, attempt_timeout_seconds=timeout,
        max_request_seconds=settings.claim_extraction_max_request_seconds,
        judge_reserve_seconds=judge.request_timeout_seconds+30, extractor_options=extractor,
        backoff_seconds=getattr(gateway, "retry_max_delay_seconds", 0),
        # Always frozen for new estimate Runs, including enabled=false: the
        # absence of this sub-contract means "frozen before T37" and must only
        # ever appear on historical snapshots (T37 §3.1).
        density_batching=DensityBatchingPolicy(
            enabled=settings.claim_extraction_density_enabled,
            chars_per_claim=settings.claim_extraction_density_prior,
            capacity_share=settings.claim_extraction_risk_share))
    if source_locating is not None:
        values["prompt_version"] = prompt_version
        values["source_locating"] = source_locating
    return EstimatePolicy(**values)


def frozen_snapshot(settings, request, gateway, counter):
    if not request.include_claim_check or settings.claim_extraction_strategy == LEGACY:
        return {}
    if settings.claim_extraction_strategy != ESTIMATE:
        raise ValueError("retired neutral strategy; create a new estimate run")
    policy = freeze_policy(settings, gateway, counter)
    return dict(claim_extraction_mode=ESTIMATE, claim_extraction_policy=policy.model_dump(mode="json"),
                claim_extraction_policy_hash=digest(policy))


def validate_entry(state, repository):
    expected = policy_from_input(state)
    if expected is not None and expected.strategy != ESTIMATE:
        raise ValueError("retired neutral snapshot is read-only; retry with a new run")
    if repository is None:
        if expected is not None:
            raise ValueError("neutral extraction persistence dependency missing")
        return None
    current = repository.get(state["run_id"])
    if (current is None) != (expected is None) or (current is not None and current.policy != expected):
        raise ValueError("extraction workflow/durable mode mismatch")
    return current


def snapshot_fields(payload):
    return {k:payload[k] for k in PRIVATE_FIELDS-{"claim_extraction_refs"} if k in payload}


def close_session(run_id, repository):
    current = repository.get(run_id)
    if current is None or current.state.active_owner is None:
        return
    session = current_execution_session()
    if session is None or session.run_id != run_id:
        raise ValueError("extraction session missing")
    repository.compare_and_swap(current, current.state.model_copy(update={"session_closed":True}),
        owner=session.owner, session_id=session.session_id)


def request_input_bound(counter, messages, schema, options):
    value = counter.request_bound(messages, schema, options)
    if type(value) is not int or value <= 0:
        raise ValueError("invalid request estimate")
    return value


def check_window(policy, counter, messages, schema, options):
    count = request_input_bound(counter, messages, schema, options)
    if count + options.max_output_tokens > policy.context_limit:
        raise ValueError("single Claim call exceeds configured context window")
    return count


def judge_messages(claims, evidence):
    import json
    from langchain_core.messages import HumanMessage, SystemMessage
    from ..claim_review_agent import JUDGE_PROMPT
    data = dict(allowed_evidence=[dict(evidence_id=e.evidence_id,excerpt=e.excerpt) for e in evidence],
        claims=[dict(claim_id=c.claim_id,claim_type=c.claim_type.value,claim_text=c.claim_text,
                     resource_id=c.resource_id,resource_version=c.resource_version) for c in claims])
    return [SystemMessage(content=JUDGE_PROMPT), HumanMessage(content=json.dumps(data,ensure_ascii=False))]


def check_judge_config(policy, gateway, counter):
    from ..claim_review_agent import JUDGE_PROMPT
    from app.models.reviews.claims import ClaimJudgementLLMOutput
    validate_counter(counter,gateway,policy)
    if (gateway_model(gateway) != policy.model_name or gateway_identity(gateway) != (policy.endpoint_hash,policy.thinking_mode)
            or gateway.options_for("claim_judge",temperature=0.0) != policy.judge_options
            or digest(JUDGE_PROMPT) != policy.judge_prompt_hash
            or digest(ClaimJudgementLLMOutput.model_json_schema()) != policy.judge_schema_hash):
        raise ValueError("frozen Judge/model/endpoint/thinking contract drift")


def check_extraction_gateway(policy, gateway):
    delay=getattr(gateway,"retry_max_delay_seconds",0)
    if not isinstance(delay,(int,float)) or not math.isfinite(delay) or delay<0 or delay>policy.backoff_seconds:
        raise ValueError("frozen extraction backoff bound drift")


def check_judge_capacity(policy,gateway,counter,claims,evidence):
    from app.models.reviews.claims import ClaimJudgementLLMOutput
    check_judge_config(policy,gateway,counter)
    if not claims or len(claims)>policy.resource_claims:
        raise ValueError("single Judge engineering candidate cap exceeded")
    check_window(policy,counter,judge_messages(claims,evidence),ClaimJudgementLLMOutput,policy.judge_options)


class JudgeWindowObserver:
    """Read-only actual-mode window checks, preserving original Judge retries."""
    def __init__(self,policy,counter):
        self.policy,self.counter=policy,counter

    def before_attempt(self,context,attempt,prepared_messages,output_schema,mode,max_output_tokens,timeout_seconds):
        if self.counter.estimate_prepared(prepared_messages,output_schema,mode)+max_output_tokens>self.policy.context_limit:
            raise ValueError("Judge actual request exceeds configured context window")

    def after_attempt(self,ticket,raw_response,elapsed_ms):
        return True

    def on_attempt_error(self,ticket,exception,elapsed_ms):
        return True


def is_context_rejection(exception,gateway):
    settings=getattr(getattr(gateway,"transport",None),"settings",None)
    host=urlsplit(str(getattr(settings,"llm_base_url",""))).hostname
    body=getattr(exception,"body",None)
    if host!="api.deepseek.com" or getattr(exception,"status_code",None)!=400 or not isinstance(body,dict):
        return False
    error=body.get("error",body)
    return isinstance(error,dict) and error.get("code")=="context_length_exceeded"


class ExtractionBudget:
    def __init__(self,state,repository,gateway,counter):
        self.state,self.repository,self.gateway,self.counter=state,repository,gateway,counter
        self.current=validate_entry(state,repository)
        if self.current is None:
            raise ValueError("neutral estimate policy missing")
        self.policy=self.current.policy
        check_judge_config(self.policy,gateway,counter)
        check_extraction_gateway(self.policy,gateway)
        self.session=current_execution_session()
        if self.session is None or self.session.run_id!=self.current.run_id:
            raise ValueError("continuous extraction session required")
        self.clock=getattr(gateway,"wall_clock",lambda:datetime.now(timezone.utc))
        old=self.current.state
        if any(not t.settled for t in old.tickets.values()):
            # Only an in-flight (unsettled) attempt blocks same-run continuation.
            # Settled failures keep their token reserve deducted (conservative
            # accounting) and stay bounded by max_attempts, so subdivision and
            # rework may continue after them (T36).
            raise ValueError("in-flight extraction attempt blocks same-run continuation")
        fence=current_execution_fence()
        self.commit(old.model_copy(update=dict(active_owner=self.session.owner,execution_session_id=self.session.session_id,
            ledger_epoch=old.ledger_epoch or 1,fence_epoch=fence.epoch if fence else None)))

    def commit(self,ledger,required_seconds=0):
        self.current=self.repository.compare_and_swap(self.current,ledger,owner=self.session.owner,
            session_id=self.session.session_id,required_seconds=required_seconds)
        return self.current

    def deadline(self):
        value=self.state.get("workflow_deadline_at")
        if not isinstance(value,datetime):
            raise ValueError("absolute workflow deadline missing")
        if value.tzinfo is None:
            value=value.replace(tzinfo=timezone.utc)
        return value-timedelta(seconds=self.policy.judge_reserve_seconds)

    def available(self):
        now=self.clock()
        return min(self.policy.max_request_seconds-self.current.state.time_ms/1000,
                   (self.deadline()-now).total_seconds(),
                   (self.current.state.owner_deadline_at-now).total_seconds()-0.1)

    def begin(self,result_key,batch):
        ledger=self.current.state
        if self.available() <= 0.01 or ledger.budget_exhausted:
            raise ValueError("extraction time/token budget exhausted")
        # Result identity includes generation_attempt; call identity survives re-entry.
        key=digest([result_key,batch.batch_id,"estimate-logical-v1"])
        if key in ledger.logical_calls or ledger.calls>=self.policy.max_calls:
            raise ValueError("logical extraction already observed or exhausted")
        logical=LogicalExtraction(result_key=result_key,batch_id=batch.batch_id)
        self.commit(ledger.model_copy(update=dict(calls=ledger.calls+1,logical_calls={**ledger.logical_calls,key:logical})))
        return key

    def observer(self,call_id):
        return ExtractionAttemptObserver(self,call_id)

    def finish(self,call_id,status,output=None,diagnostics=None):
        ledger=self.current.state
        logical=ledger.logical_calls[call_id]
        if logical.status!= "running":
            raise ValueError("logical extraction already finished")
        tickets = [t for t in ledger.tickets.values() if t.logical_call_id==call_id]
        if status=="completed" and (not tickets or any(not t.settled for t in tickets)
                or max(tickets,key=lambda t:t.attempt_index).status!="completed"):
            raise ValueError("completed extraction requires settled physical attempts")
        results=dict(ledger.results)
        if output is not None and status=="completed":
            item=results[logical.result_key]
            updates={"outputs":{**item.outputs,logical.batch_id:output}}
            if diagnostics is not None:
                updates["location_diagnostics"]={**(item.location_diagnostics or {}),logical.batch_id:diagnostics}
            results[logical.result_key]=item.model_copy(update=updates)
        elif diagnostics is not None and status == "invalid":
            item=results[logical.result_key]
            results[logical.result_key]=item.model_copy(update={
                "location_failures": {**(item.location_failures or {}),call_id:list(diagnostics)[:8]}})
        updated=ledger.model_copy(update=dict(results=results,
            logical_calls={**ledger.logical_calls,call_id:logical.model_copy(update={"status":status,
                "output_hash":digest(output) if output is not None and status=="completed" else None})}))
        try:
            self.commit(updated)
        except ValueError as exc:
            if (str(exc) == "extraction ledger byte budget exceeded"
                    and (output is not None or diagnostics is not None)):
                # Physical attempts were already settled. Persist a minimal
                # logical failure, never a successful result with missing audit.
                self.finish(call_id, "failed")
            raise


class ExtractionAttemptObserver:
    def __init__(self,budget,call_id):
        self.budget,self.call_id=budget,call_id
        self.context_rejected=False
        self.retry_allowed=True
        self.last_completion=None
        self.last_response=None

    def verify_observation(self, observation, schema):
        from app.core.llm.structured_output import parse_structured_output, StructuredOutputError
        if self.last_response is None or observation.call_id!=self.call_id:
            raise ValueError("missing matching physical response receipt")
        try:
            parsed=parse_structured_output(self.last_response.content,schema,finish_reason=self.last_response.finish_reason)
        except StructuredOutputError as exc:
            raise ValueError("invalid physical response receipt") from exc
        if parsed!=schema.model_validate(observation.output):
            raise ValueError("logical output differs from physical response")

    def before_attempt(self,context,attempt,prepared_messages,output_schema,mode,max_output_tokens,timeout_seconds):
        b=self.budget
        check_extraction_gateway(b.policy,b.gateway)
        if self.last_completion is not None:
            gap=max(0,int((time.monotonic()-self.last_completion)*1000))
            if gap:
                previous=b.current.state
                elapsed=previous.time_ms+gap
                b.commit(previous.model_copy(update=dict(backoff_ms=previous.backoff_ms+gap,time_ms=elapsed,
                    budget_exhausted=previous.tokens>=b.policy.max_tokens or elapsed>=b.policy.max_request_seconds*1000)))
            self.last_completion=None
        ledger=b.current.state
        if (context.run_id!=b.current.run_id or context.call_id!=self.call_id
                or context.node_name!="claim_extractor" or ledger.budget_exhausted
                or any(not t.settled for t in ledger.tickets.values())):
            raise ValueError("in-flight/exhausted budget or call identity mismatch")
        if ledger.attempts>=b.policy.max_attempts:
            raise ValueError("physical attempt budget exhausted")
        prior = [t.attempt_index for t in ledger.tickets.values() if t.logical_call_id==self.call_id]
        if attempt != len(prior)+1 or attempt>b.policy.extractor_options.max_attempts:
            raise ValueError("physical attempt order or call limit invalid")
        count=b.counter.estimate_prepared(prepared_messages,output_schema,mode)
        tokens=count+max_output_tokens
        if tokens>b.policy.context_limit or ledger.tokens+tokens>b.policy.max_tokens:
            raise ValueError("attempt token/window budget exhausted")
        timeout=min(timeout_seconds,b.policy.attempt_timeout_seconds,b.available()-0.01)
        if timeout<=0:
            raise ValueError("attempt time budget exhausted")
        logical=ledger.logical_calls[self.call_id]
        key=digest([logical.result_key,logical.batch_id,self.call_id,attempt])
        if key in ledger.tickets:
            raise ValueError("attempt may never be resent")
        ticket=AttemptTicket(key=key,result_key=logical.result_key,batch_id=logical.batch_id,
            logical_call_id=self.call_id,attempt_index=attempt,reserved_tokens=tokens,
            time_ms=math.ceil(timeout*1000),timeout_seconds=timeout)
        exhausted = ledger.tokens+tokens>=b.policy.max_tokens or ledger.time_ms+ticket.time_ms>=b.policy.max_request_seconds*1000
        b.commit(ledger.model_copy(update=dict(tickets={**ledger.tickets,key:ticket},attempts=ledger.attempts+1,
            tokens=ledger.tokens+tokens,time_ms=ledger.time_ms+ticket.time_ms,budget_exhausted=exhausted)),required_seconds=timeout)
        return ticket

    def settle(self,ticket,raw,elapsed_ms,status,usage_status):
        b=self.budget
        ledger=b.current.state
        current=ledger.tickets[ticket.key]
        response_hash=digest(raw) if raw is not None else None
        if current.settled:
            if current.response_hash!=response_hash or current.status!=status:
                raise ValueError("settled physical response is immutable")
            return current.usage_status=="known" and not ledger.budget_exhausted
        usage=getattr(raw,"usage",None)
        known=usage is not None and usage.input_tokens is not None and usage.output_tokens is not None and usage.total_tokens==usage.input_tokens+usage.output_tokens
        actual=usage.total_tokens if known else None
        updated=current.model_copy(update=dict(status=status,settled=True,actual_tokens=actual,
            actual_time_ms=max(0,elapsed_ms),response_hash=response_hash,usage_status="known" if known else usage_status))
        tokens=ledger.tokens-current.reserved_tokens+(actual if known else current.reserved_tokens)
        elapsed_total=ledger.time_ms-current.time_ms+max(0,elapsed_ms)
        exhausted=tokens>=b.policy.max_tokens or elapsed_total>=b.policy.max_request_seconds*1000
        b.commit(ledger.model_copy(update=dict(tickets={**ledger.tickets,ticket.key:updated},tokens=tokens,time_ms=elapsed_total,
            overrun_tokens=max(0,tokens-b.policy.max_tokens),budget_exhausted=exhausted)))
        self.retry_allowed=known and not exhausted
        self.last_completion=time.monotonic()
        return self.retry_allowed

    def after_attempt(self,ticket,raw_response,elapsed_ms):
        allowed=self.settle(ticket,raw_response,elapsed_ms,"completed","unknown")
        self.last_response=raw_response
        return allowed

    def on_attempt_error(self,ticket,exception,elapsed_ms):
        self.last_response=None
        self.context_rejected=is_context_rejection(exception,self.budget.gateway)
        self.settle(ticket,None,elapsed_ms,"failed","rejected_unknown" if self.context_rejected else "unknown")
        # Unknown-usage attempts are never gateway-replayed: the executor routes
        # context rejections and output-quality failures to bounded subdivision
        # instead, and the settled failure keeps its token reserve deducted.
        self.retry_allowed=False
        return False


class GuardedJudgeGateway:
    """Validate immediately before the original Judge call without changing it."""
    def __init__(self, state, gateway, repository, counter):
        self.state, self.gateway, self.repository, self.counter = state, gateway, repository, counter

    def options_for(self, *args, **kwargs):
        return self.gateway.options_for(*args, **kwargs)

    def invoke_structured(self, **kwargs):
        from app.agents.shared.evidence_scope import resolve_review_evidence_context
        from app.models.reviews.claims import ClaimRecord, ClaimJudgementLLMOutput
        snapshot = validate_entry(self.state, self.repository)
        if snapshot is None:
            raise ValueError("neutral Judge durable policy missing")
        session = current_execution_session()
        if session is None:
            raise ValueError("neutral Judge session missing")
        # CAS checks actual run/job lease, session and epoch in the same transaction.
        snapshot = self.repository.compare_and_swap(snapshot, snapshot.state, owner=session.owner, session_id=session.session_id)
        check_judge_config(snapshot.policy, self.gateway, self.counter)
        if kwargs["options"] != snapshot.policy.judge_options or kwargs["output_schema"] is not ClaimJudgementLLMOutput:
            raise ValueError("neutral Judge call contract mismatch")
        import json
        payload = json.loads(kwargs["messages"][-1].content)
        resource_id = payload["claims"][0]["resource_id"]
        resource = next(r for r in self.state["generated_resources"] if r.resource_id == resource_id)
        current_review_id = self.state.get("review_result", {}).get("review_ids", {}).get(resource_id) or resource.review_id
        claims = [ClaimRecord.model_validate(c) for c in self.state["extracted_claims"] if c["resource_id"] == resource_id]
        evidence = resolve_review_evidence_context(self.state, resource)
        result = next((r for r in snapshot.state.results.values() if r.resource_id == resource_id
                       and r.resource_version == resource.version and r.generation_attempt == self.state.get("generation_attempt", 1)
                       and r.final_result_hash == digest(claims)), None)
        if result is None or result.status != "completed" or result.content_hash != content_hash(resource.content_text or "") or result.evidence_hash != digest([e.model_dump(mode="json") for e in evidence]):
            raise ValueError("neutral Judge frozen result/evidence mismatch")
        if result.review_id != current_review_id or any(c.review_id != current_review_id for c in claims):
            raise ValueError("neutral Judge frozen review mismatch")
        expected = judge_messages(claims, evidence)
        if [m.content for m in kwargs["messages"]] != [m.content for m in expected]:
            raise ValueError("neutral Judge message mismatch")
        check_judge_capacity(snapshot.policy, self.gateway, self.counter, claims, evidence)
        return self.gateway.invoke_structured(**kwargs, attempt_observer=JudgeWindowObserver(snapshot.policy, self.counter))


def content_hash(text):
    from app.models.reviews.claim_extraction import content_digest
    return content_digest(text)
