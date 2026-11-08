"""Dispatch boundary: reserve -> write-ahead intent -> settle.

These tests use the real gateway, the real round budget guard and the real
Memory supplement ledger.  Only the provider transport and the capacity number
of the enclosing scope are controlled; the settlement logic under test is never
mocked.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.budget import (
    SupplementBudget,
    call_with_budget,
)
from app.core.llm.budget import LLMBudgetUnavailable, effective_context, round_call_scope
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.supplement import MemoryClaimSupplementRepository, PersistenceConflict
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceAttemptStatus,
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    batch_id_for,
)
from app.models.shared.llm import (
    LLMAttemptSummary,
    LLMBudgetScope,
    LLMCallContext,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from tests.fakes.llm import ScriptedLLMTransport
from tests.unit.core.test_round_budget_guard import budget_fixture

NOW = datetime.now(timezone.utc)
POLICY = ClaimEvidenceRetrievalPolicyV1(
    query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
    rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
    max_estimated_tokens=100_000,
)


class Echo(BaseModel):
    ok: bool = True


def _round_guard(cap: int, runtime_cap: int = 600):
    rounds, guard = budget_fixture(cap=cap)
    with rounds.transaction() as tx:
        row = tx.one("learning_round_stages", stage_id="s")
        snapshot = dict(row["budget_snapshot"])
        snapshot["runtime_scopes"] = {"sa": runtime_cap}
        tx.compare_and_set("learning_round_stages", "s", row["row_version"],
                           {"budget_snapshot": snapshot})
    return rounds, guard


def _repository():
    repository = MemoryClaimSupplementRepository(
        claim_repository=MemoryClaimRepository(),
        audit_repository=MemoryAuditRepository(),
    )
    repository.create_session(ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32, run_id="run-1", resource_id="res-1",
        resource_version=1, review_id="rev-1", content_hash="a" * 64,
        policy_hash=POLICY.policy_hash, base_evidence_set_hash="b" * 64,
        initial_judgement_hash="c" * 64, target_claim_ids=["clm_" + "1" * 32],
        created_at=NOW, updated_at=NOW,
    ))
    return repository


def _ledger(repository):
    return repository.open_run(
        run_id="run-1", policy=POLICY, started_at=NOW,
        deadline_at=NOW + timedelta(seconds=600), owner="owner-1", epoch=1,
    )


def _batch(repository):
    ident = batch_id_for(
        session_id="cers_" + "1" * 32, kind=ClaimEvidenceBatchKind.QUERY,
        ordinal=1, input_hash="a" * 64,
    )
    repository.save_batch(ClaimEvidenceRetrievalBatchV1(
        batch_id=ident, session_id="cers_" + "1" * 32,
        kind=ClaimEvidenceBatchKind.QUERY, ordinal=1, input_hash="a" * 64,
        status=ClaimEvidenceBatchStatus.PLANNED, expected_claim_ids=["clm_1"],
        payload={"claims": ["clm_1"]}, updated_at=NOW,
    ))
    return ident


def _budget(repository, ledger):
    return SupplementBudget(
        repository=repository, ledger=ledger, policy=POLICY,
        owner="owner-1", epoch=1,
    )


def _call(gateway, repository, budget, batch_id, *, max_attempts=1):
    return call_with_budget(
        gateway=gateway, budget=budget, batch_id=batch_id,
        logical_call_id=f"{batch_id}:query",
        messages=[],
        output_schema=Echo,
        output_cap=50,
        context_factory=lambda attempt_no: LLMCallContext(
            run_id="run", step_id="step-1", node_name="claim_evidence_retrieve",
            schema_name="Echo", call_id=f"{batch_id}:{attempt_no}",
            workflow_deadline_at=budget.deadline_at,
        ),
        estimated_input=20,
        max_attempts=max_attempts,
    )


def _known_response(call_id="call-1"):
    usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    return RawLLMResponse(
        content='{"ok": true}', usage=usage, finish_reason="stop",
        provider_request_id="req-1",
    )


def _gateway(transport):
    return LLMGateway(transport)


def test_upper_guard_refusal_settles_the_local_reservation_as_not_sent():
    rounds, guard = _round_guard(cap=10)  # 20 input + 50 output cannot fit
    scope = LLMBudgetScope(scope_id="sa", stage_id="s", kind="production")
    repository = _repository()
    ledger = _ledger(repository)
    batch_id = _batch(repository)
    budget = _budget(repository, ledger)
    transport = ScriptedLLMTransport([_known_response()])
    gateway = _gateway(transport)

    with round_call_scope(scope, 100_000, guard):
        with pytest.raises(LLMBudgetUnavailable):
            _call(gateway, repository, budget, batch_id)

    # The provider was never entered.
    assert transport.calls == []
    attempts = repository.list_attempts("run-1")
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.status is ClaimEvidenceAttemptStatus.NOT_SENT
    assert attempt.unknown_usage is False and attempt.known_tokens is None
    settled = repository.get_run("run-1")
    # Only a definitely-not-sent attempt may release its reservation.
    assert (settled.reserved_tokens, settled.known_tokens, settled.unknown_tokens) == (0, 0, 0)
    assert settled.attempts == 1


def test_upper_and_local_caps_intersect_at_exactly_one_token():
    rounds, guard = _round_guard(cap=100_050)  # exactly 100000 + 50
    scope = LLMBudgetScope(scope_id="sa", stage_id="s", kind="production")
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    transport = ScriptedLLMTransport([_known_response()])
    with round_call_scope(scope, 100_000, guard):
        result, _attempt = _call(_gateway(transport), repository, budget, batch_id)
    assert result.output.ok is True and len(transport.calls) == 1

    rounds_one, guard_one = _round_guard(cap=100_049)  # one token short
    repository_two = _repository()
    budget_two = _budget(repository_two, _ledger(repository_two))
    batch_two = _batch(repository_two)
    transport_two = ScriptedLLMTransport([_known_response()])
    with round_call_scope(LLMBudgetScope(scope_id="sa", stage_id="s", kind="production"), 100_000, guard_one):
        with pytest.raises(LLMBudgetUnavailable):
            _call(_gateway(transport_two), repository_two, budget_two, batch_two)
    assert transport_two.calls == []


def test_transport_failure_after_dispatch_keeps_the_reservation_as_unknown():
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    transport = ScriptedLLMTransport([TimeoutError("synthetic timeout")])
    with pytest.raises(LLMGatewayError):
        _call(_gateway(transport), repository, budget, batch_id)

    attempt = repository.list_attempts("run-1")[0]
    assert attempt.status is ClaimEvidenceAttemptStatus.FAILED
    assert attempt.unknown_usage is True
    settled = repository.get_run("run-1")
    assert settled.reserved_tokens == 0
    # The reserved amount was conservatively charged; unknown is never zero.
    assert settled.unknown_tokens == attempt.reserved_tokens == 70
    assert settled.known_tokens == 0


def test_complete_usage_settles_known_tokens_and_incomplete_usage_stays_unknown():
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    transport = ScriptedLLMTransport([_known_response()])
    _call(_gateway(transport), repository, budget, batch_id, max_attempts=1)
    attempt = repository.list_attempts("run-1")[0]
    assert attempt.status is ClaimEvidenceAttemptStatus.SUCCEEDED
    settled = repository.get_run("run-1")
    assert (settled.known_tokens, settled.unknown_tokens, settled.reserved_tokens) == (15, 0, 0)

    repository_two = _repository()
    budget_two = _budget(repository_two, _ledger(repository_two))
    batch_two = _batch(repository_two)
    partial = RawLLMResponse(
        content='{"ok": true}',
        usage=LLMUsage(input_tokens=10, output_tokens=None, total_tokens=None),
        finish_reason="stop", provider_request_id="req-2",
    )
    _call(_gateway(ScriptedLLMTransport([partial])), repository_two, budget_two, batch_two)
    attempt_two = repository_two.list_attempts("run-1")[0]
    assert attempt_two.status is ClaimEvidenceAttemptStatus.USAGE_UNKNOWN
    settled_two = repository_two.get_run("run-1")
    assert settled_two.unknown_tokens == attempt_two.reserved_tokens
    assert settled_two.known_tokens == 0


def test_attempt_settlement_is_idempotent_and_conflicts_are_rejected():
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    _call(_gateway(ScriptedLLMTransport([_known_response()])), repository, budget, batch_id)
    attempt = repository.list_attempts("run-1")[0]
    again = repository.settle_attempt(
        run_id="run-1", attempt_id=attempt.attempt_id, owner="owner-1", epoch=1,
        status=ClaimEvidenceAttemptStatus.SUCCEEDED, known_tokens=15, now=NOW,
    )
    assert again.known_tokens == 15
    with pytest.raises(PersistenceConflict):
        repository.settle_attempt(
            run_id="run-1", attempt_id=attempt.attempt_id, owner="owner-1", epoch=1,
            status=ClaimEvidenceAttemptStatus.FAILED, known_tokens=None, now=NOW,
        )


def test_stale_owner_or_epoch_cannot_settle():
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    _call(_gateway(ScriptedLLMTransport([_known_response()])), repository, budget, batch_id)
    attempt = repository.list_attempts("run-1")[0]
    for owner, epoch in (("owner-2", 1), ("owner-1", 2)):
        with pytest.raises(PersistenceConflict):
            repository.settle_attempt(
                run_id="run-1", attempt_id=attempt.attempt_id, owner=owner, epoch=epoch,
                status=ClaimEvidenceAttemptStatus.SUCCEEDED, known_tokens=15, now=NOW,
            )


def test_not_sent_cannot_close_an_attempt_that_already_dispatched():
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    batch_id = _batch(repository)
    _call(_gateway(ScriptedLLMTransport([_known_response()])), repository, budget, batch_id)
    attempt = repository.list_attempts("run-1")[0]
    with pytest.raises(PersistenceConflict):
        repository.settle_attempt(
            run_id="run-1", attempt_id=attempt.attempt_id, owner="owner-1", epoch=1,
            status=ClaimEvidenceAttemptStatus.NOT_SENT, known_tokens=None, now=NOW,
        )
    assert repository.get_run("run-1").known_tokens == 15


def test_query_and_rejudge_attempts_share_the_same_production_budget():
    """Real Gateway + local observer + RoundBudgetGuard, no fake reservations."""
    rounds, guard = _round_guard(cap=100_070)
    scope = LLMBudgetScope(scope_id="sa", stage_id="s", kind="production")
    repository = _repository()
    budget = _budget(repository, _ledger(repository))
    query = _batch(repository)
    template = repository.get_batch(query)
    rejudge = template.model_copy(update={
        "batch_id": batch_id_for(session_id=template.session_id, kind="rejudge", ordinal=0, input_hash="b" * 64),
        "kind": ClaimEvidenceBatchKind.REJUDGE, "ordinal": 0, "input_hash": "b" * 64,
    })
    repository.save_batch(rejudge)
    third = template.model_copy(update={
        "batch_id": batch_id_for(session_id=template.session_id, kind="query", ordinal=2, input_hash="c" * 64),
        "ordinal": 2, "input_hash": "c" * 64,
    })
    repository.save_batch(third)
    transport = ScriptedLLMTransport([_known_response(), _known_response(), _known_response()])
    with round_call_scope(scope, 100_000, guard):
        _call(_gateway(transport), repository, budget, query)
        _call(_gateway(transport), repository, budget, rejudge.batch_id)
        with pytest.raises(LLMBudgetUnavailable):
            _call(_gateway(transport), repository, budget, third.batch_id)
    assert len(transport.calls) == 2
    attempts = repository.list_attempts("run-1")
    assert len(attempts) == 3
    assert sum(item.status is ClaimEvidenceAttemptStatus.NOT_SENT for item in attempts) == 1
    assert repository.get_run("run-1").known_tokens == 30
    assert repository.get_run("run-1").reserved_tokens == 0
