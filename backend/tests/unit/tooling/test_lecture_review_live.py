"""Tooling tests for the T38 live acceptance adapter; no network, no model calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import SystemMessage
from pydantic import BaseModel

import scripts.lecture_review_live as live
from app.models.shared.llm import LLMUsage, RawLLMResponse, StructuredOutputMode


class _Output(BaseModel):
    ok: bool = True


class _FakeInner:
    model_name = "fake-model"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def invoke(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("transport down")
        return RawLLMResponse(
            content={"ok": True}, usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            provider_request_id="req-1", finish_reason="stop",
            structured_output_mode=StructuredOutputMode.JSON_MODE,
        )


def _sample(sample_id: str, split: str) -> live.Sample:
    return live.Sample(
        sample_id=sample_id, group_id="g", split=split, task_type="lecture_initial",
        origin="synthetic", strata={}, payload={}, input_hash="0" * 64,
    )


def _row(*, observation_id: str, sample_id: str, variant: str, actual: str, expected: str = "approve",
         closure: bool | None = None, suggestion: bool | None = None, fabrication: bool = False,
         unfounded: bool = False) -> dict:
    return {
        "observation_id": observation_id, "sample_id": sample_id, "variant_id": variant,
        "repeat_index": 1, "status": "success", "valid": True, "expected": expected, "actual": actual,
        "decision_correct": actual == expected, "closure_results": ["fixed"] if closure is not None else [],
        "expected_closures": ["fixed"] if closure is not None else [], "closure_correct": closure,
        "false_block": expected == "approve" and actual != "approve",
        "released_error": expected == "block" and actual == "approve",
        "fabrication_demand": fabrication, "unfounded_closure": unfounded,
        "suggestion_evidence_bound": suggestion, "new_defect_detected": None,
        "physical_attempts": 1, "input_tokens": 100, "output_tokens": 20, "end_to_end_ms": 1000,
        "note": "",
    }


def test_recording_transport_keeps_exact_messages_and_provider_response():
    recorder = live.RecordingTransport(_FakeInner())
    raw = recorder.invoke(messages=[SystemMessage(content="sys")], output_schema=_Output,
                          mode=StructuredOutputMode.JSON_MODE, timeout_seconds=10,
                          temperature=0.0, max_output_tokens=128)
    assert raw.content == {"ok": True}
    attempt = recorder.attempts[0]
    assert attempt["messages"] == [{"role": "system", "content": "sys"}]
    assert attempt["response_content"] == {"ok": True}
    assert attempt["usage"]["input_tokens"] == 10
    assert "authorization" not in json.dumps(attempt).lower()


def test_recording_transport_keeps_failure_without_usage():
    recorder = live.RecordingTransport(_FakeInner(fail=True))
    with pytest.raises(RuntimeError):
        recorder.invoke(messages=[], output_schema=_Output, mode=StructuredOutputMode.TEXT,
                        timeout_seconds=1, temperature=0.0, max_output_tokens=8)
    assert recorder.attempts[0]["status"] == "error"
    assert "usage" not in recorder.attempts[0]


def test_budget_reserves_settles_and_never_records_unknown_as_zero(tmp_path: Path):
    store = live.RunStore(tmp_path)
    store.reserve(phase="formal", tokens=1000)
    assert store.budget["reserved_logical"] == 1
    store.settle(phase="formal", physical_attempts=2, input_tokens=None, output_tokens=None,
                 unknown=True, reservation_tokens=1000)
    assert store.budget["logical_used"] == 1 and store.budget["formal_used"] == 1
    assert store.budget["physical_attempts"] == 2
    assert store.budget["input_tokens"] == 0 and store.budget["unknown_usage_calls"] == 1
    store.reserve(phase="formal", tokens=1000)
    with pytest.raises(ValueError):
        store.reserve(phase="formal", tokens=1000)
    store.settle(phase="formal", physical_attempts=1, input_tokens=10, output_tokens=5,
                 unknown=False, reservation_tokens=1000)
    assert store.budget["input_tokens"] == 10 and store.budget["logical_used"] == 2


def test_budget_recovers_unsettled_reservation_as_unknown(tmp_path: Path):
    store = live.RunStore(tmp_path)
    store.budget["reserved_logical"] = 1
    store._flush_budget()
    assert store._recover_incomplete() is True
    assert store.budget["logical_used"] == 1 and store.budget["unknown_usage_calls"] == 1
    assert store.budget["reserved_logical"] == 0


def test_token_ceiling_and_formal_cap_fail_closed(tmp_path: Path):
    store = live.RunStore(tmp_path)
    with pytest.raises(ValueError):
        store.reserve(phase="formal", tokens=live.MAX_TOTAL_TOKENS + 1)
    store.budget["formal_used"] = live.FORMAL_LOGICAL_CALLS
    store._flush_budget()
    with pytest.raises(ValueError):
        store.reserve(phase="formal", tokens=100)


def test_matrix_is_interleaved_and_complete():
    samples = [_sample(f"E{i}", "evaluation") for i in range(1, 7)]
    samples.append(_sample("S0", "calibration"))
    matrix = live._matrix(samples)
    assert len(matrix) == 24
    assert [item["strategy"] for item in matrix[:2]] == [live.NEW_STRATEGY, live.LEGACY_STRATEGY]
    assert [item["strategy"] for item in matrix[12:14]] == [live.LEGACY_STRATEGY, live.NEW_STRATEGY]
    assert [item["sample"].sample_id for item in matrix[:12:2]] == [f"E{i}" for i in range(1, 7)]
    assert [item["sample"].sample_id for item in matrix[12::2]] == [f"E{i}" for i in range(1, 7)]
    assert {item["repeat"] for item in matrix[:12]} == {1} and {item["repeat"] for item in matrix[12:]} == {2}
    assert [item["order"] for item in matrix] == list(range(1, 25))
    assert all(item["sample"].split == "evaluation" for item in matrix)


def test_criteria_pass_only_when_all_frozen_thresholds_hold():
    rows = []
    for variant in (live.NEW_STRATEGY, live.LEGACY_STRATEGY):
        for repeat in (1, 2):
            rows.append(_row(observation_id=f"{live.SAMPLE_CORRECT}-{variant}-{repeat}",
                             sample_id=live.SAMPLE_CORRECT, variant=variant, actual="approve"))
            rows.append(_row(observation_id=f"{live.SAMPLE_MISSING}-{variant}-{repeat}",
                             sample_id=live.SAMPLE_MISSING, variant=variant, actual="revise",
                             expected="block", suggestion=True))
            rows.append(_row(observation_id=f"{live.SAMPLE_FIXED}-{variant}-{repeat}",
                             sample_id=live.SAMPLE_FIXED, variant=variant, actual="approve",
                             closure=True if variant == live.NEW_STRATEGY else None))
            rows.append(_row(observation_id=f"{live.SAMPLE_FALSE_POSITIVE}-{variant}-{repeat}",
                             sample_id=live.SAMPLE_FALSE_POSITIVE, variant=variant, actual="approve",
                             closure=True if variant == live.NEW_STRATEGY else None))
    criteria = live._criteria(rows, [])
    assert all(item["met"] for item in criteria)

    rows[0]["actual"] = "revise"  # correct sample blocked by the new strategy
    rows[0]["false_block"] = True
    rows[0]["decision_correct"] = False
    failed = {item["id"]: item["met"] for item in live._criteria(rows, [])}
    assert failed["correct_2_of_2_approve"] is False
    assert failed["new_false_blocks_not_above_legacy"] is False


def test_criteria_zero_tolerance_metrics_and_closure_threshold():
    rows = []
    for variant in (live.NEW_STRATEGY, live.LEGACY_STRATEGY):
        for repeat in (1, 2):
            rows.append(_row(observation_id=f"a-{variant}-{repeat}", sample_id=live.SAMPLE_CORRECT,
                             variant=variant, actual="approve"))
            rows.append(_row(observation_id=f"b-{variant}-{repeat}", sample_id=live.SAMPLE_MISSING,
                             variant=variant, actual="revise", expected="block", suggestion=True))
            rows.append(_row(observation_id=f"c-{variant}-{repeat}", sample_id=live.SAMPLE_FIXED,
                             variant=variant, actual="approve",
                             closure=True if variant == live.NEW_STRATEGY else None))
            rows.append(_row(observation_id=f"d-{variant}-{repeat}", sample_id=live.SAMPLE_FALSE_POSITIVE,
                             variant=variant, actual="approve",
                             closure=True if variant == live.NEW_STRATEGY else None))
    rows[8]["fabrication_demand"] = True
    rows[9]["unfounded_closure"] = True
    criteria = {item["id"]: item for item in live._criteria(rows, [])}
    assert criteria["zero_fabrication_demand"]["met"] is False
    assert criteria["zero_unfounded_closure"]["met"] is False

    for row in rows:
        if row["sample_id"] == live.SAMPLE_FIXED and row["variant_id"] == live.NEW_STRATEGY:
            row["closure_correct"] = False
    criteria = {item["id"]: item for item in live._criteria(rows, [])}
    assert criteria["closure_at_least_3_of_4"]["met"] is False


def test_finalize_rejects_missing_or_unknown_adjudication(tmp_path: Path):
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    observations = []
    labels = []
    for index in range(6):
        for variant in (live.NEW_STRATEGY, live.LEGACY_STRATEGY):
            for repeat in (1, 2):
                sample_id = f"E{index + 1}"
                observations.append({
                    "observation_id": f"{sample_id}-{variant}-r{repeat}", "sample_id": sample_id,
                    "variant_id": variant, "repeat_index": repeat, "status": "success",
                    "result_summary": {"decision": "approve", "resolutions": []},
                    "end_to_end_ms": 1000,
                })
        labels.append({"label_id": sample_id, "sample_id": sample_id, "split": "evaluation"})
    (run_dir / "run.json").write_text(json.dumps({"run_id": live.RUN_ID, "status": "COMPLETED"}), encoding="utf-8")
    (run_dir / "observations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in observations) + "\n", encoding="utf-8")
    (run_dir / "calls.jsonl").write_text("", encoding="utf-8")
    (run_dir / "artifacts" / "labels.jsonl").write_text(
        "\n".join(json.dumps(item) for item in labels) + "\n", encoding="utf-8")

    adjudication = {"schema_version": "1.0", "rubric_version": live.ADJUDICATION_VERSION, "observations": {}}
    path = tmp_path / "adjudication.json"
    path.write_text(json.dumps(adjudication), encoding="utf-8")
    with pytest.raises(ValueError, match="missing observations"):
        live.finalize(run_dir=run_dir, adjudication_path=path, analysis_dir=tmp_path / "analysis")

    adjudication["observations"] = {f"E1-{live.NEW_STRATEGY}-r1": {"decision_correct": True}}
    path.write_text(json.dumps(adjudication), encoding="utf-8")
    with pytest.raises(ValueError, match="missing observations"):
        live.finalize(run_dir=run_dir, adjudication_path=path, analysis_dir=tmp_path / "analysis2")


def _write_scored_run(run_dir: Path, *, invalid_new_missing: bool) -> None:
    """Write a complete 24-observation run whose only defect is the E2 new arm."""
    plan = [
        (live.SAMPLE_CORRECT, "approve", "approve", [], []),
        (live.SAMPLE_MISSING, "block", "revise", [], []),
        (live.SAMPLE_FIXED, "approve", "approve", ["fixed"], ["fixed"]),
        (live.SAMPLE_FALSE_POSITIVE, "approve", "approve", ["false_positive"], ["false_positive"]),
        ("E5_out_of_evidence_requirement", "approve", "approve", ["false_positive"], ["false_positive"]),
        ("E6_fixed_but_new_factual_error", "block", "revise", ["fixed"], ["fixed"]),
    ]
    (run_dir / "artifacts").mkdir(parents=True)
    observations, labels, calls = [], [], []
    for sample_id, expected, actual, expected_old, results in plan:
        for variant in (live.NEW_STRATEGY, live.LEGACY_STRATEGY):
            for repeat in (1, 2):
                observation_id = f"{sample_id}-{variant}-r{repeat}"
                status, decision = "success", actual
                if invalid_new_missing and sample_id == live.SAMPLE_MISSING and variant == live.NEW_STRATEGY:
                    status, decision = "invalid_contract", "human_review"
                observations.append({
                    "observation_id": observation_id, "sample_id": sample_id, "variant_id": variant,
                    "repeat_index": repeat, "status": status, "end_to_end_ms": 1000,
                    "result_summary": {"decision": decision, "resolutions": [
                        {"issue_id": f"li-{sample_id}", "result": item} for item in results
                        if variant == live.NEW_STRATEGY]},
                })
                calls.append({"observation_id": observation_id, "input_tokens": 100, "output_tokens": 20})
        labels.append({"label_id": sample_id, "sample_id": sample_id, "split": "evaluation",
                       "expected_decision": expected, "expected_old_results": expected_old})
    (run_dir / "run.json").write_text(json.dumps({"run_id": live.RUN_ID, "status": "COMPLETED"}), encoding="utf-8")
    (run_dir / "observations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in observations) + "\n", encoding="utf-8")
    (run_dir / "calls.jsonl").write_text(
        "\n".join(json.dumps(item) for item in calls) + "\n", encoding="utf-8")
    (run_dir / "artifacts" / "labels.jsonl").write_text(
        "\n".join(json.dumps(item) for item in labels) + "\n", encoding="utf-8")


def _verdicts_for(run_dir: Path, *, invalid_new_missing: bool) -> dict:
    verdicts = {}
    for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines():
        observation = json.loads(line)
        sample_id, variant = observation["sample_id"], observation["variant_id"]
        invalid = invalid_new_missing and sample_id == live.SAMPLE_MISSING and variant == live.NEW_STRATEGY
        verdicts[observation["observation_id"]] = {
            "decision_correct": not invalid,
            "closure_correct": True if (variant == live.NEW_STRATEGY and sample_id in {
                live.SAMPLE_FIXED, live.SAMPLE_FALSE_POSITIVE, "E5_out_of_evidence_requirement",
                "E6_fixed_but_new_factual_error"}) else None,
            "fabrication_demand": False, "unfounded_closure": False,
            "suggestion_evidence_bound": True if sample_id in {
                live.SAMPLE_MISSING, "E6_fixed_but_new_factual_error"} else None,
            "new_defect_detected": True if sample_id == "E6_fixed_but_new_factual_error" else None,
            "notes": "synthetic fixture",
        }
    return verdicts


def test_finalize_maps_block_labels_and_counts_invalid_contract(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_scored_run(run_dir, invalid_new_missing=False)
    adjudication = {"schema_version": "1.0", "rubric_version": live.ADJUDICATION_VERSION,
                    "observations": _verdicts_for(run_dir, invalid_new_missing=False)}
    path = tmp_path / "adjudication.json"
    path.write_text(json.dumps(adjudication), encoding="utf-8")
    analysis = live.finalize(run_dir=run_dir, adjudication_path=path, analysis_dir=tmp_path / "clean")
    rates = {(item["variant_id"], item["metric_id"]): item for item in analysis["metrics"]}
    # revise/human_review must count as the frozen "block" expectation, never as a mismatch.
    assert rates[(live.NEW_STRATEGY, "decision_correct_rate")]["value"] == 1.0
    assert rates[(live.LEGACY_STRATEGY, "decision_correct_rate")]["value"] == 1.0
    closure = rates[(live.NEW_STRATEGY, "closure_correct_rate")]
    assert closure["value"] == 1.0 and closure["n_planned"] == 8 and closure["n_failed"] == 0
    assert analysis["status"] == "PASS"

    broken = tmp_path / "broken"
    _write_scored_run(broken, invalid_new_missing=True)
    adjudication["observations"] = _verdicts_for(broken, invalid_new_missing=True)
    path.write_text(json.dumps(adjudication), encoding="utf-8")
    analysis = live.finalize(run_dir=broken, adjudication_path=path, analysis_dir=tmp_path / "broken-analysis")
    rates = {(item["variant_id"], item["metric_id"]): item for item in analysis["metrics"]}
    assert rates[(live.LEGACY_STRATEGY, "decision_correct_rate")]["value"] == 1.0
    new_rate = rates[(live.NEW_STRATEGY, "decision_correct_rate")]
    assert new_rate["value"] == 1.0 and new_rate["n_valid"] == 10 and new_rate["n_failed"] == 2
    fabrication = rates[(live.NEW_STRATEGY, "fabrication_demand_count")]
    assert (fabrication["n_planned"], fabrication["n_attempted"], fabrication["n_valid"],
            fabrication["n_failed"]) == (12, 12, 10, 2)
    scores = [json.loads(line) for line in
              (tmp_path / "broken-analysis" / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
    legacy_closure = [item for item in scores if item["metric_id"] == "closure_correct"
                      and item["variant_id"] == live.LEGACY_STRATEGY]
    assert legacy_closure and all(item["valid"] is False
                                  and item["missing_reason"] == "not_applicable_legacy_or_initial"
                                  for item in legacy_closure)
    invalid = [item for item in scores
               if item["observation_id"] == f"{live.SAMPLE_MISSING}-{live.NEW_STRATEGY}-r1"]
    assert invalid and all(item["valid"] is False and item["missing_reason"] == "invalid_observation"
                           for item in invalid)
    assert {item["scorer"]["version"] for item in scores} == {live.SCORER_VERSION} == {"t38-live-score-v2"}
    assert analysis["status"] == "FAIL"
    criteria = {item["id"]: item["met"] for item in analysis["criteria"]}
    assert criteria["missing_input_2_of_2_block_executable"] is False
    assert criteria["closure_at_least_3_of_4"] is True


def test_policy_contract_is_frozen():
    policy, dumped, digest = live.policy_contract()
    assert policy.context_tokens == 129_024 and policy.max_output_tokens == 12_288
    assert digest == live.canonical_hash(dumped)
