"""Production budget scope must survive workflow threads and retries."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timezone

import pytest

from app.core.llm.budget import (
    LLMBudgetUnavailable, effective_context, reserve_call, round_call_scope,
)
from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.models.shared.llm import LLMBudgetScope, LLMCallContext, LLMUsage
from app.services.feedback.round_budget import RoundBudgetGuard
from app.services.generation.jobs import GenerationJobService
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile


INPUT_CAP = 500
SCOPE_CAP = 1200


def round_repository(seconds_cap=60):
    repository = MemoryRoundRepository()
    now = datetime.now(timezone.utc)
    with repository.transaction() as tx:
        tx.insert("learning_rounds", dict(
            round_id="round", learner_id="learner", knowledge_base_id="kb", protocol_version="learning-round/v1",
            selection_key="selection", selection_hash="hash", budget_snapshot={"L": 2, "H": 2},
            created_at=now,
        ))
        tx.insert("learning_round_nodes", dict(
            round_node_id="rn", round_id="round", skill_node_id="node", role="primary", tier=1, name="node",
        ))
        tx.insert("learning_round_stages", dict(
            stage_id="stage", round_id="round", kind="initial", ordinal=0, selection_key="selection",
            selection_hash="hash", state="producing", budget_snapshot={
                "L": 2, "H": 2, "resource_tokens": SCOPE_CAP, "workflow_seconds": 60, "input_capacity": INPUT_CAP,
                "scopes": {"sn": SCOPE_CAP}, "runtime_scopes": {"sn": seconds_cap},
            }, created_at=now,
        ))
        tx.insert("learning_round_stage_nodes", dict(
            stage_node_id="sn", stage_id="stage", round_node_id="rn", batch_id="batch",
            request_snapshot={}, resource_types=["讲义"], difficulty="初级", config_hash="config",
        ))
        for run_id in ("run-1", "run-2"):
            tx.insert("learning_round_job_bindings", dict(
                run_id=run_id, stage_node_id="sn", relation_kind="production", created_at=now,
            ))
    return repository


class ThreadedGeneration:
    """A stand-in workflow that fans out model calls exactly like resource agents."""

    def __init__(self, repository, workers=2, settle_usage=None):
        self.repository = repository
        self.workers = workers
        self.settle_usage = settle_usage
        self.thread_scopes = []
        self.reservations = []

    def generate_with_run_id(self, learner, request, *, run_id, **kwargs):
        guard = RoundBudgetGuard(self.repository)

        def work(index):
            raw = LLMCallContext(run_id=run_id, step_id=f"step-{index}", node_name="generate",
                                 schema_name="fixture", call_id=f"call-{run_id}-{index}")
            # Same helper the Gateway uses; it reads the inherited ContextVar.
            context = effective_context(raw)
            self.thread_scopes.append(context.budget_scope)
            if context.budget_scope is None:
                return None
            reservation = reserve_call(None, context, 1, output_cap=10)
            guard.settle(reservation, self.settle_usage)
            self.reservations.append(reservation)
            return reservation

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="resource-worker") as pool:
            futures = [pool.submit(copy_context().run, work, index) for index in range(self.workers)]
            return [future.result() for future in futures]


def service_for(repository, workflow):
    learner = LearnerProfile(learner_id="learner", learner_type="test", education="test", major="test",
                             knowledge_base_id="kb", learning_goal="test")
    service = GenerationJobService(MemoryGenerationJobRepository(), workflow, None, round_repository=repository)
    request = GenerateRequest(learner_id="learner", knowledge_base_id="kb", topic="node",
                              target_skill_nodes=["node"], resource_types=["讲义"], difficulty_preference="初级")
    return service, learner, request


def test_workflow_threads_inherit_the_production_scope_and_unknown_usage_stays_charged():
    repository = round_repository()
    workflow = ThreadedGeneration(repository)
    service, learner, request = service_for(repository, workflow)

    service._generate_with_budget(learner, request, run_id="run-1")

    assert [scope.scope_id for scope in workflow.thread_scopes] == ["sn", "sn"]
    assert all(scope.kind == "production" for scope in workflow.thread_scopes)
    rows = repository.find("learning_round_budget_reservations", scope_id="sn")
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {"unknown"}
    assert sum(row["reserved_tokens"] for row in rows) == 2 * (INPUT_CAP + 10)


def test_retry_reuses_the_scope_and_stops_on_exhaustion():
    repository = round_repository()
    workflow = ThreadedGeneration(repository)
    service, learner, request = service_for(repository, workflow)

    service._generate_with_budget(learner, request, run_id="run-1")
    with pytest.raises(LLMBudgetUnavailable) as caught:
        service._generate_with_budget(learner, request, run_id="run-2")
    assert str(caught.value) == "ROUND_BUDGET_EXHAUSTED"
    # The failed retry never silently switched to another scope or unlimited calls.
    assert {row["run_id"] for row in repository.find("learning_round_budget_reservations", scope_id="sn")} == {"run-1"}


def test_scope_is_not_leaked_to_the_caller_or_to_an_assessment_scope():
    repository = round_repository()
    workflow = ThreadedGeneration(repository, workers=1)
    service, learner, request = service_for(repository, workflow)
    service._generate_with_budget(learner, request, run_id="run-1")

    tutor_context = LLMCallContext(run_id="run-1", step_id="tutor", node_name="tutor", schema_name="answer")
    assert effective_context(tutor_context).budget_scope is None
    assert reserve_call(None, tutor_context, 1, output_cap=10) is None
    assert len(repository.find("learning_round_budget_reservations", scope_id="sn")) == 1

    with round_call_scope(LLMBudgetScope(scope_id="sn", stage_id="stage", kind="production"),
                          input_cap=INPUT_CAP, guard=RoundBudgetGuard(repository)):
        with pytest.raises(LLMBudgetUnavailable) as caught:
            effective_context(LLMCallContext(
                run_id="run-1", step_id="grade", node_name="grade", schema_name="grade",
                budget_scope=LLMBudgetScope(scope_id="session", stage_id="stage", kind="assessment"),
                call_purpose="assessment",
            ))
    assert str(caught.value) == "ROUND_BUDGET_CONTEXT_MISMATCH"


def test_settled_usage_returns_unused_reservation():
    repository = round_repository()
    workflow = ThreadedGeneration(repository, workers=1, settle_usage=LLMUsage(input_tokens=20, output_tokens=5))
    service, learner, request = service_for(repository, workflow)
    service._generate_with_budget(learner, request, run_id="run-1")

    row = repository.find("learning_round_budget_reservations", scope_id="sn")[0]
    assert (row["state"], row["known_tokens"]) == ("settled", 25)
    # Real usage (25) leaves room for a second attempt on the same scope.
    service._generate_with_budget(learner, request, run_id="run-2")
    assert len(repository.find("learning_round_budget_reservations", scope_id="sn")) == 2
