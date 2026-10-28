"""Offline frozen-input import and single-resource graph retry boundaries."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents import generator_agent, workflow
from app.agents.resource_workflows.learning_documents.resource_retry import reuse_resource_context_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.core.retrieval.knowledge_ids import retrieval_config_hash
from app.core.security.errors import ApplicationError
from app.models.knowledge.knowledge import EvidenceAllocation
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceArtifactMetadata
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash
from app.services.generation.generation import build_workflow_state
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


TYPES = ["讲义", "实操指南", "分阶测试题", "案例分析", "复习清单"]


def fixture_state(resource_type="讲义", *, e1=False):
    evidence = [make_evidence(evidence_id=f"old-{i}", chunk_id=f"chunk-{i}", rank=i + 1) for i in range(3)]
    allocation = None
    if e1:
        other_type = "案例分析" if resource_type != "案例分析" else "讲义"
        bindings = {evidence[0].query_hash: [{"node_id": "node", "resource_type": None}]}
        data = dict(strategy_version="resource-aware-v1", step_id="old-retrieve", config_hash="2" * 64,
                    resource_types=[resource_type, other_type], evidence_ids=[item.evidence_id for item in evidence],
                    common_evidence_ids=["old-0"], resource_specific_evidence_ids={resource_type: ["old-1"], other_type: ["old-2"]},
                    query_bindings=bindings, evidence_query_hashes={item.evidence_id: [item.query_hash] for item in evidence},
                    gaps=[], binding_hash=retrieval_config_hash(bindings))
        data["allocation_hash"] = retrieval_config_hash(data)
        allocation = EvidenceAllocation.model_validate(data)
    spec = build_resource_specs(run_id="old-run", resource_types=[resource_type], topic="冻结主题", difficulty="初级",
                                learning_plan={}, evidence=evidence, target_skill_nodes=["node"],
                                node_evidence_map={"node": [item.evidence_id for item in evidence]})[0]
    if allocation:
        ids = allocation.available_ids(resource_type)
        spec = spec.model_copy(update={"evidence_ids": ids, "node_evidence_map": {"node": ids}})
    old = LearningResource(resource_id="old-resource", run_id="old-run", learner_id="learner", resource_type=resource_type,
                           resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
                           difficulty="初级", content_text="旧版正文", knowledge_points=["node"], source_refs=[], version=3)
    context = dict(schema_version="1.0", source_run_id="old-run", source_spec_id=spec.resource_spec_id,
                   source_checkpoint_hash="a" * 64, diagnosis={"frozen": "diagnosis"}, learning_plan={"frozen": "plan"},
                   spec=spec.model_dump(mode="json"),
                   evidence=[PersistedEvidenceSnapshot.from_evidence(item, run_id="old-run", retrieval_step_id="old-retrieve").model_dump(mode="json") for item in evidence],
                   query_texts={evidence[0].evidence_id: evidence[0].query},
                   evidence_allocation=allocation.model_dump(mode="json") if allocation else None,
                   retrieval_strategy_version="resource-aware-v1" if e1 else "legacy", retrieval_config_hash="2" * 64,
                   source_resource=old.model_dump(mode="json"), revision_feedback={"issues": [{"resource_type": resource_type, "evidence_ids": ["old-0"]}]})
    context["context_hash"] = canonical_hash(context)
    learner = LearnerProfile(learner_id="learner", learner_type="初学者", education="本科", major="计算机", learning_goal="学习")
    request = GenerateRequest(learner_id="learner", topic="冻结主题", knowledge_base_id="kb-fixture", resource_types=[resource_type], include_review=True)
    state = build_workflow_state(learner, request, run_id="new-run")
    state["target_skill_nodes"] = ["node"]
    state["resource_retry_context"] = context
    return state


@pytest.mark.parametrize("resource_type", TYPES)
def test_import_clones_only_selected_frozen_spec_and_preserves_source(resource_type):
    state = fixture_state(resource_type)
    before = deepcopy(state["resource_retry_context"])
    result = reuse_resource_context_node(state)
    spec = result["resource_specs"][0]
    assert state["resource_retry_context"] == before
    assert spec["resource_spec_id"] != before["source_spec_id"]
    assert spec["resource_family_id"] == before["spec"]["resource_family_id"]
    assert result["regeneration_source"].version == 3
    assert "generated_resources" not in result
    assert result["diagnosis"] == before["diagnosis"]
    assert result["learning_plan"] == before["learning_plan"]
    assert result["trace"][0]["node_name"] == "reuse_context"
    for original, cloned in zip(before["evidence"], result["retrieved_evidence"], strict=True):
        assert cloned.evidence_id != original["evidence_id"]
        assert cloned.excerpt_hash == original["excerpt_hash"]
        assert cloned.query_hash == original["query_hash"]
        snapshot = PersistedEvidenceSnapshot.from_evidence(cloned, run_id="new-run", retrieval_step_id=result["trace"][0]["step_id"])
        assert snapshot.snapshot_hash != original["snapshot_hash"]
    assert result["retrieved_evidence"][1].query.startswith("历史检索文本未持久化，仅保留哈希：")
    assert result["constraints"]["revision_feedback"]["issues"][0]["evidence_ids"] == [spec["evidence_ids"][0]]


def test_e1_projects_selected_scope_rehashes_and_validates():
    state = fixture_state(e1=True)
    result = reuse_resource_context_node(state)
    allocation = EvidenceAllocation.model_validate(result["evidence_allocation"])
    allocation.validate_evidence(result["retrieved_evidence"], ["讲义"])
    assert len(allocation.evidence_ids) == 2
    assert set(allocation.resource_specific_evidence_ids) == {"讲义"}
    assert allocation.allocation_hash != state["resource_retry_context"]["evidence_allocation"]["allocation_hash"]
    assert allocation.step_id == result["trace"][0]["step_id"]


def test_source_without_generated_artifact_can_import_and_starts_without_parent():
    state = fixture_state()
    context = state["resource_retry_context"]
    context["source_resource"] = None
    context["context_hash"] = canonical_hash({key: value for key, value in context.items() if key != "context_hash"})
    assert reuse_resource_context_node(state)["regeneration_source"] is None


def test_e1_does_not_invent_binding_for_retained_evidence():
    state = fixture_state(e1=True)
    context = state["resource_retry_context"]
    allocation = context["evidence_allocation"]
    # A syntactically valid frozen allocation can attribute common evidence
    # solely to the other type; projection must reject that ambiguous history.
    allocation["query_bindings"] = {key: [{"node_id": "node", "resource_type": "案例分析"}]
                                     for key in allocation["query_bindings"]}
    allocation["binding_hash"] = retrieval_config_hash(allocation["query_bindings"])
    allocation["allocation_hash"] = retrieval_config_hash({key: value for key, value in allocation.items() if key != "allocation_hash"})
    context["context_hash"] = canonical_hash({key: value for key, value in context.items() if key != "context_hash"})
    with pytest.raises(ApplicationError):
        reuse_resource_context_node(state)


@pytest.mark.parametrize("damage", ["hash", "scope", "query", "version", "missing", "dependency"])
def test_corrupt_context_is_rejected_without_upstream_fallback(damage):
    state = fixture_state()
    context = state["resource_retry_context"]
    if damage == "hash":
        context["diagnosis"] = {}
    elif damage == "scope":
        context["source_run_id"] = "other-run"
    elif damage == "query":
        context["query_texts"]["old-0"] = "伪造查询"
    elif damage == "version":
        context["schema_version"] = "2.0"
    elif damage == "missing":
        context["evidence"] = []
    else:
        context["spec"]["dependencies"] = ["some-other-spec"]
    if damage != "hash":
        context["context_hash"] = canonical_hash({key: value for key, value in context.items() if key != "context_hash"})
    with pytest.raises(ApplicationError):
        reuse_resource_context_node(state)


@pytest.mark.parametrize("resource_type", TYPES)
@pytest.mark.parametrize("e1", [False, True])
@pytest.mark.parametrize("claim", [False, True])
def test_real_graph_retry_skips_upstream_and_generates_one_resource(monkeypatch, resource_type, e1, claim):
    _exercise_graph(monkeypatch, resource_type, e1, claim)


def _exercise_graph(monkeypatch, resource_type, e1, claim, invoke=None):
    state = fixture_state(resource_type, e1=e1)
    state["include_claim_check"] = claim
    calls = []

    def forbidden(*args, **kwargs):
        pytest.fail("retry called diagnose/retrieve/plan")

    def generate(spec, context, **kwargs):
        calls.append(spec.resource_type)
        assert context.constraints["previous_version_content"] == "旧版正文"
        assert context.constraints["revision_feedback"]
        return GeneratedArtifact(metadata=ResourceArtifactMetadata(
            resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
            resource_type=spec.resource_type, representation="text", agent_name="fake", prompt_version="v1", artifact_format="markdown",
            source_evidence_ids=spec.evidence_ids), difficulty="初级", content_text="新版正文", knowledge_points=["node"])

    agent = SimpleNamespace(agent_name="fake", prompt_version="v1", artifact_format="markdown", generate=generate)
    monkeypatch.setattr(generator_agent, "get_resource_agent", lambda _: agent)
    for name in ("diagnose_node", "retrieve_node", "plan_node"):
        monkeypatch.setattr(workflow, name, forbidden)
    def review(state):
        from app.models.shared.agent_contracts import build_trace_item
        from app.models.shared.workflow import StepStatus
        return {"review_result": {"decision": "approve", "passed": True, "issues": [], "revision_instructions": [],
                                   "review_ids": {item.resource_id: "new-review" for item in state["generated_resources"]}},
                "trace": [build_trace_item(state, agent_name="reviewer", action="审核", status=StepStatus.SUCCESS,
                                          input_summary="离线固定审核", output_summary="通过", decision_reason="测试固定结果")]}
    monkeypatch.setattr(workflow, "review_node", review)

    def extract(kwargs):
        payload = json.loads(kwargs["messages"][1].content)
        resource = payload["resources"][0]
        return {"resources": [{"resource_id": resource["resource_id"], "claims": [{
            "claim_text": "新版正文", "claim_type": "factual", "source_text": "新版正文",
            "source_start": 0, "source_end": 4, "knowledge_point_id": "node",
            "source_evidence_ids": [payload["allowed_evidence"][0]["evidence_id"]],
        }]}]}

    def judge(kwargs):
        payload = json.loads(kwargs["messages"][1].content)
        return {"judgements": [{"claim_id": item["claim_id"], "verdict": "supported",
                                 "evidence_ids": [payload["allowed_evidence"][0]["evidence_id"]],
                                 "reason": "冻结证据支持", "confidence": 0.99} for item in payload["claims"]]}

    gateway = ScriptedLLMGateway([extract, judge] if claim else [])
    result = invoke(state, gateway) if invoke else workflow.build_workflow(llm_gateway=gateway).invoke(state)
    assert calls == [resource_type]
    assert len(result["resource_specs"]) == len(result["generated_resources"]) == 1
    resource = result["generated_resources"][0]
    assert resource.version == 4 and resource.parent_resource_id == "old-resource"
    assert resource.publication_status == "published"
    if claim:
        assert result["claim_check_status"] == "completed"
        assert resource.claim_metric_status == "complete"
        assert len(gateway.calls) == 2
    assert not {"diagnose", "retrieve", "plan"} & {item["node_name"] for item in result["trace"]}


def test_sql_generation_service_persists_retry_evidence_claims_and_lineage(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.audit.sql_repository import SQLAuditRepository
    from app.db.claim.sql_repository import SQLClaimRepository
    from app.db.learning_documents.models import ResourceSpecRecord
    from app.db.learning_documents.sql_repository import SQLResourceRepository
    from app.db.shared.database import configure_sqlite_foreign_keys
    from app.db.shared.models import Base, KnowledgeBaseORM, LearnerProfileORM
    from app.models.shared.persistence import BeginStepCommand, CompleteStepCommand, CreateRunCommand
    from app.services.generation import generation as generation_module
    from app.services.generation.generation import GenerationService
    from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder

    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'closure.db'}"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit, resources, claims = SQLAuditRepository(factory), SQLResourceRepository(factory), SQLClaimRepository(factory)
    monkeypatch.setattr(generation_module, "ensure_generation_ready", lambda: SimpleNamespace(status="ready", error_codes=[]))

    def invoke(state, gateway):
        learner = LearnerProfile(learner_id="learner", learner_type="初学者", education="本科", major="计算机",
                                 learning_goal="学习", knowledge_base_id="kb-fixture")
        request = GenerateRequest(learner_id="learner", topic="冻结主题", knowledge_base_id="kb-fixture",
                                  resource_types=["讲义"], include_review=True, include_claim_check=True,
                                  target_skill_nodes=["node"], profile_focus_mode="off")
        with factory() as db:
            db.add(KnowledgeBaseORM(knowledge_base_id="kb-fixture", name="synthetic"))
            db.add(LearnerProfileORM(learner_id="learner", learner_type="初学者", education="本科", major="计算机", learning_goal="学习"))
            db.commit()
        context = state["resource_retry_context"]
        context.update(learner=learner.model_dump(mode="json"), request=request.model_dump(mode="json"))
        context["context_hash"] = canonical_hash({key: value for key, value in context.items() if key != "context_hash"})
        now = datetime.now(timezone.utc)
        snapshot = request.model_dump(mode="json")
        audit.create_run(CreateRunCommand(run_id="old-run", learner_id="learner", knowledge_base_id="kb-fixture",
                                         topic=request.topic, request_snapshot=snapshot, request_hash=canonical_hash(snapshot), occurred_at=now))
        audit.start_run("old-run", occurred_at=now)
        audit.begin_step(BeginStepCommand(run_id="old-run", step_id="old-retrieve", step_sequence=1,
                                         node_name="retrieve", agent_name="retriever", action="检索", started_at=now))
        evidence = [PersistedEvidenceSnapshot.model_validate_json(json.dumps(item)) for item in context["evidence"]]
        audit.complete_step(CompleteStepCommand(run_id="old-run", step_id="old-retrieve", trace={
            "step_id": "old-retrieve", "status": "success", "agent_name": "retriever", "action": "检索",
            "sequence": 1, "attempt": 1}, evidence=evidence, ended_at=now))
        resources.save_spec(ResourceSpecRecord(run_id="old-run", **context["spec"]))
        parent = LearningResource.model_validate_json(json.dumps(context["source_resource"]))
        resources.save(parent, "learner", request.topic, run_id="old-run")
        before = resources.get(parent.resource_id).model_dump(mode="json")
        old_evidence = [item.model_dump(mode="json") for item in audit.list_evidence("old-run")]
        compiled = workflow.build_workflow(llm_gateway=gateway, lifecycle_repository=audit,
                                          resource_progress_recorder=WorkflowArtifactRecorder(resources, audit, claims))

        class Capture:
            last = None

            def stream(self, initial, **kwargs):
                for value in compiled.stream(initial, **kwargs):
                    self.last = value
                    yield value

        graph = Capture()
        response = GenerationService(resources, graph, audit, claim_repo=claims).generate_with_run_id(
            learner, request, run_id="new-run", resource_retry_context=context)
        assert response.workflow_status == "completed"
        generated = response.resources[0]
        assert resources.get(generated.resource_id).publication_status == "published"
        steps = audit.list_steps("new-run")
        assert steps[0].node_name == "reuse_context" and steps[0].status == "success"
        assert len(audit.list_checkpoints("new-run")) == len(steps)
        cloned = audit.list_evidence("new-run")
        assert len(cloned) == 2 and all(item.retrieval_step_id == steps[0].step_id for item in cloned)
        assert all(item.run_id == "new-run" for item in cloned)
        child_ids = {item.evidence_id for item in cloned}
        spec = resources.get_spec(generated.resource_spec_id)
        assert spec.run_id == "new-run" and set(spec.evidence_ids) == child_ids
        assert spec.resource_family_id == parent.resource_family_id
        assert claims.list_claims_by_run("new-run")
        assert all(set(item.evidence_ids) <= child_ids for item in claims.list_judgements_by_run("new-run"))
        events = audit.list_events("new-run", limit=1000)
        assert len({item.event_id for item in events}) == len(events)
        assert resources.get(parent.resource_id).model_dump(mode="json") == before
        assert [item.model_dump(mode="json") for item in audit.list_evidence("old-run")] == old_evidence
        return graph.last

    try:
        _exercise_graph(monkeypatch, "讲义", True, True, invoke=invoke)
    finally:
        engine.dispose()
