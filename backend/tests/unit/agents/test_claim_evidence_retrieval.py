"""Pure planning tests for Claim query construction, quota and excerpt windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.budget import (
    compute_deadline,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.queries import (
    assign_query_quota,
    build_query_batches,
    collect_claim_queries,
    deterministic_queries,
    query_claim_map,
    validate_query_output,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.rejudge import (
    HARD_BLOCK_CONTRADICTED,
    HARD_BLOCK_EVIDENCE_CONFLICT,
    build_rejudge_batches,
    target_claims,
    validate_rejudge_output,
)
from app.core.retrieval.excerpt import build_excerpt_windows
from app.models.knowledge.knowledge import (
    EvidenceItem,
    ScoreKind,
    SourceLocator,
    SourceType,
)
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    ClaimQueryBatchOutputV1,
    ClaimSupplementJudgementLLMOutput,
)
from app.models.reviews.claims import ClaimRecord, ClaimType, ClaimVerdict

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)


def policy(**overrides) -> ClaimEvidenceRetrievalPolicyV1:
    payload = {
        "query_prompt_hash": "a" * 64,
        "query_schema_hash": "b" * 64,
        "rejudge_prompt_hash": "c" * 64,
        "rejudge_schema_hash": "d" * 64,
    }
    payload.update(overrides)
    return ClaimEvidenceRetrievalPolicyV1(**payload)


def claim(index: int, text: str | None = None, *, version: int = 1) -> ClaimRecord:
    return ClaimRecord(
        claim_id="clm_" + f"{index:032x}",
        run_id="run-1",
        resource_id="res-1",
        resource_version=version,
        review_id="rev-1",
        claim_index=index,
        claim_text=text or f"claim {index}",
        claim_type=ClaimType.FACTUAL,
        source_text="source",
        source_start=0,
        source_end=6,
        source_text_hash="a" * 64,
        extractor_prompt_version="p",
        claim_hash="b" * 64,
        created_at=NOW,
    )


def evidence(evidence_id: str, excerpt: str, *, query: str = "q") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        knowledge_base_id="kb-1",
        document_id="doc-1",
        document_version="v1",
        chunk_id="chunk-1",
        query=query,
        query_hash="a" * 64,
        query_rank=1,
        rank=1,
        raw_score=0.9,
        score_kind=ScoreKind.SIMILARITY,
        normalized_score=0.8,
        excerpt=excerpt,
        excerpt_hash="b" * 64,
        locator=SourceLocator(
            knowledge_base_id="kb-1", source_type=SourceType.MARKDOWN,
            source_path="docs/a.md", document_id="doc-1", document_version="v1",
            chunk_id="chunk-1", title="a.md", section="1",
        ),
        config_hash="c" * 64,
        retrieved_at=NOW,
    )


def test_query_batches_split_by_the_frozen_batch_size_and_have_stable_ids():
    claims = [claim(index) for index in range(1, 19)]
    plan = build_query_batches(
        claims, session_id="cers_" + "1" * 32, policy=policy(), knowledge_base_id="kb-1",
    )

    assert [len(item.claim_ids) for item in plan.batches] == [16, 2]
    repeated = build_query_batches(
        claims, session_id="cers_" + "1" * 32, policy=policy(), knowledge_base_id="kb-1",
    )
    assert [item.batch_id for item in plan.batches] == [item.batch_id for item in repeated.batches]
    assert plan.batches[0].payload["batch_id"] == plan.batches[0].batch_id
    assert plan.batches[0].payload["input_hash"] == plan.batches[0].input_hash


def test_query_output_rejects_missing_extra_duplicate_and_overlong_queries():
    claims = [claim(1), claim(2)]
    plan = build_query_batches(
        claims, session_id="cers_" + "1" * 32, policy=policy(), knowledge_base_id="kb-1",
    )
    batch = plan.batches[0]
    valid = {
        "batch_id": batch.batch_id,
        "input_hash": batch.input_hash,
        "items": [
            {"claim_id": claims[0].claim_id, "queries": [{"text": "RAG 召回"}]},
            {"claim_id": claims[1].claim_id, "queries": [{"text": "RAG 精排"}]},
        ],
    }
    output = ClaimQueryBatchOutputV1.model_validate(valid)
    selected = validate_query_output(output, batch=batch, policy=policy())
    assert selected[claims[0].claim_id] == ("RAG 召回",)

    missing = ClaimQueryBatchOutputV1.model_validate({
        **valid, "items": valid["items"][:1],
    })
    with pytest.raises(ValueError):
        validate_query_output(missing, batch=batch, policy=policy())

    extra = ClaimQueryBatchOutputV1.model_validate({
        **valid,
        "items": [*valid["items"], {
            "claim_id": "clm_" + "9" * 32, "queries": [{"text": "extra"}],
        }],
    })
    with pytest.raises(ValueError):
        validate_query_output(extra, batch=batch, policy=policy())

    duplicate = ClaimQueryBatchOutputV1.model_validate({
        **valid,
        "items": [
            {"claim_id": claims[0].claim_id, "queries": [{"text": "same"}, {"text": "same"}]},
            valid["items"][1],
        ],
    })
    with pytest.raises(ValueError):
        validate_query_output(duplicate, batch=batch, policy=policy())


def test_deterministic_fallback_keeps_the_claim_subject_and_conditions():
    original = claim(1, "在 2026 版本中，RAG 的召回率必须达到 95% 才能进入精排阶段。")
    queries = deterministic_queries(original, max_queries=2)

    assert queries
    assert all(len(item) <= 512 for item in queries)
    assert "2026" in queries[0]


def test_query_quota_is_round_robin_and_never_drops_a_claim_from_the_denominator():
    claims = [claim(index, f"claim {index}") for index in range(1, 129)]
    queries = {item.claim_id: (f"q{index}-a", f"q{index}-b", f"q{index}-c") for index, item in enumerate(claims, 1)}

    selected, exhausted, counts = assign_query_quota(
        queries, [item.claim_id for item in claims], max_queries=96,
    )

    assert counts["selected"] == 96
    # The budget is exhausted on the first round: 96 claims were searched and
    # the remaining 32 are reported explicitly instead of disappearing.
    assert len(exhausted) == 32
    assert max(len(value) for value in selected.values()) == 1
    # 128 claims × 3 candidate queries were requested; only 96 were executed.
    assert counts["dropped_budget"] == 384 - 96


def test_duplicate_query_text_is_dropped_and_mapped_once():
    claims = [claim(1), claim(2)]
    selected, exhausted, counts = assign_query_quota(
        {claims[0].claim_id: ("same",), claims[1].claim_id: ("same",)},
        [item.claim_id for item in claims],
        max_queries=96,
    )

    assert counts["dropped_duplicate"] == 1
    assert exhausted == (claims[1].claim_id,)
    mapping = query_claim_map(selected)
    assert mapping == {"same": (claims[0].claim_id,)}


def test_collect_claim_queries_merges_fallback_for_failed_batches():
    claims = [claim(1), claim(2)]
    plan = build_query_batches(
        claims, session_id="cers_" + "1" * 32, policy=policy(), knowledge_base_id="kb-1",
    )
    selected, exhausted, counts = collect_claim_queries(
        batches=plan.batches,
        outputs={plan.batches[0].batch_id: {claims[0].claim_id: ("model query",)}},
        fallback_claim_ids=[claims[1].claim_id],
        claims=claims,
        policy=policy(),
    )

    assert selected[claims[0].claim_id] == ("model query",)
    assert selected[claims[1].claim_id] == (claims[1].claim_text,)
    assert exhausted == ()
    assert counts["selected"] == 2


def test_rejudge_batches_report_oversize_instead_of_cutting_evidence():
    claims = [claim(1)]
    long_excerpt = "x" * 9000
    items = [evidence(f"ev-{index}", long_excerpt) for index in range(4)]

    batches, oversize = build_rejudge_batches(
        claims, evidence=items, session_id="cers_" + "1" * 32,
        policy=policy(rejudge_input_cap=4096),
    )

    assert batches == ()
    assert oversize == (claims[0].claim_id,)


def test_rejudge_validation_marks_contradiction_and_conflict_as_hard_blocks():
    claims = [claim(1)]
    items = [evidence("ev-1", "positive"), evidence("ev-2", "negative")]
    batches, _ = build_rejudge_batches(
        claims, evidence=items, session_id="cers_" + "1" * 32, policy=policy(),
    )
    batch = batches[0]
    index = {claims[0].claim_id: claims[0]}

    contradicted = ClaimSupplementJudgementLLMOutput.model_validate({
        "judgements": [{
            "claim_id": claims[0].claim_id, "verdict": "contradicted",
            "evidence_ids": ["ev-2"], "reason": "反证", "confidence": 0.8,
        }],
    })
    candidates, block = validate_rejudge_output(
        contradicted, batch=batch, claims=index,
        allowed_evidence_ids={"ev-1", "ev-2"},
    )
    assert len(candidates) == 1
    assert block == HARD_BLOCK_CONTRADICTED

    conflict = ClaimSupplementJudgementLLMOutput.model_validate({
        "judgements": [{
            "claim_id": claims[0].claim_id, "verdict": "supported",
            "evidence_ids": ["ev-1"], "reason": "冲突", "confidence": 0.6,
            "evidence_conflict": True, "conflicting_evidence_ids": ["ev-2"],
        }],
    })
    _, block = validate_rejudge_output(
        conflict, batch=batch, claims=index,
        allowed_evidence_ids={"ev-1", "ev-2"},
    )
    assert block == HARD_BLOCK_EVIDENCE_CONFLICT


def test_rejudge_rejects_a_non_target_claim_and_unknown_evidence():
    claims = [claim(1), claim(2)]
    items = [evidence("ev-1", "positive")]
    batches, _ = build_rejudge_batches(
        claims[:1], evidence=items, session_id="cers_" + "1" * 32, policy=policy(),
    )
    batch = batches[0]
    index = {item.claim_id: item for item in claims}

    with pytest.raises(ValueError):
        validate_rejudge_output(
            ClaimSupplementJudgementLLMOutput.model_validate({
                "judgements": [{
                    "claim_id": claims[1].claim_id, "verdict": "supported",
                    "evidence_ids": ["ev-1"], "reason": "x", "confidence": 0.5,
                }],
            }),
            batch=batch, claims=index, allowed_evidence_ids={"ev-1"},
        )
    with pytest.raises(ValueError):
        validate_rejudge_output(
            ClaimSupplementJudgementLLMOutput.model_validate({
                "judgements": [{
                    "claim_id": claims[0].claim_id, "verdict": "supported",
                    "evidence_ids": ["ev-unknown"], "reason": "x", "confidence": 0.5,
                }],
            }),
            batch=batch, claims=index, allowed_evidence_ids={"ev-1"},
        )


def test_target_claims_only_selects_first_round_absence():
    claims = [claim(1), claim(2), claim(3)]
    targets = target_claims(claims, effective_verdicts={
        claims[0].claim_id: ClaimVerdict.SUPPORTED,
        claims[1].claim_id: ClaimVerdict.NOT_IN_EVIDENCE,
        claims[2].claim_id: ClaimVerdict.CONTRADICTED,
    })

    assert [item.claim_id for item in targets] == [claims[1].claim_id]


def test_claim_window_keeps_a_late_decisive_condition():
    text = (
        "第一段介绍检索的基本流程与常见术语。"
        "第二段说明向量索引的构建方法。"
        "第三段强调：只有召回率不低于 95% 且经过来源校验的片段，才允许进入精排阶段。"
    )
    windows = build_excerpt_windows(text, ["召回率 95% 来源校验"], excerpt_chars=2000)

    assert windows
    assert "召回率不低于 95%" in windows[0].text
    assert text[windows[0].start:windows[0].end] == windows[0].text
    assert windows[0].excerpt_hash


def test_claim_window_keeps_negation_and_distinguishes_windows_of_one_chunk():
    filler = "背景说明段落。" * 40
    text = f"甲句说明可以扩写。{filler}乙句明确禁止扩写为事实为假，并保留否定条件。"
    first = build_excerpt_windows(
        text, ["禁止扩写"], excerpt_chars=200, structural_cap=260,
    )
    second = build_excerpt_windows(
        text, ["甲句"], excerpt_chars=200, structural_cap=260,
    )

    assert first and "禁止扩写" in first[0].text
    assert second and "甲句" in second[0].text
    assert first[0].excerpt_identity != second[0].excerpt_identity
    repeated = build_excerpt_windows(
        text, ["禁止扩写"], excerpt_chars=200, structural_cap=260,
    )
    assert repeated[0].excerpt_identity == first[0].excerpt_identity


def test_claim_window_reports_context_gap_for_an_oversize_chunk_without_terms():
    text = "甲" * 5000
    windows = build_excerpt_windows(text, ["完全不存在"], excerpt_chars=1000, structural_cap=2000)

    assert windows == []


def test_supplement_deadline_is_the_tighter_of_wall_and_workflow_reserve():
    policy_value = policy()
    workflow = NOW + timedelta(seconds=400)
    deadline = compute_deadline(
        first_started_at=NOW, workflow_deadline_at=workflow, policy=policy_value,
    )
    assert deadline == workflow - timedelta(seconds=300)

    far_workflow = NOW + timedelta(seconds=1800)
    assert compute_deadline(
        first_started_at=NOW, workflow_deadline_at=far_workflow, policy=policy_value,
    ) == NOW + timedelta(seconds=600)
