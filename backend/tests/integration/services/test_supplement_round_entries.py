"""T50 switches follow real round creation, correction and continuation."""
import pytest
from app.models.feedback.rounds import RoundCorrectionSelectionV1
from app.services.feedback.round_corrections import RoundCorrections
from tests.integration.services.test_round_generation import fixture, create_payload, publish, submit
from tests.integration.services.test_round_continuations import wired, continue_batch, continuation_payload


def assert_jobs(service, result, enabled):
    jobs = service.feedback.generation_job_service.job_repo
    ids = []
    for member in result.members:
        for ident in member.job_ids:
            request = jobs.get(ident).request_payload
            assert request["include_claim_check"] is enabled
            assert request["include_claim_evidence_retrieval"] is enabled
            assert len(request["resource_types"]) == 1 if enabled else True
            ids.append(ident)
    assert len(ids) == len(set(ids))
    return ids


@pytest.mark.parametrize("sql", [False, True])
def test_primary_and_review_and_correction_keep_independent_supplement_switches(sql):
    service, profile = fixture(sql)
    initial = service.create(profile, create_payload())
    publish(service, initial)
    submit(service, profile, initial, "first-submit")
    current = service.learners.get("learner")
    result = service._create_round(current, "supplement-dual", {"fixture": "dual"}, "b", ["讲义"], True,
                                   review_node_id="a", include_claim_evidence_retrieval=True)
    assert {member.role for member in result.members} == {"primary", "review"}
    ids = assert_jobs(service, result, True)
    bindings = [service.repository.one("learning_round_job_bindings", run_id=ident) for ident in ids]
    scopes = {row["stage_node_id"] for row in bindings}
    assert len(scopes) == 2
    stage = service.repository.one("learning_round_stages", stage_id=result.stage_id)
    assert scopes <= set(stage["budget_snapshot"]["scopes"])
    publish(service, result)
    submitted = submit(service, current, result, "dual-submit", "B")
    selection = RoundCorrectionSelectionV1(
        learner_id="learner", selection_key="supplement-correction", include_claim_check=True,
        include_claim_evidence_retrieval=True,
        targets=[{"node_id": item.node_id, "source_attempt_id": submitted.attempt_id} for item in submitted.nodes])
    correction = RoundCorrections(service).create(service.learners.get("learner"), result.round_id, selection)
    correction_ids = assert_jobs(service, correction, True)
    assert not set(ids) & set(correction_ids)
    assert RoundCorrections(service).create(service.learners.get("learner"), result.round_id, selection) == correction


@pytest.mark.parametrize("sql", [False, True])
def test_round_append_preserves_explicit_supplement_switch_and_idempotency(sql):
    service, profile = wired(sql)
    result = service.create(profile, create_payload())
    source = result.members[0].job_ids[0]
    payload = continuation_payload(source, include_claim_check=True, include_claim_evidence_retrieval=True)
    job, request = continue_batch(service, payload, "supplement-append")
    assert request.include_claim_check and request.include_claim_evidence_retrieval
    stored = service.feedback.generation_job_service.job_repo.get(job.run_id)
    assert stored.request_payload["include_claim_evidence_retrieval"] is True
    assert continue_batch(service, payload, "supplement-append")[0].run_id == job.run_id


@pytest.mark.parametrize("sql", [False, True])
def test_real_primary_and_review_bindings_charge_query_and_rejudge_to_their_own_scopes(sql):
    import hashlib
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from pydantic import BaseModel
    from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.budget import SupplementBudget, call_with_budget
    from app.core.llm.gateway import LLMGateway
    from app.db.audit.memory import MemoryAuditRepository
    from app.db.claim.memory import MemoryClaimRepository
    from app.db.claim.supplement import MemoryClaimSupplementRepository
    from app.models.learning_documents.schemas import GenerateRequest
    from app.models.reviews.claim_evidence_retrieval import (
        ClaimEvidenceRetrievalPolicyV1, ClaimEvidenceRetrievalSessionV1,
        ClaimEvidenceRetrievalBatchV1, ClaimEvidenceBatchKind, batch_id_for,
    )
    from app.models.shared.llm import LLMCallContext, LLMUsage, RawLLMResponse
    from tests.fakes.llm import ScriptedLLMTransport

    service, profile = fixture(sql)
    first = service.create(profile, create_payload())
    publish(service, first)
    submit(service, profile, first, "first-submit")
    current = service.learners.get("learner")
    result = service._create_round(current, "send-dual", {"fixture": "send"}, "b", ["讲义"], True,
                                   review_node_id="a", include_claim_evidence_retrieval=True)
    jobs = service.feedback.generation_job_service
    policy = ClaimEvidenceRetrievalPolicyV1(query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
                                            rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64)
    seen = []
    class Echo(BaseModel):
        ok: bool
    def generate(learner, request, *, run_id, **kwargs):
        now = datetime.now(timezone.utc)
        local = MemoryClaimSupplementRepository(claim_repository=MemoryClaimRepository(), audit_repository=MemoryAuditRepository())
        ledger = local.open_run(run_id=run_id, policy=policy, started_at=now,
                                 deadline_at=now + timedelta(seconds=600), owner="owner", epoch=1)
        sid = "cers_" + hashlib.sha256(run_id.encode()).hexdigest()[:32]
        local.create_session(ClaimEvidenceRetrievalSessionV1(
            session_id=sid, run_id=run_id, resource_id="res", resource_version=1, review_id="review",
            content_hash="a" * 64, policy_hash=policy.policy_hash, base_evidence_set_hash="b" * 64,
            initial_judgement_hash="c" * 64, target_claim_ids=["claim"]))
        budget = SupplementBudget(repository=local, ledger=ledger, policy=policy, owner="owner", epoch=1)
        gateway = LLMGateway(ScriptedLLMTransport([RawLLMResponse(
            content='{"ok":true}', finish_reason="stop", usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15))] * 2))
        for kind, node in [(ClaimEvidenceBatchKind.QUERY, "claim_evidence_retrieve"),
                           (ClaimEvidenceBatchKind.REJUDGE, "claim_evidence_rejudge")]:
            bid = batch_id_for(session_id=sid, kind=kind.value, ordinal=0, input_hash="e" * 64)
            local.save_batch(ClaimEvidenceRetrievalBatchV1(batch_id=bid, session_id=sid, kind=kind,
                                                          ordinal=0, input_hash="e" * 64))
            call_with_budget(gateway=gateway, budget=budget, batch_id=bid, logical_call_id=bid,
                messages=[], output_schema=Echo, output_cap=32, estimated_input=10, max_attempts=1,
                context_factory=lambda attempt, node=node, bid=bid: LLMCallContext(
                    run_id=run_id, step_id=node, node_name=node, schema_name="Echo", call_id=bid))
        assert local.get_run(run_id).known_tokens == 30
        seen.append(run_id)
        return SimpleNamespace()
    jobs.generation_service = SimpleNamespace(generate_with_run_id=generate)
    scopes = []
    for member in result.members:
        run_id = member.job_ids[0]
        request = GenerateRequest.model_validate(jobs.job_repo.get(run_id).request_payload)
        jobs._generate_with_budget(current, request, run_id=run_id)
        bound = service.repository.one("learning_round_job_bindings", run_id=run_id)
        scope = bound["stage_node_id"]
        scopes.append(scope)
        rows = service.repository.find("learning_round_budget_reservations", scope_id=scope)
        assert len(rows) == 2
        assert {row["run_id"] for row in rows} == {run_id}
        assert all(row["state"] == "settled" and row["known_tokens"] == 15 for row in rows)
    assert len(set(scopes)) == len(seen) == 2
