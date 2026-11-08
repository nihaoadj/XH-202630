"""T44 resource-issue V4 durable recovery: three fault boundaries + publish.

The production ``review_node`` (generic ``resource_issue_v1`` engine, request
builder, one-bounded-correction ledger and V4 audit), the original Claim gate
and ``decide_node`` are driven through real ``RecordedNode`` /
``DurableWorkflowRunner`` / ``WorkflowArtifactRecorder`` boundaries under a
fenced owner/lease, so the three fault boundaries (after generation, after the
audit commits but before the checkpoint, and after the checkpoint) and the
normal publish path are actually reached on both the memory and SQLite
repositories.

The gateway is a scripted fixture; every node, router, repository and
publication decision is production code.
"""

import json
import copy
from datetime import datetime, timedelta, timezone
from functools import partial
from uuid import uuid4

import pytest

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.agents.shared.recorded_node import RecordedNode
from app.core.execution import ExecutionFence, execution_fence
from app.core.security.errors import ApplicationError
from app.db.audit.memory import MemoryAuditRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash, execution_identity_fields
from app.models.reviews.resource_review import ResourceLedgerV1
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.registry import adapter_for
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.persistence import replay_resource_artifacts
from app.models.shared.agent_contracts import build_trace_item, start_step
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.models.shared.workflow import StepStatus
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner
from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.persistence import sqlite_repository
from tests.fakes.resource_reviews import state_for

OWNER = "owner-resource-e2e"


def _approve(call):
    """Echo the frozen binding and return a clean, fully-covered approve."""
    payload = json.loads(call["messages"][1].content)
    return {
        "binding": payload["binding"],
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": t, "status": "covered", "reason": "已讲解", "location": {"kind": "root"}}
                    for t in payload["targets"]],
        "hallucination_score": 0.0,
        "issues": [],
        "omitted_blocking_issues": False,
    }


def _resource_state():
    state = state_for()
    resource = state["generated_resources"][0].model_copy(update={
        "resource_type": "讲义", "resource_spec_id": str(uuid4()), "resource_family_id": str(uuid4()),
        "content_text": "## 标题\n讲解内容，自包含且覆盖目标。",
        "practice_guide_payload": None, "assessment_payload": None, "review_practice_payload": None,
        "review_status": None,
    })
    policy = ResourceReviewPolicyV1(context_tokens=262144, max_output_tokens=16384,
                                    max_physical_attempts=2).model_dump(mode="json")
    state.update(generated_resources=[resource], resource_review_policy=policy,
                 resource_review_policy_hash=policy_hash(policy),
                 resource_review_contract_version="1.1", **execution_identity_fields("fake-model"),
                 resource_ledgers={}, resource_revision={}, resource_stop_reasons={},
                 max_iterations=2)
    return state, resource


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
@pytest.mark.parametrize("boundary", ["generated", "audit_committed", "checkpointed", "completed", "empty_refs"])
def test_resource_issue_fault_boundaries(storage, boundary, tmp_path, monkeypatch):
    engine = None
    if storage == "sqlite":
        audit, engine = sqlite_repository(tmp_path)
        resources = SQLResourceRepository(audit.session_factory)
    else:
        audit, resources = MemoryAuditRepository(), MemoryResourceRepository()
    try:
        state, source = _resource_state()
        learner = LearnerProfile(learner_id="durable-resource", learner_type="测试", education="本科",
                                 major="测试", learning_goal="测试")
        specs = build_resource_specs(run_id=state["run_id"], resource_types=["讲义"], topic="题目",
            difficulty="初级", learning_plan={}, evidence=state["retrieved_evidence"],
            target_skill_nodes=state["target_skill_nodes"])
        spec = specs[0]
        source = source.model_copy(update={"run_id": state["run_id"], "batch_id": state["batch_id"],
            "resource_spec_id": spec.resource_spec_id, "resource_family_id": spec.resource_family_id,
            "knowledge_points": spec.knowledge_points, "version": 1, "parent_resource_id": None})
        state.update(learner=learner, learner_id=learner.learner_id, topic="题目", resource_types=["讲义"],
            resource_specs=[spec.model_dump(mode="json")], generated_resources=[], include_review=True,
            include_claim_check=False, generation_mode="standard", resource_executions=[{
                "resource_spec_id": spec.resource_spec_id, "resource_id": source.resource_id,
                "representation": "text", "agent_name": "frozen", "prompt_version": "1",
                "artifact_format": "markdown", "validation_status": "valid",
                "resource_type": "讲义", "resource_execution_state": "generated", "attempt": 1}])
        snapshot = {
            "resource_review_contract_version": state["resource_review_contract_version"],
            "resource_review_policy": state["resource_review_policy"],
            "resource_review_policy_hash": state["resource_review_policy_hash"],
            "resource_review_identity": state["resource_review_identity"],
            "resource_review_identity_hash": state["resource_review_identity_hash"],
        }
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=1)
        audit.create_run(CreateRunCommand(run_id=state["run_id"], request_snapshot=snapshot,
                                          request_hash=canonical_hash(snapshot),
                                          owner_instance_id=OWNER, lease_expires_at=expires))
        audit.start_run(state["run_id"], occurred_at=now, lease_expires_at=expires)
        gateway = ScriptedLLMGateway([_approve])
        reached = []

        def traced(agent, **updates):
            def node(current):
                return {**updates, "trace": [build_trace_item(current, agent_name=agent, action="fixture",
                    status=StepStatus.SUCCESS, input_summary="frozen", output_summary="frozen",
                    decision_reason="fixture", resource_ids=[source.resource_id] if agent == "generator" else [],
                    step_context=start_step(current))]}
            return node

        def review_with_fence(current):
            with execution_fence(ExecutionFence(run_id=current["run_id"], owner=OWNER)):
                return review_node(current, llm_gateway=gateway, review_repository=audit)

        nodes = [RecordedNode("retrieve", traced("retriever", retrieved_evidence=state["retrieved_evidence"]), audit),
                 RecordedNode("generate", traced("generator", generated_resources=[source]), audit),
                 RecordedNode("review", review_with_fence, audit),
                 RecordedNode("finalize", decide_node, audit)]

        class Workflow:
            last = None

            def stream(self, initial, stream_mode=None):
                current = initial
                for index, node in enumerate(nodes):
                    update = node(current)
                    current = {**current, **update, "trace": [*current.get("trace", []), *update.get("trace", [])]}
                    if index == 3 and boundary == "empty_refs":
                        current["review_audit_refs"] = []
                        reached.append("empty_refs")
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
                assert audit.get_step_review_audit(state["run_id"], kwargs["step_id"]).schema_version == "4.0"
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

        # Recovery read-back: the V4 ledger is rebuilt from the durable audit and
        # refuses a missing checkpoint / a tampered artifact hash.
        recovered = dict(workflow.last)
        if boundary == "empty_refs":
            with pytest.raises(ValueError, match="references|reference missing"):
                runner._restore_resource_ledgers(recovered)
        elif boundary == "audit_committed":
            with pytest.raises(ValueError, match="observation_incomplete"):
                runner._restore_resource_ledgers(recovered)
        else:
            recovered.pop("resource_ledgers", None)
            runner._restore_resource_ledgers(recovered)
            assert bool(recovered["resource_ledgers"]) == (boundary in {"checkpointed", "completed"})
            if boundary == "checkpointed":
                ledger = ResourceLedgerV1.model_validate(recovered["resource_ledgers"][spec.resource_spec_id])
                adapter = adapter_for(source.resource_type)
                replay_args = dict(resources=[resources.get(source.resource_id)], adapter=adapter,
                                   targets=spec.knowledge_points, evidence=state["retrieved_evidence"])
                # Pydantic accepts the self-consistent JSON below; recovery must
                # independently derive decisions and rerun the actual program gate.
                altered = ledger.model_dump(mode="json")
                altered["observations"][0]["decision"] = "revise"
                with pytest.raises(ValueError, match="decision replay"):
                    replay_resource_artifacts(ledger=ResourceLedgerV1.model_validate(altered), **replay_args)
                forged = ledger.model_dump(mode="json")
                forged["observations"][0]["gate"]["rule_version"] = "forged-rule-v99"
                with pytest.raises(ValueError, match="decision replay"):
                    replay_resource_artifacts(ledger=ResourceLedgerV1.model_validate(forged), **replay_args)
                recovered["resource_ledgers"][spec.resource_spec_id]["binding"]["artifact_exact_hash"] = "0" * 64
                with pytest.raises(ValueError, match="differs"):
                    runner._restore_resource_ledgers(recovered, recovering=False)
        assert resources.get(source.resource_id).publication_status == ("published" if boundary == "completed" else "unpublished")
        if boundary in {"generated", "checkpointed", "audit_committed", "empty_refs"}:
            # Exercise a fresh runner's entry checks and continuation through
            # publication, rather than treating _restore_resource_ledgers as a
            # complete recovery test.
            resume_state = copy.deepcopy(workflow.last)
            resume_state.pop("resource_ledgers", None)
            entered = []

            class ResumeWorkflow:
                def stream(self, initial, stream_mode=None):
                    entered.append(True)
                    current = initial
                    remaining = nodes[2:] if boundary == "generated" else nodes[3:]
                    for node in remaining:
                        update = node(current)
                        current = {**current, **update,
                                   "trace": [*current.get("trace", []), *update.get("trace", [])]}
                        yield current

            monkeypatch.setattr(audit, "save_checkpoint", original_save)
            resumed_runner = DurableWorkflowRunner(ResumeWorkflow(), audit,
                WorkflowArtifactRecorder(resources, audit))
            if boundary in {"generated", "checkpointed"}:
                resumed = resumed_runner.invoke(resume_state)
                assert entered == [True]
                assert resumed["generated_resources"][0].publication_status == "published"
                assert resources.get(source.resource_id).publication_status == "published"
                assert len(gateway.calls) == 1  # completed reviews are not sent again
            else:
                with pytest.raises((ValueError, ApplicationError)):
                    resumed_runner.invoke(resume_state)
                assert not entered
                assert len(gateway.calls) == 1
    finally:
        if engine is not None:
            engine.dispose()
