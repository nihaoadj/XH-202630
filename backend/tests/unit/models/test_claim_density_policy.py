"""T37: frozen density sub-contract, bounds and byte-level legacy compatibility."""
import json
from pathlib import Path

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
from app.models.reviews.claim_extraction import (
    DensityBatchingPolicy,
    EstimatePolicy,
    ExtractionPolicy,
    digest,
    encoded,
)
from tests.fakes.claim_extraction import (
    FixtureCounter,
    NeutralScriptedGateway,
    neutral_settings,
    policy as extraction_policy,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "density_v1"
POLICIES = FIXTURES / "policies"
META = json.loads((POLICIES / "baseline_meta.json").read_text(encoding="utf-8"))


def legacy_json():
    return json.loads((POLICIES / "estimate_2_0_baseline.json").read_text(encoding="utf-8"))


def legacy_policy():
    return EstimatePolicy.model_validate(legacy_json())


def frozen(**updates):
    return freeze_policy(neutral_settings(**updates), NeutralScriptedGateway([]), FixtureCounter())


def test_baseline_golden_hash_is_reproducible_from_current_contract():
    assert digest(legacy_policy()) == META["estimate_2_0"]["digest"]
    assert META["estimate_2_0"]["has_density_batching"] is False
    assert len(legacy_policy().model_dump(mode="json")) == META["estimate_2_0"]["field_count"] == 28


def test_legacy_policy_omits_density_key_in_every_serialization_path():
    raw = legacy_json()
    assert "density_batching" not in raw
    policy = legacy_policy()
    assert policy.density_batching is None
    assert "density_batching" not in policy.model_dump(mode="json")
    assert "density_batching" not in policy.model_dump()
    assert "density_batching" not in policy.model_dump_json()
    assert "density_batching" not in encoded(policy)
    # A nested envelope must stay byte-identical too: dispatch snapshots wrap
    # the policy inside request payloads.
    assert "density_batching" not in encoded({"snapshot": {"claim_extraction_policy": policy}})
    assert digest(policy.model_dump(mode="json")) == META["estimate_2_0"]["digest"]


def test_legacy_policy_roundtrips_without_materializing_the_new_field():
    once = legacy_policy().model_dump(mode="json")
    twice = EstimatePolicy.model_validate(once).model_dump(mode="json")
    assert once == twice
    assert set(once) == set(legacy_json())


def test_extraction_policy_1_0_keeps_its_own_hash_and_has_no_density_field():
    policy = extraction_policy()
    assert digest(policy) == META["extraction_1_0"]["digest"]
    assert "density_batching" not in policy.model_dump(mode="json")
    assert "density_batching" not in ExtractionPolicy.model_json_schema()["properties"]


def test_new_estimate_run_freezes_a_complete_density_sub_contract():
    policy = frozen()
    density = policy.model_dump(mode="json")["density_batching"]
    assert density == {"version": "claim-density-v1", "enabled": True,
                       "chars_per_claim": 35.0, "capacity_share": 0.9}
    assert digest(policy) != META["estimate_2_0"]["digest"]


def test_each_density_parameter_changes_the_frozen_hash():
    base = digest(frozen())
    assert digest(frozen(claim_extraction_density_enabled=False)) != base
    assert digest(frozen(claim_extraction_density_prior=36)) != base
    assert digest(frozen(claim_extraction_risk_share=0.8)) != base


def test_disabled_density_is_still_frozen_not_omitted():
    policy = frozen(claim_extraction_density_enabled=False)
    density = policy.model_dump(mode="json")["density_batching"]
    assert density["enabled"] is False
    assert density["chars_per_claim"] == 35.0
    # Missing sub-contract means "historical snapshot", never "feature disabled".
    assert policy.density_batching is not None


def test_later_settings_drift_cannot_rewrite_a_frozen_policy():
    frozen_policy = frozen()
    before = digest(frozen_policy)
    # Simulating process-wide drift after the Run was frozen.
    drifted = frozen(claim_extraction_density_prior=99, claim_extraction_risk_share=0.5,
                     claim_extraction_batch_claims=20)
    assert digest(frozen_policy) == before
    assert frozen_policy.density_batching.chars_per_claim == 35.0
    assert frozen_policy.batch_claims == 16
    assert digest(drifted) != before


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_non_positive_prior_is_rejected(value):
    with pytest.raises(ValueError):
        DensityBatchingPolicy(chars_per_claim=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_prior_or_share_is_rejected(value):
    with pytest.raises(ValueError):
        DensityBatchingPolicy(chars_per_claim=value)
    with pytest.raises(ValueError):
        DensityBatchingPolicy(capacity_share=value)


@pytest.mark.parametrize("value", [0, -0.1, 1.1, 2])
def test_capacity_share_outside_unit_interval_is_rejected(value):
    with pytest.raises(ValueError):
        DensityBatchingPolicy(capacity_share=value)


def test_unknown_density_version_is_rejected():
    with pytest.raises(ValueError):
        DensityBatchingPolicy(version="claim-density-v2")
    with pytest.raises(ValueError):
        EstimatePolicy.model_validate({**legacy_json(), "density_batching": {"version": "claim-density-v0"}})


def test_density_sub_contract_forbids_extra_keys():
    with pytest.raises(ValueError):
        DensityBatchingPolicy(unknown=True)


def test_absent_density_policy_is_not_materialized_by_validation():
    raw = legacy_json()
    policy = EstimatePolicy.model_validate({**raw, "density_batching": None})
    assert policy.density_batching is None
    assert "density_batching" not in policy.model_dump(mode="json")


def test_historical_parser_view_rejects_new_snapshot_but_still_reads_old_ones():
    """Simulates a pre-T37 Worker: strict model without the new field.

    Rejection happens while parsing the frozen snapshot, i.e. before any node is
    entered, so no provider call can occur. Mixing Web/Worker versions is
    therefore a controlled failure, not a silent mis-read (T37 §3.1.6).
    """
    from pydantic import ConfigDict, create_model

    fields = {name: (field.annotation, field)
              for name, field in EstimatePolicy.model_fields.items()
              if name not in {"density_batching", "source_locating"}}
    LegacyView = create_model("LegacyEstimatePolicyView",
                              __config__=ConfigDict(extra="forbid", frozen=True, protected_namespaces=()),
                              **fields)
    legacy = legacy_json()
    assert LegacyView.model_validate(legacy).model_dump(mode="json") == legacy
    modern = json.loads(frozen().model_dump_json())
    with pytest.raises(ValueError, match="density_batching"):
        LegacyView.model_validate(modern)
