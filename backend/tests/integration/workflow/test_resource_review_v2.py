import json
from types import SimpleNamespace

from app.agents.resource_agents.assessment import AssessmentAgent
from app.agents.resource_agents.checklist import ReviewChecklistAgent
from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.agents.resource_workflows.learning_documents.workflow import prepare_revision_node
from app.core.retrieval.evidence import source_refs_from_evidence
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.agent_contracts import ResourceGenerationContext
from app.services.generation.generation import _request_snapshot, build_workflow_state
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import approve, case, combined_output, questions, scope_output, state_for
from tests.unit.agents.test_resource_type_agents import CASE_STUDY_MARKDOWN, CHECKLIST_PAYLOAD, _inputs
from tests.unit.agents.test_structured_assessment import _block


def test_five_types_review_in_order_and_default_assessment_has_only_two_calls():
    sample = case("assessment.clean.01")
    state = state_for(sample)
    spec, context, evidence = _inputs("复习清单")
    artifact = ReviewChecklistAgent().generate(spec, context, llm_gateway=ScriptedLLMGateway([CHECKLIST_PAYLOAD]))
    practice = state_for()["generated_resources"][0]
    assessment = state["generated_resources"][0]
    state["retrieved_evidence"].extend([evidence, state_for()["retrieved_evidence"][0]])
    state["generated_resources"] = [
        LearningResource(resource_id="lecture", resource_type="讲义", difficulty="初级", content_text="# 讲义", knowledge_points=["synthetic-1"], source_refs=assessment.source_refs),
        practice, assessment,
        LearningResource(resource_id="case", resource_type="案例分析", difficulty="初级", content_text=CASE_STUDY_MARKDOWN, knowledge_points=["synthetic-1"], source_refs=assessment.source_refs),
        LearningResource(resource_id="checklist", resource_type="复习清单", difficulty="初级", content_text=artifact.content_text,
            knowledge_points=["skill-search"], review_practice_payload=artifact.artifact_data["review_practice_package"], source_refs=source_refs_from_evidence([evidence])),
    ]
    gateway = ScriptedLLMGateway([approve(), approve(), scope_output(sample), approve(), approve(), approve()])
    result = review_node(state, llm_gateway=gateway)
    assert len(gateway.calls) == 6
    assert [c["phase"] for c in result["review_audit"]["calls"]] == ["content_v2", "practice_semantic_v2", "assessment_scope_v1", "assessment_package_v1", "content_v2", "content_v2"]
    assert all(r.publication_status == "published" for r in result["generated_resources"])


def test_correction_package_layout_remains_advisory():
    state = state_for()
    state["generated_resources"] = [LearningResource(resource_id="correction", resource_type="个性化纠错训练包", difficulty="初级",
        content_text="先练习再总结，章节可以自由组织。", knowledge_points=["synthetic-practice"], source_refs=state["generated_resources"][0].source_refs)]
    result = review_node(state, llm_gateway=ScriptedLLMGateway([approve()]))
    assert result["review_result"]["decision"] == "approve"


def test_all_failed_questions_reach_real_generator_scoped_to_node_and_sibling_is_untouched(monkeypatch):
    monkeypatch.setattr("app.agents.resource_workflows.learning_documents.generator_agent.get_settings", lambda: SimpleNamespace(resource_worker_max_concurrency=1))
    sample = case("assessment.clean.12")
    state = state_for(sample, strategy="combined_v2")
    evidence = state["retrieved_evidence"]
    specs = build_resource_specs(run_id=state["run_id"], resource_types=["分阶测试题"], topic="合成工单", difficulty="初级",
        learning_plan={}, evidence=evidence, target_skill_nodes=state["target_skill_nodes"])
    state.update(resource_specs=[s.model_dump(mode="json") for s in specs], resource_types=["分阶测试题"], topic="合成工单",
                 learner=LearnerProfile(learner_id="synthetic-learner", learner_type="测试", education="本科", major="测试", learning_goal="验证审核修订"))
    state["generated_resources"][0].resource_spec_id = specs[0].resource_spec_id
    sibling = LearningResource(resource_id="approved-sibling", resource_type="讲义", difficulty="初级", content_text="# 已批准讲义",
        knowledge_points=["synthetic-1"], review_status="approved", publication_status="published", review_id="sibling-review", source_refs=[])
    # The sibling is already terminal and therefore does not enter resource-scope resolution.
    state["generated_resources"].append(sibling)
    raw = combined_output(sample, failed_ids=[q["question_id"] for q in questions(sample)])
    reviewed = review_node(state, llm_gateway=ScriptedLLMGateway([raw]))
    revised = prepare_revision_node({**state, **reviewed})
    assert len(revised["constraints"]["revision_feedback"]["assessment_findings"]) == 12
    gateway = ScriptedLLMGateway([_block("synthetic-1", evidence[0].evidence_id), _block("synthetic-2", evidence[1].evidence_id)])
    generated = generate_node({**state, **reviewed, **revised}, llm_gateway=gateway)
    for index, call in enumerate(gateway.calls):
        payload = json.loads(call["messages"][-1].content)
        findings = payload["revision_feedback"]["assessment_findings"]
        assert len(findings) == 6
        assert {f["skill_node_id"] for f in findings} == {f"synthetic-{index+1}"}
        assert len(payload["revision_feedback"]["rejected_question_ids"]) == 6
    assert next(r for r in generated["generated_resources"] if r.resource_id == sibling.resource_id) == sibling


def test_policy_frozen_by_service_cannot_be_overridden_by_request(monkeypatch):
    from app.config import Settings
    settings = Settings(_env_file=None, assessment_review_strategy="two_stage_v1")
    monkeypatch.setattr("app.services.generation.generation.get_settings", lambda: settings)
    learner = LearnerProfile(learner_id="frozen", learner_type="测试", education="本科", major="测试", learning_goal="验证策略冻结")
    request = GenerateRequest(learner_id="frozen", topic="合成测试", resource_types=["讲义"])
    state = build_workflow_state(learner, request)
    settings.assessment_review_strategy = "combined_v2"
    settings.assessment_review_context_tokens = 262144
    assert state["review_policy"]["assessment_strategy"] == "two_stage_v1"
    assert _request_snapshot(request, state)["review_policy"] == state["review_policy"]


def test_private_answers_and_model_echo_cannot_enter_trace_summary_or_markdown():
    sample = case("assessment.clean.01")
    sample["resource"]["assessment_payload"]["node_blocks"][0]["short_answer_questions"][0]["reference_answer"] = "PRIVATE_ANSWER_SENTINEL"
    raw = combined_output(sample, failed_ids=["q-001"])
    raw["findings"][0]["reason"] = "PRIVATE_ANSWER_SENTINEL"
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=ScriptedLLMGateway([raw]))
    for value in [result["review_audit"], result["review_result"], result["trace"], result["errors"], result["generated_resources"][0].content_text]:
        assert "PRIVATE_ANSWER_SENTINEL" not in str(value)
