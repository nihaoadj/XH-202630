"""T48 v2 evaluation: ordinary-review coverage is the only M-COVERAGE source.

The v1 report stays untouched on disk; v2 is a separate suite version and a
separate report shape.  These tests pin the metric separation rather than the
fixture numbers: changing Claim facts may move the hallucination gate, but it
must never move coverage, and a missing case can never leave the denominator.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.reports.competition_suite import (
    evaluate_competition_metrics,
    load_suite,
    validate_suite,
)
from app.services.reviews.quality_metrics import ordinary_coverage_evaluation
from app.models.reviews.quality_metrics import QualityEvidenceMode, QualityMetricStatus

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "competition"


@pytest.fixture(scope="module")
def suite():
    return load_suite()


@pytest.fixture(scope="module")
def baseline(suite):
    return evaluate_competition_metrics(suite)


def _coverage_gate(report):
    return next(gate for gate in report.gates if gate.metric_id == "M-COVERAGE")


def _with_all_targets_covered(suite):
    mutated = copy.deepcopy(suite)
    for case in mutated["coverage_payload"]["cases"]:
        for target in case["targets"]:
            target["covered"] = True
    return mutated


def _with_missing_cases(suite, count=3):
    mutated = copy.deepcopy(suite)
    for case in mutated["coverage_payload"]["cases"][:count]:
        case["observed"] = False
        case["failure_code"] = "GENERATION_FAILED"
        case["targets"] = []
    return mutated


def test_v2_report_has_no_claim_coverage_and_uses_ordinary_units(baseline):
    assert baseline.suite_version == "v2"
    assert baseline.report_schema_version == "2.0"
    assert baseline.metric_definition_version == "resource-quality/v2"

    coverage = baseline.ordinary_coverage
    assert coverage.definition_version == "ordinary-target-coverage/v2"
    assert coverage.planned_case_total == 54
    assert coverage.observed_case_total == 54
    assert coverage.planned_unit_total == 54
    assert coverage.covered_unit_total == 51
    assert coverage.missing_unit_total == 3
    assert coverage.metric.value == 51 / 54
    assert coverage.metric.status.value == "complete"

    # The Claim aggregate must not carry a second coverage definition.
    for retired in ("knowledge_coverage_rate", "covered_skill_total", "target_skill_total"):
        assert not hasattr(baseline.claim_metrics, retired)


def test_offline_pass_is_not_an_official_pass(baseline):
    assert {gate.status for gate in baseline.gates} == {"PASS"}
    assert all(gate.status == "NOT_MEASURABLE" for gate in baseline.official_gates)
    assert baseline.evidence_scope.startswith("offline_gold")


def test_report_is_json_serialisable_and_rejects_unknown_fields(baseline):
    payload = baseline.model_dump(mode="json")
    assert payload["ordinary_coverage"]["metric"]["numerator"] == 51
    assert payload["ordinary_coverage"]["metric"]["denominator"] == 54
    assert "knowledge_coverage_rate" not in json.dumps(payload)
    # extra="forbid" applies at validation time.
    from app.services.reports.competition_suite import CompetitionMetricReport

    with pytest.raises(Exception):
        CompetitionMetricReport.model_validate({**payload, "unexpected": 1})


def test_changing_only_ordinary_coverage_moves_m_coverage(suite, baseline):
    mutated = _with_all_targets_covered(suite)
    report = evaluate_competition_metrics(mutated)

    assert report.ordinary_coverage.metric.value == 1.0
    assert report.ordinary_coverage.covered_unit_total == 54
    assert _coverage_gate(report).actual_value == 1.0
    assert _coverage_gate(report).status == "PASS"
    # Claims were not touched, so the hallucination result is identical.
    assert report.claim_metrics == baseline.claim_metrics


def test_changing_claim_verdicts_and_relations_never_moves_coverage(suite, baseline):
    mutated = copy.deepcopy(suite)
    nodes = list(mutated["claims_payload"]["target_skill_nodes"])
    flipped = False
    for index, claim in enumerate(mutated["claims_payload"]["claims"]):
        if (not flipped and claim["claim_type"] == "factual"
                and claim["verdict"] == "supported" and claim["evidence_ids"]):
            claim["verdict"] = "contradicted"
            flipped = True
        # Rotate the valid node ids: every reference stays legal, but the
        # Claim→knowledge relation is materially different from the fixture.
        claim["knowledge_point_id"] = nodes[index % len(nodes)]

    report = evaluate_competition_metrics(mutated)

    assert report.ordinary_coverage.model_dump() == baseline.ordinary_coverage.model_dump()
    assert _coverage_gate(report).actual_value == _coverage_gate(baseline).actual_value
    # The hallucination gate does react to the Claim facts.
    assert report.claim_metrics.claim_hallucination_rate > baseline.claim_metrics.claim_hallucination_rate


def test_missing_cases_keep_the_planned_denominator_and_never_pass(suite, baseline):
    mutated = _with_missing_cases(suite, count=3)
    report = evaluate_competition_metrics(mutated)

    coverage = report.ordinary_coverage
    assert coverage.planned_case_total == baseline.ordinary_coverage.planned_case_total == 54
    assert coverage.observed_case_total == 51
    assert coverage.missing_case_count == 3
    assert coverage.failed_case_total == 3
    assert coverage.metric.status.value == "incomplete"
    assert coverage.metric.value is None
    assert coverage.missing_unit_total is None
    assert coverage.unknown_case_ids  # named, not silently dropped
    gate = _coverage_gate(report)
    assert gate.status == "FAIL"
    assert gate.actual_value is None
    assert "missing_cases=3" in gate.evidence


def test_missing_case_in_one_unit_result_also_blocks_completeness():
    cases = [
        {
            "case_id": "case-a", "observed": True,
            "targets": [{"target_id": "node-1", "covered": True}],
        },
    ]
    evaluation = ordinary_coverage_evaluation(
        __import__(
            "app.services.reports.competition_suite", fromlist=["build_ordinary_coverage_cases"],
        ).build_ordinary_coverage_cases({"cases": cases}),
        planned_case_total=2,
        planned_unit_total=2,
        fixture_version="ordinary-coverage/v2",
        evidence_mode=QualityEvidenceMode.OFFLINE_GOLD,
    )
    assert evaluation.metric.status.value == "incomplete"
    assert evaluation.metric.value is None
    assert evaluation.observed_case_total == 1
    assert evaluation.missing_case_count == 1


def test_v1_manifest_is_refused_instead_of_silently_reinterpreted(tmp_path):
    manifest = json.loads((FIXTURE_ROOT / "suite_v2.json").read_text(encoding="utf-8"))
    manifest["suite_version"] = "v1"
    path = tmp_path / "suite_v1.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="retired Claim knowledge-coverage"):
        load_suite(path)


def test_v2_suite_requires_the_coverage_fixture(suite):
    mutated = dict(suite)
    mutated.pop("coverage_payload", None)
    with pytest.raises(ValueError, match="requires a coverage payload"):
        validate_suite(mutated)


def test_coverage_target_drift_is_rejected(suite):
    mutated = copy.deepcopy(suite)
    case = mutated["coverage_payload"]["cases"][0]
    case["targets"][0]["target_id"] = "not-a-frozen-target"
    with pytest.raises(ValueError, match="targets drift"):
        validate_suite(mutated)


def test_v1_fixture_file_bytes_are_untouched():
    # v1 is retained verbatim; v2 is a new manifest and a new coverage file.
    assert (FIXTURE_ROOT / "suite.json").is_file()
    assert (FIXTURE_ROOT / "suite_v2.json").is_file()
    assert (FIXTURE_ROOT / "coverage" / "ordinary_coverage_v2.json").is_file()
    v1 = json.loads((FIXTURE_ROOT / "suite.json").read_text(encoding="utf-8"))
    assert v1["suite_version"] == "v1"
    assert "coverage" not in (v1.get("files") or {})


def test_cli_render_emits_the_v2_coverage_name_only(baseline):
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "competition_eval.py"
    spec = importlib.util.spec_from_file_location("competition_eval_t48", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module._render_report(baseline)
    metrics = rendered["metrics"]
    assert metrics["core_knowledge_coverage_rate"] == 51 / 54
    assert metrics["coverage_definition_version"] == "ordinary-target-coverage/v2"
    # The retired Claim-based name must not reappear as a key anywhere in a v2
    # JSON report.  (The new name contains it as a substring, so check keys.)
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert "knowledge_coverage_rate" not in set(keys(rendered))



def _typed_records():
    from app.models.reviews.quality_metrics import EvaluationQualityManifestV2, EvaluationQualityCaseV2
    from app.services.reviews.quality_evaluation import manifest_hash
    manifest = EvaluationQualityManifestV2(
        evaluation_id="test", experiment_name="main", suite_id="test-suite", suite_version="v2",
        fixture_version="labels/v1", coverage_fixture_version="coverage/v2", evidence_mode="offline_gold",
        source_snapshot_hash="a" * 64, suite_data_hash="b" * 64,
        selected_case_targets={"one": ("same-target",), "two": ("same-target", "other")},
    )
    cases = [EvaluationQualityCaseV2(
        manifest_hash=manifest_hash(manifest), case_id=case_id, generation_status="reference_only",
        expected_difficulty="medium", predicted_difficulty="medium",
        ordinary_coverage={"case_id": case_id, "observed": True,
                           "targets": [{"target_id": target, "covered": True} for target in targets]},
        claim_status="complete", claim_counts={"claim_total": 10, "factual_claim_total": 10, "supported_claim_total": 10},
    ) for case_id, targets in manifest.selected_case_targets.items()]
    return manifest, cases


def test_typed_evaluation_case_target_denominators_and_duplicate_idempotency():
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    manifest, cases = _typed_records()
    result = aggregate_evaluation(manifest, [*cases, cases[0]])
    assert result.status == "complete"
    assert result.received_case_total == 2
    assert result.coverage.denominator == 3 and result.coverage.numerator == 3
    assert result.difficulty.denominator == 2
    assert result.hallucination.denominator == 20
    missing = aggregate_evaluation(manifest, cases[:1])
    assert missing.planned_case_total == 2
    assert missing.status == "incomplete"
    assert missing.coverage.value is missing.hallucination.value is missing.difficulty.value is None


def test_typed_conflicts_and_wrong_frozen_targets_never_pass():
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    manifest, cases = _typed_records()
    conflict = cases[0].model_copy(update={"predicted_difficulty": "easy"})
    result = aggregate_evaluation(manifest, [*cases, conflict])
    assert result.status == "invalid"
    assert result.coverage.value is result.difficulty.value is result.hallucination.value is None
    foreign = cases[0].model_copy(update={"manifest_hash": "c" * 64})
    assert aggregate_evaluation(manifest, [foreign, cases[1]]).status == "invalid"


def test_typed_metric_independence_claim_failure_does_not_erase_coverage():
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    manifest, cases = _typed_records()
    cases[0] = cases[0].model_copy(update={"claim_status": QualityMetricStatus.FAILED,
                                         "claim_counts": None,
                                         "generation_status": "failed"})
    result = aggregate_evaluation(manifest, cases)
    assert result.coverage.value == 1
    assert result.hallucination.value is None
    assert result.difficulty.value == .5


def test_evaluation_service_only_consumes_explicit_v2_records():
    from types import SimpleNamespace
    from app.services.reports.evaluation import EvaluationService
    manifest, cases = _typed_records()
    rows = [SimpleNamespace(experiment_name="main", case_id=record.case_id,
        metrics={"resource_quality_case_v2": {"manifest": manifest.model_dump(mode="json"),
                                            "case": record.model_dump(mode="json")}}) for record in cases]
    groups, invalid_rows = EvaluationService._resource_quality(rows)
    assert groups[0].coverage.value == 1
    assert EvaluationService._resource_quality([SimpleNamespace(metrics={"coverage_rate": 1})]) == ([], 0)
    rows[0].experiment_name = "foreign"
    groups, invalid_rows = EvaluationService._resource_quality(rows)
    assert invalid_rows == 1
    assert groups[0].status == "invalid"
    assert groups[0].coverage.value is None


def test_cli_records_roundtrip_to_the_same_frozen_manifest(baseline):
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    result = aggregate_evaluation(baseline.quality_manifest, baseline.quality_case_records)
    assert result.received_case_total == result.planned_case_total == 54
    assert result.coverage.value == baseline.ordinary_coverage.metric.value
    assert result.difficulty.value == baseline.difficulty.accuracy
    assert result.hallucination.value is not None
    assert result.manifest.evidence_mode == "offline_gold"


def test_missing_offline_cases_keep_frozen_target_units(suite):
    report = evaluate_competition_metrics(_with_missing_cases(suite))
    assert report.ordinary_coverage.planned_unit_total == 54
    assert report.ordinary_coverage.planned_case_total == 54



def test_live_double_ordinary_coverage_survives_claim_failure_and_no_publication(monkeypatch, suite):
    from types import SimpleNamespace
    from app.models.learning_documents.schemas import LearningResource, LearnerProfile
    from app.services.reports import competition_suite as module
    monkeypatch.setattr(module, "is_live_ready", lambda: (True, "isolated double, no model"))
    monkeypatch.setattr(module, "_persist_learner", lambda container, plan: LearnerProfile(
        learner_id=plan.learner_id, learner_type="test", education=plan.education, major=plan.major,
        knowledge_base_id=plan.knowledge_base_id, learning_goal=plan.learning_goal, skill_level=plan.skill_level))
    stored = {}
    class Jobs:
        def create_job(self, profile, request):
            run_id = f"run-{len(stored)}"
            stored[run_id] = LearningResource(
                resource_id=f"resource-{run_id}", run_id=run_id, resource_spec_id=f"spec-{run_id}",
                resource_type=request.resource_types[0], difficulty="中级", content_text="fixture",
                knowledge_points=request.target_skill_nodes, source_refs=[], version=1,
                review_id=f"review-{run_id}", publication_status="unpublished")
            return SimpleNamespace(run_id=run_id, batch_id="test")
        def run_job(self, *args):
            pass
    class Query:
        def get_timeline(self, run_id, limit):
            return SimpleNamespace(resource_versions=[stored[run_id].model_dump()], events=[], evidence=[])
        def get_claims(self, run_id):
            return SimpleNamespace(claims=[], judgements=[])
    class Quality:
        def get_run_quality(self, run_id):
            resource = stored[run_id]
            data = {"resource_id": resource.resource_id, "run_id": run_id,
                    "resource_version": 1, "review_id": resource.review_id,
                    "claim": {"status": "failed", "counts": None}}
            item = SimpleNamespace(**{k: v for k, v in data.items() if k != "claim"},
                coverage=SimpleNamespace(status=QualityMetricStatus.COMPLETE),
                target_coverage=[SimpleNamespace(target_id=target, status="covered") for target in resource.knowledge_points],
                model_dump=lambda **kwargs: data)
            return SimpleNamespace(items=[item])
    container = SimpleNamespace(generation_job_service=lambda: Jobs(), run_query_service=lambda: Query(),
                                resource_quality_query_service=lambda: Quality())
    report = module.evaluate_live_metrics(suite, container=container)
    assert report.completed_generation_count == 0
    assert report.ordinary_coverage.metric.value == 1
    gates = {gate.metric_id: gate.status for gate in report.gates}
    assert gates["M-COVERAGE"] == "PASS"
    assert gates["M-HALLUCINATION"] == "NOT_MEASURABLE"
    assert all(gate.status == "NOT_MEASURABLE" for gate in report.official_gates)



def test_same_live_binding_is_never_multiple_independent_cases():
    from app.services.reviews.quality_evaluation import aggregate_evaluation, manifest_hash
    manifest, cases = _typed_records()
    manifest = manifest.model_copy(update={"evidence_mode": "live_model"})
    identity = manifest_hash(manifest)
    cases = [case.model_copy(update={"manifest_hash": identity, "generation_status": "completed",
             "run_id": "same", "resource_id": "same", "resource_version": 1, "review_id": "same"}) for case in cases]
    result = aggregate_evaluation(manifest, cases)
    assert result.status == "invalid"
    assert result.coverage.value is result.hallucination.value is result.difficulty.value is None



def test_bad_records_do_not_hide_an_independent_valid_group():
    from types import SimpleNamespace
    from app.services.reports.evaluation import EvaluationService
    manifest, cases = _typed_records()
    rows = [SimpleNamespace(experiment_name="main", case_id=record.case_id,
        metrics={"resource_quality_case_v2": {"manifest": manifest.model_dump(mode="json"),
                                            "case": record.model_dump(mode="json")}}) for record in cases]
    rows.append(SimpleNamespace(experiment_name="bad", case_id="bad", metrics={"resource_quality_case_v2": {"case": {}}}))
    groups, invalid = EvaluationService._resource_quality(rows)
    assert invalid == 1
    assert len(groups) == 1 and groups[0].coverage.value == 1



@pytest.mark.parametrize("generation_status", ["reference_only", "completed"])
def test_live_measurement_requires_actual_generation_and_exact_resource_binding(generation_status):
    from app.services.reviews.quality_evaluation import aggregate_evaluation, manifest_hash
    manifest, cases = _typed_records()
    manifest = manifest.model_copy(update={"evidence_mode": "live_model"})
    identity = manifest_hash(manifest)
    cases = [case.model_copy(update={"manifest_hash": identity, "generation_status": generation_status,
        "ordinary_coverage": case.ordinary_coverage.model_copy(update={"observed": False, "targets": ()})}) for case in cases]
    result = aggregate_evaluation(manifest, cases)
    assert result.status == "invalid"
    assert result.hallucination.value is result.difficulty.value is None



@pytest.mark.parametrize("field", ["expected_difficulty", "predicted_difficulty"])
@pytest.mark.parametrize("value", ["", "x" * 33])
def test_case_difficulty_labels_reject_values_the_aggregate_cannot_consume(field, value):
    from pydantic import ValidationError
    from app.models.reviews.quality_metrics import EvaluationQualityCaseV2
    _, cases = _typed_records()
    payload = cases[0].model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        EvaluationQualityCaseV2.model_validate(payload)


@pytest.mark.parametrize("field", ["expected_difficulty", "predicted_difficulty"])
def test_case_difficulty_label_32_character_boundary_is_accepted_by_aggregate(field):
    from app.models.reviews.quality_metrics import EvaluationQualityCaseV2
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    manifest, cases = _typed_records()
    payload = cases[0].model_dump(mode="json")
    payload[field] = "x" * 32
    cases[0] = EvaluationQualityCaseV2.model_validate(payload)
    result = aggregate_evaluation(manifest, cases)
    assert result.status == "complete"
    assert result.difficulty.value == .5


def test_case_null_prediction_remains_an_unproduced_result():
    from app.models.reviews.quality_metrics import EvaluationQualityCaseV2
    from app.services.reviews.quality_evaluation import aggregate_evaluation
    manifest, cases = _typed_records()
    payload = cases[0].model_dump(mode="json")
    payload.update(predicted_difficulty=None, generation_status="failed")
    cases[0] = EvaluationQualityCaseV2.model_validate(payload)
    assert aggregate_evaluation(manifest, cases).difficulty.value == .5
