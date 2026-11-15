import copy
import importlib.util
import json
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[3] / "scripts/resource_review_eval.py"
spec = importlib.util.spec_from_file_location("resource_review_eval", PATH)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def config():
    return {"model_name": "offline-scripted", "context_tokens": 262144, "max_output_tokens": 16384,
            "temperature": 0.0, "max_attempts": 2, "structured_output_mode": "text", "ruleset_version": "resource-review-v2"}


@pytest.fixture(scope="module")
def normalized_quality_observations():
    manifest = evaluation.load_manifest(evaluation.DEFAULT_MANIFEST)
    observations = evaluation.evaluate(manifest, config())["observations"]
    for observation in observations:
        observation.update(total_tokens=100, wall_ms=100,
                           usage_complete={"input_tokens": True, "output_tokens": True, "total_tokens": True})
    return observations


@pytest.fixture
def quality_observations(normalized_quality_observations):
    observations = copy.deepcopy(normalized_quality_observations)
    assert evaluation.quality_gate(observations, evaluation.metrics(observations)) == "PASS"
    return observations


def test_offline_full_inventory_needs_no_credentials_settings_or_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline evaluation must not access credentials or network")
    monkeypatch.setattr("app.config.get_settings", forbidden)
    monkeypatch.setattr("app.core.retrieval.knowledge_base.get_settings", forbidden)
    monkeypatch.setattr("app.config.Settings.__init__", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    output = tmp_path / "offline.json"
    assert evaluation.main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["quality_gate"] == "NOT_RUN_OFFLINE" and report["combined_enabled"] is False
    assert report["preflight"]["max_logical_calls"] == 396
    assert report["preflight"]["max_transport_attempts"] == 792
    assert len(report["observations"]) == 288
    assert report["metrics"]["combined_v2"]["effective_detections"] == 72
    assert report["metrics"]["practice_semantic_v2"]["effective_detections"] == 36
    assert report["fixture_policy_gate"] == "PASS"
    assert evaluation.main(["--output", str(output)]) == 2  # Preserve prior evidence.


@pytest.mark.parametrize("flags", [[], ["--model-name", "deployment-model"], ["--max-seconds", "7201"], ["--max-transport-attempts", "793"], ["--max-total-tokens", "1", "--max-transport-attempts", "792", "--max-seconds", "60"]])
def test_live_and_frozen_budget_gates_reject_before_provider_construction(flags, monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before reading model settings")
    monkeypatch.setattr("app.core.llm.gateway.default_llm_gateway", forbidden)
    assert evaluation.main(["--live", "--output", str(tmp_path / "live.json"), *flags]) == 2


def test_preflight_is_stable_and_requires_all_budget_fields(tmp_path):
    manifest = evaluation.load_manifest(evaluation.DEFAULT_MANIFEST)
    first = evaluation.preflight(manifest, config(), {"max_total_tokens": None, "max_transport_attempts": None, "max_seconds": None})
    assert first == evaluation.preflight(manifest, config(), first["budget"])
    assert first["required_reserved_tokens"] > 0
    budget = {"max_total_tokens": first["required_reserved_tokens"], "max_transport_attempts": 792, "max_seconds": 7200}
    frozen = evaluation.preflight(manifest, config(), budget)
    assert frozen["preflight_hash"] != first["preflight_hash"]
    output = tmp_path / "preflight.json"
    budget_path = tmp_path / "budget.json"
    assert evaluation.main(["--preflight", "--max-total-tokens", str(budget["max_total_tokens"]), "--max-transport-attempts", "792",
        "--max-seconds", "7200", "--budget-record", str(budget_path), "--output", str(output)]) == 0
    assert json.loads(budget_path.read_text(encoding="utf-8"))["preflight_hash"] == json.loads(output.read_text(encoding="utf-8"))["preflight_hash"]


def test_metrics_use_resource_denominators_nearest_rank_and_unknown_usage():
    rows = [{"strategy": "combined_v2", "is_correct": index < 36, "primary_defect": "answer" if index >= 36 else None,
             "detected": index >= 36, "decision": "approve" if index < 36 else "revise", "wall_ms": index+1, "total_tokens": 10}
            for index in range(108)]
    report = evaluation.metrics(rows)["combined_v2"]
    assert report["bad_denominator"] == 72 and report["clean_denominator"] == 36
    assert report["p95_resource_wall_ms"] == 103
    assert report["mean_resource_tokens"] == 10
    rows[0]["total_tokens"] = None
    report = evaluation.metrics(rows)["combined_v2"]
    assert report["mean_resource_tokens"] is None and report["unknown_usage"] == 1
    assert report["known_total_tokens"] == 1070
    rows[0]["total_tokens"] = 10
    rows[0]["usage_complete"] = {"input_tokens": False, "output_tokens": False, "total_tokens": True}
    assert evaluation.metrics(rows)["combined_v2"]["unknown_usage"] == 1


def test_missing_or_invalid_observation_cannot_pass_quality_gate():
    manifest = evaluation.load_manifest(evaluation.DEFAULT_MANIFEST)
    observations = evaluation.evaluate(manifest, config())["observations"]
    observations[0]["invalid"] = True
    assert evaluation.quality_gate(observations, evaluation.metrics(observations)) == "INCOMPLETE"
    observations[0]["invalid"] = False
    observations[0]["total_tokens"] = None
    assert evaluation.quality_gate(observations, evaluation.metrics(observations)) == "INCONCLUSIVE_USAGE"
    assert evaluation.quality_gate(observations[:-1], evaluation.metrics(observations[:-1])) == "INCOMPLETE"
    copy_rows = copy.deepcopy(observations)
    bad = next(o for o in copy_rows if not o["is_correct"] and o["strategy"] == "combined_v2")
    bad["decision"] = "approve"
    assert evaluation.quality_gate(copy_rows, evaluation.metrics(copy_rows)) == "FAIL_CRITICAL_APPROVAL"


def test_baseline_critical_miss_is_reported_but_does_not_block_candidate(quality_observations):
    baseline_bad = next(o for o in quality_observations if o["strategy"] == "two_stage_v1" and not o["is_correct"])
    baseline_bad.update(decision="approve", detected=False)

    summary = evaluation.metrics(quality_observations)
    assert summary["two_stage_v1"]["critical_approvals"] == 1
    assert summary["two_stage_v1"]["effective_detections"] == 71
    assert summary["combined_v2"]["critical_approvals"] == 0
    assert summary["combined_v2"]["effective_detections"] == 72
    defect = baseline_bad["primary_defect"]
    assert summary["two_stage_v1"]["defects"][defect]["effective_detections"] == 11
    assert summary["combined_v2"]["defects"][defect]["effective_detections"] == 12
    assert evaluation.quality_gate(quality_observations, summary) == "PASS"


def test_candidate_critical_miss_blocks_even_when_baseline_also_misses(quality_observations):
    baseline_bad = next(o for o in quality_observations if o["strategy"] == "two_stage_v1" and not o["is_correct"])
    candidate_bad = next(o for o in quality_observations if o["strategy"] == "combined_v2"
                         and (o["case_id"], o["repeat_index"]) == (baseline_bad["case_id"], baseline_bad["repeat_index"]))
    baseline_bad.update(decision="approve", detected=False)
    candidate_bad.update(decision="approve", detected=False)

    summary = evaluation.metrics(quality_observations)
    for strategy in ("two_stage_v1", "combined_v2"):
        assert summary[strategy]["critical_approvals"] == 1
        assert summary[strategy]["effective_detections"] == 71
    assert evaluation.quality_gate(quality_observations, summary) == "FAIL_CRITICAL_APPROVAL"


def test_practice_critical_miss_still_blocks_quality_gate(quality_observations):
    practice_bad = next(o for o in quality_observations if o["strategy"] == "practice_semantic_v2" and not o["is_correct"])
    practice_bad.update(decision="approve", detected=False)

    summary = evaluation.metrics(quality_observations)
    assert summary["combined_v2"]["effective_detections"] == 72
    assert summary["practice_semantic_v2"]["critical_approvals"] == 1
    assert summary["practice_semantic_v2"]["effective_detections"] == 35
    assert evaluation.quality_gate(quality_observations, summary) == "FAIL_CRITICAL_APPROVAL"


@pytest.mark.parametrize("baseline_miss", [False, True], ids=["baseline_detects_all", "baseline_misses_one"])
@pytest.mark.parametrize(("failure", "expected"), [
    ("missing_observation", "INCOMPLETE"),
    ("invalid_output", "INCOMPLETE"),
    ("candidate_detection", "FAIL_CRITICAL_DETECTION"),
    ("practice_detection", "FAIL_CRITICAL_DETECTION"),
    ("false_rejection", "FAIL_QUALITY"),
    ("unknown_usage", "INCONCLUSIVE_USAGE"),
    ("incomplete_usage", "INCONCLUSIVE_USAGE"),
    ("resource_cost", "FAIL_COST_OR_LATENCY"),
    ("p95_latency", "FAIL_COST_OR_LATENCY"),
    ("logical_calls", "FAIL_CALL_COUNT"),
])
def test_other_quality_gates_remain_blocking_with_or_without_baseline_miss(quality_observations, baseline_miss, failure, expected):
    if baseline_miss:
        baseline_bad = next(o for o in quality_observations if o["strategy"] == "two_stage_v1" and not o["is_correct"])
        baseline_bad.update(decision="approve", detected=False)
    candidate_clean = next(o for o in quality_observations if o["strategy"] == "combined_v2" and o["is_correct"])
    baseline_clean = next(o for o in quality_observations if o["strategy"] == "two_stage_v1" and o["is_correct"])
    if failure == "missing_observation":
        quality_observations.pop()
    elif failure == "invalid_output":
        candidate_clean["invalid"] = True
    elif failure in ("candidate_detection", "practice_detection"):
        strategy = "combined_v2" if failure == "candidate_detection" else "practice_semantic_v2"
        bad = next(o for o in quality_observations if o["strategy"] == strategy and not o["is_correct"])
        bad["detected"] = False
    elif failure == "false_rejection":
        candidate_clean["decision"] = "revise"
    elif failure == "unknown_usage":
        baseline_clean["total_tokens"] = None
    elif failure == "incomplete_usage":
        baseline_clean["usage_complete"]["input_tokens"] = False
    elif failure == "resource_cost":
        candidate_clean["total_tokens"] = 101
    elif failure == "p95_latency":
        for observation in quality_observations:
            if observation["strategy"] == "combined_v2":
                observation["wall_ms"] = 101
    elif failure == "logical_calls":
        candidate_clean["logical_call_count"] = 2
    assert evaluation.quality_gate(quality_observations, evaluation.metrics(quality_observations)) == expected


def test_live_freeze_mismatch_is_checked_with_complete_valid_budget_before_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen mismatch must precede provider settings")
    monkeypatch.setattr("app.core.llm.gateway.default_llm_gateway", forbidden)
    manifest = evaluation.load_manifest(evaluation.DEFAULT_MANIFEST)
    selected = dict(config(), model_name="deployment-model")
    unbudgeted = evaluation.preflight(manifest, selected, {"max_total_tokens": None, "max_transport_attempts": None, "max_seconds": None})
    budget = {"max_total_tokens": unbudgeted["required_reserved_tokens"], "max_transport_attempts": 792, "max_seconds": 7200}
    frozen = evaluation.preflight(manifest, selected, budget)
    record, budget_path = tmp_path / "frozen.json", tmp_path / "budget.json"
    record.write_text(json.dumps(frozen), encoding="utf-8")
    budget_path.write_text(json.dumps({"preflight_hash": "tampered", "budget": budget}), encoding="utf-8")
    args = ["--live", "--model-name", "deployment-model", "--context-tokens", "262144", "--preflight-report", str(record),
            "--budget-record", str(budget_path), "--max-total-tokens", str(budget["max_total_tokens"]),
            "--max-transport-attempts", "792", "--max-seconds", "7200", "--output", str(tmp_path / "live.json")]
    assert evaluation.main(args) == 2
    budget_path.write_text(json.dumps({"preflight_hash": frozen["preflight_hash"], "budget": budget}), encoding="utf-8")
    frozen["config_hash"] = "tampered"
    record.write_text(json.dumps(frozen), encoding="utf-8")
    assert evaluation.main(args) == 2


def test_runtime_budget_stops_new_calls_without_fabricating_an_observation():
    from app.agents.resource_workflows.learning_documents.reviewing import ReviewAuditInput, build_review_prompt, build_review_request, resolve_review_profile
    from app.models.shared.llm import LLMCallContext
    from tests.fakes.resource_reviews import approve, state_for
    state = state_for()
    profile = resolve_review_profile(resource_type="实操指南", phase="practice_semantic_v2")
    request = build_review_request(profile=profile, prompt_bundle=build_review_prompt(profile=profile),
        audit_input=ReviewAuditInput(resource=state["generated_resources"][0]))
    raw = evaluation.FixtureGateway([approve()], config())
    gateway = evaluation.BudgetedGateway(raw, config(), {"max_total_tokens": 1, "max_transport_attempts": 2, "max_seconds": 60})
    with pytest.raises(evaluation.BudgetExhausted):
        gateway.invoke_structured(messages=list(request.messages), output_schema=profile.output_schema,
            context=LLMCallContext(run_id="budget", step_id="step", node_name="reviewer", schema_name="ReviewLLMOutput"),
            options=raw.options_for("reviewer"))
    assert len(raw.outputs) == 1 and gateway.logical_calls == 0


def test_preparation_defect_annotation_points_to_preparation_phase():
    manifest = evaluation.load_manifest(evaluation.DEFAULT_MANIFEST)
    preparation = [c for c in manifest["cases"] if c["case_id"].startswith("practice.bad.preparation.")]
    assert len(preparation) == 3
    for sample in preparation:
        assert sample["location"]["step_id"] == "prepare"
        assert "prepare" in sample["offline_outputs"]["practice_semantic_v2"][0]["issues"][0]["description"]
