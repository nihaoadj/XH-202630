"""T42: frozen source-locating sub-contract, bounds and byte-level legacy compat."""
import json
from pathlib import Path

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
from app.agents.resource_workflows.learning_documents.claim_extraction.contracts import select_contract
from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import load_rules
from app.models.reviews.claim_extraction import (
    BatchOutput,
    BatchOutputV2,
    EstimatePolicy,
    SourceLocatingPolicy,
    digest,
    encoded,
    PROMPT_VERSION_V2,
)
from tests.fakes.claim_extraction import FixtureCounter, NeutralScriptedGateway, neutral_settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "source_locating_v1"
POLICY_SRC = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "density_v1" / "policies" / "estimate_2_0_baseline.json"


def legacy_json():
    return json.loads(POLICY_SRC.read_text(encoding="utf-8"))


def frozen(**updates):
    updates.setdefault("claim_extraction_source_locating_mode", "tolerant_v1")
    return freeze_policy(neutral_settings(**updates), NeutralScriptedGateway([]), FixtureCounter())


def test_baseline_golden_hash_is_reproducible_without_source_locating():
    policy = EstimatePolicy.model_validate(legacy_json())
    assert policy.source_locating is None
    assert "source_locating" not in policy.model_dump(mode="json")


def test_new_estimate_run_freezes_a_complete_source_locating_sub_contract():
    policy = frozen()
    sub = policy.source_locating
    rules = load_rules()
    assert policy.prompt_version == PROMPT_VERSION_V2
    assert sub.mode == "tolerant_v1"
    assert sub.rules_hash == rules.hash
    assert sub.max_edits == rules.thresholds.max_edits
    assert sub.max_edit_ratio == rules.thresholds.max_edit_ratio
    assert sub.min_effective_chars == rules.thresholds.min_effective_chars
    assert sub.min_score_margin == rules.thresholds.min_score_margin
    assert sub.max_candidate_chars == 2000
    assert sub.locator_algorithm_version == "locator-v2"


def test_exact_v1_mode_is_frozen_distinct_from_tolerant():
    exact = frozen(claim_extraction_source_locating_mode="exact_v1")
    tolerant = frozen(claim_extraction_source_locating_mode="tolerant_v1")
    assert exact.source_locating.mode == "exact_v1"
    assert digest(exact) != digest(tolerant)


def test_source_locating_key_is_omitted_for_historical_policy():
    policy = freeze_policy(neutral_settings(), NeutralScriptedGateway([]), FixtureCounter())
    assert policy.source_locating is None
    for payload in (policy.model_dump(mode="json"), policy.model_dump(), json.loads(policy.model_dump_json())):
        assert "source_locating" not in payload
    assert "source_locating" not in encoded({"snapshot": {"claim_extraction_policy": policy}})


def test_frozen_source_locating_digest_is_deterministic():
    """The frozen sub-contract is fully reproducible from the rules asset."""
    policy = frozen()
    rules = load_rules()
    rebuilt = SourceLocatingPolicy(
        locator_algorithm_version="locator-v2",
        mode="tolerant_v1",
        extractor_prompt_hash=policy.source_locating.extractor_prompt_hash,
        output_schema_hash=policy.source_locating.output_schema_hash,
        rules_hash=rules.hash,
        max_edits=rules.thresholds.max_edits,
        max_edit_ratio=rules.thresholds.max_edit_ratio,
        min_effective_chars=rules.thresholds.min_effective_chars,
        min_score_margin=rules.thresholds.min_score_margin,
        max_unit_chars=rules.thresholds.max_unit_chars,
        max_candidate_chars=rules.thresholds.max_candidate_chars,
        max_dp_cells_per_ref=rules.thresholds.max_dp_cells_per_ref,
        max_distinct_intervals=rules.thresholds.max_distinct_intervals,
        max_work_cells_per_batch=rules.thresholds.max_work_cells_per_batch,
    )
    assert digest(rebuilt) == digest(policy.source_locating)
    assert rebuilt.rules_hash == rules.hash


def test_drifted_rules_hash_changes_the_sub_contract_digest():
    policy = frozen()
    drifted = policy.source_locating.model_copy(update={"rules_hash": "0" * 64})
    assert digest(drifted) != digest(policy.source_locating)


def test_unknown_source_locating_mode_is_rejected():
    with pytest.raises(ValueError):
        SourceLocatingPolicy(mode="fuzzy_v2", extractor_prompt_hash="a" * 64,
                             output_schema_hash="b" * 64, rules_hash="c" * 64,
                             max_edits=2, max_edit_ratio=0.04, min_effective_chars=40,
                             min_score_margin=0.02, max_unit_chars=16000, max_candidate_chars=2000,
                             max_dp_cells_per_ref=2000000, max_distinct_intervals=32,
                             max_work_cells_per_batch=8000000)


def test_source_locating_policy_forbids_extra_keys():
    with pytest.raises(ValueError):
        SourceLocatingPolicy(mode="tolerant_v1", extractor_prompt_hash="a" * 64,
                             output_schema_hash="b" * 64, rules_hash="c" * 64,
                             max_edits=2, max_edit_ratio=0.04, min_effective_chars=40,
                             min_score_margin=0.02, unknown=True)


def test_neutral_v2_prompt_requires_source_locating():
    raw = {**legacy_json(), "prompt_version": PROMPT_VERSION_V2}
    with pytest.raises(ValueError):
        EstimatePolicy.model_validate(raw)


def test_source_locating_requires_neutral_v2_prompt():
    policy = frozen()
    with pytest.raises(ValueError):
        EstimatePolicy.model_validate({**policy.model_dump(mode="json"),
                                       "prompt_version": "claim-extract-neutral-v1"})


def test_select_contract_resolves_v1_and_v2_consistently():
    legacy = freeze_policy(neutral_settings(), NeutralScriptedGateway([]), FixtureCounter())
    modern = frozen()
    assert select_contract(legacy).output_schema is BatchOutput
    assert select_contract(legacy).is_v2 is False
    assert select_contract(modern).output_schema is BatchOutputV2
    assert select_contract(modern).is_v2 is True
    assert select_contract(modern).prompt_version == PROMPT_VERSION_V2


def test_v2_output_schema_has_no_offset_fields():
    schema = BatchOutputV2.model_json_schema()
    candidate = schema["$defs"]["NeutralCandidateV2"]
    assert "source_start" not in candidate["properties"]
    assert "source_end" not in candidate["properties"]
    assert "source_text" in candidate["properties"]
    assert "claim_text" in candidate["properties"]


def test_v1_output_schema_still_has_offset_fields():
    schema = BatchOutput.model_json_schema()
    candidate = schema["$defs"]["NeutralCandidate"]
    assert "source_start" in candidate["properties"]
    assert "source_end" in candidate["properties"]


def test_rules_parameters_manifest_matches_frozen_rules():
    rp = json.loads((FIXTURES / "rules_parameters.json").read_text(encoding="utf-8"))
    assert rp["rules_hash"] == load_rules().hash
