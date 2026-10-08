"""Gold evidence must be frozen, and generation failures cannot vanish."""
import copy
import shutil
from types import SimpleNamespace

import pytest

from app.config import PROJECT_ROOT
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.reports import competition_suite as module
from app.services.reports.competition_evidence import confined_path


@pytest.mark.parametrize(("key", "value"), [
    ("minimum_case_count", 49), ("hallucination_rate_max", .051),
    ("difficulty_match_accuracy_min", .849), ("knowledge_coverage_min", .899),
])
def test_official_thresholds_cannot_be_weakened(key, value):
    suite = module.load_suite()
    suite["competition_thresholds"][key] = value
    with pytest.raises(ValueError):
        module.validate_suite(suite)


def test_fixture_version_and_actual_background_usage_are_checked():
    suite = module.load_suite()
    broken = copy.deepcopy(suite)
    broken["claims_payload"]["fixture_version"] = "future"
    with pytest.raises(ValueError, match="fixture_version"):
        module.validate_suite(broken)
    for learner in suite["profiles_payload"]["learners"]:
        learner["background_id"] = "student"
    with pytest.raises(ValueError, match="cases must use"):
        module.validate_suite(suite)


def test_snapshot_rejects_changed_knowledge_and_unknown_evidence(tmp_path):
    suite = module.load_suite()
    kb = PROJECT_ROOT / "knowledge_base" / suite["knowledge_base_id"]
    clone = tmp_path / suite["knowledge_base_id"]
    shutil.copytree(kb, clone)
    module.validate_suite(suite, kb_root=tmp_path)
    document = next((clone / "modules").glob("*.md"))
    document.write_text(document.read_text(encoding="utf-8") + "\nchanged knowledge\n", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot drift"):
        module.validate_suite(suite, kb_root=tmp_path)
    suite["claims_payload"]["claims"][0]["evidence_ids"] = ["ev-mod01-sec999"]
    with pytest.raises(ValueError, match="unknown source section"):
        module.validate_suite(suite)


def test_fixture_path_cannot_escape_its_root(tmp_path):
    with pytest.raises(ValueError, match="within its root"):
        confined_path(tmp_path, "../outside.json")


def test_default_suite_cannot_drop_its_source_snapshot():
    suite = module.load_suite()
    suite.pop("sources_payload")
    suite["files"].pop("sources")
    with pytest.raises(ValueError, match="requires frozen sources"):
        module.validate_suite(suite)


def test_offline_has_zero_generations_and_per_case_reference_evidence():
    report = module.evaluate_competition_metrics(module.load_suite())
    assert report.completed_generation_count == 0
    assert report.selected_case_count == len(report.case_results) == 54
    assert {gate.status for gate in report.official_gates} == {"NOT_MEASURABLE"}
    assert report.source_snapshot_hash and report.suite_data_hash
    assert {item["status"] for item in report.case_results} == {"REFERENCE_ONLY"}
    assert all(item["output"] is None and not item["runtime_events"] for item in report.case_results)
    assert all(item["gold_claim_ids"] and item["gold_source_evidence_ids"] for item in report.case_results)


def test_hallucination_strict_boundary_and_inclusive_accuracy_boundary():
    suite = module.load_suite()
    baseline = module.evaluate_competition_metrics(suite)
    suite["competition_thresholds"]["hallucination_rate_max"] = baseline.claim_metrics.claim_hallucination_rate
    suite["competition_thresholds"]["difficulty_match_accuracy_min"] = baseline.difficulty.accuracy
    suite["competition_thresholds"]["knowledge_coverage_min"] = 1.0
    gates = {item.metric_id: item.status for item in module.evaluate_competition_metrics(suite).gates}
    assert gates == {"M-HALLUCINATION": "FAIL", "M-DIFFICULTY": "PASS", "M-COVERAGE": "PASS"}


def test_live_failures_remain_in_denominator_and_exception_text_is_redacted(monkeypatch):
    # Everything is an in-memory test double; no container/model/database is initialized.
    monkeypatch.setattr(module, "is_live_ready", lambda: (True, "isolated test double"))
    monkeypatch.setattr(module, "_persist_learner", lambda container, plan: LearnerProfile(
        learner_id=plan.learner_id, learner_type="test", education=plan.education, major=plan.major,
        knowledge_base_id=plan.knowledge_base_id, learning_goal=plan.learning_goal, skill_level=plan.skill_level))

    class Jobs:
        index = 0
        def create_job(self, profile, request):
            self.index += 1
            return SimpleNamespace(run_id=f"test-run-{self.index}", batch_id="test-batch")
        def run_job(self, *args):
            if self.index == 1:
                raise RuntimeError("DO_NOT_EXPORT_SECRET")

    class Query:
        def get_timeline(self, run_id, limit):
            items = [] if run_id.endswith("2") else [LearningResource(
                resource_id=run_id, resource_type="分阶测试题", difficulty="初级", content_text="fixture",
                knowledge_points=["rag_basics"], source_refs=[], publication_status="published").model_dump()]
            return SimpleNamespace(resource_versions=items, events=[], evidence=[])
        def get_claims(self, run_id):
            return SimpleNamespace(claims=[], judgements=[])

    jobs = Jobs()
    container = SimpleNamespace(generation_job_service=lambda: jobs, run_query_service=lambda: Query())
    report = module.evaluate_live_metrics(module.load_suite(), max_cases=3, container=container)
    assert report.selected_case_count == report.difficulty.case_total == 3
    assert report.failed_case_count == 2 and report.completed_generation_count == 1
    assert report.difficulty.accuracy == 1 / 3
    assert report.case_results[0]["failure_stage"] == "generation"
    assert report.case_results[1]["error_type"] == "NoPublishedResource"
    assert "DO_NOT_EXPORT_SECRET" not in report.model_dump_json()
    assert {item.status for item in report.gates + report.official_gates} == {"NOT_MEASURABLE"}


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_live_max_cases_requires_positive_integer(monkeypatch, value):
    monkeypatch.setattr(module, "is_live_ready", lambda: (True, "test"))
    with pytest.raises(ValueError, match="positive integer"):
        module.evaluate_live_metrics({}, max_cases=value, container=object())
