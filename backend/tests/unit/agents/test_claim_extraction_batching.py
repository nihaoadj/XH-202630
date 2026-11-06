from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import scan_units, split_unit
from app.agents.resource_workflows.learning_documents.claim_extraction.batching import plan_batches, subdivide
from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output, conservative_merge, materialize_result
from app.models.reviews.claim_extraction import BatchOutput, UnitOutput, NeutralCandidate, content_digest
from app.models.reviews.claims import ClaimCandidate
from tests.fakes.claim_extraction import policy, FixtureCounter


@pytest.mark.parametrize("text", [
    "# 主题\r\n\r\n第一段事实。\r\n第二个事实。\r\n\r\n",
    "前文[^1]。\n\n- 步骤一，解释一个事实。\n  - 子步骤\n\n```python\nx = 'a  b'\n```\n末尾事实。",
    "## 表格\n| 名称 | 值 |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n",
    "🙂e\u0301中文\t数据\n\n~~~ odd\nunknown syntax :::\n", " \r\n\t\n",
    "非标准 <tag>\n::::\n(a) 原始语法\n末尾无换行",
])
def test_source_partition_independent_character_oracle(text):
    counter = FixtureCounter()
    units = scan_units(text)
    covered = [0] * len(text)
    for u in units:
        for i in range(u.start, u.end):
            covered[i] += 1
    assert covered == [1] * len(text)
    assert "".join(text[u.start:u.end] for u in units) == text
    batches = plan_batches(text, policy(target_tokens=80), counter)
    assert "".join(text[u.start:u.end] for b in batches for u in b.units) == text


def test_short_resource_one_batch_many_paragraphs_long_resource_adjacent_and_context():
    counter = FixtureCounter()
    text = "# 章节\n\n第一条。\n\n第二条。\n"
    assert len(plan_batches(text, policy(), counter)) == 1
    long = text * 60
    p = policy(target_tokens=160)
    batches = plan_batches(long, p, counter)
    assert len(batches) > 1
    assert all(sum(counter.count_text(long[u.start:u.end]) for u in b.units) <= 160 for b in batches)
    assert all(sum(counter.count_text(long[s.start:s.end]) for s in b.context) <= 512 for b in batches)
    assert plan_batches(long, p, counter) == batches


def test_long_table_code_and_unsplittable_line():
    counter = FixtureCounter()
    text = "| Key | Value |\n| --- | --- |\n" + "| a | 1 |\n" * 40 + "\n```py\n" + "x = 1\n" * 30 + "```\n"
    batches = plan_batches(text, policy(target_tokens=80), counter)
    assert len(batches) > 2
    assert any("| --- |" in text[s.start:s.end] for b in batches for s in b.context)
    assert any("```py" in text[s.start:s.end] for b in batches for s in b.context)
    with pytest.raises(ValueError, match="safe unit"):
        plan_batches("```py\n" + "x"*100 + "\n```", policy(target_tokens=80), counter)
    with pytest.raises(ValueError, match="safe unit"):
        plan_batches("x" * 100, policy(target_tokens=80), counter)


def _validated(text, raw, *, start=0, end=None):
    from app.agents.resource_workflows.learning_documents.claim_extraction.batching import make_batch
    from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import unit_for
    unit = unit_for(text, start, len(text) if end is None else end, "paragraph")
    batch = make_batch(text, [unit], policy(), FixtureCounter())
    output = BatchOutput(resource_id="r", resource_version=1, content_hash=content_digest(text), batch_id=batch.batch_id,
        units=[UnitOutput(unit_id=unit.unit_id, status="claims", reason="synthetic", claims=raw)])
    return validate_output(text, batch, output, resource=SimpleNamespace(resource_id="r", version=1), policy=policy(), allowed_nodes={"k"})


def test_whitespace_adjusted_before_old_dto_and_hash_exact_source():
    text = "\r\n\t 事实🙂\r\n内部  空白 \t\r\n"
    result = _validated(text, [NeutralCandidate(claim_text="事实", claim_type="factual", source_text=text,
                                               source_start=0, source_end=len(text))])
    candidate = result[0]
    assert candidate.source_text == text.strip()
    assert text[candidate.source_start:candidate.source_end] == candidate.source_text
    assert "\r\n内部  空白" in candidate.source_text
    records = materialize_result(result, text=text, resource=SimpleNamespace(resource_id="r", version=1),
        review_id="review", run_id="run", policy=policy(), created_at=datetime.now(timezone.utc))
    assert records[0].source_text_hash == content_digest(text.strip())
    assert records[0].source_evidence_ids == []


def test_relocation_is_target_local_and_ambiguous_occurrence_fails():
    with pytest.raises(ValueError, match="ambiguous"):
        _validated("same    same", [NeutralCandidate(claim_text="same", claim_type="factual", source_text="same", source_start=4, source_end=8)])
    with pytest.raises(ValueError, match="absent"):
        _validated("first fact\nsecond body", [NeutralCandidate(claim_text="first", claim_type="factual", source_text="first", source_start=0, source_end=5)], start=11)


def test_absolute_unit_offsets_relocate_instead_of_rejecting():
    # T36 live run 10d9243a: the model copied the unit's absolute payload offsets
    # (unit_start/unit_end) into a claim whose contract wants unit-local indexes.
    # source_text stays authoritative and relocates inside the target unit.
    result = _validated("alpha beta gamma", [NeutralCandidate(claim_text="beta", claim_type="factual",
        source_text="beta", source_start=6, source_end=10)], start=6, end=17)
    assert [(c.source_start, c.source_end) for c in result] == [(6, 10)]
    assert result[0].source_text == "beta"


def test_conservative_dedup_preserves_internal_whitespace_case_positions_and_ids():
    text = "a  b a  b"
    def c(value, start=0, kind="factual", label=None):
        return ClaimCandidate(claim_text=value, claim_type=kind, source_text="a  b", source_start=start, source_end=start+4,
                              knowledge_point_id=label)
    candidates = [c("Token"), c("token"), c("a  b"), c("a b"), c("Token"), c("Token", 5)]
    merged = conservative_merge(candidates)
    assert len(merged) == 5
    assert {c.claim_text for c in merged} == {"Token", "token", "a  b", "a b"}
    kw = dict(text=text, resource=SimpleNamespace(resource_id="r", version=1), review_id="review", run_id="run",
              policy=policy(), created_at=datetime(2026,10,30,tzinfo=timezone.utc))
    a = materialize_result(candidates, **kw)
    b = materialize_result(list(reversed(candidates)), **kw)
    assert a == b and len({c.claim_id for c in a}) == 5
    with pytest.raises(ValueError, match="conflict"):
        conservative_merge([c("same"), c("same", kind="non_factual")])
    with pytest.raises(ValueError, match="conflict"):
        conservative_merge([c("same"), c("same", label="k")])


def test_parent_subdivision_replaces_exact_range_and_minimum_failure():
    counter, p = FixtureCounter(), policy()
    text = "First fact. Second fact. Third fact."
    batch = plan_batches(text, p, counter)[0]
    children = subdivide(text, batch, p, counter)
    assert all(c.parent_id == batch.batch_id for c in children)
    assert "".join(text[u.start:u.end] for child in children for u in child.units) == text
    with pytest.raises(ValueError, match="minimum"):
        subdivide("fact", plan_batches("fact", p, counter)[0], p, counter)


def test_unit_count_128_is_limit_not_a_claim_denominator():
    text = "x\n\n" * 130
    batches = plan_batches(text, policy(target_tokens=8192), FixtureCounter())
    assert len(batches) > 1
    assert all(len(b.units) <= 128 for b in batches)


def test_combined_required_context_overflow_is_a_batch_boundary():
    from app.agents.resource_workflows.learning_documents.claim_extraction.batching import make_batch
    from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import unit_for
    from app.models.reviews.claim_extraction import Span
    # Independent required contexts each fit; the combined context cannot fit.
    text = "A"*300 + "B"*300 + "row1\nrow2\n"
    a = unit_for(text, 600, 605, "table", required_context=[Span(start=0, end=300)])
    b = unit_for(text, 605, 610, "table", required_context=[Span(start=300, end=600)])
    assert make_batch(text, [a], policy(), FixtureCounter())
    assert make_batch(text, [b], policy(), FixtureCounter())
    with pytest.raises(ValueError, match="required"):
        make_batch(text, [a,b], policy(), FixtureCounter())
    # Exercise the real scanner/packing with two long table headers.
    header1 = "|" + "A"*260 + "| X |\n| --- | --- |\n"
    header2 = "|" + "B"*260 + "| Y |\n| --- | --- |\n"
    source = header1 + "| a | 1 |\n"*45 + "\n" + header2 + "| b | 2 |\n"*45
    batches = plan_batches(source, policy(target_tokens=300), FixtureCounter())
    assert len(batches) > 2
    assert "".join(source[u.start:u.end] for batch in batches for u in batch.units) == source


def test_fixture_wire_bound_covers_multibyte_raw_schema_repairs():
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.core.llm.gateway import LLMGateway
    from app.models.shared.llm import LLMCallOptions
    from app.core.security.errors import ErrorCode
    messages = [SystemMessage(content="抽取"), HumanMessage(content="原文🙂")]
    options = LLMCallOptions(max_attempts=3, max_output_tokens=8192)
    failure = SimpleNamespace(code=ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, safe_detail="错误"*256)
    repair = LLMGateway._repair_messages(messages, BatchOutput, "🙂"*12000, failure)
    actual = LLMGateway._text_messages(repair, BatchOutput)
    from app.core.llm.counting import CharacterEstimator
    counter = CharacterEstimator()
    from app.models.shared.llm import StructuredOutputMode
    first = counter.request_bound(messages, BatchOutput, options)
    # Repair text is reserved when that request actually exists, not on attempt 1.
    repaired = counter.estimate_prepared(actual, BatchOutput, StructuredOutputMode.TEXT)
    assert repaired > first
    assert repaired < 96000
