"""Actual durable runner/recorded nodes and repositories at three fault boundaries."""
from datetime import datetime, timezone
from functools import partial

import pytest

from app.agents.shared.recorded_node import RecordedNode
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.db.audit.memory import MemoryAuditRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.models.shared.agent_contracts import build_trace_item, start_step
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.models.shared.workflow import StepStatus
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner
from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder
from tests.fakes.persistence import sqlite_repository
from tests.fakes.llm import ScriptedLLMGateway
from tests.unit.agents.test_lecture_review_engine import lecture_state, response


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
@pytest.mark.parametrize("boundary", ["generated", "audit_committed", "checkpointed", "completed"])
def test_new_lecture_runner_fault_boundaries(storage, boundary, tmp_path, monkeypatch):
    engine = None
    if storage == "sqlite":
        audit, engine = sqlite_repository(tmp_path)
        resources = SQLResourceRepository(audit.session_factory)
    else:
        audit, resources = MemoryAuditRepository(), MemoryResourceRepository()
    try:
        state, source = lecture_state()
        learner = LearnerProfile(learner_id="durable-lecture", learner_type="测试", education="本科", major="测试", learning_goal="测试")
        specs = build_resource_specs(run_id=state["run_id"], resource_types=["讲义"], topic="题目", difficulty="初级",
            learning_plan={}, evidence=state["retrieved_evidence"], target_skill_nodes=source.knowledge_points)
        spec = specs[0]
        source = source.model_copy(update={"run_id": state["run_id"], "batch_id": state["batch_id"],
            "resource_spec_id": spec.resource_spec_id, "resource_family_id": spec.resource_family_id,
            "knowledge_points": spec.knowledge_points, "version": 1, "parent_resource_id": None})
        state.update(learner=learner, learner_id=learner.learner_id, topic="题目", resource_types=["讲义"],
            resource_specs=[spec.model_dump(mode="json")], generated_resources=[], include_review=True,
            include_claim_check=False, lecture_review_contract_version="1.0", claim_revision_count=0,
            claim_max_iterations=0, generation_mode="standard", resource_executions=[{
                "resource_spec_id": spec.resource_spec_id, "resource_id": source.resource_id, "representation": "text",
                "agent_name": "frozen", "prompt_version": "1", "artifact_format": "markdown", "validation_status": "valid",
                "resource_type": "讲义", "resource_execution_state": "generated", "attempt": 1}])
        snapshot = {key: state[key] for key in ("review_policy", "lecture_review_contract_version", "lecture_review_policy", "lecture_review_policy_hash")}
        audit.create_run(CreateRunCommand(run_id=state["run_id"], request_snapshot=snapshot, request_hash=canonical_hash(snapshot)))
        audit.start_run(state["run_id"], occurred_at=datetime.now(timezone.utc))
        gateway = ScriptedLLMGateway([response])
        reached = []
        def traced(agent, **updates):
            def node(current):
                return {**updates, "trace": [build_trace_item(current, agent_name=agent, action="fixture",
                    status=StepStatus.SUCCESS, input_summary="frozen", output_summary="frozen", decision_reason="fixture",
                    resource_ids=[source.resource_id] if agent == "generator" else [], step_context=start_step(current))]}
            return node
        nodes = [RecordedNode("retrieve", traced("retriever", retrieved_evidence=state["retrieved_evidence"]), audit),
            RecordedNode("generate", traced("generator", generated_resources=[source]), audit),
            RecordedNode("review", partial(review_node, llm_gateway=gateway), audit),
            RecordedNode("finalize", decide_node, audit)]
        class Workflow:
            last = None
            def stream(self, initial, stream_mode=None):
                current = initial
                for index, node in enumerate(nodes):
                    update = node(current)
                    current = {**current, **update, "trace": [*current.get("trace", []), *update.get("trace", [])]}
                    self.last = current
                    yield current
                    if index == 1:
                        reached.append("generated")
                        if boundary == "generated":
                            raise RuntimeError("fault after generated checkpoint")
                    if index == 2:
                        reached.append("checkpointed")
                        if boundary == "checkpointed":
                            raise RuntimeError("fault after review checkpoint")
        workflow = Workflow()
        original_save = audit.save_checkpoint
        def save_checkpoint(**kwargs):
            if kwargs["node_name"] in {"review", "reviewer"} and boundary == "audit_committed":
                reached.append("audit_committed")
                assert audit.get_step_review_audit(state["run_id"], kwargs["step_id"]).schema_version == "2.0"
                raise RuntimeError("fault before review checkpoint")
            return original_save(**kwargs)
        monkeypatch.setattr(audit, "save_checkpoint", save_checkpoint)
        runner = DurableWorkflowRunner(workflow, audit, WorkflowArtifactRecorder(resources, audit))
        if boundary == "completed":
            runner.invoke(state)
            reached.append("completed")
        else:
            with pytest.raises(Exception) as failure:
                runner.invoke(state)
            assert boundary in reached, repr(failure.value) + repr(failure.value.__cause__)
        assert resources.get(source.resource_id).publication_status == ("published" if boundary == "completed" else "unpublished")
        assert len(gateway.calls) == (0 if boundary == "generated" else 1)
        recovered = dict(workflow.last)
        if boundary == "audit_committed":
            with pytest.raises(ValueError, match="observation_incomplete"):
                runner._restore_lecture_ledgers(recovered)
        else:
            recovered.pop("lecture_ledgers", None)
            runner._restore_lecture_ledgers(recovered)
            assert bool(recovered["lecture_ledgers"]) == (boundary in {"checkpointed", "completed"})
            if boundary == "checkpointed":
                # The same persisted audit is rechecked immediately before publication.
                recovered["lecture_ledgers"][spec.resource_spec_id]["binding"]["content_hash"] = "0" * 64
                with pytest.raises(ValueError, match="differs"):
                    runner._restore_lecture_ledgers(recovered, recovering=False)
        assert resources.get(source.resource_id).publication_status == ("published" if boundary == "completed" else "unpublished")
    finally:
        if engine is not None:
            engine.dispose()
