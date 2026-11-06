from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.courseware_content_review_eval import load_manifest, aggregate_observations, main
from scripts.courseware_content_review_fixtures import frozen_manifest
from app.models.courseware.content_review import json_hash


def observations(manifest):
    return [{"sample_id": c["id"], "repeat": r, "strategy": s, "approved": not bool(c["primary_defect"]),
        "valid_structure": True, "valid_detection": bool(c["primary_defect"]), "located_item": c["item_id"],
        "input_tokens": 128, "output_tokens": 128, "duration_ms": 10}
        for c in manifest["cases"] for r in range(3) for s in ("baseline", "candidate")]


def test_manifest_is_frozen_complete_and_tampering_rejected(tmp_path):
    manifest = frozen_manifest(); path = tmp_path/"manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert len(load_manifest(path)["cases"]) == 36
    manifest["cases"][0]["candidate"]["learning_scope"] = "changed"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError): load_manifest(path)


@pytest.mark.parametrize("fault,expected", [("missing", "INCOMPLETE_OBSERVATIONS"), ("duplicate", "INCOMPLETE_OBSERVATIONS"), ("usage", "INCONCLUSIVE_USAGE"), ("annotation", "INCOMPLETE_ANNOTATION"), ("budget", "INCOMPLETE_BUDGET"), ("bad_approved", "FAIL"), ("generic_rejection", "FAIL"), ("first_pass_invalid", "FAIL"), ("cost", "FAIL")])
def test_quality_gate_never_turns_incomplete_or_leaked_bad_sample_into_pass(fault, expected):
    manifest = frozen_manifest(); obs = observations(manifest)
    bad = next(o for o in obs if o["strategy"] == "candidate" and not o["approved"])
    if fault == "missing": obs.pop()
    elif fault == "duplicate": obs.append(obs[0])
    elif fault == "usage": obs[0]["input_tokens"] = None
    elif fault == "budget": obs[0]["over_budget"] = True
    elif fault == "bad_approved": bad["approved"] = True
    elif fault == "generic_rejection": bad["valid_detection"] = False
    elif fault == "first_pass_invalid": bad["valid_structure"] = False
    elif fault == "cost":
        for o in obs:
            if o["strategy"] == "candidate": o["input_tokens"] *= 5
    result = aggregate_observations(manifest, obs, annotations_complete=fault != "annotation")
    assert result["quality_gate"] == expected and result["enabled"] is False


def test_nearest_rank_and_complete_counterfactual_quality_metrics():
    manifest = frozen_manifest(); obs = observations(manifest)
    result = aggregate_observations(manifest, obs, annotations_complete=True)
    assert result["quality_gate"] == "PASS" and result["metrics"]["candidate"]["p95_ms"] == 10
    assert result["metrics"]["candidate"]["groups"]["overall"]["bad"] == 72


@pytest.mark.parametrize("args", [["--live"], ["--preflight"], ["--preflight", "--max-total-tokens", "0"]])
def test_live_and_preflight_reject_missing_explicit_authorization_or_finite_budget(tmp_path, monkeypatch, args):
    monkeypatch.delenv("COURSEWARE_LIVE_EVAL", raising=False)
    with pytest.raises(SystemExit): main([*args, "--output", str(tmp_path/"report.json")])
    assert not (tmp_path/"report.json").exists()
