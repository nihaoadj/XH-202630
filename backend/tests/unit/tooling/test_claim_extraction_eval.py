import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/claim_extraction_eval.py"
spec = importlib.util.spec_from_file_location("claim_extraction_eval", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_offline_runs_real_extractor_and_judge_without_env_or_network(monkeypatch):
    import socket
    import app.config
    def forbidden(*a, **kw):
        raise AssertionError("offline evaluation touched environment/provider")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(app.config, "get_settings", forbidden)
    report = evaluation.evaluate()
    assert report["fixture_policy_gate"] == "PASS", report["cases"]
    assert report["quality_gate"] == report["judge_capacity_gate"] == "NOT_RUN_OFFLINE"
    assert len(report["cases"]) >= 23 and report["live_models"] is False
    assert all(r["facts_recall"] == "NOT_MEASURED_SCRIPTED_OUTPUT" for r in report["cases"])
    assert all(r["model_calls_for_merge"] == 0 and r["judge_calls"] <= 1 for r in report["cases"])


def test_fixture_hash_tamper_fails_and_wrong_expected_gate_never_passes(tmp_path):
    manifest, cases = evaluation.load_cases()
    file = tmp_path / "cases.json"
    file.write_text("[]", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        evaluation.load_cases(path)
    bad = {**cases[0], "expected": {**cases[0]["expected"], "candidates": 999}}
    report = evaluation.run_case(bad)
    assert report["fixture_policy_gate"] == "FAIL" and report["errors"]


def test_eval_cli_persists_evidence_and_refuses_overwrite(tmp_path):
    path = tmp_path / "report.json"
    assert evaluation.main(["--output", str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["fixture_policy_gate"] == "PASS"
    with pytest.raises(SystemExit):
        evaluation.main(["--output", str(path)])
