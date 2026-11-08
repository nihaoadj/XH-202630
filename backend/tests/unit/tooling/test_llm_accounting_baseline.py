"""P0 baseline tool contracts (T41 §8.2).

The record/compare harness must freeze the original requests and business
projections, detect any regression (a changed request parameter, a changed
review/claim result, or a drifted source fingerprint), refuse to overwrite a
non-empty fixture directory, and never write real user data into fixtures.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "llm_accounting_baseline", ROOT / "backend/scripts/llm_accounting_baseline.py"
)
baseline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline)

FROZEN_DIR = ROOT / "backend/tests/fixtures/llm_accounting/baseline_v1"


def _record(fixture_dir: Path, output_dir: Path) -> int:
    return baseline.main(["--mode", "record", "--fixture-dir", str(fixture_dir), "--output", str(output_dir)])


def _compare(fixture_dir: Path, output_dir: Path) -> int:
    return baseline.main(["--mode", "compare", "--fixture-dir", str(fixture_dir), "--output", str(output_dir)])


def test_record_then_compare_roundtrip(tmp_path):
    fixture_dir = tmp_path / "baseline"
    output = tmp_path / "out"
    assert _record(fixture_dir, output) == 0
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenarios"] == sorted(baseline.SCENARIOS)
    assert (fixture_dir / "scenarios").is_dir()
    assert _compare(fixture_dir, tmp_path / "out2") == 0


def test_historical_fixture_business_matches_with_explicit_observer_drift(tmp_path):
    """Preserve history: fixes change observer code, not frozen business requests.

    This is a partial audit, NOT the missing pre-implementation baseline (R10).
    The strict CLI remains red on observer drift; no fixture is re-recorded.
    """
    result = _compare(FROZEN_DIR, tmp_path / "out")
    report = json.loads((tmp_path / "out" / "compare-summary.json").read_text(encoding="utf-8"))
    assert result == 1
    assert report["failures"] == ["source_fingerprint: observed gateway/collector source drifted"]
    frozen = json.loads((FROZEN_DIR / "manifest.json").read_text(encoding="utf-8"))["source_fingerprint"]
    current = baseline._ast_fingerprint()
    for key in ("gateway_invoke_structured", "gateway_invoke_plain_text", "gateway_hard_timeout"):
        assert current[key] == frozen[key]


def test_changed_request_parameter_is_detected(tmp_path):
    fixture_dir = tmp_path / "baseline"
    _record(fixture_dir, tmp_path / "out")
    scenario = fixture_dir / "scenarios" / "text_claim_extract.json"
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    # Tamper with one transport request: append a message that was never sent.
    payload["requests"][0]["messages"].append({"role": "system", "content": "INJECTED"})
    scenario.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _compare(fixture_dir, tmp_path / "out2") != 0


def test_changed_business_result_is_detected(tmp_path):
    fixture_dir = tmp_path / "baseline"
    _record(fixture_dir, tmp_path / "out")
    scenario = fixture_dir / "scenarios" / "text_claim_extract.json"
    payload = json.loads(scenario.read_text(encoding="utf-8"))
    # Tamper with a review/claim result: flip the claim-check status.
    payload["projection"]["claim_check_status"] = "completed"
    scenario.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _compare(fixture_dir, tmp_path / "out2") != 0


def test_source_fingerprint_drift_is_detected(tmp_path):
    fixture_dir = tmp_path / "baseline"
    _record(fixture_dir, tmp_path / "out")
    manifest_path = fixture_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_fingerprint"]["accounting_module"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert _compare(fixture_dir, tmp_path / "out2") != 0


def test_record_refuses_nonempty_fixture_dir(tmp_path):
    fixture_dir = tmp_path / "baseline"
    fixture_dir.mkdir()
    (fixture_dir / "stale.json").write_text("{}", encoding="utf-8")
    assert _record(fixture_dir, tmp_path / "out") != 0


def test_fixtures_are_synthetic_and_privacy_clean():
    """No real prompt/PII may leak into fixtures; content is synthetic teaching data."""
    pii_patterns = [
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),  # email
        re.compile(r"\b1[3-9]\d{9}\b"),  # mainland mobile
        re.compile(r"\b\d{3}-\d{4}-\d{4}\b"),  # phone
    ]
    synthetic_markers = {"Python 使用缩进定义代码块", "受控检索", "阶段一"}
    scanned = 0
    found_markers = set()
    for path in (FROZEN_DIR / "scenarios").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        scanned += 1
        for pattern in pii_patterns:
            assert not pattern.search(text), f"PII-like content in {path.name}"
        found_markers |= {m for m in synthetic_markers if m in text}
    assert scanned >= 3
    assert found_markers, "expected synthetic teaching content in fixtures"
