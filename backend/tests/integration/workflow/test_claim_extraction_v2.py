from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy, validate_counter, validate_entry
from app.core.security.errors import ApplicationError
from app.db.audit.memory import MemoryAuditRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.shared.persistence import build_checkpoint_projection
from app.models.reviews.claim_extraction import ESTIMATE as NEUTRAL, digest
from app.services.generation.generation import build_workflow_state, _request_snapshot, GenerationService
from app.services.generation.jobs import GenerationJobService
from app.models.generation.dispatch import ESTIMATE_TEXT_WORKFLOW_VERSION as NEUTRAL_TEXT_WORKFLOW_VERSION
from tests.fakes.claim_extraction import FixtureCounter, NeutralScriptedGateway, neutral_settings, snapshot_for, prepare_ledger
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.claim_extraction import state_for_extraction, extract_every_unit, judge_all
from app.core.execution import execution_session
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node, claim_decide_node


def extract(state, repo, gateway, counter):
    return claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter)


def judge(state, repo, gateway, counter):
    return claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter)


def test_asset_free_factory_and_retired_snapshot_rejection():
    from app.core.llm.counting import CharacterEstimator
    from tests.fakes.claim_extraction import policy
    p=freeze_policy(neutral_settings(),NeutralScriptedGateway([]),CharacterEstimator())
    assert p.strategy==NEUTRAL and "profile" not in p.model_dump()
    with pytest.raises(ValueError,match="read-only"):
        validate_entry(dict(run_id="old",**snapshot_for(policy())),None)


def test_submission_state_and_dispatch_freeze_policy_not_latest_configuration(monkeypatch):
    import app.services.generation.generation as generation
    import app.services.generation.jobs as jobs
    settings = neutral_settings()
    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    # jobs._dispatch_snapshot freezes the lecture review policy with its own
    # get_settings import; isolate it too so the frozen claim workflow version
    # is not overwritten by a real .env lecture strategy.
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    gateway, counter = NeutralScriptedGateway([]), FixtureCounter()
    service = GenerationService(SimpleNamespace(), SimpleNamespace(), audit_repo=MemoryAuditRepository(),
        claim_extraction_gateway=gateway, claim_extraction_counter=counter)
    learner = LearnerProfile(learner_id="l", learner_type="test", education="本科", major="软件", learning_goal="Python")
    req = GenerateRequest(learner_id="l", topic="Python", resource_types=["讲义"], include_claim_check=True)
    frozen = service.freeze_claim_extraction(req)
    assert frozen["claim_extraction_mode"] == NEUTRAL
    state = build_workflow_state(learner, req, claim_extraction_snapshot=frozen)
    request = _request_snapshot(req, state)
    assert request["claim_extraction_policy_hash"] == digest(freeze_policy(settings, gateway, counter))
    jobs = GenerationJobService(SimpleNamespace(), service)
    dispatch = jobs._dispatch_snapshot(learner, req)
    assert dispatch["workflow_version"] == NEUTRAL_TEXT_WORKFLOW_VERSION
    assert dispatch["claim_extraction_policy"] == frozen["claim_extraction_policy"]
    settings.claim_extraction_target_tokens = 2000
    replay = build_workflow_state(learner, req, claim_extraction_snapshot=frozen)
    assert replay["claim_extraction_policy"]["target_tokens"] == 4096
    assert service.freeze_claim_extraction(req)["claim_extraction_policy"]["target_tokens"] == 2000
    assert "claim_extraction_policy" in build_checkpoint_projection(state)
    req.include_claim_check = False
    assert service.freeze_claim_extraction(req) == {}
    with pytest.raises(ApplicationError):
        build_workflow_state(learner, req, claim_extraction_snapshot=frozen)


@pytest.mark.parametrize("missing", ["policy", "hash", "both"])
def test_state_cannot_downgrade_durable_neutral_mode(missing):
    p = freeze_policy(neutral_settings(), NeutralScriptedGateway([]), FixtureCounter())
    _, repo = prepare_ledger(p=p)
    state = dict(run_id="run-neutral", **snapshot_for(p))
    if missing in {"policy", "both"}:
        state.pop("claim_extraction_policy")
    if missing in {"hash", "both"}:
        state.pop("claim_extraction_policy_hash")
    with pytest.raises(ValueError):
        validate_entry(state, repo)


@pytest.mark.parametrize("count", [1, 10, 16, 48])
def test_all_candidates_one_original_judge_and_no_extra_evidence_in_extract(count):
    import json
    state, audit, repo, gateway, counter = state_for_extraction("\n\n".join(f"Fact {i:02}." for i in range(count)))
    gateway.outcomes = [extract_every_unit] * 8 + [judge_all]
    with execution_session(state["run_id"], "owner"):
        state.update(extract(state, repo, gateway, counter))
        assert len(state.get("extracted_claims", [])) == count
        extraction_calls = len(gateway.calls)
        gateway.outcomes = [judge_all]
        state.update(judge(state, repo, gateway, counter))
        state.update(claim_decide_node(state))
    assert state["claim_check_status"] == "completed"
    assert len(gateway.calls) == extraction_calls + 1
    assert gateway.calls[-1]["context"].node_name == "claim_judge"
    for call in gateway.calls[:-1]:
        payload = json.loads(call["messages"][-1].content)
        assert "allowed_evidence" not in payload and "evidence_id" not in json.dumps(payload)
        assert call["options"].max_output_tokens == call["options"].truncated_retry_output_tokens == 8192
        assert call["options"].request_timeout_seconds <= 60 and call["options"].retry_request_timeout_seconds <= 60
    assert all(c["source_evidence_ids"] == [] and c["knowledge_point_id"] is None for c in state["extracted_claims"])
    assert all(j["evidence_ids"] == ["ev"] for j in state["claim_judgements"])
    assert state["trace"][0]["evidence_refs"] == []
    if count < 16:
        assert extraction_calls == 1
    else:
        assert extraction_calls > 1
    saved = repo.get(state["run_id"])
    assert saved.state.calls == extraction_calls and saved.state.tokens == 15 * extraction_calls
    assert len(audit.list_events(state["run_id"])) == 2


def test_completed_extractor_same_active_session_is_zero_call_idempotent_read():
    state, _, repo, gateway, counter = state_for_extraction()
    gateway.outcomes = [extract_every_unit]
    with execution_session(state["run_id"], "owner"):
        first = extract(state, repo, gateway, counter)
        second = extract(state, repo, gateway, counter)
        assert first["extracted_claims"] == second["extracted_claims"]
        assert len(gateway.calls) == 1
    with execution_session(state["run_id"], "owner"):
        assert extract(state, repo, gateway, counter)["claim_check_status"] == "failed"
        assert len(gateway.calls) == 1


def test_judge_configuration_drift_is_zero_judge_calls():
    state, _, repo, gateway, counter = state_for_extraction()
    gateway.outcomes = [extract_every_unit]
    with execution_session(state["run_id"], "owner"):
        state.update(extract(state, repo, gateway, counter))
        original = gateway.options_for
        gateway.options_for = lambda *a, **kw: original(*a, **kw).model_copy(update={"temperature": 0.2})
        result = judge(state, repo, gateway, counter)
    assert len(gateway.calls) == 1 and result["claim_failed_resource_ids"] == ["r"]


def test_resource_overflow_is_failed_without_dropping_candidates_or_batching_judge():
    settings = neutral_settings(claim_extraction_resource_claims=16, claim_extraction_max_calls=16)
    state, _, repo, gateway, counter = state_for_extraction("\n\n".join(f"Fact {i}." for i in range(21)), settings=settings)
    gateway.outcomes = [extract_every_unit] * 16
    with execution_session(state["run_id"], "owner"):
        result = extract(state, repo, gateway, counter)
    assert result["claim_check_status"] == "failed" and not result.get("extracted_claims")
    assert all(c["context"].node_name == "claim_extractor" for c in gateway.calls)
    assert next(iter(repo.get(state["run_id"]).state.results.values())).status == "failed"


def test_unknown_usage_retains_reserved_tokens_and_unknown_attempts_keep_attempts():
    from app.models.shared.llm import LLMCallResult, LLMAttemptSummary, LLMUsage
    state, _, repo, gateway, counter = state_for_extraction()
    def outcome(call):
        return LLMCallResult(output=call["output_schema"].model_validate(extract_every_unit(call)), call_id="unknown",
            model_name="fake-model", structured_output_mode="text", attempt_count=1, retry_count=0, latency_ms=2,
            attempts=[LLMAttemptSummary(attempt=1, status="success", latency_ms=2, structured_output_mode="text", usage=LLMUsage())])
    gateway.outcomes = [outcome]
    with execution_session(state["run_id"], "owner"):
        result = extract(state, repo, gateway, counter)
    assert len(result["extracted_claims"]) == 1
    saved = repo.get(state["run_id"]).state
    ticket = next(iter(saved.tickets.values()))
    assert not ticket.usage_known and ticket.charged_tokens is None
    assert saved.tokens == ticket.tokens > 8192 and saved.time_ms == 2


@pytest.mark.parametrize("case", ["zero", "missing", "version", "cap", "unknown_label"])
def test_invalid_single_unit_never_reaches_judge(case):
    def bad(call):
        output = extract_every_unit(call)
        if case == "zero":
            output["units"][0].update(status="non_factual", claims=[])
        elif case == "missing":
            output["units"][0]["unit_id"] = "foreign-unit"
        elif case == "version":
            output["resource_version"] += 1
        elif case == "cap":
            output["units"][0]["claims"] *= 16
        else:
            output["units"][0]["claims"][0]["knowledge_point_id"] = "foreign-label"
        return output
    state, _, repo, gateway, counter = state_for_extraction("Fact without a safe split")
    gateway.outcomes = [bad]
    with execution_session(state["run_id"], "owner"):
        result = extract(state, repo, gateway, counter)
    assert result["claim_check_status"] == "failed" and len(gateway.calls) == 1
    saved = repo.get(state["run_id"]).state
    assert next(iter(saved.results.values())).status == "failed"
    assert not next(iter(saved.results.values())).final_claims


def test_timeout_compressed_for_all_attempts_and_insufficient_time_zero_calls():
    class ThreeAttempts(NeutralScriptedGateway):
        def options_for(self, *args, **kwargs):
            return super().options_for(*args, **kwargs).model_copy(update=dict(max_attempts=3, schema_repair_attempts=1))
    gateway = ThreeAttempts([extract_every_unit])
    state, _, repo, gateway, counter = state_for_extraction(settings=neutral_settings(
        claim_extraction_max_request_seconds=1, claim_extraction_max_tokens=1000000), gateway=gateway)
    with execution_session(state["run_id"], "owner"):
        assert extract(state, repo, gateway, counter).get("extracted_claims")
    options = gateway.calls[0]["options"]
    # Per-attempt allocation no longer divides the first timeout by all possible retries.
    assert 0 < options.request_timeout_seconds == options.retry_request_timeout_seconds < 1
    assert repo.get(state["run_id"]).state.attempts == 1
    from datetime import datetime, timedelta, timezone
    state, _, repo, gateway, counter = state_for_extraction()
    state["workflow_deadline_at"] = datetime.now(timezone.utc) + timedelta(seconds=1)
    with execution_session(state["run_id"], "owner"):
        assert extract(state, repo, gateway, counter)["claim_check_status"] == "failed"
    assert gateway.calls == [] and repo.get(state["run_id"]).state.calls == 0


def test_two_resources_share_ledger_and_failed_sibling_does_not_block_success():
    state, _, repo, gateway, counter = state_for_extraction()
    resource = state["generated_resources"][0]
    empty = resource.model_copy(update=dict(resource_id="empty", content_text=""))
    second = resource.model_copy(update=dict(resource_id="second", content_text="Second fact."))
    state["generated_resources"] = [empty, resource, second]
    state["review_result"]["review_ids"].update(empty="review-empty", second="review-second")
    gateway.outcomes = [extract_every_unit, extract_every_unit, judge_all, judge_all]
    with execution_session(state["run_id"], "owner"):
        state.update(extract(state, repo, gateway, counter))
        assert state["claim_failed_resource_ids"] == ["empty"] and len(state["extracted_claims"]) == 2
        state.update(judge(state, repo, gateway, counter))
    assert len(gateway.calls) == 4
    assert [c["context"].node_name for c in gateway.calls] == ["claim_extractor"]*2 + ["claim_judge"]*2
    assert repo.get(state["run_id"]).state.calls == 2
    assert state["claim_metrics"]["empty"]["metric_status"] == "incomplete"


def test_real_gateway_schema_repair_reserves_and_accounts_every_attempt():
    import json
    from app.core.llm.gateway import LLMGateway
    from app.models.shared.llm import LLMCallOptions, RawLLMResponse, LLMUsage
    from tests.fakes.claim_extraction import NeutralScriptedTransport
    def valid(call):
        original = next(m for m in call["messages"] if '"target_units"' in str(m.content))
        output = extract_every_unit({"messages": [original]})
        return RawLLMResponse(content=output, usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15))
    transport = NeutralScriptedTransport([RawLLMResponse(content={"wrong": "🙂"*12000},
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)), valid])
    gateway = LLMGateway(transport, default_options=LLMCallOptions(max_attempts=3, schema_repair_attempts=1,
        structured_output_mode="text"), claim_schema_repair_attempts=1, retry_max_delay_seconds=0, sleep=lambda _: None)
    state, _, repo, _, counter = state_for_extraction(gateway=gateway, settings=neutral_settings(claim_extraction_max_tokens=1000000))
    with execution_session(state["run_id"], "owner"):
        result = extract(state, repo, gateway, counter)
    assert len(result["extracted_claims"]) == 1 and len(transport.calls) == 2
    ledger = repo.get(state["run_id"]).state
    assert len(ledger.tickets)==2 and ledger.attempts==2 and ledger.calls==1
    assert all(t.attempts==1 and t.actual_tokens==15 and t.settled for t in ledger.tickets.values())
    tickets=list(ledger.tickets.values())
    assert tickets[1].reserved_tokens > tickets[0].reserved_tokens
    assert any("🙂" in str(m.content) for m in transport.calls[-1]["messages"])
    assert "allowed_evidence" not in json.dumps([str(m.content) for m in transport.calls[-1]["messages"]])


@pytest.mark.parametrize("resource_type", ["讲义", "案例分析", "实操指南", "复习清单"])
@pytest.mark.parametrize("max_calls", [1, 8])
@pytest.mark.parametrize("rework", ["claim", "ordinary"])
def test_real_graph_claim_rework_uses_same_session_and_remaining_budget(monkeypatch, resource_type, max_calls, rework):
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.claim.memory import MemoryClaimRepository
    from tests.fakes.claim_extraction import graph_service
    audit, resources, claims = MemoryAuditRepository(), MemoryResourceRepository(), MemoryClaimRepository()
    service, gateway, _ = graph_service(monkeypatch, audit, resources, claims, fail_first_judge=True,
        settings=neutral_settings(resource_aware_retrieval_enabled=False, claim_extraction_max_calls=max_calls), service_counter_only=True)
    learner = LearnerProfile(learner_id="l", learner_type="test", education="本科", major="软件", learning_goal="Python", knowledge_base_id="kb-fixture")
    req = GenerateRequest(learner_id="l", topic="Python", resource_types=[resource_type], include_claim_check=True,
                          claim_max_iterations=1 if rework=="claim" else 0, max_iterations=1 if rework=="ordinary" else 0, profile_focus_mode="off")
    response = service.generate_with_run_id(learner, req, run_id="graph-neutral")
    ledger = service.claim_extraction_repository.get("graph-neutral").state
    assert ledger.session_closed and ledger.ledger_epoch == 1
    if max_calls == 8 and rework == "claim":
        assert response.workflow_status == "completed"
        assert ledger.calls == 2 and len(ledger.results) == 2
        assert {r.generation_attempt for r in ledger.results.values()} == {1,2}
        assert [c["context"].node_name for c in gateway.calls] == ["claim_extractor", "claim_judge"]*2
        assert response.resources[0].publication_status == "published"
        assert len(claims.list_claims_by_run("graph-neutral")) == 2
    else:
        assert ledger.calls == 1
        assert [c["context"].node_name for c in gateway.calls] == ["claim_extractor", "claim_judge"]
        assert response.resources[0].publication_status == "unpublished"
    assert audit.get_run("graph-neutral").status.value in {"completed", "human_review"}


@pytest.mark.parametrize("known_usage", [True, False])
def test_actual_gateway_truncated_parent_is_replaced_not_accumulated(known_usage):
    from app.core.llm.gateway import LLMGateway
    from app.models.shared.llm import LLMCallOptions, RawLLMResponse, LLMUsage
    from tests.fakes.claim_extraction import NeutralScriptedTransport
    seen = 0
    def transport_output(call):
        nonlocal seen
        seen += 1
        if seen == 1:
            original=next(m for m in call["messages"] if '"target_units"' in str(m.content))
            # Even valid complete-looking JSON cannot override finish_reason=length.
            return RawLLMResponse(content=extract_every_unit({"messages":[original]}), finish_reason="length",
                usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15) if known_usage else LLMUsage())
        original = next(m for m in call["messages"] if '"target_units"' in str(m.content))
        return RawLLMResponse(content=extract_every_unit({"messages":[original]}), usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15))
    transport = NeutralScriptedTransport([transport_output]*8)
    gateway = LLMGateway(transport,default_options=LLMCallOptions(max_attempts=1,schema_repair_attempts=0),claim_schema_repair_attempts=0)
    state, _, repo, _, counter = state_for_extraction("First fact.\n\nLast fact.",gateway=gateway)
    with execution_session(state["run_id"],"owner"):
        result=extract(state,repo,gateway,counter)
    # Unknown usage settles conservatively (the reserve stays deducted) but no
    # longer kills the resource: truncation subdivides and recovers (T36).
    assert len(result["extracted_claims"])==2 and len(transport.calls)==3
    saved=next(iter(repo.get(state["run_id"]).state.results.values()))
    assert len(saved.replaced_batches)==1 and len(saved.outputs)==2
    tickets=list(repo.get(state["run_id"]).state.tickets.values())
    assert tickets[0].settled and tickets[0].usage_status==("known" if known_usage else "unknown")


def test_transport_truncation_error_recovers_via_subdivision():
    # 11-01 regression (run 15f874a4): a LengthFinishReasonError surfaces as a
    # transport exception, settles failed/unknown-usage, and the old executor
    # treated it as fatal because observer.retry_allowed is always False on
    # error paths. Output-quality errors must route to bounded subdivision.
    from app.core.llm.gateway import LLMGateway
    from app.models.shared.llm import LLMCallOptions, RawLLMResponse, LLMUsage
    from tests.fakes.claim_extraction import NeutralScriptedTransport

    class LengthFinishReasonError(Exception):
        pass

    def valid(call):
        original=next(m for m in call["messages"] if '"target_units"' in str(m.content))
        return RawLLMResponse(content=extract_every_unit({"messages":[original]}),
            usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15))

    transport = NeutralScriptedTransport([LengthFinishReasonError("output budget exhausted"),valid,valid])
    gateway = LLMGateway(transport,default_options=LLMCallOptions(max_attempts=1,schema_repair_attempts=0),
        claim_schema_repair_attempts=0,retry_max_delay_seconds=0,sleep=lambda _: None)
    state, _, repo, _, counter = state_for_extraction("First fact.\n\nLast fact.",gateway=gateway)
    with execution_session(state["run_id"],"owner"):
        result=extract(state,repo,gateway,counter)
    assert len(result["extracted_claims"])==2 and len(transport.calls)==3
    ledger=repo.get(state["run_id"]).state
    tickets=list(ledger.tickets.values())
    assert tickets[0].status=="failed" and tickets[0].usage_status=="unknown" and tickets[0].settled
    assert all(t.status=="completed" and t.usage_status=="known" for t in tickets[1:])
    saved=next(iter(ledger.results.values()))
    assert saved.status=="completed" and len(saved.replaced_batches)==1 and len(saved.outputs)==2


def test_single_resource_retry_freezes_new_policy_and_uses_child_evidence(monkeypatch):
    from copy import deepcopy
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.claim.memory import MemoryClaimRepository
    from app.models.learning_documents.schemas import LearningResource
    from app.models.shared.persistence import canonical_hash
    from app.models.generation.dispatch import ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION as NEUTRAL_RESOURCE_RETRY_WORKFLOW_VERSION
    from tests.integration.workflow.test_resource_retry import fixture_state
    from tests.fakes.claim_extraction import graph_service
    state = fixture_state(e1=True)
    context = deepcopy(state["resource_retry_context"])
    learner = LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件",
                             learning_goal="test", knowledge_base_id="kb-fixture")
    request = GenerateRequest(learner_id="learner",topic="冻结主题",resource_types=["讲义"],include_claim_check=True,
                              target_skill_nodes=["node"],profile_focus_mode="off")
    context.update(learner=learner.model_dump(mode="json"), request=request.model_dump(mode="json"))
    context["context_hash"] = canonical_hash({k:v for k,v in context.items() if k != "context_hash"})
    audit, resources, claims = MemoryAuditRepository(), MemoryResourceRepository(), MemoryClaimRepository()
    parent=LearningResource.model_validate(context["source_resource"])
    resources.save(parent, "learner", request.topic, run_id="old-run")
    service,gateway,_=graph_service(monkeypatch,audit,resources,claims)
    jobs=GenerationJobService(SimpleNamespace(),service)
    dispatch=jobs._dispatch_snapshot(learner,request,context)
    assert dispatch["workflow_version"] == NEUTRAL_RESOURCE_RETRY_WORKFLOW_VERSION
    before=resources.get(parent.resource_id).model_dump(mode="json")
    response=service.generate_with_run_id(learner,request,run_id="new-neutral",resource_retry_context=context)
    assert response.workflow_status=="completed"
    resource=response.resources[0]
    assert resource.version==4 and resource.parent_resource_id==parent.resource_id
    assert resources.get(parent.resource_id).model_dump(mode="json")==before
    assert len(gateway.calls)==2
    evidence_ids={e.evidence_id for e in audit.list_evidence("new-neutral")}
    assert len(evidence_ids)==2 and not evidence_ids.intersection({"old-0","old-1","old-2"})
    assert all(set(j.evidence_ids)<=evidence_ids for j in claims.list_judgements_by_run("new-neutral"))
    assert all(c.run_id=="new-neutral" and c.review_id != parent.review_id for c in claims.list_claims_by_run("new-neutral"))


@pytest.mark.parametrize("structured",[True,False])
def test_assessment_runtime_payload_controls_bypass_not_submission_mode(structured):
    state,_,repo,gateway,counter=state_for_extraction()
    resource=state["generated_resources"][0]
    resource.resource_type="分阶测试题"
    resource.assessment_payload={"schema_version":"2.0"} if structured else None
    gateway.outcomes=[extract_every_unit,judge_all]
    with execution_session(state["run_id"],"owner"):
        state.update(extract(state,repo,gateway,counter))
        state.update(judge(state,repo,gateway,counter))
    assert state["claim_check_status"]=="completed"
    assert len(gateway.calls)==(0 if structured else 2)
    assert repo.get(state["run_id"]).state.calls==(0 if structured else 1)


def test_backoff_drift_before_extraction_and_review_drift_before_judge_fail_closed():
    state,_,repo,gateway,counter=state_for_extraction()
    gateway.retry_max_delay_seconds=3
    with execution_session(state["run_id"],"owner"):
        assert extract(state,repo,gateway,counter)["claim_check_status"]=="failed"
    assert gateway.calls==[] and repo.get(state["run_id"]).state.calls==0
    state,_,repo,gateway,counter=state_for_extraction()
    gateway.outcomes=[extract_every_unit,judge_all]
    with execution_session(state["run_id"],"owner"):
        state.update(extract(state,repo,gateway,counter))
        state["review_result"]["review_ids"]["r"]="changed-review"
        result=judge(state,repo,gateway,counter)
    assert result["claim_failed_resource_ids"]==["r"] and len(gateway.calls)==1


def test_real_graph_unknown_ticket_cannot_be_bypassed_by_advancing_attempt(monkeypatch):
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.claim.memory import MemoryClaimRepository
    from app.agents.resource_workflows.learning_documents import workflow
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import ExtractionAttemptObserver
    from tests.fakes.claim_extraction import graph_service
    audit=MemoryAuditRepository()
    service,gateway,_=graph_service(monkeypatch,audit,MemoryResourceRepository(),MemoryClaimRepository())
    real_decide=workflow.claim_decide_node
    def adversarial_decide(state):
        result=real_decide(state)
        if state["generation_attempt"]==1:
            result["review_result"].update(decision="revise",status="revise",revision_instructions=[
                dict(target_resource_type="讲义",target_claim_ids=["clm_"+"a"*32],action="synthetic forced retry")])
        return result
    monkeypatch.setattr(workflow,"claim_decide_node",adversarial_decide)
    # Recompile the actual graph with the adversarial routing input, retaining all
    # production extraction/ownership gates and one service-wide session.
    service.workflow=workflow.build_workflow(llm_gateway=gateway,lifecycle_repository=audit,
        claim_extraction_counter=service.claim_extraction_counter)
    def interrupted_settlement(*a,**kw):
        raise ValueError("synthetic lost result before atomic settlement")
    monkeypatch.setattr(ExtractionAttemptObserver,"settle",interrupted_settlement)
    learner=LearnerProfile(learner_id="l",learner_type="test",education="本科",major="软件",learning_goal="test",knowledge_base_id="kb-fixture")
    request=GenerateRequest(learner_id="l",topic="fixture",resource_types=["讲义"],include_claim_check=True,
                            claim_max_iterations=1,max_iterations=0,profile_focus_mode="off")
    with pytest.raises(ApplicationError):
        service.generate_with_run_id(learner,request,run_id="unknown-graph")
    state=service.claim_extraction_repository.get("unknown-graph").state
    assert len(gateway.calls)==state.calls==1
    assert len(state.results)==1 and all(t.status=="in_flight" for t in state.tickets.values())
    assert state.tokens==sum(t.tokens for t in state.tickets.values()) and not state.session_closed
    assert audit.get_run("unknown-graph").status.value=="failed"


@pytest.mark.parametrize("loss", ["dispatch_policy", "dispatch_both", "dispatch_version", "input_policy", "ledger", "input_and_ledger", "mode"])
def test_actual_worker_rejects_frozen_mode_corruption_before_any_model(tmp_path,monkeypatch,loss):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.shared.models import Base,AgentRunORM,ClaimExtractionRunORM,GenerationJobORM,LearnerProfileORM,KnowledgeBaseORM
    from app.db.audit.sql_repository import SQLAuditRepository
    from app.db.claim.sql_repository import SQLClaimRepository
    from app.db.learning_documents.sql_repository import SQLResourceRepository
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.worker import GenerationWorker
    from app.models.shared.persistence import CreateRunCommand,canonical_hash
    from tests.fakes.claim_extraction import graph_service
    engine=create_engine(f"sqlite:///{tmp_path/'corrupt.db'}",connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add(KnowledgeBaseORM(knowledge_base_id="kb-fixture",name="fixture"))
        db.add(LearnerProfileORM(learner_id="l",learner_type="test",education="本科",major="软件",learning_goal="test"))
        db.commit()
    audit=SQLAuditRepository(factory)
    service,gateway,_=graph_service(monkeypatch,audit,SQLResourceRepository(factory),SQLClaimRepository(factory))
    learner=LearnerProfile(learner_id="l",learner_type="test",education="本科",major="软件",learning_goal="test",knowledge_base_id="kb-fixture")
    request=GenerateRequest(learner_id="l",topic="fixture",resource_types=["讲义"],include_claim_check=True,profile_focus_mode="off")
    jobs=SQLGenerationJobRepository(factory)
    dispatch=GenerationJobService(jobs,service,dispatch_mode="worker")
    job=dispatch.create_job(learner,request,run_id="corrupt-worker")
    frozen=service.freeze_claim_extraction(request)
    state=build_workflow_state(learner,request,run_id=job.run_id,claim_extraction_snapshot=frozen)
    payload=_request_snapshot(request,state)
    audit.create_run(CreateRunCommand(run_id=job.run_id,learner_id="l",knowledge_base_id="kb-fixture",topic=request.topic,
        request_snapshot=payload,request_hash=canonical_hash(payload)))
    with factory() as db:
        row=db.get(GenerationJobORM,job.run_id)
        saved=dict(row.dispatch_snapshot)
        if loss in {"dispatch_policy","dispatch_both"}:
            saved.pop("claim_extraction_policy")
        if loss=="dispatch_both":
            saved.pop("claim_extraction_policy_hash")
        if loss=="dispatch_version":
            saved["workflow_version"]="learning_documents.v1"
        row.dispatch_snapshot=saved
        run=db.get(AgentRunORM,job.run_id)
        if loss in {"input_policy","input_and_ledger"}:
            run.input_payload={k:v for k,v in run.input_payload.items() if not k.startswith("claim_extraction_")}
        if loss in {"ledger","input_and_ledger"}:
            db.delete(db.get(ClaimExtractionRunORM,job.run_id))
        if loss=="mode":
            run.claim_extraction_mode="legacy_v3"
        db.commit()
    worker=GenerationWorker(jobs,SimpleNamespace(reconcile_incomplete_followups=lambda **_:0),lambda:dispatch,
        lease_seconds=1260,poll_seconds=.05)
    result=worker.run_once()
    assert result["claimed"]==1 and result["failed"]==1
    assert jobs.get(job.run_id).job_status=="failed" and gateway.calls==[]
    engine.dispose()
