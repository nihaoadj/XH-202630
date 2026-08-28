import json
from pathlib import Path

from app.core.courseware.evaluation import evaluate_courseware_case, evaluate_manifest, quality_gate_report


def test_courseware_evaluation_report_contains_release_debug_fields():
    case = {
        "id": "eval", "scene_requirements": ["intro"], "allowed_components": ["callout"],
        "hard_gate_result": "publish", "expected_artifact_hash": "not-the-current-hash",
        "fallback": "deterministic_scene", "expected_status": "published", "expected_failed_gates": [],
        "expected_fallback": "deterministic_scene", "artifact_policy": "required",
        "max_attempts": 1, "max_llm_calls": 0, "max_tokens": 0, "max_duration_ms": 1000,
        "budget": {"max_attempts": 1},
    }
    snapshots = [{"resource_id": "source", "version": 1, "blocks": [{"block_id": "b1"}]}]
    report = evaluate_courseware_case(case, {
        "title": "评测", "scenes": [{
            "kind": "intro", "title": "开始", "blocks": ["内容"],
            "source_refs": ["source"], "source_block_ids": ["b1"],
            "source_map": {"blocks": [["b1"]]},
        }],
    }, snapshots)
    assert report["passed"] is False
    assert report["artifact_hash"]
    assert report["source_block_ids"] == ["b1"]
    assert report["allowed_components"] == ["callout"]
    assert report["unexpected_components"] == []
    assert report["baseline_diff"]["changed"] is True
    assert report["outcome_matches_manifest"] is True
    assert report["status"] == "published"
    assert report["artifact_policy"] == "required"
    assert report["quality"]["passed"] is False
    assert report["quality"]["component_asset_count"] == 12


def test_quality_gate_keeps_teaching_visual_interaction_failures_separate():
    report = quality_gate_report({
        "title": "不完整", "scenes": [{"kind": "explain", "title": "解释", "blocks": ["内容"]}],
    }, snapshots=[])
    assert report["passed"] is False
    assert "teaching.objective_coverage" in report["failed_dimensions"]
    assert "interaction.interaction_bound_to_objective" in report["failed_dimensions"]
    assert "visual" not in report["failed_dimensions"]


def test_manifest_runner_produces_one_hash_report_per_bounded_case():
    manifest_path = Path(__file__).parents[2] / "fixtures" / "courseware" / "evals" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    reports = evaluate_manifest(manifest)

    assert len(reports) == manifest["budget"]["max_cases"]
    assert {item["fixture"] for item in reports} == {item["id"] for item in manifest["cases"]}
    assert all("failed_gates" in item and "artifact_hash" in item and "baseline_diff" in item for item in reports)
