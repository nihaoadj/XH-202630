from datetime import datetime, timezone

from app.models.agent_contracts import build_trace_item, start_step
from app.models.persistence import canonical_hash
from app.models.workflow import StepStatus
from app.services.durable_workflow_runner import DurableWorkflowRunner
from app.services.recorded_node import RecordedNode
from app.agents import workflow as workflow_module
from app.models.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation_service import build_workflow_state
from tests.fakes.evidence import make_evidence
from backend.tests.fakes.persistence import create_command, memory_repository


def test_step_is_running_before_node_side_effect_and_checkpoint_after_merge():
    repository = memory_repository()
    command = create_command()
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    observed = {}

    def node(state):
        running = repository.list_steps(command.run_id)
        observed["status_during_node"] = running[-1].status
        context = start_step(state)
        trace = build_trace_item(
            state,
            agent_name="diagnosis",
            action="学情诊断",
            status=StepStatus.SUCCESS,
            input_summary="已验证输入",
            output_summary="诊断完成",
            decision_reason="离线测试",
            step_context=context,
        )
        return {"current_node": "diagnosis", "trace": [trace], "errors": []}

    recorded = RecordedNode("diagnose", node, repository)

    class Workflow:
        def stream(self, state, stream_mode=None):
            update = recorded(state)
            merged = {**state, **update}
            merged["trace"] = state.get("trace", []) + update["trace"]
            yield merged

    initial = {
        "schema_version": "1.0",
        "run_id": command.run_id,
        "learner_id": "learner-001",
        "knowledge_base_id": "kb-001",
        "topic": "RAG",
        "generation_attempt": 1,
        "revision_count": 0,
        "trace": [],
        "errors": [],
    }
    result = DurableWorkflowRunner(Workflow(), repository).invoke(initial)
    assert observed["status_during_node"] == "running"
    assert repository.list_steps(command.run_id)[0].status == "success"
    checkpoint = repository.list_checkpoints(command.run_id)[0]
    assert checkpoint.step_id == result["trace"][-1]["step_id"]
    assert checkpoint.state_hash == canonical_hash(checkpoint.state_projection)


def test_recorded_node_failure_persists_sanitized_terminal_step():
    repository = memory_repository()
    command = create_command("run-node-failure")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=datetime.now(timezone.utc))

    def failing_node(state):
        raise RuntimeError("provider secret must not be stored")

    try:
        RecordedNode("diagnose", failing_node, repository)(
            {"run_id": command.run_id, "trace": [], "generation_attempt": 1}
        )
    except RuntimeError:
        pass
    step = repository.list_steps(command.run_id)[0]
    assert step.status == "failed"
    assert step.error_code == "INTERNAL_ERROR"
    assert "provider secret" not in (step.error_message or "")


def test_compiled_workflow_records_every_agent_and_supervisor_node(monkeypatch):
    repository = memory_repository()
    learner = LearnerProfile(
        learner_id="durable-user",
        learner_type="测试",
        education="本科",
        major="计算机",
        learning_goal="验证完整持久化工作流",
    )
    request = GenerateRequest(
        learner_id=learner.learner_id,
        topic="RAG",
        knowledge_base_id="kb-001",
        resource_types=["讲义"],
        include_review=False,
    )
    state = build_workflow_state(learner, request, run_id="run-compiled")

    def trace(state, name):
        return build_trace_item(
            state,
            agent_name=name,
            action=name,
            status=StepStatus.SUCCESS,
            input_summary="safe",
            output_summary="safe",
            decision_reason="test",
        )

    monkeypatch.setattr(
        workflow_module,
        "diagnose_node",
        lambda state: {"diagnosis": {}, "trace": [trace(state, "diagnosis")], "errors": []},
    )

    def retrieve(state):
        evidence = make_evidence(knowledge_base_id="kb-001")
        return {
            "retrieved_evidence": [evidence],
            "retrieval_status": "available",
            "retrieval_config_hash": evidence.config_hash,
            "retrieval_query_hashes": [evidence.query_hash],
            "retrieval_candidate_count": 1,
            "retrieval_dropped_candidate_count": 0,
            "retrieval_partial_failure_count": 0,
            "trace": [trace(state, "retriever")],
            "errors": [],
        }

    monkeypatch.setattr(workflow_module, "retrieve_node", retrieve)
    monkeypatch.setattr(
        workflow_module,
        "plan_node",
        lambda state: {"learning_plan": {}, "trace": [trace(state, "planner")], "errors": []},
    )

    def generate(state):
        resource = LearningResource(
            resource_id="resource-compiled",
            resource_type="讲义",
            difficulty="初级",
            content_text=None,
            knowledge_points=["RAG"],
            source_refs=[],
        )
        return {
            "generated_resources": [resource],
            "trace": [trace(state, "generator")],
            "errors": [],
        }

    monkeypatch.setattr(workflow_module, "generate_node", generate)
    command = create_command("run-compiled")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    workflow = workflow_module.build_workflow(lifecycle_repository=repository)
    result = DurableWorkflowRunner(workflow, repository).invoke(state)
    steps = repository.list_steps(command.run_id)
    checkpoints = repository.list_checkpoints(command.run_id)
    assert [item.step_sequence for item in steps] == list(range(1, len(steps) + 1))
    assert len(checkpoints) == len(steps)
    assert [item.node_name for item in checkpoints] == [item.node_name for item in steps]
    assert any(item.agent_name == "supervisor" for item in steps)
    assert result["workflow_status"] == "completed"
