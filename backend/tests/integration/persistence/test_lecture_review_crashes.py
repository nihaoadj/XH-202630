"""Inject real interruptions in RecordedNode and resume through the real runner."""
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.shared.recorded_node import RecordedNode
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.core.execution import ExecutionFence, execution_fence
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner
from tests.fakes.llm import ScriptedLLMGateway
from tests.integration.persistence.test_private_review_audit import repository as repository  # noqa: F401
from tests.unit.agents.test_lecture_review_v2_engine import builder


class Crash(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["begin_failure", "after_begin", "first_response",
                                     "correction_response", "before_checkpoint", "lost_lease"])
def test_actual_review_interruptions(repository, monkeypatch, boundary):  # noqa: F811
    from tests.integration.workflow.test_lecture_v2_end_to_end import _v2_state, _generator, REVISED_CONTENT
    from app.agents.resource_workflows.learning_documents import generator_agent
    state, _ = _v2_state(["融合分计算", "名次来源说明"], run_id="crash-run", include_claim=False)
    monkeypatch.setattr(generator_agent, "get_resource_agent", lambda _: _generator(revised_content=REVISED_CONTENT))
    state.update(generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([])))
    state["trace"] = []
    run_id = state["run_id"]
    now = datetime.now(timezone.utc)
    lease = now + timedelta(hours=1)
    snapshot = {key: state[key] for key in ("lecture_review_contract_version",
        "lecture_review_policy", "lecture_review_policy_hash", "review_policy")}
    repository.create_run(CreateRunCommand(run_id=run_id, request_snapshot=snapshot,
        request_hash=canonical_hash(snapshot), owner_instance_id="worker", lease_expires_at=lease))
    repository.start_run(run_id, occurred_at=now, lease_expires_at=lease)
    gateway = ScriptedLLMGateway([builder(missing=True), builder(missing=True, issue=True)])
    reached = []
    original_call = gateway.invoke_structured

    def call(**kwargs):
        result = original_call(**kwargs)
        count = len(gateway.calls)
        if boundary == "first_response" and count == 1:
            reached.append(boundary)
            raise Crash()
        if boundary == "correction_response" and count == 2:
            reached.append(boundary)
            raise Crash()
        if boundary == "lost_lease" and count == 1:
            if hasattr(repository, "session_factory"):
                from app.db.shared.models import AgentRunORM
                with repository.session_factory() as db:
                    db.get(AgentRunORM, run_id).lease_expires_at = now - timedelta(seconds=1)
                    db.commit()
            else:
                repository.runs[run_id]["lease_expires_at"] = now - timedelta(seconds=1)
            reached.append(boundary)
        return result
    monkeypatch.setattr(gateway, "invoke_structured", call)

    def node(current):
        if boundary == "after_begin":
            reached.append(boundary)
            raise Crash()
        value = review_node(current, llm_gateway=gateway, review_repository=repository)
        if boundary == "lost_lease":
            assert len(gateway.calls) == 1
            raise Crash()
        return value

    if boundary == "begin_failure":
        def fail(*args, **kwargs):
            reached.append(boundary)
            raise RuntimeError("injected begin write failure")
        monkeypatch.setattr(repository, "begin_step", fail)

    class Workflow:
        entered = 0
        def stream(self, initial, stream_mode=None):
            self.entered += 1
            update = RecordedNode("review", node, repository)(initial)
            if boundary == "before_checkpoint":
                assert repository.get_step_review_audit(run_id, update["review_audit"]["step_id"]).schema_version == "3.0"
                reached.append(boundary)
                raise Crash()
            yield {**initial, **update, "trace": [*initial.get("trace", []), *update["trace"]]}
    workflow = Workflow()
    runner = DurableWorkflowRunner(workflow, repository)
    with execution_fence(ExecutionFence(run_id, "worker")):
        with pytest.raises(BaseException) as failure:
            runner.invoke(state)
    assert reached == [boundary], repr(failure.value)
    expected_calls = {"begin_failure": 0, "after_begin": 0, "first_response": 1,
                      "correction_response": 2, "before_checkpoint": 2, "lost_lease": 1}
    assert len(gateway.calls) == expected_calls[boundary]
    assert all(r.publication_status != "published" for r in state["generated_resources"])
    if boundary != "begin_failure":
        entered = workflow.entered
        with execution_fence(ExecutionFence(run_id, "worker")):
            with pytest.raises(Exception):
                runner.invoke(state)
        assert workflow.entered == entered
        assert len(gateway.calls) == expected_calls[boundary]
