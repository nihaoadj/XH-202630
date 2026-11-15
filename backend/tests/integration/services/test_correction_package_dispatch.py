"""Private wrapper must preserve nested dispatch hashes and reject tampering."""
import copy

import pytest

from app.models.generation.correction_dispatch import wrap_correction_dispatch, unwrap_correction_dispatch, VERSION
from app.agents.resource_agents.correction_package import structured_generation_contract
from app.models.shared.persistence import canonical_hash


@pytest.mark.parametrize("version", ["legacy", "learning_documents.resource_issue.v1", "estimate"])
def test_correction_dispatch_preserves_inner_snapshot(version):
    inner = {"workflow_version": version, "request_hash": "a" * 64, "resource_dispatch_hash": "b" * 64}
    original = copy.deepcopy(inner)
    wrapped = wrap_correction_dispatch(inner, structured_generation_contract())
    assert wrapped["workflow_version"] == VERSION
    restored, contract = unwrap_correction_dispatch(wrapped)
    assert restored == original == inner
    assert contract == structured_generation_contract()
    restored["request_hash"] = "changed"
    assert wrapped["inner_dispatch"] == original


@pytest.mark.parametrize("damage", ["inner", "contract", "version", "unknown"])
def test_correction_dispatch_tampering_rejected(damage):
    wrapped = wrap_correction_dispatch({"workflow_version": "legacy"}, structured_generation_contract())
    if damage == "inner": wrapped["inner_dispatch"]["workflow_version"] = "changed"
    elif damage == "contract": wrapped["correction_package_contract"]["prompt_hash"] = "c" * 64
    elif damage == "version": wrapped["workflow_version"] = "changed"
    else: wrapped["unknown"] = "extra"
    with pytest.raises(ValueError): unwrap_correction_dispatch(wrapped)


def test_historical_dispatch_is_unchanged_and_unversioned_private_fields_fail():
    old = {"workflow_version": "legacy", "request_hash": "old"}
    assert unwrap_correction_dispatch(old) == (old, None)
    with pytest.raises(ValueError):
        unwrap_correction_dispatch({**old, "correction_package_contract": {}})


def test_nested_envelope_is_rejected_even_with_valid_hash():
    wrapped = wrap_correction_dispatch({"workflow_version": "legacy"}, structured_generation_contract())
    wrapped["inner_dispatch"] = {"workflow_version": VERSION}
    wrapped["correction_dispatch_hash"] = canonical_hash({k: v for k, v in wrapped.items() if k != "correction_dispatch_hash"})
    with pytest.raises(ValueError): unwrap_correction_dispatch(wrapped)


from tests.integration.services.test_generation_dispatch import state


@pytest.mark.parametrize("mode", ["worker", "background"])
@pytest.mark.parametrize("strategy", ["compat", "resource_issue_v1"])
@pytest.mark.parametrize("claim_check", [False, True])
def test_new_dispatch_routes_frozen_format_without_changing_request_hash(state, monkeypatch, mode, strategy, claim_check):
    from types import SimpleNamespace
    from app.config import Settings
    from app.services.generation.generation import GenerationService
    import app.services.generation.jobs as module
    settings = Settings(_env_file=None, resource_review_strategy=strategy)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    s = state
    seen = []
    generation = SimpleNamespace(
        audit_repo=s.audit,
        freeze_correction_package=lambda req: GenerationService.freeze_correction_package(None, req),
        freeze_claim_extraction=lambda req: {},
        generate_with_run_id=lambda learner, req, **kw: seen.append((req, kw)) or SimpleNamespace(resources=[], workflow_status="completed"))
    s.service.generation_service = generation
    s.service.dispatch_mode = mode
    if mode == "background":
        from app.db.generation.memory import MemoryGenerationJobRepository
        s.repo = MemoryGenerationJobRepository()
        s.service.job_repo = s.repo
    req = s.req.model_copy(update={"include_review": True, "include_claim_check": claim_check,
        "resource_types": ["个性化纠错训练包"], "target_skill_nodes": ["k"],
        "constraints": {"correction_focus_snapshot": {"ordered_target_nodes": [{"skill_node_id": "k"}]}}})
    job = s.service.create_job(s.learner, req)
    frozen = s.repo.get_dispatch(job.run_id)["dispatch_snapshot"]
    inner, contract = unwrap_correction_dispatch(frozen)
    assert contract == structured_generation_contract()
    assert inner["request_hash"] == canonical_hash(s.repo.get(job.run_id).request_payload)
    if mode == "worker":
        s.service.run_claim(s.repo.claim_next("worker", 60))
    else:
        s.service.run_job(s.learner, req, run_id=job.run_id)
    assert s.repo.get(job.run_id).job_status == "completed"
    assert len(seen) == 1 and seen[0][1]["correction_package_snapshot"] == contract


def test_client_cannot_inject_private_format_and_old_snapshot_stays_old():
    from app.services.generation.generation import build_workflow_state
    from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
    learner = LearnerProfile(learner_id="l", learner_type="test", education="本科", major="软件", learning_goal="验证")
    request = GenerateRequest(learner_id="l", topic="测试", resource_types=["个性化纠错训练包"],
        constraints={"_correction_package_contract": structured_generation_contract()})
    old = build_workflow_state(learner, request, claim_extraction_snapshot={}, correction_package_snapshot={})
    assert "_correction_package_contract" not in old["constraints"]
    assert not old.get("correction_package_snapshot")


@pytest.mark.parametrize("claim_check", [False, True])
def test_two_node_followup_has_independent_focus_difficulty_and_history(claim_check):
    from app.services.feedback.followup_plan import FollowupRequestPlan
    from app.models.learning_documents.schemas import GenerateRequest
    focus = {"difficulty": "中级", "focus_snapshot_hash": "parent", "ordered_target_nodes": [
        {"skill_node_id": "a", "name": "A", "mastery_status": "weak", "node_context": {"tier": 1}},
        {"skill_node_id": "b", "name": "B", "mastery_status": "learning", "node_context": {"tier": 2}}]}
    req = GenerateRequest(learner_id="l", topic="纠错", resource_types=["个性化纠错训练包", "分阶测试题"],
        target_skill_nodes=["a", "b"], constraints={"correction_focus_snapshot": focus,
        "historical_assessment_questions": [{"skill_node_id": "a", "question_text": "A题"}, {"skill_node_id": "b", "question_text": "B题"}]})
    plan = FollowupRequestPlan(req, req.resource_types, "source")
    requests = plan.requests(include_claim_check=claim_check)
    assert len(requests) == (4 if claim_check else 2)
    assert {(tuple(r.target_skill_nodes), tuple(r.resource_types)) for r in requests} == {
        ((n,), tuple(group)) for n in ("a", "b")
        for group in ([[k] for k in req.resource_types] if claim_check else [req.resource_types])}
    for r in requests:
        node = r.target_skill_nodes[0]
        assert r.difficulty_preference == ("初级" if node == "a" else "中级")
        assert len(r.constraints["correction_focus_snapshot"]["ordered_target_nodes"]) == 1
        assert all(q["skill_node_id"] == node for q in r.constraints["historical_assessment_questions"])
        assert r.include_claim_check == claim_check
    assert requests[0].constraints["correction_focus_snapshot"]["focus_snapshot_hash"] != requests[-1].constraints["correction_focus_snapshot"]["focus_snapshot_hash"]
    assert len(focus["ordered_target_nodes"]) == 2


@pytest.mark.parametrize("structured", [False, "v1", "v2"])
def test_resource_retry_restart_keeps_format_parent_package_and_hash(structured, monkeypatch):
    from tests.unit.services.test_resource_retry_service import source_state
    from app.services.generation.generation import GenerationService, build_workflow_state
    from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
    from app.agents.resource_workflows.learning_documents.resource_retry import reuse_resource_context_node
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.learning_documents.models import ResourceSpecRecord, ResourceExecutionRecord
    from app.services.generation.jobs import GenerationJobService
    from app.models.shared.persistence import canonical_hash
    from app.config import Settings
    from tests.unit.agents.test_structured_correction_package import content
    from app.models.learning_documents.correction_package import assemble_correction_package
    from app.core.learning_documents.correction_package import render_correction_markdown
    from tests.fakes.llm import ScriptedLLMGateway
    settings = Settings(_env_file=None, resource_review_strategy="compat", lecture_review_strategy="legacy_content_v2", claim_extraction_strategy="legacy_v3")
    monkeypatch.setattr("app.services.generation.jobs.get_settings", lambda: settings)
    s = source_state()
    focus = {"ordered_target_nodes": [{"skill_node_id": "node", "name": "编码契约", "mastery_status": "weak", "failed_dimensions": ["concept_application"]}]}
    s.req = s.req.model_copy(update={"resource_types": ["个性化纠错训练包"], "target_skill_nodes": ["node"],
        "constraints": {"correction_focus_snapshot": focus}})
    s.spec = s.spec.model_copy(update={"resource_type": "个性化纠错训练包"})
    parent = s.resources.get("parent").model_copy(update={"resource_type": s.spec.resource_type})
    if structured:
        from tests.unit.agents.test_compact_correction_package import compact_content
        from app.models.learning_documents.correction_package import assemble_compact_correction_package
        assemble = assemble_compact_correction_package if structured == "v2" else assemble_correction_package
        package = assemble(content=compact_content() if structured == "v2" else content(), title="旧纠错包", run_id="source", focus_snapshot_hash=canonical_hash(focus),
            target=dict(node_id="node", node_name="编码契约", mastery_status="weak", failed_dimensions=["concept_application"]))
        parent = parent.model_copy(update={"content_text": render_correction_markdown(package).strip(),
            "correction_package_payload": package.model_dump(mode="json"), "correction_package_payload_hash": package.payload_hash})
    s.resources = MemoryResourceRepository()
    s.resources.save_spec(ResourceSpecRecord(run_id="source", **s.spec.model_dump(mode="json")))
    s.resources.save(parent, "learner", "retry", run_id="source", batch_id="batch")
    s.resources.upsert_execution(ResourceExecutionRecord(run_id="source", resource_spec_id=s.spec.resource_spec_id,
        resource_type=s.spec.resource_type, state="revision_requested", resource_id="parent", attempt=1,
        validation_status="passed", agent_name="correction", prompt_version="v1", artifact_format="json" if structured else "markdown"))
    s.generation.resource_repo = s.resources
    s.generation.freeze_correction_package = lambda req: GenerationService.freeze_correction_package(None, req)
    s.audit.list_reviews_by_run = lambda _: [{"resource_id": "parent", "issues": [], "revision_instructions": [{"target_resource_type": s.spec.resource_type, "action": "补全答案"}]}]
    projection = {**s.checkpoint.state_projection, "resource_specs": [s.spec.model_dump(mode="json")]}
    contract = structured_generation_contract("correction-json-generation-" + structured) if structured else None
    if contract: projection["correction_package_snapshot"] = contract
    s.checkpoint = s.checkpoint.model_copy(update={"state_projection": projection, "state_hash": canonical_hash(projection)})
    s.audit.get_run_creation_snapshot = lambda _: {"correction_package_snapshot": contract} if contract else {}
    s.repo._store["source"]["request_payload"] = s.req.model_dump(mode="json")
    snapshot = s.service._dispatch_snapshot(s.learner, s.req)
    inner = unwrap_correction_dispatch(snapshot)[0]
    # Source metadata is historical, not the new submission default.
    snapshot = wrap_correction_dispatch(inner, contract) if structured else inner
    s.repo._dispatch_metadata["source"]["dispatch_snapshot"] = snapshot
    child, request = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    inner, frozen = unwrap_correction_dispatch(s.repo.get_dispatch(child.run_id)["dispatch_snapshot"])
    assert frozen == contract
    retry = inner["resource_retry_context"]
    assert retry.get("correction_package_snapshot") == contract
    if structured:
        assert retry["source_resource"]["correction_package_payload"] == parent.correction_package_payload
        state = build_workflow_state(s.learner, request, run_id=child.run_id, claim_extraction_snapshot={}, correction_package_snapshot=contract)
        state["resource_retry_context"] = retry
        state.update(reuse_resource_context_node(state))
        changed = compact_content() if structured == "v2" else content()
        changed["summary"] = "先检查条件并记录判断依据。"
        gateway = ScriptedLLMGateway([changed])
        update = generate_node(state, llm_gateway=gateway)
        result = update["generated_resources"][0]
        assert result.correction_package_payload, update["errors"]
        assert result.correction_package_payload["provenance"] == parent.correction_package_payload["provenance"]
        assert result.parent_resource_id == "parent" and result.version == 2
        assert "concept_application" not in gateway.calls[0]["messages"][-1].content
    restarted = GenerationJobService(s.repo, s.generation)
    restarted.run_job(s.learner, request, child.run_id)
    assert s.repo.get(child.run_id).job_status == "completed"
    assert s.calls[0][2]["correction_package_snapshot"] == (contract or {})


@pytest.mark.parametrize("claim_check", [False, True])
def test_old_feedback_two_node_confirmation_is_idempotent_and_keeps_representative(claim_check):
    from types import SimpleNamespace
    from tests.integration.services.test_feedback_loop_service import _setup, _request
    from app.models.feedback.feedback_loop import FeedbackFollowupSelection, KnowledgePointAttemptResult
    from app.services.learners.mastery import MasteryService
    from app.db.learners.mastery import MemoryMasteryRepository
    service, learners, jobs, profile, resource = _setup()
    resource.knowledge_points = ["skill-a", "skill-b"]
    nodes = [SimpleNamespace(node_id=n, name=n, description=None, level="L1", tier=1, prerequisites=[], children=[]) for n in resource.knowledge_points]
    service.mastery_service = MasteryService(MemoryMasteryRepository(learners), SimpleNamespace(list_skill_nodes=lambda _: nodes),
        resource_repo=SimpleNamespace(list_by_learner=lambda _: [resource]))
    request = _request(0.4).model_copy(update={"knowledge_point_results": [
        KnowledgePointAttemptResult(knowledge_point_id=n, question_ids=["q-"+n], correct_count=1, total_count=2) for n in resource.knowledge_points]})
    result = service.process_learning_attempt(profile, resource, request)
    selection = FeedbackFollowupSelection(learner_id="learner", attempt_id=result.attempt.attempt_id,
        option_id="personalized-correction-package-v1", learning_intent="reinforce_weakness",
        selected_skill_node_ids=resource.knowledge_points, next_generation_snapshot_hash=result.generation_options.snapshot_hash,
        include_claim_check=claim_check)
    events = []
    service._append_event = lambda *args: events.append(args)
    selected = service.choose_followup(learners.get("learner"), selection)
    again = service.choose_followup(learners.get("learner"), selection)
    assert set(selected.followup_run_ids) == set(again.followup_run_ids)
    assert len(jobs.list_by_learner("learner")) == (4 if claim_check else 2)
    assert selected.followup_run_id == selected.followup_run_ids[0]
    event = next(e for e in events if e[1].value == "followup_generation_created")
    assert event[3]["child_run_id"] == selected.followup_run_id
    assert set(event[3]["child_run_ids"]) == set(selected.followup_run_ids)
    for job in jobs.list_by_learner("learner"):
        assert len(job.request_payload["target_skill_nodes"]) == 1
        assert job.batch_id == "source-batch"
