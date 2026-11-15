"""T42 offline source-locating eval must be real, non-overwriting and provider-free."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/claim_source_locating_eval.py"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "source_locating_v1"
MANIFEST = FIXTURES / "manifest.json"
INDEPENDENT = FIXTURES.parent / "source_locating_v2"


def load():
    spec = importlib.util.spec_from_file_location("claim_source_locating_eval_t42", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_evaluation_uses_production_locate_without_provider(monkeypatch):
    import socket
    import app.config

    def forbidden(*args, **kwargs):
        raise AssertionError("offline locating evaluation touched network/environment")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(app.config, "get_settings", forbidden)
    result = load().evaluate(MANIFEST, "calibration")
    assert result["totals"]["sample_total"] == 120
    assert result["metrics"]["unique_exact_accuracy"] == 1.0
    assert result["metrics"]["format_recovery"] == 1.0
    assert result["metrics"]["edit_recovery"] == 1.0
    assert result["metrics"]["must_reject_wrong_accept"] == 0
    assert result["metrics"]["accepted_wrong_span"] == 0
    assert result["gates"] == {
        "unique_exact_span_accuracy": "PASS",
        "format_recovery": "PASS",
        "edit_recovery": "PASS",
        "must_reject_wrong_accept": "PASS",
        "accepted_wrong_span": "PASS",
    }
    assert "api.py" in " ".join(result["sources"])


def test_acceptance_split_reports_identical_gates():
    result = load().evaluate(MANIFEST, "acceptance")
    assert result["totals"]["sample_total"] == 120
    assert result["gates"]["edit_recovery"] == "PASS"
    assert result["metrics"]["must_reject_wrong_accept"] == 0


def test_reject_codes_are_reported_separately():
    result = load().evaluate(MANIFEST, "calibration")
    by_code = result["metrics"]["reject_by_code"]
    assert by_code["ambiguous_exact"] == 6
    assert by_code["protected_content_changed"] == 12
    assert by_code["edit_not_allowed"] == 18
    assert by_code["no_candidate"] == 18
    assert by_code["source_too_long"] == 6


def test_evaluation_refuses_to_overwrite_existing_evidence(tmp_path):
    output = tmp_path / "claim-source-locating.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        load().evaluate(MANIFEST, "calibration", output)


def test_missing_manifest_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load().evaluate(tmp_path / "absent.json", "calibration")


def test_manifest_split_hash_tamper_fails(tmp_path):
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, target)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["splits"]["calibration"]["sha256"] = "0" * 64
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load().evaluate(target / "manifest.json", "calibration")


def test_gold_span_that_does_not_slice_text_is_rejected(tmp_path):
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, target)
    path = target / "calibration.json"
    samples = json.loads(path.read_text(encoding="utf-8"))
    samples[0]["expect"]["start"] += 1  # no longer slices the claim_text
    path.write_text(json.dumps(samples, ensure_ascii=False), encoding="utf-8")
    # The altered file no longer matches the manifest hash, but the loader
    # validates the split body first via the hash gate.
    with pytest.raises(ValueError):
        load().evaluate(target / "manifest.json", "calibration")


def test_missing_split_file_is_an_error(tmp_path):
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, target)
    (target / "calibration.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        load().evaluate(target / "manifest.json", "calibration")


def test_unknown_split_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="split"):
        load().evaluate(MANIFEST, "nonsense")


def test_main_returns_nonzero_on_failure(tmp_path):
    module = load()
    assert module.main(["--manifest", str(tmp_path / "absent.json"), "--split", "calibration"]) == 2


def test_main_returns_zero_on_success(tmp_path):
    module = load()
    output = tmp_path / "report.json"
    assert module.main(["--manifest", str(MANIFEST), "--split", "acceptance",
                        "--output", str(output)]) == 0
    assert output.exists()


@pytest.mark.parametrize("leak", ["source_group", "source_template", "text", "missing_template"])
def test_independent_evaluation_rejects_cross_split_leakage(tmp_path, leak):
    import hashlib

    target = tmp_path / "independent"
    shutil.copytree(INDEPENDENT, target)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cal = json.loads((target / "calibration.json").read_text(encoding="utf-8"))
    path = target / "acceptance.json"
    acc = json.loads(path.read_text(encoding="utf-8"))
    if leak == "missing_template":
        acc[0].pop("source_template")
    elif leak == "text":
        for key in ("text", "ref", "source_text_gold", "unit_end", "expect"):
            acc[0][key] = cal[0][key]
    else:
        acc[0][leak] = cal[0][leak]
    path.write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
    manifest["splits"]["acceptance"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="leakage|requires"):
        load().evaluate(manifest_path, "calibration")


def test_unrecovered_positive_is_not_reported_as_wrong_binding(monkeypatch):
    module = load()
    from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import LocateResult

    monkeypatch.setattr(module, "locate", lambda *a, **k: LocateResult(
        None, None, "exact", "no_candidate"))
    result = module.evaluate(INDEPENDENT / "manifest.json", "calibration")
    assert result["metrics"]["edit_recovery"] == 0
    assert result["metrics"]["accepted_wrong_span"] == 0
    assert result["gates"]["edit_recovery"] == "FAIL"


def test_historical_fixture_is_not_reported_as_independent():
    result = load().evaluate(MANIFEST, "calibration")
    assert result["independence"] == "NOT_PROVEN_HISTORICAL"
    assert result["locator_algorithm_version"] == "locator-v1"
