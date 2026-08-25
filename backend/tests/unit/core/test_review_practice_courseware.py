from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.services.courseware.composition import compose_scenes


def _source(nodes=1):
    blocks = []
    package_nodes = []
    for index in range(1, nodes + 1):
        recall = [{"question_id": f"q-{index}{item:02d}", "prompt": f"核心含义是什么（{item}）？", "reference_answer": "参考答案", "explanation": "证据解释", "pass_criteria": "说明关键条件"} for item in range(1, 5)]
        distinction = [{"question_id": f"q-{index}{item:02d}", "statement": f"待判断陈述（{item}）", "truth_value": False, "correction": "修正表述", "explanation": "判断依据"} for item in range(5, 9)]
        examples = [{"question_id": f"q-{index}{item:02d}", "candidate_a": "A", "candidate_b": "B", "positive_candidate": "A", "decisive_boundary": "明确边界", "explanation": "边界解释"} for item in range(9, 11)]
        package_nodes.append({"skill_node_id": f"node-{index}", "skill_node_name": f"节点{index}", "recall_questions": recall, "distinction_questions": distinction, "example_recognition": None, "example_recognition_questions": examples, "omitted_slots": [], "knowledge_summary": f"节点{index}的小结应以冻结证据为依据，完整说明核心概念、实际作用和判断边界，并把主动回忆、概念辨析与正反例识别连成一次可执行的复盘。复习时需要逐项核对结论是否满足前提、是否能够定位到来源；若发现遗漏条件、混淆概念或无法解释判断依据，应及时回到材料重新确认，再进入下一个学习节点。", "summary_evidence_ids": ["ev-review"]})
        for question in [*recall, *distinction, *examples]:
            blocks.append({"block_id": f"b-{question['question_id']}", "review_question_id": question["question_id"], "text": question.get("prompt") or question.get("statement") or question["candidate_a"]})
    for node in package_nodes:
        blocks.append({"block_id": f"summary-{node['skill_node_id']}", "text": node["knowledge_summary"], "kind": "review_summary", "skill_node_id": node["skill_node_id"]})
    return {"resource_id": "review", "resource_type": "复习清单", "resource_family_id": "review", "role": "checklist", "version": 1, "topic": "主题", "knowledge_points": [item["skill_node_id"] for item in package_nodes], "content": "复习清单", "content_hash": "a" * 64, "blocks": blocks, "exercise_items": [], "source_graph": {"nodes": [{"node_id": "resource:review", "node_type": "resource", "resource_id": "review", "version": 1}], "edges": []}, "review_practice_payload_hash": "b" * 64, "review_practice_payload": {"schema_version": "2.0", "title": "主题复习清单", "instructions": "先回忆后揭示", "payload_hash": "b" * 64, "node_blocks": package_nodes}}


def test_review_practice_v2_paginates_two_questions_per_page_and_hides_answers():
    source = _source(2)
    design = build_learning_design([source])
    assert len(design.storyboard.scenes) == 14
    scenes, warnings = compose_scenes([source], learning_design=design)
    assert not warnings
    assert [scene["page_role"] for scene in scenes] == ["review_overview", "review_recall", "review_recall", "review_distinction", "review_distinction", "review_example", "review_node_summary", "review_recall", "review_recall", "review_distinction", "review_distinction", "review_example", "review_node_summary", "summary_action"]
    assert all(len(scene["component_blocks"][0]["items"]) == 2 for scene in scenes if scene["page_role"] in {"review_recall", "review_distinction", "review_example"})
    html = render_courseware({"title": "主题复习清单", "scenes": scenes}).decode()
    assert "data-review-reveal" in html
    assert 'class="review-answer" hidden' in html
    assert "review_self_assessed" in html
    assert "review-overview-card" in html
    assert "学习范围" in html
    assert "学习方法" in html
    assert "review-overview-path" in html
    assert 'data-review-rating="uncertain" aria-pressed="false"' in html
    assert "card.querySelectorAll('[data-review-rating]').forEach(button=>{const selected=button===choice" in html
    assert ".review-card{min-height:clamp(20rem,43vh,30rem);height:100%}" in html
    assert ".review-answer{max-height:min(24vh,14rem);overflow-y:auto" in html
    assert "NODE RECAP" in html
    assert "review-node-summary" in html
    assert 'class="block component-review-node-summary review-node-summary"' in html
    assert ".recipe-review_node_summary .scene-body>.review-node-summary{display:grid" in html
    assert ".review-summary-action{grid-column:2;grid-row:1/4" in html
    assert "recipe-review_recall_grid .scene-body,.recipe-review_distinction_grid .scene-body{display:block;overflow-y:auto" in html
    assert "[data-review-practice]{min-height:auto;overflow:visible}" in html
    assert ".recipe-review_overview{color:#fff;background:linear-gradient" in html
    assert "['cover','review_overview'].includes" in html
    assert ".recipe-recap_dashboard[data-page-role=\"summary_action\"]" in html
    assert "review-completion-kicker" in html
    assert "review-completion-summary" in html
    assert "OVERALL REVIEW" in html
    assert "review-completion-next" in html
    assert ".review-overview-card p{min-height:0;max-height:clamp(7rem,16vh,12rem);overflow-y:auto" in html
    assert '.recipe-recap_dashboard[data-page-role="summary_action"] .review-completion-summary,.recipe-recap_dashboard[data-page-role="summary_action"] .review-completion-next{min-height:0;overflow-y:auto' in html


def test_review_practice_v2_keeps_reflection_page_when_example_is_omitted():
    source = _source()
    node = source["review_practice_payload"]["node_blocks"][0]
    node["example_recognition"] = None
    node["example_recognition_questions"] = []
    node["omitted_slots"] = [{"local_id": "example-1", "reason": "NO_EXPLICIT_CONCEPT_BOUNDARY"}, {"local_id": "example-2", "reason": "NO_EXPLICIT_CONCEPT_BOUNDARY"}]
    scenes, _ = compose_scenes([source])
    example = next(scene for scene in scenes if scene["page_role"] == "review_example")
    assert example["component_blocks"][0]["component"] == "review_reflection"
