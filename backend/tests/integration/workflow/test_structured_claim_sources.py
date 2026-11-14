"""Structured source boundaries, private answers and unchanged generic Judge."""
import json
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.agents.resource_agents.assessment import AssessmentAgent
from app.agents.resource_agents.checklist import _canonical_hash, render_review_practice_markdown
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import (
    build_source, frozen_extension, GUIDANCE, source_for_claims,
)
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node, claim_decide_node
from app.agents.resource_workflows.learning_documents.revision_inputs import build_claim_review_revision_input
from app.agents.resource_workflows.learning_documents.workflow import decide_node, route_after_initial_claim_judge
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.core.execution import execution_session
from app.models.shared.agent_contracts import ReviewPracticePackageV2, ResourceGenerationContext
from app.models.reviews.claim_extraction import digest, content_digest
from app.models.shared.persistence import WorkflowEvent, canonical_hash, WorkflowEventType
from app.models.reviews.claims import RunClaimsResponse
from app.services.reviews.assessment_privacy import public_claims, public_timeline, public_review
from app.services.runs.events import to_public_event
from tests.fakes.claim_extraction import state_for_extraction, extract_every_unit, extract_every_unit_v2, judge_all, neutral_settings
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.evidence import make_evidence
from tests.unit.agents.test_structured_assessment import _block as assessment_block
from tests.unit.agents.test_review_practice_v2 import _block as checklist_block
from tests.integration.workflow.test_claim_evidence_retrieval import storage as supplement_storage


def setup_source(kind, *, locating=False):
    settings = neutral_settings(claim_extraction_resource_claims=128, claim_extraction_max_calls=32,
                                claim_extraction_max_attempts=64, claim_extraction_max_tokens=1000000,
                                claim_extraction_source_locating_mode="exact_v1" if locating else None)
    state, audit, repo, gateway, counter = state_for_extraction(settings=settings)
    resource = state["generated_resources"][0]
    resource.resource_type = kind
    if kind == "复习清单":
        block = checklist_block().model_dump(mode="json")
        block["skill_node_id"] = "k"
        block["evidence_ids"] = block["summary_evidence_ids"] = ["ev"]
        for q in block["recall_questions"] + block["distinction_questions"]:
            q["evidence_ids"] = ["ev"]
        block["distinction_questions"][0].update(statement="RAG保证所有答案正确。", correction="RAG不能保证所有答案正确。")
        package = ReviewPracticePackageV2(title="复习", instructions="先作答后看答案。", node_blocks=[block]).model_dump(mode="json")
        package["payload_hash"] = _canonical_hash({k: v for k, v in package.items() if k != "payload_hash"})
        resource.review_practice_payload = package
        resource.content_text = render_review_practice_markdown(package)
    else:
        evidence = make_evidence(evidence_id="ev")
        spec = build_resource_specs(run_id=state["run_id"], resource_types=[kind], topic="RAG", difficulty="初级",
                                    learning_plan={}, evidence=[evidence], target_skill_nodes=["k"])[0]
        block = assessment_block("k", "ev")
        block["short_answer_questions"][0]["reference_answer"] = "私有答案：RAG不能保证所有答案正确。"
        artifact = AssessmentAgent().generate(spec, ResourceGenerationContext(run_id=state["run_id"], batch_id=state["run_id"], topic="RAG", evidence=[evidence]),
                                              llm_gateway=ScriptedLLMGateway([block]))
        resource.assessment_payload = artifact.artifact_data["assessment_package"]
        resource.content_text = artifact.content_text
    return state, audit, repo, gateway, counter


def extract_and_judge(state, repo, gateway, counter, *, bad_answer=False):
    def extraction(call):
        return (extract_every_unit_v2 if call["output_schema"].__name__ == "BatchOutputV2" else extract_every_unit)(call)
    gateway.outcomes = [extraction] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                       claim_extraction_counter=counter))
        def judge(call):
            result = judge_all(call)
            if bad_answer:
                claims = json.loads(call["messages"][-1].content)["claims"]
                source = build_source(state["generated_resources"][0], repo.get(state["run_id"]).policy)
                records = {c["claim_id"]: c for c in state["extracted_claims"]}
                answers = [c for c in claims if c["claim_type"] == "factual" and any(
                    f["role"] == "answer" and f["start"] <= records[c["claim_id"]]["source_start"]
                    and records[c["claim_id"]]["source_end"] <= f["end"] for f in source.fields)]
                selected = next((c["claim_id"] for c in answers if "私有答案" in c["claim_text"]), answers[0]["claim_id"])
                for j in result["judgements"]:
                    if j["claim_id"] == selected:
                        j["verdict"] = "not_in_evidence" if bad_answer == "missing" else "contradicted"
                        if bad_answer == "missing":
                            j["evidence_ids"] = []
            return result
        gateway.outcomes = [judge]
        state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                     claim_extraction_counter=counter))


@pytest.mark.parametrize("kind", ["复习清单", "分阶测试题"])
@pytest.mark.parametrize("locating", [False, True])
def test_structured_source_exact_binding_and_shared_judge(kind, locating):
    state, _, repo, gateway, counter = setup_source(kind, locating=locating)
    policy = repo.get(state["run_id"]).policy
    resource = state["generated_resources"][0]
    before = resource.content_text
    source = build_source(resource, policy)
    assert source.snapshot["public_content_hash"] == content_digest(before)
    assert source.snapshot["resource_version"] == resource.version
    if kind == "分阶测试题":
        assert "私有答案" not in before and "私有答案" in source.text
    extract_and_judge(state, repo, gateway, counter)
    assert state["claim_failed_resource_ids"] == []
    assert state["assessment_claim_skipped_resource_ids"] == []
    assert state["claim_metrics"]["r"]["metric_status"] == "complete"
    for claim in state["extracted_claims"]:
        assert source.text[claim["source_start"]:claim["source_end"]] == claim["source_text"]
        assert claim["source_text_hash"] == content_digest(claim["source_text"])
    if kind == "复习清单":
        q = next(c for c in state["extracted_claims"] if c["source_text"] == "RAG保证所有答案正确。")
        assert q["claim_type"] == "non_factual"
        assert any(c["claim_type"] == "factual" and c["source_text"] == "RAG不能保证所有答案正确。" for c in state["extracted_claims"])
        assert "已完成来源核验" not in source.text
    judge_calls = [c for c in gateway.calls if c["context"].node_name == "claim_judge"]
    assert set(json.loads(judge_calls[0]["messages"][-1].content)) == {"allowed_evidence", "claims"}
    assert any(GUIDANCE in c["messages"][0].content for c in gateway.calls if c["context"].node_name == "claim_extractor")
    saved = next(iter(repo.get(state["run_id"]).state.results.values()))
    assert saved.source_snapshot == source.snapshot
    assert resource.content_text == before


@pytest.mark.parametrize("kind", ["复习清单", "分阶测试题"])
def test_structured_claim_failures_build_exact_revision_and_block_publication(kind, monkeypatch):
    state, _, repo, gateway, counter = setup_source(kind)
    extract_and_judge(state, repo, gateway, counter, bad_answer=True)
    resource = state["generated_resources"][0]
    from app.models.reviews.claims import ClaimRecord, ClaimJudgement
    claims = [ClaimRecord.model_validate(c) for c in state["extracted_claims"]]
    judgements = [ClaimJudgement.model_validate(j) for j in state["claim_judgements"]]
    model = build_claim_review_revision_input(resource_spec_id="spec", resource=resource, targets=["k"],
                                              claims=claims, judgements=judgements, evidence=state["retrieved_evidence"])
    assert model.problems and model.previous_structured_payload
    assert model.previous_text == source_for_claims(resource, claims).text
    for span in model.spans:
        assert model.previous_text[span.source_start:span.source_end] == span.source_text
    state.update(include_claim_evidence_retrieval=True, claim_workflow_version="contradiction_first_v3",
                 claim_evidence_retrieval_policy={"enabled": True})
    assert route_after_initial_claim_judge(state) == "claim_decide"
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(claim_partial_publish=True))
    assert decide_node(state)["generated_resources"][0].publication_status == "unpublished"


@pytest.mark.parametrize("kind", ["复习清单", "分阶测试题"])
@pytest.mark.parametrize("tamper", ["text", "package", "hash", "persisted_hash"])
def test_structured_mismatch_is_rejected(kind, tamper):
    state, _, repo, gateway, counter = setup_source(kind)
    r = state["generated_resources"][0]
    package = r.assessment_payload if kind == "分阶测试题" else r.review_practice_payload
    if tamper == "text":
        r.content_text += "改动"
    elif tamper == "package":
        package["instructions"] += "改动"
    elif tamper == "hash":
        package["payload_hash"] = "0" * 64
    elif kind == "分阶测试题":
        r.assessment_payload_hash = "0" * 64
    else:
        r.review_practice_payload_hash = "0" * 64
    with pytest.raises(ValueError):
        build_source(r, repo.get(state["run_id"]).policy)
    gateway.outcomes = []
    with execution_session(state["run_id"], "owner"):
        failed = claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter)
    assert failed["claim_check_status"] == "failed"
    assert gateway.calls == []


def test_legacy_checklist_notice_and_no_payload_fallback():
    state, _, repo, _, _ = setup_source("复习清单")
    r = state["generated_resources"][0]
    policy = repo.get(state["run_id"]).policy
    r.content_text = r.content_text.replace("请结合关联材料核对。", "已完成来源核验。")
    assert build_source(r, policy).snapshot is not None
    r.review_practice_payload = None
    assert build_source(r, policy).text == r.content_text
    assert build_source(r, policy).snapshot is None


def test_frozen_policy_and_other_resource_compatibility():
    state, _, repo, _, _ = setup_source("复习清单")
    r = state["generated_resources"][0]
    p = repo.get(state["run_id"]).policy
    old = p.model_copy(update={"structured_sources": None})
    assert "structured_sources" not in old.model_dump(mode="json")
    assert build_source(r, old).text == r.content_text
    assert digest(type(p).model_validate(old.model_dump(mode="json"))) == digest(old)
    r.resource_type = "实操指南"
    assert build_source(r, p).snapshot is None
    assert build_source(r, p).text == r.content_text
    broken = p.model_copy(update={"structured_sources": {**frozen_extension(), "guidance_hash": "0" * 64}})
    assert build_source(r, broken).text == r.content_text  # Unrelated resource never adopts the adapter.
    r.resource_type = "复习清单"
    with pytest.raises(ValueError, match="drift"):
        build_source(r, broken)


def test_structural_instruction_keeps_separately_located_factual_clause():
    from app.models.reviews.claims import ClaimCandidate
    state, _, repo, _, _ = setup_source("复习清单")
    r = state["generated_resources"][0]
    package = r.review_practice_payload
    package["node_blocks"][0]["recall_questions"][0]["pass_criteria"] = "能够说明RAG不能保证事实正确。"
    package["payload_hash"] = _canonical_hash({k: v for k, v in package.items() if k != "payload_hash"})
    r.content_text = render_review_practice_markdown(package)
    source = build_source(r, repo.get(state["run_id"]).policy)
    field = next(f for f in source.fields if f["role"] == "criterion")
    text = source.text[field["start"]:field["end"]]
    full = ClaimCandidate(claim_text=text, source_text=text, source_start=field["start"], source_end=field["end"], claim_type="factual")
    start = field["start"] + len("能够说明")
    fact = ClaimCandidate(claim_text=source.text[start:field["end"]], source_text=source.text[start:field["end"]],
                          source_start=start, source_end=field["end"], claim_type="factual")
    classified = source.classify([full, fact])
    assert classified[0].claim_type.value == "instructional"
    assert classified[1].claim_type.value == "factual"


def test_private_source_copy_cannot_escape_its_target_unit():
    from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import unit_for
    from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import build_messages
    from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output
    from app.models.reviews.claim_extraction import ExtractionBatch
    state, _, repo, _, _ = setup_source("复习清单")
    r = state["generated_resources"][0]
    policy = repo.get(state["run_id"]).policy
    source = build_source(r, policy)
    first = source.fields[0]
    unit = unit_for(source.text, first["start"], first["end"], "paragraph")
    batch = ExtractionBatch(batch_id="isolated", units=[unit])
    messages = build_messages(source.text, r, batch, policy, {"k"})
    output = extract_every_unit({"messages": messages})
    foreign = next(f for f in source.fields if f["role"] == "answer"
                   and source.text[f["start"]:f["end"]] not in source.text[first["start"]:first["end"]])
    text = source.text[foreign["start"]:foreign["end"]]
    output["units"][0]["claims"][0].update(source_text=text, claim_text=text, source_end=len(text))
    with pytest.raises(ValueError, match="substring absent"):
        validate_output(source.text, batch, output, resource=r, policy=policy, allowed_nodes={"k"})


def test_new_assessment_without_private_package_fails_before_model_call():
    state, _, repo, gateway, counter = setup_source("分阶测试题")
    state["generated_resources"][0].assessment_payload = None
    gateway.outcomes = []
    with execution_session(state["run_id"], "owner"):
        failed = claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter)
    assert failed["claim_check_status"] == "failed" and gateway.calls == []


def test_private_answers_hidden_from_public_audit_projections():
    state, _, repo, gateway, counter = setup_source("分阶测试题")
    extract_and_judge(state, repo, gateway, counter)
    response = RunClaimsResponse(run_id=state["run_id"], claims=state["extracted_claims"],
                                 judgements=state["claim_judgements"], resource_metrics=state["claim_metrics"])
    public = public_claims(response)
    assert public.claims == [] and public.judgements == []
    assert public.resource_metrics == response.resource_metrics
    secret = "私有答案：RAG不能保证所有答案正确。"
    assert secret not in public.model_dump_json()
    payload = {"claim_count": 2, "private_answer": secret, "resource_metrics": {"r": {"reason": secret}}}
    event = WorkflowEvent(event_id="e", run_id="run", event_sequence=1,
                          event_type=WorkflowEventType.CLAIM_METRIC_COMPUTED, payload=payload,
                          payload_hash=canonical_hash(payload), occurred_at=datetime.now(timezone.utc))
    assert secret not in to_public_event(event).model_dump_json()
    review = {"resource_id": "r", "status": "human_review", "issues": [{"description": secret}]}
    from app.models.shared.persistence import AgentStepRecord
    step = AgentStepRecord(step_id="s", run_id="run", step_sequence=1, node_name="claim_judge", action="判定",
                            agent_name="judge", status="degraded", input_summary=secret, output_summary=secret,
                            started_at=datetime.now(timezone.utc))
    class Timeline(SimpleNamespace):
        def model_copy(self, *, update):
            return Timeline(**(vars(self) | update))
    timeline = Timeline(resource_versions=[{"resource_type": "分阶测试题"}], steps=[step], events=[event], reviews=[review])
    safe = public_timeline(timeline)
    assert secret not in json.dumps({"steps": [s.model_dump(mode="json") for s in safe.steps],
                                    "events": [e.model_dump(mode="json") for e in safe.events], "reviews": safe.reviews}, ensure_ascii=False)
    assert "issues" not in public_review(review)


def test_unchanged_structured_revision_stops_further_automatic_body_rework():
    from app.agents.resource_workflows.learning_documents.workflow import route_after_claim_decide
    state, _, repo, gateway, counter = setup_source("复习清单")
    extract_and_judge(state, repo, gateway, counter, bad_answer=True)
    r = state["generated_resources"][0]
    r.resource_spec_id = "spec"
    r.parent_resource_id = "parent"
    source = build_source(r, repo.get(state["run_id"]).policy)
    state.update(claim_max_iterations=2, claim_revision_count=1)
    state["constraints"] = {"generation_revision_inputs": {"spec": {"kind": "claim", "input": {
        "parent_resource_id": "parent", "previous_structured_payload": deepcopy(r.review_practice_payload),
        "previous_text": source.text,
    }}}}
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == "finalize"
    # A real modification does not hit the no-change guard.
    state["constraints"]["generation_revision_inputs"]["spec"]["input"]["previous_text"] += "old"
    assert route_after_claim_decide(state) == "prepare_claim_revision"


def test_assessment_api_uses_public_projection_but_internal_metrics_remain_available():
    from app.api.runs.run_queries import get_run_claims
    from app.api.reviews.reviews import get_resource_review
    from app.models.learning_documents.schemas import ReviewSummary
    from starlette.requests import Request
    state, _, repo, gateway, counter = setup_source("分阶测试题")
    extract_and_judge(state, repo, gateway, counter)
    response = RunClaimsResponse(run_id=state["run_id"], claims=state["extracted_claims"],
                                judgements=state["claim_judgements"], resource_metrics=state["claim_metrics"])
    secret = "私有答案"
    internal_review = ReviewSummary(review_id="review", resource_id="r", status="approved",
                                   issues=[{"description": secret}], revision_instructions=[{"action": secret}])
    container = SimpleNamespace(
        run_query_service=lambda: SimpleNamespace(get_claims=lambda _: response),
        resource_service=lambda: SimpleNamespace(get=lambda _: state["generated_resources"][0]),
        review_service=lambda: SimpleNamespace(get_by_resource=lambda _: internal_review),
    )
    request = Request({"type": "http", "app": SimpleNamespace(container=container), "state": {}})
    public = get_run_claims(state["run_id"], request)
    assert public.claims == [] and public.resource_metrics == response.resource_metrics
    assert response.claims  # Internal publication service still receives all metrics and rows.
    assert secret not in get_resource_review("r", request).model_dump_json()


def test_structured_private_snapshot_roundtrips_sql_and_cannot_be_rewritten(tmp_path):
    from tests.fakes.persistence import sqlite_repository
    from tests.fakes.claim_extraction import prepare_ledger
    from app.core.execution import ExecutionFence, execution_fence
    state, _, memory, gateway, counter = setup_source("分阶测试题")
    audit, engine = sqlite_repository(tmp_path)
    try:
        with execution_fence(ExecutionFence(state["run_id"], "owner")):
            _, repo = prepare_ledger(audit, p=memory.get(state["run_id"]).policy)
            extract_and_judge(state, repo, gateway, counter)
            saved = repo.get(state["run_id"])
            result_key, result = next(iter(saved.state.results.items()))
            assert result.source_snapshot["payload_hash"] == state["generated_resources"][0].assessment_payload["payload_hash"]
            assert any("私有答案" in c.source_text for c in result.final_claims)
            replacement = result.model_copy(update={"source_snapshot": {**result.source_snapshot, "payload_hash": "0" * 64}})
            modified = saved.state.model_copy(update={"results": {result_key: replacement}})
            with pytest.raises(ValueError, match="identity|immutable"):
                repo.compare_and_swap(saved, modified, owner="owner", session_id=saved.state.execution_session_id)
            assert repo.get(state["run_id"]).state_hash == saved.state_hash
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["复习清单", "分阶测试题"])
def test_structured_missing_claim_uses_existing_supplement_and_publication(kind, supplement_storage, monkeypatch):
    from tests.integration.workflow.test_claim_evidence_retrieval import (
        _call_retrieve, _call_rejudge, _new_evidence, ObserverGateway, policy, query_hash,
    )
    from tests.fakes.evidence import ScriptedEvidenceRetriever
    from app.models.knowledge.knowledge import EvidenceBatch, RetrievalStatus
    state, _, repo, gateway, counter = setup_source(kind)
    extract_and_judge(state, repo, gateway, counter, bad_answer="missing")
    # Rebind the node result to the existing supplement test's isolated run.
    state["run_id"] = "run-claim"
    state["generated_resources"][0].run_id = "run-claim"
    for c in state["extracted_claims"]:
        c["run_id"] = "run-claim"
    for j in state["claim_judgements"]:
        j["run_id"] = "run-claim"
    state.update(knowledge_base_id="kb-fixture", include_claim_evidence_retrieval=True,
                 claim_evidence_retrieval_policy=policy().model_dump(mode="json"),
                 claim_evidence_retrieval_policy_hash=policy().policy_hash,
                 claim_workflow_version="contradiction_first_v3")
    assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"
    target = next(j["claim_id"] for j in state["claim_judgements"] if j["verdict"] == "not_in_evidence")
    def query(call):
        data = json.loads(call["messages"][-1].content)
        return {"batch_id": data["batch_id"], "input_hash": data["input_hash"],
                "items": [{"claim_id": target, "queries": [{"text": "RAG知识核验"}]}]}
    supplement_gateway = ObserverGateway([query])
    item = _new_evidence("chunk-structured", "冻结的补充事实证据。", "RAG知识核验")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[item], query_hashes=[query_hash("RAG知识核验")], query_count=1, candidate_count=1,
        dropped_candidate_count=0, config_hash="9" * 64)])
    state.update(_call_retrieve(state, supplement_storage, supplement_gateway, retriever))
    assert state["claim_evidence_retrieval_refs"][0]["status"] == "rejudging"
    supplement_gateway.outcomes = [{"judgements": [{"claim_id": target, "verdict": "supported",
        "evidence_ids": [item.evidence_id], "reason": "新增冻结证据支持", "confidence": 0.9}]}]
    state.update(_call_rejudge(state, supplement_storage, supplement_gateway))
    assert state["claim_metrics"]["r"]["not_in_evidence_claim_total"] == 0
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(claim_partial_publish=False))
    assert decide_node(state)["generated_resources"][0].publication_status == "published"
