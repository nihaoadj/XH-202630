"""Prompt routing: one typed revision input, never both, per resource worker (T46)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agents.resource_agents.revision_prompts import (
    CLAIM_REVISION_GUIDANCE,
    ORDINARY_REVISION_GUIDANCE,
    attach_revision_fields,
)
from app.agents.resource_agents.registry import get_resource_agent
from app.core.retrieval.knowledge_ids import sha256_hex
from app.models.reviews.revision_inputs import (
    ClaimReviewRevisionInput,
    ClaimRevisionContextGroupV1,
    ClaimRevisionProblemV1,
    ResourceReviewRevisionInput,
    RevisionSourceSpanV1,
)
from app.models.shared.agent_contracts import ResourceGenerationContext, ResourceSpec
from tests.fakes.evidence import make_evidence


def _spec(resource_type="讲义", knowledge_points=None, node_evidence_map=None):
    return ResourceSpec(
        resource_spec_id="11111111-1111-1111-1111-111111111111",
        resource_family_id="22222222-2222-2222-2222-222222222222",
        resource_type=resource_type,
        learning_objective="学习目标",
        knowledge_points=knowledge_points or ["node-1"],
        evidence_ids=["evidence"],
        node_evidence_map=node_evidence_map or {"node-1": ["evidence"]},
        difficulty="初级",
        representations=[{"representation": "text", "max_output_tokens": 1024}],
        display_order=1,
    )


def _claim_input():
    return ClaimReviewRevisionInput(
        resource_spec_id="spec",
        parent_resource_id="parent",
        parent_version=1,
        content_hash=sha256_hex("原句"),
        previous_text="原句",
        targets=["node-1"],
        spans=[RevisionSourceSpanV1(span_id="sp_0000", source_text="原句", source_start=0, source_end=2, source_text_hash=sha256_hex("原句"))],
        problems=[ClaimRevisionProblemV1(claim_id="clm_a", claim_index=0, claim_text="断言", verdict="contradicted", reason="理由", source_span_id="sp_0000", evidence_ids=["evidence"])],
        groups=[ClaimRevisionContextGroupV1(group_id="grp_0000", unit_id="u_0", problem_claim_ids=["clm_a"])],
    )


def _ordinary_input():
    return ResourceReviewRevisionInput(
        resource_spec_id="spec",
        parent_resource_id="parent",
        revision_source="compat",
        feedback={"issues": [{"message": "修"}]},
    )


def _context(*, claim=None, ordinary=None, constraints=None):
    return ResourceGenerationContext(
        run_id="run",
        batch_id="batch",
        topic="主题",
        evidence=[make_evidence(evidence_id="evidence", chunk_id="chunk")],
        node_evidence_map={"node-1": ["evidence"]},
        constraints=constraints or {},
        claim_review_revision=claim,
        resource_review_revision=ordinary,
    )


def _human_payload(messages):
    return json.loads(messages[1].content)


def test_attach_revision_fields_claim_vs_ordinary_are_mutually_exclusive():
    payload = {}
    assert attach_revision_fields(payload, _context(claim=_claim_input())) == {
        "claim_review_revision": _claim_input().model_dump(mode="json"),
        "revision_guidance": CLAIM_REVISION_GUIDANCE,
    }
    ordinary_payload = {}
    attach_revision_fields(ordinary_payload, _context(ordinary=_ordinary_input()))
    assert "resource_review_revision" in ordinary_payload
    assert "claim_review_revision" not in ordinary_payload
    assert ordinary_payload["revision_guidance"] == ORDINARY_REVISION_GUIDANCE


def test_v3_ordinary_revision_sends_one_numbered_parent_copy():
    ordinary = ResourceReviewRevisionInput(
        resource_spec_id="spec", parent_resource_id="parent", previous_text="# 标题\n问题句",
        input_version="2.0", issues=[{"issue_id": "i1", "location": {
            "kind": "paragraph", "paragraph_id": "p000002", "end_paragraph_id": "p000003"}}],
    )
    payload = attach_revision_fields({}, _context(ordinary=ordinary))
    assert ordinary.previous_text == "# 标题\n问题句"
    assert payload["resource_review_revision"]["previous_text"] == "p000001 | # 标题\np000002 | 问题句"
    assert "end_paragraph_id" in payload["revision_guidance"]
    assert "不得包含编号" in payload["revision_guidance"]


def test_attach_revision_fields_leaves_first_generation_untouched():
    payload = {"constraints": {}}
    assert attach_revision_fields(payload, _context()) == payload
    assert "revision_guidance" not in payload


def test_context_rejects_both_inputs_at_once():
    with pytest.raises(ValidationError):
        _context(claim=_claim_input(), ordinary=_ordinary_input())


def test_common_prompt_payload_claim_input_replaces_legacy_fields():
    agent = get_resource_agent("讲义")
    spec = _spec("讲义")
    context = _context(claim=_claim_input(), constraints={"revision_feedback": {"stale": True}})
    payload = agent.common_prompt_payload(spec, context)
    assert "claim_review_revision" in payload
    assert payload["revision_guidance"] == CLAIM_REVISION_GUIDANCE
    assert "revision_feedback" not in payload
    assert "resource_review_revision" not in payload
    assert "generation_revision_inputs" not in payload.get("constraints", {})


def test_common_prompt_payload_ordinary_input():
    payload = get_resource_agent("讲义").common_prompt_payload(_spec("讲义"), _context(ordinary=_ordinary_input()))
    assert "resource_review_revision" in payload
    assert payload["revision_guidance"] == ORDINARY_REVISION_GUIDANCE
    assert "claim_review_revision" not in payload


def test_common_prompt_payload_legacy_revision_feedback_still_works_without_typed_input():
    context = _context(constraints={"revision_feedback": {"issues": [{"message": "修"}]}})
    payload = get_resource_agent("讲义").common_prompt_payload(_spec("讲义"), context)
    assert payload["revision_feedback"] == {"issues": [{"message": "修"}]}
    assert "claim_review_revision" not in payload and "resource_review_revision" not in payload


@pytest.mark.parametrize("resource_type", ["讲义", "案例分析", "实操指南"])
def test_base_path_types_attach_typed_claim_input(resource_type):
    agent = get_resource_agent(resource_type)
    payload = agent.common_prompt_payload(_spec(resource_type), _context(claim=_claim_input()))
    assert payload.get("claim_review_revision") == _claim_input().model_dump(mode="json")
    assert payload["revision_guidance"] == CLAIM_REVISION_GUIDANCE


def test_assessment_messages_attach_typed_input():
    agent = get_resource_agent("分阶测试题")
    spec = _spec("分阶测试题")
    messages = agent._messages(spec, _context(claim=_claim_input()), "node-1")
    payload = _human_payload(messages)
    assert payload["claim_review_revision"] == _claim_input().model_dump(mode="json")
    assert payload["revision_guidance"] == CLAIM_REVISION_GUIDANCE


def test_checklist_messages_attach_typed_input():
    agent = get_resource_agent("复习清单")
    spec = _spec("复习清单")
    messages = agent._messages(spec, _context(ordinary=_ordinary_input()), "node-1")
    payload = _human_payload(messages)
    assert payload["resource_review_revision"] == _ordinary_input().model_dump(mode="json")
    assert payload["revision_guidance"] == ORDINARY_REVISION_GUIDANCE


def test_correction_package_payload_attaches_typed_input():
    agent = get_resource_agent("个性化纠错训练包")
    spec = _spec("个性化纠错训练包")
    constraints = {"correction_focus_snapshot": {"ordered_target_nodes": [{"skill_node_id": "node-1"}]}}
    payload = agent._prompt_payload(spec, _context(claim=_claim_input(), constraints=constraints))
    assert payload["claim_review_revision"] == _claim_input().model_dump(mode="json")
    assert payload["revision_guidance"] == CLAIM_REVISION_GUIDANCE


def _preservation_context():
    text = "# 标题\r\n\r\n保留甲。目标原句。保留乙。\n"
    start = text.index("目标原句。")
    claim = _claim_input().model_copy(update={
        "previous_text": text, "content_hash": sha256_hex(text),
        "spans": [RevisionSourceSpanV1(span_id="sp_0000", source_text="目标原句。",
                    source_start=start, source_end=start+5, source_text_hash=sha256_hex("目标原句。"))],
    })
    return _context(claim=claim, constraints={"_claim_revision_edit_policy": "minimal_change_v1"}), text, start


@pytest.mark.parametrize("resource_type", ["讲义", "案例分析", "实操指南"])
def test_minimal_edit_policy_preserves_non_target_ranges_without_repeating_parent(resource_type):
    context, text, start = _preservation_context()
    before = context.claim_review_revision.model_dump(mode="json")
    payload = get_resource_agent(resource_type).common_prompt_payload(_spec(resource_type), context)
    policy = payload["revision_edit_policy"]
    assert policy["target_ranges"] == [{"start":start, "end":start+5}]
    assert policy["preserve_ranges"] == [
        {"start":0, "end":start, "sha256":sha256_hex(text[:start])},
        {"start":start+5, "end":len(text), "sha256":sha256_hex(text[start+5:])},
    ]
    assert payload["claim_review_revision"]["previous_text"] == text
    assert "尽量逐字复制" in payload["revision_guidance"]
    assert "已有的冻结evidence" in payload["revision_guidance"]
    assert "不代表整段均可改写" in payload["revision_guidance"]
    assert "_claim_revision_edit_policy" not in payload.get("constraints", {})
    assert context.claim_review_revision.model_dump(mode="json") == before


@pytest.mark.parametrize("resource_type", ["分阶测试题", "复习清单", "个性化纠错训练包"])
def test_custom_payload_types_receive_the_same_minimal_edit_instructions(resource_type):
    context, text, start = _preservation_context()
    agent, spec = get_resource_agent(resource_type), _spec(resource_type)
    if resource_type == "个性化纠错训练包":
        context.constraints["correction_focus_snapshot"] = {"ordered_target_nodes":[{"skill_node_id":"node-1"}]}
        payload = agent._prompt_payload(spec, context)
    else:
        payload = _human_payload(agent._messages(spec, context, "node-1"))
    assert payload["revision_edit_policy"]["target_ranges"] == [{"start":start,"end":start+5}]
    assert payload["claim_review_revision"]["previous_text"] == text
    assert "不代表整段均可改写" in payload["revision_guidance"]


def test_overlapping_target_spans_merge_but_do_not_expand_to_paragraph():
    context, text, start = _preservation_context()
    span = RevisionSourceSpanV1(span_id="sp_0001", source_start=start+2, source_end=start+6,
                               source_text=text[start+2:start+6], source_text_hash=sha256_hex(text[start+2:start+6]))
    problem = context.claim_review_revision.problems[0].model_copy(update={"claim_id":"clm_b", "source_span_id":"sp_0001"})
    claim = context.claim_review_revision.model_copy(update={
        "spans":[*context.claim_review_revision.spans, span],
        "problems":[*context.claim_review_revision.problems, problem],
    })
    context = context.model_copy(update={"claim_review_revision":claim})
    policy = attach_revision_fields({}, context)["revision_edit_policy"]
    assert policy["target_ranges"] == [{"start":start, "end":start+6}]


@pytest.mark.parametrize("damage", ["hash", "offset", "span_hash"])
def test_minimal_preservation_rejects_corrupt_parent_or_span(damage):
    context, text, start = _preservation_context()
    claim = context.claim_review_revision
    if damage == "hash":
        claim = claim.model_copy(update={"content_hash":"0"*64})
    else:
        span = claim.spans[0].model_copy(update={"source_start":0} if damage == "offset" else {"source_text_hash":"0"*64})
        claim = claim.model_copy(update={"spans":[span]})
    with pytest.raises(ValueError, match="preservation"):
        attach_revision_fields({}, context.model_copy(update={"claim_review_revision":claim}))


def test_no_target_preserves_whole_text_and_leaves_no_permission_to_rewrite():
    context, text, _ = _preservation_context()
    claim = context.claim_review_revision.model_copy(update={"problems":[], "spans":[], "groups":[]})
    policy = attach_revision_fields({}, context.model_copy(update={"claim_review_revision":claim}))["revision_edit_policy"]
    assert policy["target_ranges"] == []
    assert policy["preserve_ranges"] == [{"start":0,"end":len(text),"sha256":sha256_hex(text)}]
