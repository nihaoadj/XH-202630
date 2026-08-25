"""Four deterministic end-to-end V2 checklist release samples."""
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.models.learning_documents.schemas import LearnerProfile
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def _node_payload(node_id: str, evidence_id: str) -> dict:
    recall = lambda index: {"local_id": f"recall-{index}", "prompt": f"闭卷说明 {node_id} 的要点 {index}。", "reference_answer": f"{node_id} 的证据化答案 {index}。", "explanation": "答案只概括当前 Evidence 支持的要点。", "evidence_ids": [evidence_id], "pass_criteria": "说出关键条件并能指出证据。"}
    distinction = lambda index, truth: {"local_id": f"distinction-{index}", "statement": f"关于 {node_id} 的待判断陈述 {index}。", "truth_value": truth, "correction": "以冻结 Evidence 中的条件为准。", "explanation": "核对陈述是否满足 Evidence 明确条件。", "evidence_ids": [evidence_id], "pass_criteria": "判断正误并说明证据依据。"}
    return {"schema_version": "2.0", "skill_node_id": node_id, "skill_node_name": node_id,
            "recall_questions": [recall(1), recall(2), recall(3), recall(4)],
            "distinction_questions": [distinction(1, True), distinction(2, False), distinction(3, True), distinction(4, False)],
            "example_recognition": None,
            "example_recognition_questions": [{"local_id": "example-1", "candidate_a": "满足明确条件的情境。", "candidate_b": "只缺少一个明确条件的情境。", "positive_candidate": "A", "decisive_boundary": "是否满足冻结 Evidence 明确给出的条件。", "explanation": "反例只违反该单一条件。", "evidence_ids": [evidence_id], "pass_criteria": "识别正反例并说明边界."}, {"local_id": "example-2", "candidate_a": "满足全部明确条件的情境。", "candidate_b": "违反一个关键边界的情境。", "positive_candidate": "A", "decisive_boundary": "是否违反冻结 Evidence 明确给出的关键边界。", "explanation": "反例只违反该单一边界。", "evidence_ids": [evidence_id], "pass_criteria": "识别正反例并说明边界。"}],
            "omitted_slots": [], "knowledge_summary": "本节点小结要求以已冻结证据为唯一依据，完整说明核心概念、实际作用、关键边界和典型误区，并把主动回忆、概念辨析与正反例识别整合为一次可执行复盘。下一次复习时应逐项检查结论是否满足前提、是否能准确回溯到来源；一旦发现遗漏条件、混淆概念或无法解释判断依据，就应回到原始材料核对后再继续学习。", "summary_evidence_ids": [evidence_id], "evidence_ids": [evidence_id]}


@pytest.mark.parametrize("batch", range(1, 5))
def test_four_review_practice_batches_publish(monkeypatch, batch):
    monkeypatch.setattr("app.agents.resource_workflows.learning_documents.generator_agent.get_settings", lambda: SimpleNamespace(resource_worker_max_concurrency=1))
    node_id, evidence_id = f"review-node-{batch}", f"review-ev-{batch}"
    evidence = make_evidence(evidence_id=evidence_id, chunk_id=f"review-chunk-{batch}", excerpt=f"{node_id} 的冻结证据包含明确条件。")
    state = {"schema_version": "1.0", "run_id": f"review-run-{batch}", "batch_id": f"review-batch-{batch}",
             "learner": LearnerProfile(learner_id=f"review-learner-{batch}", learner_type="测试", education="本科", major="计算机", skill_level="中级", learning_goal="主动回忆"),
             "topic": "受控检索", "resource_types": ["复习清单"], "target_skill_nodes": [node_id],
             "retrieved_evidence": [evidence], "node_evidence_map": {node_id: [evidence_id]},
             "learning_plan": {"learning_path": [{"topic": node_id, "order": 1}]}, "generation_attempt": 1, "trace": [], "include_claim_check": False}
    generated = generate_node(state, llm_gateway=ScriptedLLMGateway([_node_payload(node_id, evidence_id)]))
    reviewed = review_node({**state, **generated}, llm_gateway=ScriptedLLMGateway([{"decision": "approve", "hallucination_score": 0.0, "issues": [], "difficulty_match": True, "coverage_rate": 1.0, "suggestion": "结构、证据和难度符合要求。", "revision_instructions": []}]))
    resource = reviewed["generated_resources"][0]
    assert resource.review_status == "approved"
    assert resource.publication_status == "published"
