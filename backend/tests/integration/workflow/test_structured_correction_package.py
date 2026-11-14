"""T60 content-only audit, exact source and shared Claim pipeline acceptance."""
import copy
import json
from types import SimpleNamespace

import pytest

from app.core.execution import execution_session
from app.core.learning_documents.correction_package import render_correction_markdown
from app.models.learning_documents.correction_package import assemble_correction_package
from app.models.reviews.claim_extraction import digest
from app.models.reviews.claims import ClaimCandidate, ClaimRecord, ClaimJudgement
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import build_source, source_for_claims
from app.agents.resource_workflows.learning_documents.claim_extraction.correction_sources import frozen_extension, GUIDANCE
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node, claim_decide_node
from app.agents.resource_workflows.learning_documents.revision_inputs import build_claim_review_revision_input
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from tests.fakes.claim_extraction import state_for_extraction, neutral_settings, prepare_ledger, extract_every_unit, extract_every_unit_v2, judge_all
from tests.fakes.llm import ScriptedLLMGateway
from tests.unit.agents.test_structured_correction_package import content
from tests.integration.workflow.test_claim_evidence_retrieval import storage as supplement_storage


def setup_source(locating=False, filtered=False):
    state, _, repo, gateway, counter = state_for_extraction(settings=neutral_settings(
        claim_extraction_source_locating_mode="exact_v1" if locating else None))
    from app.agents.resource_workflows.learning_documents.claim_extraction.filtered_correction_sources import frozen_extension as filtered_extension
    policy = repo.get(state["run_id"]).policy.model_copy(update={"correction_sources": filtered_extension() if filtered else frozen_extension()})
    audit, repo = prepare_ledger(p=policy)
    state.update(claim_extraction_policy=policy.model_dump(mode="json"), claim_extraction_policy_hash=digest(policy))
    body = content()
    body["unit"]["worked_example"]["scenario"] = "假设某团队更换索引。相同维度不保证编码契约兼容。"
    package = assemble_correction_package(content=body, title="单节点纠错",
        target=dict(node_id="k", node_name="编码契约", mastery_status="weak", failed_dimensions=["concept_application"]),
        run_id=state["run_id"], focus_snapshot_hash="a" * 64)
    r = state["generated_resources"][0]
    r.resource_type = "个性化纠错训练包"
    r.correction_package_payload = package.model_dump(mode="json")
    r.correction_package_payload_hash = package.payload_hash
    r.content_text = render_correction_markdown(package).strip()
    return state, audit, repo, gateway, counter


def extract_and_judge(state, repo, gateway, counter, missing=False):
    def extract(call):
        output = (extract_every_unit_v2 if call["output_schema"].__name__ == "BatchOutputV2" else extract_every_unit)(call)
        # Scripted semantic choice: a pure fictional event is non-factual;
        # the separate mixed scenario's technical assertion stays factual.
        for unit in output["units"]:
            for candidate in unit["claims"]:
                if candidate["source_text"].strip() == "某团队使用一个索引。":
                    candidate["claim_type"] = "non_factual"
        return output
    gateway.outcomes = [extract] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter))
        assert not state["claim_failed_resource_ids"], state["errors"]
        def judge(call):
            output = judge_all(call)
            if missing:
                records = {c["claim_id"]: c for c in state["extracted_claims"]}
                target = next(c["claim_id"] for c in state["extracted_claims"] if c["source_text"] == "应检查编码契约。")
                for j in output["judgements"]:
                    if j["claim_id"] == target:
                        j.update(verdict="not_in_evidence", evidence_ids=[])
            return output
        gateway.outcomes = [judge]
        state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter))


@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("locating", [False, True])
def test_new_source_exact_binding_roles_judge_and_publication(locating, filtered, monkeypatch):
    state, _, repo, gateway, counter = setup_source(locating, filtered)
    resource = state["generated_resources"][0]
    source = build_source(resource, repo.get(state["run_id"]).policy)
    extract_and_judge(state, repo, gateway, counter)
    assert state["claim_metrics"]["r"]["metric_status"] == "complete"
    for claim in state["extracted_claims"]:
        assert source.text[claim["source_start"]:claim["source_end"]] == claim["source_text"]
        assert len([f for f in source.fields if f["start"] <= claim["source_start"] < claim["source_end"] <= f["end"]]) == 1
        assert "当前状态" not in claim["source_text"] and "concept_application" not in claim["source_text"]
    assert source.snapshot == next(iter(repo.get(state["run_id"]).state.results.values())).source_snapshot
    # Mixed scenario facts stay factual: field role is not a blanket waiver.
    assert any("相同维度" in c["source_text"] and c["claim_type"] == "factual" for c in state["extracted_claims"])
    assert all(c["claim_type"] == "non_factual" for c in state["extracted_claims"] if c["source_text"] == "某团队使用一个索引。")
    if filtered:
        assert all(c["source_text"] != "维度相同即可混用。" for c in state["extracted_claims"])
        assert all(f["role"] != "exercise_proposition" for f in source.fields)
    else:
        assert any(c["source_text"] == "维度相同即可混用。" and c["claim_type"] == "non_factual" for c in state["extracted_claims"])
    for call in gateway.calls:
        payload = call["messages"][-1].content
        assert "learning_status" not in payload and "concept_application" not in payload
        if call["context"].node_name == "claim_judge":
            assert set(json.loads(payload)) == {"allowed_evidence", "claims"}
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(claim_partial_publish=False))
    assert decide_node(state)["generated_resources"][0].publication_status == "published"


@pytest.mark.parametrize(("strategy", "input_contract"), [
    ("resource_issue_v1", None), ("resource_issue_v1", "single_representation_v4"), ("compat", None),
])
def test_ordinary_review_content_only_and_exact_full_artifact_binding(strategy, input_contract):
    state, _, _, _, _ = setup_source()
    r = state["generated_resources"][0]
    if strategy == "resource_issue_v1":
        r = r.model_copy(update={"resource_spec_id": "spec-1", "resource_family_id": "fam-1"})
        from tests.unit.agents.test_resource_issue_engine import _policy, _state, _approve_outcome
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import review_resource_v1
        from app.agents.resource_workflows.learning_documents.reviewing import ReviewCallCollector
        from app.models.shared.llm import LLMCallContext
        s = _state(_policy().model_copy(update={"input_contract": input_contract}), r)
        s["resource_specs"][0]["knowledge_points"] = ["k"]
        gateway = ScriptedLLMGateway([_approve_outcome])
        outcome = review_resource_v1(state=s, resource=r, evidence=[], step_id="s", context=LLMCallContext(
            run_id="run-1", step_id="s", node_name="reviewer", schema_name="ResourceReviewInitialV1", generation_attempt=1),
            gateway=gateway, collector=ReviewCallCollector(), review_id="review", step_guard=lambda **kw: None)
        assert outcome.raw["decision"] == "approve"
        assert outcome.ledger.binding.structured_payload_hash
        text = gateway.calls[0]["messages"][-1].content
        if input_contract:
            assert '"binding"' not in text
            assert outcome.ledger.binding.evidence_context_id
    else:
        from app.agents.resource_workflows.learning_documents.reviewing.profiles import resolve_review_profile, correction_content_profile
        from app.agents.resource_workflows.learning_documents.reviewing.prompts.builder import build_review_prompt
        from app.agents.resource_workflows.learning_documents.reviewing.payloads import build_review_request
        from app.agents.resource_workflows.learning_documents.reviewing.types import ReviewAuditInput
        profile = correction_content_profile(resolve_review_profile(resource_type=r.resource_type, phase="content_v2"))
        request = build_review_request(profile=profile, prompt_bundle=build_review_prompt(profile=profile),
            audit_input=ReviewAuditInput(resource=r, constraints={"correction_focus_snapshot": {"private": "secret-focus"}}))
        text = request.messages[-1].content
    assert "learning_status" not in text and "concept_application" not in text and "secret-focus" not in text
    assert "应检查编码契约" in text and "相同维度不保证编码契约兼容" in text


@pytest.mark.parametrize("damage", ["hash", "text", "target", "payload", "policy"])
def test_new_source_drift_fails_before_extractor_call(damage):
    state, _, repo, gateway, counter = setup_source()
    r = state["generated_resources"][0]
    if damage == "hash": r.correction_package_payload_hash = "0" * 64
    elif damage == "text": r.content_text += "changed"
    elif damage == "target": r.knowledge_points = ["other"]
    elif damage == "payload": r.correction_package_payload["content"]["summary"] = "changed"
    else:
        policy = repo.get(state["run_id"]).policy.model_copy(update={"correction_sources": None})
        with pytest.raises(ValueError): build_source(r, policy)
        return
    gateway.outcomes = []
    with execution_session(state["run_id"], "owner"):
        update = claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter)
    assert update["claim_check_status"] == "failed" and not gateway.calls


@pytest.mark.parametrize("filtered", [False, True])
def test_answer_gap_builds_exact_revision_and_blocks_publication(filtered, monkeypatch):
    state, _, repo, gateway, counter = setup_source(filtered=filtered)
    extract_and_judge(state, repo, gateway, counter, missing=True)
    r = state["generated_resources"][0]
    claims = [ClaimRecord.model_validate(c) for c in state["extracted_claims"]]
    judgements = [ClaimJudgement.model_validate(j) for j in state["claim_judgements"]]
    revision = build_claim_review_revision_input(resource_spec_id="spec", resource=r, targets=["k"],
        claims=claims, judgements=judgements, evidence=state["retrieved_evidence"])
    assert revision.problems and revision.previous_structured_payload == r.correction_package_payload
    assert revision.previous_text == source_for_claims(r, claims).text
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(claim_partial_publish=False))
    assert decide_node(state)["generated_resources"][0].publication_status == "unpublished"


@pytest.mark.parametrize("filtered", [False, True])
def test_mixed_instruction_and_scenario_fact_not_programmatically_exempted(filtered):
    state, _, repo, _, _ = setup_source(filtered=filtered)
    source = build_source(state["generated_resources"][0], repo.get(state["run_id"]).policy)
    for role in ("scenario", "question_context", "instruction", "explanation"):
        field = next(f for f in source.fields if f["role"] == role)
        text = source.text[field["start"]:field["end"]]
        c = ClaimCandidate(claim_text=text, claim_type="factual", source_text=text, source_start=field["start"], source_end=field["end"])
        assert source.classify([c])[0].claim_type.value == "factual"


@pytest.mark.parametrize("filtered", [False, True, "compact", "contextual"])
def test_correction_gap_uses_existing_supplement_then_publishes(filtered, supplement_storage, monkeypatch):
    from tests.integration.workflow.test_claim_evidence_retrieval import _call_retrieve, _call_rejudge, _new_evidence, ObserverGateway, policy, query_hash
    from tests.fakes.evidence import ScriptedEvidenceRetriever
    from app.models.knowledge.knowledge import EvidenceBatch, RetrievalStatus
    if filtered == "contextual":
        from tests.unit.agents.test_correction_claim_input_v4 import contextual_setup
        state, _, repo, gateway, counter = contextual_setup(False)
    elif filtered == "compact":
        from tests.unit.agents.test_compact_correction_package import compact_source_setup
        state, _, repo, gateway, counter = compact_source_setup()
    else:
        state, _, repo, gateway, counter = setup_source(filtered=filtered)
    extract_and_judge(state, repo, gateway, counter, missing=True)
    state["run_id"] = "run-claim"
    state["generated_resources"][0].run_id = "run-claim"
    for item in [*state["extracted_claims"], *state["claim_judgements"]]: item["run_id"] = "run-claim"
    state.update(knowledge_base_id="kb-fixture", include_claim_evidence_retrieval=True,
        claim_evidence_retrieval_policy=policy().model_dump(mode="json"), claim_evidence_retrieval_policy_hash=policy().policy_hash,
        claim_workflow_version="contradiction_first_v3")
    target = next(j["claim_id"] for j in state["claim_judgements"] if j["verdict"] == "not_in_evidence")
    def query(call):
        data = json.loads(call["messages"][-1].content)
        assert "learning_status" not in json.dumps(data) and "concept_application" not in json.dumps(data)
        return {"batch_id": data["batch_id"], "input_hash": data["input_hash"],
                "items": [{"claim_id": target, "queries": [{"text": "编码契约核验"}]}]}
    supplement_gateway = ObserverGateway([query])
    item = _new_evidence("chunk-correction", "编码契约应先核验。", "编码契约核验")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[item], query_hashes=[query_hash("编码契约核验")], query_count=1, candidate_count=1,
        dropped_candidate_count=0, config_hash="9" * 64)])
    state.update(_call_retrieve(state, supplement_storage, supplement_gateway, retriever))
    assert state["claim_evidence_retrieval_refs"][0]["status"] == "rejudging"
    supplement_gateway.outcomes = [{"judgements": [{"claim_id": target, "verdict": "supported", "evidence_ids": [item.evidence_id], "reason": "新增冻结证据支持", "confidence": 0.9}]}]
    state.update(_call_rejudge(state, supplement_storage, supplement_gateway))
    assert state["claim_metrics"]["r"]["not_in_evidence_claim_total"] == 0
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(claim_partial_publish=False))
    assert decide_node(state)["generated_resources"][0].publication_status == "published"


@pytest.mark.parametrize("kind", ["ordinary", "claim"])
def test_revision_model_sees_only_content_and_preserves_server_envelope(kind):
    from app.agents.resource_agents.correction_package import CorrectionTrainingPackageAgent
    from app.agents.resource_workflows.learning_documents.revision_inputs import build_resource_review_revision_input
    from tests.unit.agents.test_structured_correction_package import structured_inputs
    spec, context = structured_inputs()
    agent = CorrectionTrainingPackageAgent()
    first = agent.generate(spec, context, llm_gateway=ScriptedLLMGateway([content()]))
    from app.models.learning_documents.schemas import LearningResource
    parent = LearningResource(resource_id="parent", resource_type=spec.resource_type, difficulty=spec.difficulty,
        content_text=first.content_text, knowledge_points=spec.knowledge_points, source_refs=[],
        correction_package_payload=first.artifact_data["correction_package"],
        correction_package_payload_hash=first.artifact_data["correction_package"]["payload_hash"])
    ordinary = build_resource_review_revision_input(resource_spec_id=spec.resource_spec_id, resource=parent, targets=spec.knowledge_points,
        feedback={"issues": [], "revision_instructions": []})
    # Claim envelope construction is separately verified above against actual extraction.
    if kind == "ordinary":
        revision_context = context.model_copy(update={"resource_review_revision": ordinary, "generation_attempt": 2})
    else:
        from app.models.reviews.revision_inputs import ClaimReviewRevisionInput
        value = dict(resource_spec_id=spec.resource_spec_id, parent_resource_id="parent", parent_version=1,
            content_hash=ordinary.content_hash, previous_text=parent.content_text,
            previous_structured_payload=parent.correction_package_payload, targets=spec.knowledge_points,
            problems=[], spans=[], groups=[], evidence=[])
        revision_context = context.model_copy(update={"claim_review_revision": ClaimReviewRevisionInput(**value), "generation_attempt": 2})
    changed = content(); changed["summary"] = "核对编码契约并记录判断条件。"
    gateway = ScriptedLLMGateway([changed])
    updated = agent.generate(spec, revision_context, llm_gateway=gateway)
    new = updated.artifact_data["correction_package"]
    assert new["learning_status"] == parent.correction_package_payload["learning_status"]
    assert new["provenance"] == parent.correction_package_payload["provenance"]
    payload = gateway.calls[0]["messages"][-1].content
    assert "learning_status" not in payload and "concept_application" not in payload
    assert "payload_hash" not in payload and "当前状态" not in payload
    assert new["payload_hash"] != parent.correction_package_payload_hash
    from app.core.security.errors import ApplicationError
    with pytest.raises(ApplicationError):
        agent.generate(spec, revision_context, llm_gateway=ScriptedLLMGateway([content()]))


@pytest.mark.parametrize("strategy", ["compat", "resource_issue_v1"])
@pytest.mark.parametrize("extraction", ["legacy_v3", "neutral_estimate_v1", "neutral_dispatch"])
@pytest.mark.parametrize("package_version", ["v1", "v2"])
def test_service_graph_generation_claim_revision_reaudit_and_publication(strategy, extraction, package_version, monkeypatch, tmp_path):
    from app.db.audit.memory import MemoryAuditRepository
    from app.db.learning_documents.memory import MemoryResourceRepository
    from app.db.claim.memory import MemoryClaimRepository
    from app.agents.resource_workflows.learning_documents import workflow as graph_module
    from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
    from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
    from app.services.generation.generation import GenerationService
    from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
    from tests.fakes.claim_extraction import graph_service, NeutralScriptedGateway, FixtureCounter
    from tests.unit.agents.test_resource_issue_engine import _approve_outcome
    audit, resources, claims = MemoryAuditRepository(), MemoryResourceRepository(), MemoryClaimRepository()
    counter = FixtureCounter()
    seen = []
    def route(call):
        schema = call["output_schema"].__name__
        seen.append((schema, call["context"].generation_attempt))
        if schema in {"CorrectionPackageContentV1", "CorrectionPackageContentV2"}:
            body = content()
            if schema == "CorrectionPackageContentV2":
                body["unit"].pop("worked_example")
                body["unit"]["exercises"].pop("similar")
            if call["context"].generation_attempt > 1:
                body["unit"]["exercises"]["guided"]["reference_answer"] = "先核对模型及编码契约。"
            return body
        if schema in {"ResourceReviewInitialV1", "ResourceReviewRecheckV1"}:
            result = _approve_outcome(call)
            if schema == "ResourceReviewRecheckV1": result["resolutions"] = []
            return result
        if schema == "ReviewLLMOutput":
            return {"decision": "approve", "hallucination_score": 0.0, "coverage_rate": 1.0,
                    "difficulty_match": True, "issues": [], "suggestion": "通过", "revision_instructions": []}
        if schema == "ClaimExtractionLLMOutput":
            data = json.loads(call["messages"][-1].content)
            r = data["resources"][0]
            text = r["content_text"]
            quote = "应检查编码契约。" if call["context"].generation_attempt == 1 else "先核对模型及编码契约。"
            start = text.index(quote)
            return {"resources": [{"resource_id": r["resource_id"], "claims": [{
                "claim_text": quote, "claim_type": "factual", "source_text": quote,
                "source_start": start, "source_end": start + len(quote), "knowledge_point_id": "k", "source_evidence_ids": []}]}]}
        if schema in {"BatchOutput", "BatchOutputV2"}:
            return (extract_every_unit_v2 if schema == "BatchOutputV2" else extract_every_unit)(call)
        result = judge_all(call)
        if call["context"].generation_attempt == 1:
            data = json.loads(call["messages"][-1].content)
            target = next(c["claim_id"] for c in data["claims"] if c["claim_type"] == "factual" and "应检查编码契约" in c["claim_text"])
            for j in result["judgements"]:
                if j["claim_id"] == target: j.update(verdict="contradicted", reason="参考答案不完整")
        return result
    gateway = NeutralScriptedGateway([route] * 64)
    settings = neutral_settings(resource_aware_retrieval_enabled=False, resource_review_strategy=strategy,
        lecture_review_strategy="legacy_content_v2", llm_model="fake-model").model_copy(update={"claim_extraction_strategy": "neutral_estimate_v1" if extraction == "neutral_dispatch" else extraction})
    graph_service(monkeypatch, audit, resources, claims, settings=settings, gateway=gateway, counter=counter,
                  output_path=tmp_path / "correction.md")
    # Restore the real generation and ordinary review nodes; only upstream
    # diagnosis/retrieval/planning and the model transport remain scripted.
    monkeypatch.setattr(graph_module, "generate_node", generate_node)
    monkeypatch.setattr(graph_module, "review_node", review_node)
    graph = graph_module.build_workflow(llm_gateway=gateway, lifecycle_repository=audit, claim_extraction_counter=counter)
    service = GenerationService(resources, graph, audit, claim_repo=claims, claim_extraction_gateway=gateway, claim_extraction_counter=counter)
    from app.agents.resource_agents.correction_package import structured_generation_contract
    service.freeze_correction_package = lambda req: structured_generation_contract("correction-json-generation-" + package_version)
    learner = LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件", learning_goal="验证", knowledge_base_id="kb-fixture")
    request = GenerateRequest(learner_id="learner", topic="编码契约", knowledge_base_id="kb-fixture", target_skill_nodes=["k"],
        resource_types=["个性化纠错训练包"], profile_focus_mode="off", include_review=True, include_claim_check=True,
        difficulty_preference="初级", constraints={"correction_focus_snapshot": {"ordered_target_nodes": [{
            "skill_node_id": "k", "name": "编码契约", "mastery_status": "weak", "failed_dimensions": ["concept_application"]}]}})
    from app.core.execution import execution_fence, ExecutionFence
    with execution_fence(ExecutionFence("run-correction", "owner")):
        kwargs = {}
        if extraction == "neutral_dispatch":
            from app.agents.resource_workflows.learning_documents.claim_extraction.budget import for_correction_contract
            kwargs['claim_extraction_snapshot'] = for_correction_contract(service.freeze_claim_extraction(request),
                service.freeze_correction_package(request))
        response = service.generate_with_run_id(learner, request, run_id="run-correction", **kwargs)
    if extraction in {"neutral_estimate_v1", "neutral_dispatch"} and package_version == "v1":
        # The default eight-call run budget is exhausted by the first full
        # source pass. A modified child must not inherit its parent's approval.
        assert response.workflow_status == "human_review"
        assert response.resources[0].publication_status == "unpublished"
        ledger = service.claim_extraction_repository.get(response.run_id)
        assert ledger.policy.max_calls == settings.claim_extraction_max_calls == 8
        assert 0 < len([c for c in gateway.calls if c["context"].node_name == "claim_extractor"]) <= 8
        return
    assert response.workflow_status == "completed", (seen, [(t.agent_name, t.error_code, t.error_message) for t in response.trace if t.error_code], [(c["context"].node_name, c["output_schema"].__name__) for c in gateway.calls])
    result = response.resources[0]
    assert result.publication_status == "published" and result.version == 2
    assert result.correction_package_payload and result.parent_resource_id
    parent = resources.get(result.parent_resource_id)
    assert parent is not None and parent.publication_status != "published"
    assert result.correction_package_payload["provenance"] == parent.correction_package_payload["provenance"]
    assert result.correction_package_payload["learning_status"] == parent.correction_package_payload["learning_status"]
    generated_schema = "CorrectionPackageContentV1" if package_version == "v1" else "CorrectionPackageContentV2"
    assert (generated_schema, 1) in seen and (generated_schema, 2) in seen
    assert any(s == "ClaimJudgementLLMOutput" and a == 2 for s,a in seen)
    frozen = audit.get_run_creation_snapshot(response.run_id)["correction_package_snapshot"]
    assert all(cp.state_projection["correction_package_snapshot"] == frozen for cp in audit.list_checkpoints(response.run_id))
    for call in gateway.calls:
        if call["output_schema"].__name__ in {"CorrectionPackageContentV1", "CorrectionPackageContentV2"} or call["context"].node_name in {"reviewer", "claim_extractor", "claim_judge"}:
            assert "concept_application" not in call["messages"][-1].content
            assert '"learning_status"' not in call["messages"][-1].content
