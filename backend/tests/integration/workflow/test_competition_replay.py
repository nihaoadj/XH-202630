"""54 frozen cases through the real graph/Claim/publish controls with scripted Agents.

This is workflow evidence, not live generation or independent knowledge grading.
"""
import json
import os
from pathlib import Path

from app.agents.resource_workflows.learning_documents import workflow as graph
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node
from app.config import PROJECT_ROOT
from app.core.learning_tiers import difficulty_for_tier
from app.core.retrieval.evidence import source_refs_from_evidence
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.shared.agent_contracts import build_trace_item
from app.models.shared.workflow import StepStatus
from app.services.generation.generation import build_workflow_state
from app.services.reports.competition_evidence import json_hash
from app.services.reports.competition_suite import build_live_plan, load_skill_node_tiers, load_suite, _build_live_request, _case_reference
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def test_frozen_cases_preserve_input_agent_claim_and_output_chain(monkeypatch, tmp_path):
    suite = load_suite()
    tiers = load_skill_node_tiers(suite["knowledge_base_id"])
    records = []
    for plan in build_live_plan(suite):
        gold = next(item for item in suite["claims_payload"]["claims"]
                    if item["knowledge_point_id"] in plan.target_skill_nodes and item["verdict"] == "supported")
        evidence_id = gold["evidence_ids"][0]
        source = suite["sources_payload"]["evidence"][evidence_id]
        text = (PROJECT_ROOT / "knowledge_base" / plan.knowledge_base_id / source["file"]).read_text(encoding="utf-8")
        excerpt = "\n".join(text.splitlines()[source["start_line"] - 1:source["end_line"]])
        evidence = make_evidence(knowledge_base_id=plan.knowledge_base_id, evidence_id=evidence_id,
            document_id=source["document_id"], document_version="dv_" + suite["sources_payload"]["files"][source["file"]],
            chunk_id="chk_" + source["section_sha256"], excerpt=excerpt, source_path=source["file"])
        evidence = evidence.model_copy(update={"locator": evidence.locator.model_copy(update={
            "title": source["document_id"], "section": source["section"],
            "line_start": source["start_line"], "line_end": source["end_line"]})})
        content = f"# {plan.resource_type}\n\n{gold['claim_text']}"
        resource = LearningResource(resource_id="replay-" + plan.case_id, run_id="replay-" + plan.case_id,
            resource_type=plan.resource_type, difficulty=difficulty_for_tier(tiers[plan.target_skill_nodes[0]]),
            content_text=content, knowledge_points=plan.target_skill_nodes, source_refs=source_refs_from_evidence([evidence]))

        background = _case_reference(suite, plan)["background_id"]
        def trace(state, name, output_summary):
            return [build_trace_item(state, agent_name=name, action=name, status=StepStatus.SUCCESS,
                                    input_summary=f"background={background}; target={plan.target_skill_nodes[0]}; type={plan.resource_type}",
                                    output_summary=output_summary, decision_reason="frozen gold/scripted decision; not independent review")]
        def diagnose(state):
            return {"diagnosis": {"target_skill_nodes": plan.target_skill_nodes, "tier": tiers[plan.target_skill_nodes[0]]},
                    "trace": trace(state, "diagnosis", f"target tier={tiers[plan.target_skill_nodes[0]]}"), "errors": []}
        def retrieve(state):
            return {"retrieval_status": "available", "retrieved_evidence": [evidence], "retrieval_config_hash": "2" * 64,
                    "retrieval_query_hashes": [evidence.query_hash], "trace": trace(state, "retriever", f"source={source['document_id']}; evidence={evidence_id}"), "errors": []}
        def planner(state):
            return {"learning_plan": {"target_skill_nodes": plan.target_skill_nodes, "resource_types": [plan.resource_type]},
                    "trace": trace(state, "planner", f"resource type={plan.resource_type}; target={plan.target_skill_nodes[0]}"), "errors": []}
        def generate(state):
            return {"generated_resources": [resource], "trace": trace(state, "generator", f"resource={resource.resource_id}; difficulty={resource.difficulty}"), "errors": []}
        def review(state):
            return {"review_result": {"decision": "approve", "status": "approve", "passed": True,
                    "hallucination_score": 0.0, "review_ids": {resource.resource_id: "review-" + plan.case_id}},
                    "trace": trace(state, "reviewer", "decision=approve; scripted gold content"), "errors": []}
        def extract(state):
            gateway = ScriptedLLMGateway([{"resources": [{"resource_id": resource.resource_id, "claims": [{
                "claim_text": gold["claim_text"], "claim_type": "factual", "source_text": gold["claim_text"],
                "source_start": content.index(gold["claim_text"]), "source_end": len(content),
                "knowledge_point_id": plan.target_skill_nodes[0], "source_evidence_ids": [evidence_id]}]}]}])
            return claim_extract_node(state, llm_gateway=gateway)
        def judge(state):
            gateway = ScriptedLLMGateway([{"judgements": [{"claim_id": item["claim_id"], "verdict": "supported",
                "evidence_ids": [evidence_id], "reason": "scripted gold verdict; not independent review", "confidence": 1.0}
                for item in state["extracted_claims"]]}])
            return claim_judge_node(state, llm_gateway=gateway)
        for name, node in (("diagnose_node", diagnose), ("retrieve_node", retrieve), ("plan_node", planner),
                           ("generate_node", generate), ("review_node", review), ("claim_extract_node", extract), ("claim_judge_node", judge)):
            monkeypatch.setattr(graph, name, node)
        profile = LearnerProfile(learner_id=plan.learner_id, learner_type="frozen synthetic profile", education=plan.education,
            major=plan.major, learning_goal=plan.learning_goal, knowledge_base_id=plan.knowledge_base_id, skill_level=plan.skill_level)
        state = build_workflow_state(profile, _build_live_request(profile, plan), run_id="replay-" + plan.case_id)
        # An empty scripted gateway fails if any unplanned node attempts a model call.
        result = graph.build_workflow(llm_gateway=ScriptedLLMGateway([])).invoke(state)
        assert result["workflow_status"] == "completed", result.get("errors")
        assert result["claim_check_status"] == "completed"
        output = result["generated_resources"][0].model_dump(mode="json")
        assert output["publication_status"] == "published"
        assert output["source_refs"][0]["doc_id"] == source["document_id"]
        assert output["source_refs"][0]["line_start"] == source["start_line"]
        assert output["source_refs"][0]["section"] == source["section"]
        roles = {item["agent_name"] for item in result["trace"]}
        assert {"diagnosis", "retriever", "planner", "generator", "reviewer"} <= roles
        assert result["diagnosis"]["target_skill_nodes"] == plan.target_skill_nodes
        assert result["learning_plan"]["resource_types"] == [plan.resource_type]
        record = _case_reference(suite, plan)
        record.update(status="REPLAY_COMPLETED", trace=result["trace"], retrieved_evidence=evidence.model_dump(mode="json"),
                      diagnosis=result["diagnosis"], learning_plan=result["learning_plan"], review_result=result["review_result"],
                      claims=result["extracted_claims"], judgements=result["claim_judgements"],
                      output=output, output_hash=json_hash(output))
        records.append(record)
    assert len(records) == 54 and len({item["background_id"] for item in records}) == 3
    assert len({item["output"]["resource_type"] for item in records}) == 3
    output_dir = Path(os.getenv("TEST_RUN_OUTPUT", str(tmp_path)))
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0", "evidence_scope": "deterministic_workflow_replay_with_scripted_agents",
               "source_snapshot_hash": json_hash(suite["sources_payload"]), "case_count": len(records),
               "live_generation_count": 0, "independent_quality_review": "NOT_RUN", "cases": records}
    (output_dir / "competition-replay.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
