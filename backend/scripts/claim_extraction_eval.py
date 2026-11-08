"""Frozen synthetic extraction policy replay; no .env, credentials or network."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node
from app.core.execution import execution_session
from app.models.shared.llm import LLMCallResult, LLMAttemptSummary, LLMUsage
from app.models.reviews.claim_extraction import content_digest
from tests.fakes.claim_extraction import (
    state_for_extraction, neutral_settings, extract_every_unit, judge_all, FixtureCounter,
)

FIXTURES = ROOT / "backend/tests/fixtures/claim_extraction"


def load_cases(manifest_path=FIXTURES / "manifest.json"):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0" or manifest.get("provenance") != "synthetic-scripted-v1":
        raise ValueError("invalid extraction fixture manifest")
    cases = []
    for record in manifest["files"]:
        path = (manifest_path.parent / record["path"]).resolve()
        if path.parent != manifest_path.parent or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("fixture path/hash mismatch")
        cases.extend(json.loads(path.read_text(encoding="utf-8")))
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("fixture IDs must be nonempty and unique")
    return manifest, cases


def run_case(case):
    settings = neutral_settings(**case.get("settings", {}))
    state, _, repo, gateway, counter = state_for_extraction(case["text"], settings=settings)
    fault = case.get("fault")
    invocations = 0
    def output(call):
        nonlocal invocations
        invocations += 1
        result = extract_every_unit(call)
        if fault == "truncated_parent" and invocations == 1:
            from app.core.llm.gateway import LLMGatewayError
            from app.core.security.errors import ErrorCode
            from app.models.shared.agent_contracts import make_error_info
            raise LLMGatewayError(error=make_error_info(ErrorCode.LLM_OUTPUT_TRUNCATED, source="claim_extractor"),
                call_id="scripted-truncation", retry_count=0, latency_ms=1, model_name="fake-model",
                attempts=[LLMAttemptSummary(attempt=1,status="failed",latency_ms=1,structured_output_mode="text",usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15))])
        if fault == "zero":
            for unit in result["units"]:
                unit.update(status="non_factual", claims=[])
        elif fault == "missing_unit":
            result["units"][0]["unit_id"] = "missing"
        elif fault == "version":
            result["resource_version"] += 1
        elif fault == "cap":
            result["units"][0]["claims"] *= 16
        elif fault == "unknown_usage":
            return LLMCallResult(output=call["output_schema"].model_validate(result), model_name="fake-model", call_id="unknown",
                structured_output_mode="text", attempt_count=1, retry_count=0, latency_ms=1,
                attempts=[LLMAttemptSummary(attempt=1, status="success", latency_ms=1, structured_output_mode="text", usage=LLMUsage())])
        return result
    gateway.outcomes = [output]*64
    if fault == "unknown_profile":
        # Historical fixture name; the current equivalent is unknown estimator
        # configuration. The frozen input and expected failure are unchanged.
        counter.parameters = counter.parameters.model_copy(update=dict(version="unknown"))
    if fault == "judge_window":
        counter.request_bound = lambda messages, schema, options: (100000000 if schema.__name__ == "ClaimJudgementLLMOutput" else 100)
    with patch("app.agents.resource_workflows.learning_documents.claim_review_agent.get_settings", lambda: settings):
        with execution_session(state["run_id"], "owner"):
            state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter))
            if state.get("extracted_claims"):
                gateway.outcomes = [judge_all]
                state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo, claim_extraction_counter=counter))
    saved = repo.get(state["run_id"])
    extract_calls = sum(c["context"].node_name == "claim_extractor" for c in gateway.calls)
    judge_calls = sum(c["context"].node_name == "claim_judge" for c in gateway.calls)
    claims = state.get("extracted_claims", [])
    targets, processed = 0, 0
    for result in saved.state.results.values():
        for batch in result.batches:
            targets += len(batch.units)
            if batch.batch_id in result.outputs:
                processed += len(result.outputs[batch.batch_id].units)
    exact_spans = all(case["text"][c["source_start"]:c["source_end"]] == c["source_text"]
                      and content_digest(c["source_text"]) == c["source_text_hash"] and c["source_evidence_ids"] == [] for c in claims)
    observed = dict(status=state["claim_check_status"], candidates=len(claims), judge_calls=judge_calls)
    errors = [f"{key}: expected {value!r}, got {observed.get(key)!r}" for key,value in case["expected"].items()
              if observed.get(key) != value]
    if not exact_spans or judge_calls > 1:
        errors.append("span or single-Judge invariant failed")
    if case.get("expected_extract_calls") is not None and extract_calls != case["expected_extract_calls"]:
        errors.append(f"extract calls expected {case['expected_extract_calls']}, got {extract_calls}")
    if fault == "unknown_usage" and any(t.usage_known or t.charged_tokens is not None for t in saved.state.tickets.values()):
        errors.append("unknown usage released budget")
    return dict(case_id=case["id"], fixture_policy_gate="FAIL" if errors else "PASS", errors=errors,
        **observed, extract_calls=extract_calls, transport_attempts=saved.state.attempts,
        charged_or_reserved_tokens=saved.state.tokens, charged_or_reserved_ms=saved.state.time_ms,
        target_units=targets, returned_units=processed, exact_spans=exact_spans,
        facts_recall="NOT_MEASURED_SCRIPTED_OUTPUT", model_calls_for_merge=0)


def evaluate(manifest_path=FIXTURES / "manifest.json"):
    manifest, cases = load_cases(manifest_path)
    records = [run_case(case) for case in cases]
    sources = [ROOT / "backend/app/agents/resource_workflows/learning_documents/claim_review_agent.py",
               ROOT / "backend/app/models/reviews/claim_extraction.py",
               *sorted((ROOT / "backend/app/agents/resource_workflows/learning_documents/claim_extraction").rglob("*.py"))]
    return dict(schema_version="1.0", fixture_policy_gate="PASS" if all(r["fixture_policy_gate"] == "PASS" for r in records) else "FAIL",
        quality_gate="NOT_RUN_OFFLINE", judge_capacity_gate="NOT_RUN_OFFLINE", live_models=False,
        provenance=manifest["provenance"], manifest_hash=hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        source_hashes={str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        cases=records, failed=sum(r["fixture_policy_gate"] != "PASS" for r in records))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=FIXTURES / "manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output must not exist")
    report = evaluate(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("fixture_policy_gate", "quality_gate", "failed")}))
    return 0 if report["fixture_policy_gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
