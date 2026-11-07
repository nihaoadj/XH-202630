"""Deterministic construction of Claim/ordinary generation revision inputs (T46)."""

from __future__ import annotations

import pytest

from app.agents.resource_workflows.learning_documents.revision_inputs import (
    MAX_CONTEXT_CHARS,
    build_claim_review_revision_input,
    build_resource_review_revision_input,
)
from app.models.reviews.claims import ClaimVerdict
from app.models.reviews.revision_inputs import (
    ClaimReviewRevisionInput,
    ResourceReviewRevisionInput,
)
from tests.fixtures.claim_revision.targeted_v1.synthetic import (
    make_claim,
    make_judgement,
    make_resource,
)


def _build_claim_input(resource, claims, judgements, evidence=None):
    return build_claim_review_revision_input(
        resource_spec_id=resource.resource_spec_id,
        resource=resource,
        targets=["node"],
        claims=claims,
        judgements=judgements,
        evidence=evidence or [],
    )


def test_only_completed_bad_verdicts_for_bound_parent_are_included():
    resource = make_resource(resource_id="parent", version=2, content_text="正文A。")
    good = make_claim(seed="good", resource_id="parent", resource_version=2,
                      claim_text="好断言", source_text="正文A", source_start=0, source_end=3)
    contradicted = make_claim(seed="bad", resource_id="parent", resource_version=2, claim_index=1,
                              claim_text="错断言", source_text="正文A", source_start=0, source_end=3)
    sibling = make_claim(seed="sibling", resource_id="other", resource_version=2,
                         claim_text="别家", source_text="正文A", source_start=0, source_end=3)
    wrong_version = make_claim(seed="old", resource_id="parent", resource_version=1,
                               claim_text="旧版", source_text="正文A", source_start=0, source_end=3)
    judgements = [
        make_judgement(claim=good, verdict=ClaimVerdict.SUPPORTED, evidence_ids=["evidence"]),
        make_judgement(claim=contradicted, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"]),
        make_judgement(claim=sibling, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"]),
        make_judgement(claim=wrong_version, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"]),
    ]
    model = _build_claim_input(resource, [good, contradicted, sibling, wrong_version], judgements)
    assert [item.claim_id for item in model.problems] == [contradicted.claim_id]


def test_verdict_evidence_roles_are_distinct():
    resource = make_resource(resource_id="parent", content_text="正文A。")
    contradicted = make_claim(seed="c", resource_id="parent", claim_text="错", source_text="正文A", source_start=0, source_end=3)
    absent = make_claim(seed="n", resource_id="parent", claim_index=1, claim_text="无据", source_text="正文A", source_start=0, source_end=3)
    judgements = [
        make_judgement(claim=contradicted, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev-1"]),
        make_judgement(claim=absent, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[]),
    ]
    model = _build_claim_input(resource, [contradicted, absent], judgements)
    by_id = {item.claim_id: item for item in model.problems}
    assert by_id[contradicted.claim_id].evidence_ids == ["ev-1"]
    assert by_id[absent.claim_id].evidence_ids == []


def test_same_span_is_pooled_and_same_text_at_other_offset_keeps_its_own_span():
    content = "同一句里有两个断言。另起一处同一句里有两个断言。"
    resource = make_resource(resource_id="parent", content_text=content)
    first = make_claim(seed="a", resource_id="parent", claim_text="甲", source_text="同一句里有两个断言", source_start=0, source_end=9)
    second = make_claim(seed="b", resource_id="parent", claim_index=1, claim_text="乙", source_text="同一句里有两个断言", source_start=0, source_end=9)
    elsewhere = make_claim(seed="c", resource_id="parent", claim_index=2, claim_text="丙", source_text="同一句里有两个断言", source_start=14, source_end=23)
    judgements = [
        make_judgement(claim=first, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
        make_judgement(claim=second, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
        make_judgement(claim=elsewhere, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
    ]
    model = _build_claim_input(resource, [first, second, elsewhere], judgements)
    # Pooled: two problems reference one span; the other offset keeps its own.
    assert len(model.spans) == 2
    span_ids = {item.source_span_id for item in model.problems}
    assert len(span_ids) == 2
    first_span = next(s for s in model.spans if s.span_id == next(
        p.source_span_id for p in model.problems if p.claim_id == first.claim_id))
    assert first_span.source_start == 0 and first_span.source_end == 9
    elsewhere_span = next(s for s in model.spans if s.span_id == next(
        p.source_span_id for p in model.problems if p.claim_id == elsewhere.claim_id))
    assert elsewhere_span.source_start == 14 and elsewhere_span.source_end == 23


def test_same_unit_claims_share_group_and_cross_unit_claims_do_not():
    content = "第一句。第二句。\n\n第三句。\n"
    resource = make_resource(resource_id="parent", content_text=content)
    a = make_claim(seed="a", resource_id="parent", claim_text="甲", source_text="第一句。", source_start=0, source_end=4)
    b = make_claim(seed="b", resource_id="parent", claim_index=1, claim_text="乙", source_text="第二句。", source_start=4, source_end=8)
    c = make_claim(seed="c", resource_id="parent", claim_index=2, claim_text="丙", source_text="第三句。", source_start=10, source_end=14)
    judgements = [
        make_judgement(claim=a, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
        make_judgement(claim=b, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
        make_judgement(claim=c, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
    ]
    model = _build_claim_input(resource, [a, b, c], judgements)
    group_by_claim = {
        claim_id: next(g for g in model.groups if claim_id in g.problem_claim_ids)
        for claim_id in (a.claim_id, b.claim_id, c.claim_id)
    }
    assert group_by_claim[a.claim_id].group_id == group_by_claim[b.claim_id].group_id
    assert group_by_claim[a.claim_id].group_id != group_by_claim[c.claim_id].group_id


def test_optional_context_omitted_when_unit_exceeds_cap():
    long_para = "长" * (MAX_CONTEXT_CHARS + 10)
    content = f"{long_para}\n"
    resource = make_resource(resource_id="parent", content_text=content)
    claim = make_claim(seed="a", resource_id="parent", claim_text="甲",
                       source_text=long_para[:4], source_start=0, source_end=4)
    model = _build_claim_input(resource, [claim], [make_judgement(claim=claim, evidence_ids=["ev"])])
    group = next(g for g in model.groups if claim.claim_id in g.problem_claim_ids)
    assert group.context_text is None
    # The verbatim span still survives even when the optional context is omitted.
    assert model.spans[0].source_text == long_para[:4]


def test_deterministic_ordering_by_start_end_index_id():
    content = "A句。\n\nB句。\n"
    resource = make_resource(resource_id="parent", content_text=content)
    b = make_claim(seed="b", resource_id="parent", claim_index=2, claim_text="乙", source_text="B句。", source_start=5, source_end=8)
    a = make_claim(seed="a", resource_id="parent", claim_index=0, claim_text="甲", source_text="A句。", source_start=0, source_end=3)
    judgements = [
        make_judgement(claim=a, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
        make_judgement(claim=b, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"]),
    ]
    model = _build_claim_input(resource, [b, a], judgements)
    assert [item.claim_index for item in model.problems] == [0, 2]


def test_constructor_never_mutates_inputs():
    resource = make_resource(resource_id="parent", content_text="正文A。")
    claim = make_claim(seed="a", resource_id="parent", claim_text="甲", source_text="正文A", source_start=0, source_end=3)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["ev"])
    claim_before = claim.model_dump(mode="json")
    judgement_before = judgement.model_dump(mode="json")
    _build_claim_input(resource, [claim], [judgement])
    assert claim.model_dump(mode="json") == claim_before
    assert judgement.model_dump(mode="json") == judgement_before


def test_ordinary_input_prefers_work_order_then_lecture_then_compat():
    resource = make_resource(resource_id="parent", content_text="正文")
    work_order = {
        "previous_text": "work正文",
        "parent_resource_id": "parent",
        "parent_binding": {"version": 3},
        "open_issues": [{"issue_id": "i1"}],
        "closed_issues": [{"issue_id": "i2"}],
        "unchanged": True,
    }
    model = build_resource_review_revision_input(
        resource_spec_id="spec", resource=resource, targets=["node"], work_order=work_order,
    )
    assert model.revision_source == "ordinary"
    assert model.previous_text == "work正文" and model.parent_version == 3
    assert model.issues == [{"issue_id": "i1"}] and model.closed_issues == [{"issue_id": "i2"}]
    assert model.unchanged is True

    lecture = {"previous_content": "lec正文", "parent_resource_id": "parent", "open_issues": [{"issue_id": "l1"}], "unchanged": False}
    from_lecture = build_resource_review_revision_input(
        resource_spec_id="spec", resource=resource, targets=["node"], lecture_revision=lecture,
    )
    assert from_lecture.previous_text == "lec正文"
    assert from_lecture.issues == [{"issue_id": "l1"}]

    compat = build_resource_review_revision_input(
        resource_spec_id="spec", resource=resource, targets=["node"], feedback={"issues": [{"message": "m"}]},
    )
    assert isinstance(compat, ResourceReviewRevisionInput)
    assert compat.revision_source == "compat"
    assert compat.feedback["issues"] == [{"message": "m"}]


def test_assessment_compat_feedback_is_scoped_to_parent():
    resource = make_resource(resource_id="parent", resource_type="分阶测试题")
    feedback = {
        "assessment_findings": [
            {"resource_spec_id": "spec", "resource_id": "parent", "code": "keep"},
            {"resource_spec_id": "other-spec", "resource_id": "parent", "code": "drop-spec"},
            {"resource_spec_id": "spec", "resource_id": "other", "code": "drop-resource"},
        ],
    }
    model = build_resource_review_revision_input(
        resource_spec_id="spec", resource=resource, targets=["node"], feedback=feedback,
    )
    assert model.feedback["assessment_findings"] == [
        {"resource_spec_id": "spec", "resource_id": "parent", "code": "keep"},
    ]


def test_claim_input_is_a_targeted_projection():
    resource = make_resource(resource_id="parent", content_text="正文A。")
    claim = make_claim(seed="a", resource_id="parent", claim_text="甲", source_text="正文A", source_start=0, source_end=3)
    model = _build_claim_input(resource, [claim], [make_judgement(claim=claim, evidence_ids=["ev"])])
    assert isinstance(model, ClaimReviewRevisionInput)
    assert model.parent_resource_id == "parent"
    assert model.previous_text == "正文A。"
    assert model.problems[0].claim_text == "甲"
    assert model.problems[0].reason == "合成判定理由"


def test_verbatim_input_roundtrip_preserves_whitespace_and_hash():
    import hashlib
    text = "  原句\n"
    resource = make_resource(content_text=text)
    claim = make_claim(seed="space", resource_id="parent", source_text="原句", source_start=2, source_end=4)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[])
    model = _build_claim_input(resource, [claim], [judgement])
    restored = ClaimReviewRevisionInput.model_validate_json(model.model_dump_json())
    assert restored.previous_text == text
    assert hashlib.sha256(restored.previous_text.encode()).hexdigest() == restored.content_hash


def test_invalid_parent_slice_is_rejected():
    resource = make_resource(content_text="实际原句")
    claim = make_claim(seed="wrong", resource_id="parent", source_text="别的句", source_start=0, source_end=3)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[])
    with pytest.raises(ValueError):
        _build_claim_input(resource, [claim], [judgement])


def test_compat_feedback_filters_other_resource_and_claim_issues():
    resource = make_resource(resource_id="parent", resource_spec_id="mine", content_text="正文")
    feedback = {"issues": [
        {"resource_id": "parent", "description": "own"},
        {"resource_id": "sibling", "description": "foreign"},
        {"resource_id": "parent", "claim_ids": ["c"], "description": "claim"},
    ], "revision_instructions": [{"target_resource_id": "sibling", "action": "foreign"}]}
    model = build_resource_review_revision_input(resource_spec_id="mine", resource=resource,
        targets=["node"], feedback=feedback)
    assert [i["description"] for i in model.feedback["issues"]] == ["own"]
    assert model.feedback["revision_instructions"] == []
