"""T37: density-aware packing on the single production planner.

Every case asserts on spans/partitions independently of ``assert_partition`` so a
bug in the partition helper cannot validate itself.
"""
import json

import pytest
from pathlib import Path

from app.agents.resource_workflows.learning_documents.claim_extraction.batching import (
    RISK_KINDS,
    density_allows,
    plan_batches,
    risk_chars,
)
from app.core.llm.counting import CharacterEstimator
from app.models.reviews.claim_extraction import EstimatePolicy

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "density_v1"
TEXTS = FIXTURES / "texts"
POLICIES = FIXTURES / "policies"
LEGACY = EstimatePolicy.model_validate(json.loads((POLICIES / "estimate_2_0_baseline.json").read_text(encoding="utf-8")))


def text_of(name):
    # newline="" keeps CRLF fixtures byte-faithful; pathlib.read_text has no
    # newline parameter on Python 3.11.
    with open(TEXTS / f"{name}.md", encoding="utf-8", newline="") as handle:
        return handle.read()


def with_policy(*, density=None, batch_claims=None):
    raw = LEGACY.model_dump(mode="json")
    if density is not None:
        raw["density_batching"] = {"version": "claim-density-v1", "enabled": True,
                                   "chars_per_claim": 35.0, "capacity_share": 0.9, **density}
    if batch_claims is not None:
        raw["batch_claims"] = batch_claims
    return EstimatePolicy.model_validate(raw)


def plan(text, policy, fits=None):
    return plan_batches(text, policy, CharacterEstimator(policy.estimator_parameters),
                        fits=fits or (lambda batch: True))


def assert_exact_partition(text, batches):
    """Each character covered exactly once, in ascending non-overlapping order."""
    covered = [0] * len(text)
    for batch in batches:
        for unit in batch.units:
            assert 0 <= unit.start < unit.end <= len(text)
            for index in range(unit.start, unit.end):
                covered[index] += 1
    assert all(count == 1 for count in covered), "every source character must be covered exactly once"
    spans = [unit for batch in batches for unit in batch.units]
    for previous, current in zip(spans, spans[1:]):
        assert previous.end == current.start
    assert spans[0].start == 0 and spans[-1].end == len(text)


def batch_details(batches):
    return [(b.batch_id, [(u.kind, u.start, u.end) for u in b.units], [ (s.start, s.end) for s in b.context]) for b in batches]


# --- density fires before token/token-only would allow a single batch ---------

def test_density_splits_paragraphs_that_token_budget_would_merge():
    text = text_of("t01_paragraphs")
    enabled = plan(text, with_policy(density={}, batch_claims=20))
    disabled = plan(text, with_policy(batch_claims=20))
    assert len(enabled) == 4  # 361+361=722 > 630 risk chars, so one paragraph each
    assert len(disabled) == 1
    assert all(risk_chars(batch.units) <= 630 for batch in enabled)
    assert_exact_partition(text, enabled)
    assert_exact_partition(text, disabled)


def test_density_boundary_is_inclusive_at_630_and_splits_at_631():
    # segmentation absorbs the first newline into the preceding paragraph, so
    # 314 "甲" becomes a 315-char span; 315+315 == 630 exactly.
    exact = "甲" * 314 + "\n\n" + "乙" * 315
    over = "甲" * 315 + "\n\n" + "乙" * 315
    policy = with_policy(density={}, batch_claims=20)
    assert len(plan(exact, policy)) == 1
    assert len(plan(over, policy)) == 2
    assert risk_chars(plan(exact, policy)[0].units) == 630


def test_density_boundary_respects_default_batch_claims_16():
    exact = "甲" * 251 + "\n\n" + "乙" * 252
    over = "甲" * 252 + "\n\n" + "乙" * 252
    policy = with_policy(density={})
    assert policy.batch_claims == 16
    assert len(plan(exact, policy)) == 1
    assert len(plan(over, policy)) == 2


def test_one_unit_is_exempt_from_density_but_not_from_other_bounds():
    text = text_of("t04_code")  # single 768-char code unit, above the 630 risk budget
    policy = with_policy(density={}, batch_claims=20)
    batches = plan(text, policy)
    assert len(batches) == 1
    assert risk_chars(batches[0].units) > 630
    assert_exact_partition(text, batches)


def test_single_unit_exemption_does_not_leak_to_two_unit_candidates():
    text = "甲" * 320 + "\n\n" + "乙" * 320
    policy = with_policy(density={}, batch_claims=20)
    assert len(plan(text, policy)) == 2


# --- structure kinds ---------------------------------------------------------

def test_headings_and_whitespace_carry_zero_risk_yet_stay_in_the_payload():
    text = text_of("t05_headings")
    batches = plan(text, with_policy(density={}))
    assert len(batches) == 1
    kinds = [unit.kind for batch in batches for unit in batch.units]
    assert kinds.count("heading") == 6
    assert kinds.count("whitespace") == 6
    assert risk_chars(batches[0].units) == 28  # only the final paragraph counts
    assert_exact_partition(text, batches)


def test_structural_only_text_plans_without_empty_batches():
    text = text_of("t07_structural")
    batches = plan(text, with_policy(density={}))
    assert batches and all(batch.units for batch in batches)
    assert risk_chars([u for b in batches for u in b.units]) == 0
    assert_exact_partition(text, batches)


def test_heading_text_still_reaches_the_model_and_can_still_hit_the_cap():
    """Zero risk weight is a heuristic, not a semantic guarantee."""
    text = "# 标题也包含事实陈述\n\n正文段落。\n"
    batches = plan(text, with_policy(density={}))
    heading = [u for b in batches for u in b.units if u.kind == "heading"][0]
    assert "# 标题也包含事实陈述" in text[heading.start:heading.end]
    assert risk_chars([heading]) == 0


def test_table_and_code_risk_uses_source_spans_and_keeps_required_context():
    for name in ("t03_table", "t04_code"):
        text = text_of(name)
        batches = plan(text, with_policy(density={}, batch_claims=20))
        units = [u for b in batches for u in b.units]
        assert risk_chars(units) == sum(u.end - u.start for u in units) > 0
        assert_exact_partition(text, batches)
    table = plan(text_of("t03_table"), with_policy(density={}))[0]
    assert any(unit.kind == "table" for unit in table.units)


def test_unicode_crlf_and_missing_trailing_newline_roundtrip_exactly():
    text = text_of("t06_unicode_crlf")
    assert "\r\n" in text and not text.endswith("\n")
    batches = plan(text, with_policy(density={}))
    assert_exact_partition(text, batches)
    rebuilt = "".join(text[u.start:u.end] for b in batches for u in b.units)
    assert rebuilt == text


# --- low density and mixed documents ----------------------------------------

def test_low_density_long_document_groups_by_risk_not_by_paragraph_count():
    text = text_of("t08_mixed")
    policy = with_policy(density={}, batch_claims=20)
    batches = plan(text, policy)
    # 245+249 = 494 <= 630, adding the third paragraph reaches 738 > 630.
    assert len(batches) == 2
    assert [risk_chars(b.units) for b in batches] == [494, 244]
    assert_exact_partition(text, batches)


def test_batch_claims_16_and_20_differ_on_mid_density_text():
    text = "甲" * 300 + "\n\n" + "乙" * 300  # 600 risk chars
    assert len(plan(text, with_policy(density={}, batch_claims=20))) == 1
    assert len(plan(text, with_policy(density={}, batch_claims=16))) == 2


# --- each bound must fail independently -------------------------------------

def test_max_units_still_bounds_packing_when_density_allows():
    text = text_of("t08_mixed")
    policy = with_policy(density={}, batch_claims=20).model_copy(update={"max_units": 3})
    batches = plan(text, policy)
    assert all(len(batch.units) <= 3 for batch in batches)
    assert len(batches) > 2
    assert_exact_partition(text, batches)


def test_real_fits_rejects_a_merged_batch_that_density_would_allow():
    text = "短段落一。\n\n短段落二。\n"
    policy = with_policy(density={}, batch_claims=20)
    calls = []

    def fits(batch):
        calls.append(batch.batch_id)
        return len(batch.units) == 1

    batches = plan(text, policy, fits=fits)
    # paragraph, whitespace, paragraph: fits forbids any merge, so all three
    # units become their own batch and the merged candidate is consulted.
    assert len(batches) == 3
    assert calls  # fits is consulted for the merged candidate


def test_density_disabled_restores_token_only_packing_and_ids():
    text = text_of("t01_paragraphs")
    legacy = plan(text, with_policy(batch_claims=20))
    disabled = plan(text, with_policy(density={"enabled": False}, batch_claims=20))
    assert batch_details(legacy) == batch_details(disabled)
    assert len(disabled) == 1


def test_historical_policy_without_density_keeps_ids_and_spans():
    text = text_of("t08_mixed")
    batches = plan(text, LEGACY)
    assert all(batch.parent_id is None for batch in batches)
    assert len(batches) == 1
    assert_exact_partition(text, batches)


# --- helper contract --------------------------------------------------------

def test_density_helper_matches_the_frozen_formula():
    policy = with_policy(density={}, batch_claims=20)
    limit = 35.0 * 20 * 0.9
    assert density_allows(policy, []) is True
    two = [type("U", (), {"kind": "paragraph", "start": 0, "end": 315})(),
           type("U", (), {"kind": "list", "start": 315, "end": 630})()]
    assert density_allows(policy, two) is True
    two[1].end = 631
    assert density_allows(policy, two) is False
    single = [type("U", (), {"kind": "paragraph", "start": 0, "end": 5000})()]
    assert density_allows(policy, single) is True
    assert limit == 630.0


def test_risk_kinds_are_the_frozen_four():
    assert RISK_KINDS == frozenset({"paragraph", "list", "table", "code"})


def test_density_policy_does_not_bypass_the_candidate_cap_gate():
    """Density is a packing heuristic; the cap hard door must stay untouched."""
    from types import SimpleNamespace

    from app.agents.resource_workflows.learning_documents.claim_extraction.batching import make_batch
    from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output
    from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import scan_units
    from app.models.reviews.claim_extraction import BatchOutput, NeutralCandidate, UnitOutput

    text = "一条事实陈述。" * 60
    policy = with_policy(density={})  # batch_claims == 16
    counter = CharacterEstimator(policy.estimator_parameters)
    units = scan_units(text)
    batch = make_batch(text, units, policy, counter)
    unit = batch.units[0]
    claim = NeutralCandidate(claim_text="一条事实陈述。", claim_type="factual",
                             source_text="一条事实陈述。", source_start=0, source_end=7)
    reached = [claim for _ in range(policy.batch_claims)]
    output = BatchOutput(resource_id="r", resource_version=1, content_hash=__import__(
        "app.models.reviews.claim_extraction", fromlist=["content_digest"]).content_digest(text),
        batch_id=batch.batch_id,
        units=[UnitOutput(unit_id=unit.unit_id, status="claims", reason="synthetic", claims=reached)])
    with pytest.raises(ValueError, match="candidate cap"):
        validate_output(text, batch, output,
                        resource=SimpleNamespace(resource_id="r", version=1),
                        policy=policy, allowed_nodes=set())
