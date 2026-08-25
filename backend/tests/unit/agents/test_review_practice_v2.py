from app.agents.resource_agents.checklist import _canonical_hash, render_review_practice_markdown
from app.models.shared.agent_contracts import ReviewPracticeNodeBlockV2, ReviewPracticePackageV2


def _block():
    return ReviewPracticeNodeBlockV2(
        skill_node_id="node-a", skill_node_name="节点 A", evidence_ids=["ev-1"],
        recall_questions=[{"local_id": "recall-1", "prompt": "说明概念。", "reference_answer": "答案。", "explanation": "解释。", "evidence_ids": ["ev-1"], "pass_criteria": "包含关键条件。"}],
        distinction_questions=[{"local_id": "distinction-1", "statement": "这是待判断陈述。", "truth_value": False, "correction": "应改为证据支持的表述。", "explanation": "解释。", "evidence_ids": ["ev-1"], "pass_criteria": "判断并说明依据。"}],
        omitted_slots=[
            {"local_id": "recall-2", "reason": "INSUFFICIENT_DISTINCT_EVIDENCE"},
            {"local_id": "recall-3", "reason": "INSUFFICIENT_DISTINCT_EVIDENCE"},
            {"local_id": "distinction-2", "reason": "INSUFFICIENT_DISTINCT_EVIDENCE"},
            {"local_id": "distinction-3", "reason": "INSUFFICIENT_DISTINCT_EVIDENCE"},
            {"local_id": "example-1", "reason": "NO_EXPLICIT_CONCEPT_BOUNDARY"},
        ],
    )


def test_review_practice_minimum_quota_and_deterministic_markdown():
    package = ReviewPracticePackageV2(title="主题复习清单", instructions="先闭卷作答。", node_blocks=[_block()]).model_dump(mode="json")
    package["node_blocks"][0]["recall_questions"][0]["question_id"] = "q-001"
    package["node_blocks"][0]["distinction_questions"][0]["question_id"] = "q-004"
    package["payload_hash"] = _canonical_hash(package)
    first = render_review_practice_markdown(package)
    assert first == render_review_practice_markdown(package)
    assert first.index("## 答案与证据解释") > first.index("## 节点一")
    assert "[ ] 会  [ ] 模糊  [ ] 不会" in first


def test_review_practice_rejects_unaccounted_fixed_slots():
    payload = _block().model_dump(mode="json")
    payload["omitted_slots"].pop()
    try:
        ReviewPracticeNodeBlockV2.model_validate(payload)
    except ValueError:
        return
    raise AssertionError("missing fixed slot must fail")
