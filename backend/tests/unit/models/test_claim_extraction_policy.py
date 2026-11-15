import pytest

from app.models.reviews.claim_extraction import (
    BatchOutput, ExtractionPolicy, NeutralCandidate, UnitOutput, check_ledger_size, ExtractionLedger,
    policy_from_input,
)
from tests.fakes.claim_extraction import policy, snapshot_for


def test_private_policy_versions_bounds_and_cross_constraints():
    p = policy()
    assert policy_from_input(snapshot_for(p)) == p
    for key, value in [("strategy", "unknown"), ("target_tokens", 8193), ("max_calls", 0),
                       ("resource_claims", 49), ("max_units", 129), ("attempt_timeout_seconds", 61),
                       ("max_request_seconds", float("nan")), ("ledger_bytes", 2**21 + 1)]:
        with pytest.raises(ValueError):
            ExtractionPolicy.model_validate({**p.model_dump(mode="json"), key: value})
    bad = snapshot_for(p)
    bad["claim_extraction_policy_hash"] = "0" * 64
    with pytest.raises(ValueError):
        policy_from_input(bad)
    with pytest.raises(ValueError):
        policy_from_input({**snapshot_for(p), "include_claim_check": False})
    assert policy_from_input({}) is None


def test_ledger_json_cap_includes_policy_bytes():
    from app.models.reviews.claim_extraction import encoded
    state = ExtractionLedger()
    p = policy(ledger_bytes=3000)
    size = len(encoded(state).encode()) + len(encoded(p).encode())
    with pytest.raises(ValueError):
        check_ledger_size(p.model_copy(update={"ledger_bytes": size - 1}), state)
    check_ledger_size(p.model_copy(update={"ledger_bytes": size + 1}), state)


def test_raw_candidate_whitespace_preserved_and_envelopes_strict():
    candidate = NeutralCandidate(claim_text=" a  b ", claim_type="factual", source_text="\r\n x \t",
                                 source_start=0, source_end=7)
    assert candidate.source_text == "\r\n x \t"
    assert candidate.claim_text == " a  b "
    with pytest.raises(ValueError):
        NeutralCandidate(**candidate.model_dump(), source_evidence_ids=[])
    with pytest.raises(ValueError):
        UnitOutput(unit_id="u", status="non_factual", reason="x", claims=[candidate])
    with pytest.raises(ValueError):
        BatchOutput(resource_id="r", resource_version=1, content_hash="a"*64, batch_id="b", units=[])
    with pytest.raises(ValueError):
        check_ledger_size(policy(ledger_bytes=1), ExtractionLedger())
