"""Round gateway guards reserve before dispatch and retain uncertain usage."""

import pytest

from app.core.llm.budget import LLMBudgetUnavailable, budgeted_transport_call, reserve_call
from app.core.llm.budget import effective_context, round_call_scope
from app.db.feedback.round_memory import MemoryRoundRepository
from app.models.shared.llm import LLMBudgetScope, LLMCallContext, LLMUsage, RawLLMResponse
from app.services.feedback.round_budget import RoundBudgetGuard
from tests.integration.persistence.test_learning_round_repository import NOW, round_values, add_member, add_stage, add_stage_member


def budget_fixture(cap=100):
    rounds = MemoryRoundRepository()
    with rounds.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
        add_stage(tx)
        add_stage_member(tx, "sa", "a", batch="batch")
        tx.compare_and_set("learning_round_stages", "s", 1, {"budget_snapshot": {"scopes": {"sa": cap}}})
        tx.insert("learning_round_job_bindings", dict(run_id="run", stage_node_id="sa", relation_kind="production", created_at=NOW))
    return rounds, RoundBudgetGuard(rounds)


def context(call="first"):
    return LLMCallContext(run_id="run", step_id="step", node_name="generate", schema_name="resource", call_id=call,
                          budget_scope=LLMBudgetScope(scope_id="sa", stage_id="s", kind="production"),
                          call_purpose="production", budget_input_token_cap=20)


def test_reservation_precedes_dispatch_and_complete_usage_releases_unused_capacity():
    rounds, guard = budget_fixture()
    ticket = reserve_call(guard, context(), 1, 50)

    def invoke(**kwargs):
        assert rounds.one("learning_round_budget_reservations", reservation_id=ticket)["state"] == "reserved"
        return RawLLMResponse(content="test", usage=LLMUsage(input_tokens=10, output_tokens=10))

    budgeted_transport_call(invoke, guard, ticket)
    assert rounds.one("learning_round_budget_reservations", reservation_id=ticket)["known_tokens"] == 20
    assert reserve_call(guard, context("second"), 1, 50)


def test_unknown_transport_usage_conservatively_consumes_the_reservation():
    rounds, guard = budget_fixture()
    ticket = reserve_call(guard, context(), 1, 50)

    def fail(**kwargs):
        raise TimeoutError("synthetic timeout")

    with pytest.raises(TimeoutError):
        budgeted_transport_call(fail, guard, ticket)
    assert rounds.one("learning_round_budget_reservations", reservation_id=ticket)["state"] == "unknown"
    with pytest.raises(LLMBudgetUnavailable, match="EXHAUSTED"):
        reserve_call(guard, context("second"), 1, 50)


def test_reusing_spent_attempt_identity_cannot_send_another_provider_request():
    _, guard = budget_fixture()
    reserve_call(guard, context(), 1, 10)
    with pytest.raises(LLMBudgetUnavailable, match="ALREADY_RESERVED"):
        reserve_call(guard, context(), 1, 10)


def test_scoped_call_without_guard_or_input_bound_fails_before_dispatch():
    with pytest.raises(LLMBudgetUnavailable, match="NOT_CONFIGURED"):
        reserve_call(None, context(), 1, 10)
    _, guard = budget_fixture()
    with pytest.raises(LLMBudgetUnavailable):
        reserve_call(guard, context().model_copy(update={"budget_input_token_cap": None}), 1, 10)


def test_unscoped_legacy_call_does_not_require_a_round_budget():
    legacy = context().model_copy(update={"budget_scope": None, "call_purpose": None})
    assert reserve_call(None, legacy, 1, 100000) is None
    assert budgeted_transport_call(lambda: "unchanged", None, None) == "unchanged"


def test_usage_overrun_blocks_subsequent_calls():
    _, guard = budget_fixture(1000)
    ticket = reserve_call(guard, context(), 1, 10)
    guard.settle(ticket, LLMUsage(input_tokens=50, output_tokens=50))
    with pytest.raises(LLMBudgetUnavailable, match="OVERRUN"):
        reserve_call(guard, context("second"), 1, 10)


def test_trusted_call_scope_is_reset_and_cannot_be_replaced_by_a_nested_scope():
    _, guard = budget_fixture()
    ordinary = context().model_copy(update={"budget_scope": None, "call_purpose": None})
    with round_call_scope(context().budget_scope, 20, guard):
        scoped = effective_context(ordinary)
        assert scoped.budget_scope == context().budget_scope
        assert scoped.call_id == ordinary.call_id
        assert reserve_call(None, scoped, 1, 10)
        other = LLMBudgetScope(scope_id="other", stage_id="s", kind="production")
        with pytest.raises(LLMBudgetUnavailable, match="NESTED_SCOPE"):
            with round_call_scope(other, 20, guard):
                pass
    assert effective_context(ordinary).budget_scope is None


def test_call_scope_does_not_leak_to_an_unrelated_thread():
    from concurrent.futures import ThreadPoolExecutor

    _, guard = budget_fixture()
    ordinary = context().model_copy(update={"budget_scope": None, "call_purpose": None})
    with round_call_scope(context().budget_scope, 20, guard):
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(effective_context, ordinary).result().budget_scope is None
