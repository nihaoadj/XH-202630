from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.services.courseware.composition import compose_scenes


def _source(nodes=1):
    blocks = []
    package_nodes = []
    for index in range(1, nodes + 1):
        recall = [{"question_id": f"q-{index}01", "prompt": "核心含义是什么？", "reference_answer": "参考答案", "explanation": "证据解释", "pass_criteria": "说明关键条件"}]
        distinction = [{"question_id": f"q-{index}04", "statement": "待判断陈述", "truth_value": False, "correction": "修正表述", "explanation": "判断依据"}]
        example = {"question_id": f"q-{index}07", "candidate_a": "A", "candidate_b": "B", "positive_candidate": "A", "decisive_boundary": "明确边界", "explanation": "边界解释"}
        package_nodes.append({"skill_node_id": f"node-{index}", "skill_node_name": f"节点{index}", "recall_questions": recall, "distinction_questions": distinction, "example_recognition": example, "omitted_slots": []})
        for question in [*recall, *distinction, example]:
            blocks.append({"block_id": f"b-{question['question_id']}", "review_question_id": question["question_id"], "text": question.get("prompt") or question.get("statement") or question["candidate_a"]})
    return {"resource_id": "review", "resource_type": "复习清单", "resource_family_id": "review", "role": "checklist", "version": 1, "topic": "主题", "knowledge_points": [item["skill_node_id"] for item in package_nodes], "content": "复习清单", "content_hash": "a" * 64, "blocks": blocks, "exercise_items": [], "source_graph": {"nodes": [{"node_id": "resource:review", "node_type": "resource", "resource_id": "review", "version": 1}], "edges": []}, "review_practice_payload_hash": "b" * 64, "review_practice_payload": {"schema_version": "2.0", "title": "主题复习清单", "instructions": "先回忆后揭示", "payload_hash": "b" * 64, "node_blocks": package_nodes}}


def test_review_practice_v2_has_fixed_three_pages_per_node_and_hidden_answers():
    source = _source(2)
    design = build_learning_design([source])
    assert len(design.storyboard.scenes) == 8
    scenes, warnings = compose_scenes([source], learning_design=design)
    assert not warnings
    assert [scene["page_role"] for scene in scenes] == ["review_overview", "review_recall", "review_distinction", "review_example", "review_recall", "review_distinction", "review_example", "summary_action"]
    html = render_courseware({"title": "主题复习清单", "scenes": scenes}).decode()
    assert "data-review-reveal" in html
    assert 'class="review-answer" hidden' in html
    assert "review_self_assessed" in html


def test_review_practice_v2_keeps_reflection_page_when_example_is_omitted():
    source = _source()
    node = source["review_practice_payload"]["node_blocks"][0]
    node["example_recognition"] = None
    node["omitted_slots"] = [{"local_id": "example-1", "reason": "NO_EXPLICIT_CONCEPT_BOUNDARY"}]
    scenes, _ = compose_scenes([source])
    example = next(scene for scene in scenes if scene["page_role"] == "review_example")
    assert example["component_blocks"][0]["component"] == "review_reflection"
