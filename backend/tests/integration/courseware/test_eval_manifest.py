"""Low-cost, versioned release-evaluation inventory for courseware CI."""

import json
from pathlib import Path

from app.core.courseware.evaluation import execute_workflow_case


def test_compact_courseware_eval_manifest_is_complete_and_bounded():
    path = Path(__file__).parents[2] / "fixtures" / "courseware" / "evals" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    assert manifest["schema_version"] == "2.0"
    assert manifest["budget"] == {"max_cases": 20, "network": False, "llm_calls": 0, "max_tokens": 0, "max_duration_seconds": 60}
    assert len(manifest["hard_gates"]) == 6
    assert len(cases) == manifest["budget"]["max_cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    required = {
        "frozen_input", "scene_requirements", "allowed_components", "hard_gate_result", "fallback",
        "expected_status", "expected_failed_gates", "expected_fallback", "artifact_policy",
        "max_attempts", "max_llm_calls", "max_tokens", "max_duration_ms",
        "expected_artifact_hash", "baseline_diff", "budget",
    }
    assert all(required <= case.keys() for case in cases)
    assert {"auto_revision", "quarantine", "release_reject"} <= {case["hard_gate_result"] for case in cases}
    assert all(case["budget"]["max_attempts"] > 0 and case["budget"]["max_seconds"] > 0 for case in cases)
    assert all(case["artifact_policy"] in {"required", "forbidden"} for case in cases)
    assert sum(case["artifact_policy"] == "required" for case in cases) >= 6
    quality_ids = {
        "short-low-interaction", "medium-interaction-30m", "high-interaction-60m",
        "multi-resource-concept-fusion", "duplicate-and-complementary-sources",
        "source-conflict-parallel", "constrained-interaction-quota", "localized-review-repair",
    }
    assert all("quality_expectations" in case for case in cases if case["id"] in quality_ids)


def test_fault_injection_cases_reach_their_release_gate_without_executor_type_error():
    manifest_path = Path(__file__).parents[2] / "fixtures" / "courseware" / "evals" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = [case for case in manifest["cases"] if case["id"] in {"unknown-component", "unknown-source-block"}]

    actual = [execute_workflow_case(case) for case in cases]

    assert [item["status"] for item in actual] == ["quarantined", "quarantined"]
    assert all(item["artifact_present"] is False for item in actual)
