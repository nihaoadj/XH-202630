"""Budget fences and settlement use the same SQL/Memory storage contract."""

import pytest

from app.core.llm.budget import LLMBudgetUnavailable
from app.db.feedback.round_sql_repository import SQLRoundRepository
from app.db.shared.models import AgentRunORM, GenerationJobORM
from app.models.shared.llm import LLMUsage
from app.services.feedback.round_budget import RoundBudgetGuard
from tests.integration.persistence.test_learning_round_repository import (
    NOW, repository, round_values, add_member, add_stage, add_stage_member,  # noqa: F401
)
from tests.unit.core.test_round_budget_guard import context


def setup_budget(repository):
    if isinstance(repository, SQLRoundRepository):
        with repository.session_factory() as db:
            db.add(AgentRunORM(run_id="run", learner_id="learner", status="queued"))
            db.flush()
            db.add(GenerationJobORM(run_id="run", batch_id="batch", learner_id="learner", topic="test", status="queued"))
            db.commit()
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
        add_stage(tx)
        add_stage_member(tx, "sa", "a", batch="batch")
        tx.compare_and_set("learning_round_stages", "s", 1, {
            "budget_snapshot": {"scopes": {"sa": 100}, "runtime_scopes": {"sa": 10}},
        })
        tx.insert("learning_round_job_bindings", dict(run_id="run", stage_node_id="sa", relation_kind="production", created_at=NOW))
    return RoundBudgetGuard(repository)


def test_unknown_usage_and_elapsed_time_remain_charged(repository):
    guard = setup_budget(repository)
    first = guard.reserve(context(), 1, 60, 8)
    guard.settle(first, None)
    with pytest.raises(LLMBudgetUnavailable, match="RUNTIME_BUDGET"):
        guard.reserve(context("second"), 1, 10, 3)
    assert repository.one("learning_round_budget_reservations", reservation_id=first)["known_tokens"] is None


def test_settlement_releases_only_verified_unused_capacity(repository):
    guard = setup_budget(repository)
    first = guard.reserve(context(), 1, 60, 8)
    guard.settle(first, LLMUsage(input_tokens=5, output_tokens=5), 1)
    second = guard.reserve(context("second"), 1, 60, 8)
    assert first != second
    assert repository.one("learning_round_budget_reservations", reservation_id=first)["row_version"] == 2
    with pytest.raises(LLMBudgetUnavailable, match="EXHAUSTED"):
        guard.reserve(context("third"), 1, 90)


def test_scope_forgery_does_not_consume_capacity(repository):
    guard = setup_budget(repository)
    forged = context().model_copy(update={"run_id": "unrelated"})
    with pytest.raises(LLMBudgetUnavailable, match="RUN_MISMATCH"):
        guard.reserve(forged, 1, 60, 8)
    assert repository.find("learning_round_budget_reservations") == []


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
def test_concurrent_distinct_calls_cannot_overbook_a_scope(storage, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.feedback.round_memory import MemoryRoundRepository
    from app.db.shared.database import configure_sqlite_foreign_keys
    from app.db.shared.models import Base, LearnerProfileORM

    engine = None
    if storage == "memory":
        rounds = MemoryRoundRepository()
    else:
        engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'budget.db'}"))
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(LearnerProfileORM(learner_id="learner", learner_type="test", education="test", major="test", learning_goal="test"))
            db.commit()
        rounds = SQLRoundRepository(factory)
    guard = setup_budget(rounds)

    def attempt(index):
        try:
            return guard.reserve(context(f"parallel-{index}"), 1, 30)
        except LLMBudgetUnavailable as error:
            assert "EXHAUSTED" in str(error)
            return None

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(attempt, range(8)))
        assert sum(result is not None for result in results) == 3
        assert sum(row["reserved_tokens"] for row in rounds.find("learning_round_budget_reservations")) == 90
    finally:
        if engine is not None:
            engine.dispose()
