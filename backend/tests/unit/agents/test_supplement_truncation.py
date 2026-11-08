"""One truncation upgrade per logical call, with exact per-attempt accounting."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval import budget as budget_module
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.budget import (
    SupplementBudget,
    SupplementBudgetExceeded,
    call_with_budget,
)
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.core.security.errors import ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.supplement import MemoryClaimSupplementRepository
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceAttemptStatus,
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    batch_id_for,
)
from app.models.shared.llm import LLMCallContext, LLMUsage, RawLLMResponse
from tests.fakes.llm import ScriptedLLMTransport

T0 = datetime.now(timezone.utc)


class Echo(BaseModel):
    ok: bool = True


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


def _policy(**overrides):
    values = dict(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        max_estimated_tokens=100_000,
        attempts_per_call=2,
    )
    values.update(overrides)
    return ClaimEvidenceRetrievalPolicyV1(**values)


def _setup(policy=None):
    policy = policy or _policy()
    repository = MemoryClaimSupplementRepository(
        claim_repository=MemoryClaimRepository(),
        audit_repository=MemoryAuditRepository(),
    )
    repository.create_session(ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32, run_id="run-1", resource_id="res-1",
        resource_version=1, review_id="rev-1", content_hash="a" * 64,
        policy_hash=policy.policy_hash, base_evidence_set_hash="b" * 64,
        initial_judgement_hash="c" * 64, target_claim_ids=["clm_" + "1" * 32],
        created_at=T0, updated_at=T0,
    ))
    ledger = repository.open_run(
        run_id="run-1", policy=policy, started_at=T0,
        deadline_at=T0 + timedelta(seconds=600), owner="owner-1", epoch=1,
    )
    batch_id = batch_id_for(
        session_id="cers_" + "1" * 32, kind=ClaimEvidenceBatchKind.QUERY,
        ordinal=1, input_hash="a" * 64,
    )
    repository.save_batch(ClaimEvidenceRetrievalBatchV1(
        batch_id=batch_id, session_id="cers_" + "1" * 32,
        kind=ClaimEvidenceBatchKind.QUERY, ordinal=1, input_hash="a" * 64,
        status=ClaimEvidenceBatchStatus.PLANNED, expected_claim_ids=["clm_1"],
        payload={"claims": ["clm_1"]}, updated_at=T0,
    ))
    budget = SupplementBudget(
        repository=repository, ledger=ledger, policy=policy,
        owner="owner-1", epoch=1,
    )
    return repository, budget, batch_id


def _response(*, finish_reason="stop", content='{"ok": true}', usage=None, call_id="call-1"):
    return RawLLMResponse(
        content=content,
        usage=usage if usage is not None else LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason=finish_reason, provider_request_id=f"req-{call_id}",
    )


def _call(gateway, repository, budget, batch_id, *, output_cap=50, truncated_cap=150, max_attempts=2):
    return call_with_budget(
        gateway=gateway, budget=budget, batch_id=batch_id,
        logical_call_id=f"{batch_id}:rejudge",
        messages=[],
        output_schema=Echo,
        output_cap=output_cap,
        truncated_output_cap=truncated_cap,
        context_factory=lambda attempt_no: LLMCallContext(
            run_id="run-1", step_id="step-1", node_name="claim_evidence_rejudge",
            schema_name="Echo", call_id=f"call-{attempt_no}",
            workflow_deadline_at=budget.deadline_at,
        ),
        estimated_input=20,
        max_attempts=max_attempts,
    )


def _attempts(repository):
    return [(item.status, item.output_cap, item.reserved_tokens)
            for item in repository.list_attempts("run-1")]


def test_length_terminated_valid_json_upgrades_exactly_once(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(budget_module, "utcnow", clock)
    repository, budget, batch_id = _setup()
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", call_id="call-1"),
        _response(finish_reason="stop", call_id="call-2"),
    ])
    result, attempt_no = _call(LLMGateway(transport), repository, budget, batch_id)
    assert attempt_no == 2 and result.output.ok is True
    assert [item["max_output_tokens"] for item in transport.calls] == [50, 150]
    attempts = _attempts(repository)
    assert attempts[0][:2] == (ClaimEvidenceAttemptStatus.SUCCEEDED, 50)
    assert attempts[1][:2] == (ClaimEvidenceAttemptStatus.SUCCEEDED, 150)
    # Each observer reservation used the cap of its own attempt.
    assert [item[2] for item in attempts] == [70, 170]
    settled = repository.get_run("run-1")
    assert settled.known_tokens == 30 and settled.unknown_tokens == 0 and settled.reserved_tokens == 0


def test_a_second_truncation_stops_without_a_third_send():
    repository, budget, batch_id = _setup(_policy(attempts_per_call=3))
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", call_id="call-1"),
        _response(finish_reason="length", call_id="call-2"),
        _response(finish_reason="stop", call_id="call-3"),
    ])
    with pytest.raises(LLMGatewayError) as caught:
        _call(LLMGateway(transport), repository, budget, batch_id, max_attempts=3)
    assert caught.value.error.code == ErrorCode.LLM_OUTPUT_TRUNCATED.value
    assert len(transport.calls) == 2
    assert [item["max_output_tokens"] for item in transport.calls] == [50, 150]
    assert [item.status for item in repository.list_attempts("run-1")] == [
        ClaimEvidenceAttemptStatus.SUCCEEDED, ClaimEvidenceAttemptStatus.SUCCEEDED,
    ]


def test_truncated_exception_uses_the_same_single_upgrade():
    repository, budget, batch_id = _setup(_policy(attempts_per_call=3))
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", content='{"ok": tr', call_id="call-1"),
        _response(finish_reason="stop", call_id="call-2"),
        _response(finish_reason="stop", call_id="call-3"),
    ])
    result, attempt_no = _call(LLMGateway(transport), repository, budget, batch_id, max_attempts=3)
    assert attempt_no == 2 and result.finish_reason == "stop"
    assert [item["max_output_tokens"] for item in transport.calls] == [50, 150]
    # The provider did answer, so the first attempt settled its known usage;
    # truncation is recorded by the gateway error, not by rewriting the tokens.
    first = repository.list_attempts("run-1")[0]
    assert first.status is ClaimEvidenceAttemptStatus.SUCCEEDED
    assert first.known_tokens == 15
    settled = repository.get_run("run-1")
    assert settled.known_tokens == 30 and settled.unknown_tokens == 0


def test_non_truncation_failures_keep_the_frozen_cap():
    repository, budget, batch_id = _setup(_policy(attempts_per_call=3))
    transport = ScriptedLLMTransport([
        TimeoutError("synthetic timeout"),
        _response(finish_reason="stop", call_id="call-2"),
        _response(finish_reason="stop", call_id="call-3"),
    ])
    result, attempt_no = _call(LLMGateway(transport), repository, budget, batch_id, max_attempts=3)
    assert attempt_no == 2
    assert [item["max_output_tokens"] for item in transport.calls] == [50, 50]


def test_an_equal_or_smaller_upgrade_cap_is_not_a_real_upgrade():
    repository, budget, batch_id = _setup()
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", call_id="call-1"),
        _response(finish_reason="stop", call_id="call-2"),
    ])
    with pytest.raises(LLMGatewayError):
        _call(LLMGateway(transport), repository, budget, batch_id, truncated_cap=50)
    assert len(transport.calls) == 1


def test_upgrade_is_skipped_when_the_token_ledger_cannot_fit_it():
    repository, budget, batch_id = _setup(_policy(max_estimated_tokens=1024))
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", call_id="call-1"),
        _response(finish_reason="stop", call_id="call-2"),
    ])
    with pytest.raises(SupplementBudgetExceeded):
        _call(LLMGateway(transport), repository, budget, batch_id,
              output_cap=900, truncated_cap=1500)
    assert len(transport.calls) == 1
    settled = repository.get_run("run-1")
    assert settled.known_tokens == 15 and settled.unknown_tokens == 0
    assert settled.attempts == 1


def test_no_second_send_when_the_frozen_attempt_budget_is_spent():
    repository, budget, batch_id = _setup(_policy(attempts_per_call=1))
    transport = ScriptedLLMTransport([
        _response(finish_reason="length", call_id="call-1"),
        _response(finish_reason="stop", call_id="call-2"),
    ])
    with pytest.raises(LLMGatewayError):
        _call(LLMGateway(transport), repository, budget, batch_id, max_attempts=1)
    assert len(transport.calls) == 1
    attempts = repository.list_attempts("run-1")
    # The first attempt was reserved and settled; no second attempt exists.
    assert len(attempts) == 1 and attempts[0].status is ClaimEvidenceAttemptStatus.SUCCEEDED


def test_expired_wall_clock_blocks_the_upgrade_send(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(budget_module, "utcnow", clock)
    repository, budget, batch_id = _setup()
    transport = ScriptedLLMTransport([
        lambda kwargs: (_ for _ in ()).throw(TimeoutError("synthetic timeout")),
        _response(finish_reason="stop", call_id="call-2"),
    ])
    original = transport.invoke

    def invoke(**kwargs):
        try:
            return original(**kwargs)
        finally:
            clock.advance(700)

    transport.invoke = invoke
    with pytest.raises(SupplementBudgetExceeded):
        _call(LLMGateway(transport), repository, budget, batch_id)
    assert len(transport.calls) == 1
    assert repository.get_run("run-1").reserved_tokens == 0
    # The failed send kept its reservation as unknown; no free retry was granted.
    assert repository.get_run("run-1").unknown_tokens > 0


def test_query_path_without_an_upgrade_cap_accepts_a_valid_length_answer():
    repository, budget, batch_id = _setup()
    transport = ScriptedLLMTransport([_response(finish_reason="length", call_id="call-1")])
    result, attempt_no = _call(
        LLMGateway(transport), repository, budget, batch_id, truncated_cap=None, max_attempts=1)
    assert attempt_no == 1 and result.output.ok is True
    assert len(transport.calls) == 1
