import json
import subprocess
import sys
from pathlib import Path

from app.core.courseware.release_candidate import build_release_candidate_report


def test_release_candidate_requires_evidence_and_never_upgrades_external_work(tmp_path):
    evaluator = tmp_path / "evaluator.json"
    artifacts = tmp_path / "artifacts.json"
    fault_matrix = tmp_path / "fault-matrix.json"
    browser = tmp_path / "browser.json"
    live = tmp_path / "live.json"
    evaluator.write_text(json.dumps({"case_count": 12, "passed": True}), encoding="utf-8")
    artifacts.write_text(json.dumps({
        "case_count": 12, "covered_cases": [f"case-{index}" for index in range(12)],
        "artifacts": [{"status": "produced", "sha256": "a" * 64}],
    }), encoding="utf-8")
    fault_matrix.write_text(json.dumps({"passed": True, "categories": {"backup_restore": {"status": "passed"}}}), encoding="utf-8")
    browser.write_text(json.dumps({"consoleErrors": [], "keyboard": ["Tab"], "reducedMotion": True}), encoding="utf-8")
    live.write_text(json.dumps({"status": "CONFIG_MISSING"}), encoding="utf-8")

    report = build_release_candidate_report(
        evaluator_path=evaluator, artifact_summary_path=artifacts,
        fault_matrix_path=fault_matrix, browser_summary_path=browser,
        live_model_path=live,
    )

    assert report["status"] == "PARTIAL"
    assert report["evidence"]["evaluator"]["status"] == "failed"
    assert report["evidence"]["live_model"]["status"] == "external_pending"
    assert {"CI_REQUIRED", "DEPLOYMENT_REQUIRED", "RELEASE_CYCLE_REQUIRED"} <= set(report["external_pending"])
    assert "a" * 64 not in json.dumps(report)  # hashes are summarized, not copied from artifact payloads


def test_ci_artifact_summary_covers_rejected_cases_without_fabricating_artifacts(tmp_path):
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "artifacts"
    result = subprocess.run(
        [sys.executable, "backend/scripts/courseware_ci_artifacts.py", "--manifest",
         "backend/tests/fixtures/courseware/evals/manifest.json", "--output", str(output)],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "artifact-summary.json").read_text(encoding="utf-8"))

    assert summary["case_count"] == 12
    assert len(summary["covered_cases"]) == 12
    assert {item["case"] for item in summary["artifacts"] if item.get("sha256")} < set(summary["covered_cases"])
    forbidden = {"duplicate-source", "empty-source", "unknown-source", "unknown-component", "unknown-source-block", "ai-review-unresolved"}
    assert not any(item.get("case") in forbidden and item.get("status") == "produced" for item in summary["artifacts"])
