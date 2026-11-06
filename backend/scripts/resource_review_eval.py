"""Frozen resource review comparison. Default is credential-free scripted policy QA."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
from time import monotonic
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.reviewing import (
    ReviewAuditInput, build_review_prompt, build_review_request, check_resource_structure,
    resolve_review_profile, select_specialties,
)
from app.agents.resource_workflows.learning_documents.reviewing.payloads import estimate_review_input
from app.agents.resource_workflows.learning_documents.specialized_reviews.assessment_scope import assessment_catalog_snapshot, prepare_assessment_scope
from app.agents.shared.evidence_scope import validate_payload_evidence
from app.core.retrieval.evidence import source_refs_are_scoped
from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.review_audit import ReviewPolicySnapshotV1
from app.models.shared.agent_contracts import AssessmentPackageV2, PracticeGuidePackageV3
from app.models.shared.llm import LLMAttemptSummary, LLMCallOptions, LLMCallResult, LLMUsage, StructuredOutputMode
from app.models.shared.persistence import canonical_hash


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "tests/fixtures/resource_reviews/manifest.json"
MAX_LOGICAL_CALLS = 396
MAX_TRANSPORT_ATTEMPTS = 792
MAX_SECONDS = 7200


def _retry_input_margin(schema):
    # Gateway repair serializes at most 12000 Unicode characters (<=48000 bytes),
    # plus another schema and bounded repair/recovery instructions. TEXT mode's
    # normal schema is already included in the base estimate.
    return 48000 + len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) + 2048


def _expected_case_ids():
    return ({f"assessment.clean.{i:02}" for i in range(1, 13)}
            | {f"assessment.bad.{d}.{i:02}" for d in ("scope", "evidence", "answer", "clarity", "rubric", "package") for i in range(1, 5)}
            | {f"practice.clean.{i:02}" for i in range(1, 13)}
            | {f"practice.bad.{d}.{i:02}" for d in ("preparation", "sequence", "fact", "verification") for i in range(1, 4)})


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if (manifest["schema_version"] != "1.0" or manifest["ruleset_version"] != "resource-review-v2"
            or manifest["repetitions"] != 3 or len(cases) != 60
            or {c["case_id"] for c in cases} != _expected_case_ids()):
        raise ValueError("frozen manifest inventory invalid")
    for sample in cases:
        resource = LearningResource.model_validate(sample["resource"])
        if sample["is_correct"] == sample["critical_for_gate"] or bool(sample["primary_defect"]) == sample["is_correct"]:
            raise ValueError("frozen case annotation invalid")
        if sample["resource_type"] != resource.resource_type or check_resource_structure(resource=resource) is not None:
            raise ValueError("semantic fixture failed structural hard gate")
        package = resource.assessment_payload or resource.practice_guide_payload
        schema = AssessmentPackageV2 if resource.assessment_payload else PracticeGuidePackageV3
        schema.model_validate({k: v for k, v in package.items() if k != "payload_hash"})
        if package["payload_hash"] != canonical_hash({k: v for k, v in package.items() if k != "payload_hash"}):
            raise ValueError("frozen payload hash invalid")
        evidence = [EvidenceItem.model_validate_json(json.dumps(e)) for e in sample["evidence"]]
        if not source_refs_are_scoped(resource.source_refs, evidence):
            raise ValueError("frozen resource source provenance invalid")
        validate_payload_evidence(resource, evidence)
        if set(sample["catalog_nodes"]) != set(sample["target_skill_nodes"]):
            raise ValueError("frozen catalog inventory invalid")
        prefix, index = sample["case_id"].rsplit(".", 1)
        if resource.assessment_payload:
            expected_nodes = 1 if int(index) <= (6 if sample["is_correct"] else 2) else 2
            if len(package["node_blocks"]) != expected_nodes:
                raise ValueError("frozen assessment node balance invalid")
        elif bool(package["practice"]["steps"][0]["code_blocks"]) != sample["has_code"]:
            raise ValueError("frozen practice code annotation invalid")
        if not sample["is_correct"] and not sample["expected_findings"]:
            raise ValueError("frozen expected findings missing")
    practice = [c for c in cases if c["resource_type"] == "实操指南"]
    if any(sum(c["has_code"] for c in practice if c["is_correct"] == correct) != 6 for correct in (True, False)):
        raise ValueError("frozen practice balance invalid")
    return manifest


def _state(sample, strategy, config):
    selected = "combined_v2" if strategy == "combined_v2" else "two_stage_v1"
    return {"run_id": f"eval:{sample['case_id']}", "batch_id": "frozen-eval", "trace": [], "errors": [],
            "generated_resources": [LearningResource.model_validate(sample["resource"])],
            "retrieved_evidence": [EvidenceItem.model_validate_json(json.dumps(e)) for e in sample["evidence"]],
            "target_skill_nodes": sample["target_skill_nodes"], "difficulty_preference": "初级", "constraints": {},
            "generation_attempt": 1, "revision_count": 0,
            "review_policy": ReviewPolicySnapshotV1(assessment_strategy=selected,
                combined_context_tokens=config["context_tokens"] if selected == "combined_v2" else None,
                combined_max_output_tokens=config["max_output_tokens"]).model_dump(mode="json")}


def _requests(sample, strategy, config):
    state = _state(sample, strategy, config)
    resource, evidence = state["generated_resources"][0], state["retrieved_evidence"]
    policy = ReviewPolicySnapshotV1.model_validate(state["review_policy"])
    if strategy == "practice_semantic_v2":
        phases = [strategy]
        scope_payload = None
    else:
        phases = ["assessment_combined_v2"] if strategy == "combined_v2" else ["assessment_scope_v1", "assessment_package_v1"]
        with assessment_catalog_snapshot(sample["catalog_nodes"]):
            scope_payload, _, _ = prepare_assessment_scope(resource=resource, evidence=evidence, target_skill_nodes=sample["target_skill_nodes"])
        if strategy == "combined_v2":
            scope_payload = {**scope_payload, "assessment_package": resource.assessment_payload,
                             "target_skill_nodes": list(sample["target_skill_nodes"]), "difficulty": resource.difficulty}
    requests = []
    for phase in phases:
        profile = resolve_review_profile(resource_type=resource.resource_type, phase=phase, policy=policy)
        request = build_review_request(profile=profile,
            prompt_bundle=build_review_prompt(profile=profile, enabled_specialties=select_specialties(profile=profile, resource=resource)),
            audit_input=ReviewAuditInput(resource=resource, evidence=tuple(evidence), difficulty="初级", scope_payload=scope_payload, policy=policy))
        estimate = estimate_review_input(request=request)
        requests.append({"phase": phase, "input_estimate": estimate,
                         "retry_input_estimate": estimate + _retry_input_margin(profile.output_schema.model_json_schema()),
                         "output_budget": request.max_output_tokens or config["max_output_tokens"],
                         "prompt_fingerprint": request.prompt_bundle.fingerprint})
    return requests


def preflight(manifest, config, budget):
    inventory = []
    for sample in manifest["cases"]:
        strategies = ("two_stage_v1", "combined_v2") if sample["resource_type"] == "分阶测试题" else ("practice_semantic_v2",)
        for strategy in strategies:
            requests = _requests(sample, strategy, config)
            for request in requests:
                if strategy == "combined_v2" and request["input_estimate"] + request["output_budget"] > config["context_tokens"]:
                    raise ValueError("preflight combined input_budget exceeded")
            inventory.append({"case_id": sample["case_id"], "strategy": strategy, "repetitions": 3, "requests": requests})
    calls = sum(len(row["requests"]) * 3 for row in inventory)
    reserved = sum((r["input_estimate"] + r["retry_input_estimate"] + r["output_budget"] * 2) * 3 for row in inventory for r in row["requests"])
    report = {"schema_version": "1.0", "mode": "preflight_offline", "manifest_hash": canonical_hash(manifest),
              "config": config, "config_hash": canonical_hash(config), "inventory": inventory,
              "expected_observations": 288, "max_logical_calls": calls, "max_transport_attempts": calls * 2,
              "required_reserved_tokens": reserved, "budget": budget}
    if calls != MAX_LOGICAL_CALLS:
        raise ValueError("preflight call inventory invalid")
    report["preflight_hash"] = canonical_hash(report)
    return report


class FixtureGateway:
    """Scripted policy evidence, never a model-quality measurement."""
    def __init__(self, outputs, config):
        self.outputs = copy.deepcopy(outputs)
        self.config = config

    def options_for(self, role, *, temperature=0.0):
        return LLMCallOptions(temperature=temperature, max_attempts=2, max_output_tokens=self.config["max_output_tokens"], structured_output_mode="text")

    def invoke_structured(self, *, messages, output_schema, context, options):
        if not self.outputs:
            raise ValueError("offline scripted call inventory exhausted")
        output = output_schema.model_validate(self.outputs.pop(0))
        usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        return LLMCallResult(output=output, call_id=context.call_id, model_name="offline-scripted",
            structured_output_mode="text", attempt_count=1, retry_count=0, latency_ms=1, usage=usage,
            attempts=[LLMAttemptSummary(attempt=1, status="success", latency_ms=1, structured_output_mode="text", usage=usage)])


class BudgetExhausted(RuntimeError):
    pass


class BudgetedGateway:
    def __init__(self, gateway, config, budget):
        self.gateway, self.config, self.budget = gateway, config, budget
        self.reserved_tokens = self.reserved_attempts = self.logical_calls = 0
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=budget["max_seconds"])

    def options_for(self, role, *, temperature=0.0):
        return self.gateway.options_for(role, temperature=temperature).model_copy(update={
            "max_attempts": 2, "max_output_tokens": self.config["max_output_tokens"],
            "structured_output_mode": StructuredOutputMode(self.config["structured_output_mode"])})

    def invoke_structured(self, **kwargs):
        options = kwargs["options"]
        material = {"messages": [{"role": m.type, "content": m.content} for m in kwargs["messages"]],
                    "schema": kwargs["output_schema"].model_json_schema()}
        estimate = len(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) + 1024
        reserve = estimate * 2 + _retry_input_margin(kwargs["output_schema"].model_json_schema()) + options.max_output_tokens * 2
        remaining = (self.deadline - datetime.now(timezone.utc)).total_seconds()
        if (remaining <= 0 or self.logical_calls >= MAX_LOGICAL_CALLS
                or self.reserved_tokens + reserve > self.budget["max_total_tokens"]
                or self.reserved_attempts + 2 > self.budget["max_transport_attempts"]):
            raise BudgetExhausted("INCOMPLETE_BUDGET")
        self.reserved_tokens += reserve
        self.reserved_attempts += 2
        self.logical_calls += 1
        current = kwargs["context"].workflow_deadline_at
        kwargs["context"] = kwargs["context"].model_copy(update={"workflow_deadline_at": min(current, self.deadline) if current else self.deadline})
        kwargs["options"] = options.model_copy(update={"request_timeout_seconds": min(options.request_timeout_seconds, remaining)})
        # Reservations remain consumed, including unknown usage and timed-out upstream threads.
        return self.gateway.invoke_structured(**kwargs)


def _detected(sample, audit):
    if audit["decision"] == "approve" or any(c["status"] != "success" for c in audit["calls"]):
        return False
    location = sample["location"]
    expected = set(sample["expected_findings"])
    for resource in audit["resources"]:
        for finding in resource["findings"]:
            if expected.intersection(finding["codes"]) and (not location.get("question_id") or finding["question_id"] == location["question_id"]) and finding["skill_node_id"] == location["skill_node_id"]:
                return True
        for issue in resource["issue_locations"]:
            if issue["code"] not in expected:
                continue
            if location.get("question_id") and location["question_id"] not in issue["question_ids"]:
                continue
            if location.get("step_id") and location["step_id"] not in issue["step_ids"]:
                continue
            if not location.get("question_id") and not location.get("step_id") and issue["knowledge_point"] != location["skill_node_id"]:
                continue
            return True
    return False


def metrics(observations):
    result = {}
    for strategy in ("two_stage_v1", "combined_v2", "practice_semantic_v2"):
        rows = [o for o in observations if o["strategy"] == strategy]
        bad, clean = [o for o in rows if not o["is_correct"]], [o for o in rows if o["is_correct"]]
        latencies = sorted(o["wall_ms"] for o in rows)
        known = [o["total_tokens"] for o in rows if o["total_tokens"] is not None and all(o.get("usage_complete", {}).values())]
        result[strategy] = {"observations": len(rows), "bad_denominator": 72 if strategy != "practice_semantic_v2" else 36,
            "clean_denominator": 36, "effective_detections": sum(o["detected"] for o in bad),
            "false_rejections": sum(o["decision"] != "approve" for o in clean),
            "critical_approvals": sum(o["decision"] == "approve" for o in bad),
            "unknown_usage": len(rows) - len(known), "known_total_tokens": sum(known),
            "mean_resource_tokens": sum(known) / len(rows) if len(rows) and len(known) == len(rows) else None,
            "p95_resource_wall_ms": latencies[math.ceil(0.95 * len(latencies))-1] if latencies else None,
            "defects": {d: {"denominator": 12 if strategy != "practice_semantic_v2" else 9,
                             "effective_detections": sum(o["detected"] for o in bad if o["primary_defect"] == d)}
                        for d in sorted({o["primary_defect"] for o in bad})}}
    return result


def quality_gate(observations, summary):
    if len(observations) != 288 or any(o["invalid"] for o in observations):
        return "INCOMPLETE"
    baseline, combined = summary["two_stage_v1"], summary["combined_v2"]
    # Baseline misses remain comparison metrics, not candidate hard-gate failures.
    if combined["critical_approvals"] or summary["practice_semantic_v2"]["critical_approvals"]:
        return "FAIL_CRITICAL_APPROVAL"
    if combined["effective_detections"] != 72 or summary["practice_semantic_v2"]["effective_detections"] != 36:
        return "FAIL_CRITICAL_DETECTION"
    if (combined["effective_detections"] < baseline["effective_detections"] or combined["false_rejections"] > baseline["false_rejections"]
            or any(combined["defects"][d]["effective_detections"] < counts["effective_detections"] for d, counts in baseline["defects"].items())):
        return "FAIL_QUALITY"
    if any(s["unknown_usage"] for s in summary.values()):
        return "INCONCLUSIVE_USAGE"
    if combined["mean_resource_tokens"] > baseline["mean_resource_tokens"] or combined["p95_resource_wall_ms"] > baseline["p95_resource_wall_ms"]:
        return "FAIL_COST_OR_LATENCY"
    if any(o["logical_call_count"] != 1 for o in observations if o["strategy"] == "combined_v2"):
        return "FAIL_CALL_COUNT"
    return "PASS"


def evaluate(manifest, config, *, gateway=None):
    observations = []
    incomplete = None
    for sample in manifest["cases"]:
        for repeat in range(3):
            strategies = ["two_stage_v1", "combined_v2"] if sample["resource_type"] == "分阶测试题" else ["practice_semantic_v2"]
            if repeat % 2:
                strategies.reverse()  # Frozen AB/BA, serial execution.
            for strategy in strategies:
                selected = gateway or FixtureGateway(sample["offline_outputs"][strategy], config)
                started = monotonic()
                try:
                    with assessment_catalog_snapshot(sample["catalog_nodes"]):
                        output = review_node(_state(sample, strategy, config), llm_gateway=selected)
                except BudgetExhausted:
                    incomplete = "INCOMPLETE_BUDGET"
                    break
                audit = output["review_audit"]
                usage = audit["summary"]["usage"]
                usage_complete = audit["summary"]["usage_complete"]
                cost_tokens = usage["input_tokens"] + usage["output_tokens"] if all(usage_complete.values()) else None
                invalid = any(c["status"] != "success" for c in audit["calls"]) or any(r["semantic_status"] == "unavailable" for r in audit["resources"])
                observations.append({"case_id": sample["case_id"], "repeat_index": repeat, "strategy": strategy,
                    "is_correct": sample["is_correct"], "primary_defect": sample["primary_defect"], "decision": audit["decision"],
                    "detected": _detected(sample, audit), "invalid": invalid,
                    "logical_call_count": audit["summary"]["logical_call_count"],
                    "total_tokens": cost_tokens, "usage_complete": usage_complete, "wall_ms": (monotonic()-started)*1000,
                    "audit": audit})
            if incomplete:
                break
        if incomplete:
            break
    summary = metrics(observations)
    offline_ok = len(observations) == 288 and all(not o["invalid"] and (o["decision"] == "approve" if o["is_correct"] else o["detected"]) for o in observations)
    return {"mode": "live" if gateway else "offline_scripted", "quality_gate": incomplete or (quality_gate(observations, summary) if gateway else "NOT_RUN_OFFLINE"),
            "fixture_policy_gate": "PASS" if offline_ok else "FAIL", "combined_enabled": False,
            "observations": observations, "metrics": summary}


def _positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--preflight-report", type=Path)
    parser.add_argument("--budget-record", type=Path)
    parser.add_argument("--model-name", default="offline-scripted")
    parser.add_argument("--context-tokens", type=_positive)
    parser.add_argument("--max-output-tokens", type=_positive, default=16384)
    parser.add_argument("--structured-output-mode", choices=["text", "auto", "function_calling", "json_schema", "json_mode"], default="text")
    parser.add_argument("--max-total-tokens", type=_positive)
    parser.add_argument("--max-transport-attempts", type=_positive)
    parser.add_argument("--max-seconds", type=_positive)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("output already exists; preserve prior evidence")
        # Authorization/budget validation precedes importing any provider factory or settings.
        if args.live and os.environ.get("RUN_LIVE_LLM") != "1":
            raise ValueError("live requires --live and RUN_LIVE_LLM=1 plus explicit user authorization")
        if args.live and (not args.preflight_report or not args.budget_record):
            raise ValueError("live requires frozen preflight and budget records")
        if args.model_name != "offline-scripted" and args.context_tokens is None:
            raise ValueError("deployment context window must be explicit")
        config = {"model_name": args.model_name, "context_tokens": args.context_tokens or 262144,
                  "max_output_tokens": args.max_output_tokens, "temperature": 0.0, "max_attempts": 2,
                  "structured_output_mode": args.structured_output_mode, "ruleset_version": "resource-review-v2"}
        budget = {"max_total_tokens": args.max_total_tokens, "max_transport_attempts": args.max_transport_attempts, "max_seconds": args.max_seconds}
        if args.live and (args.model_name == "offline-scripted" or any(v is None for v in budget.values())):
            raise ValueError("live requires explicit deployment model and three finite budgets")
        if budget["max_transport_attempts"] is not None and budget["max_transport_attempts"] > MAX_TRANSPORT_ATTEMPTS:
            raise ValueError("transport budget exceeds frozen maximum 792")
        if budget["max_seconds"] is not None and budget["max_seconds"] > MAX_SECONDS:
            raise ValueError("time budget exceeds frozen maximum 7200")
        manifest = load_manifest(args.manifest)
        frozen = preflight(manifest, config, budget)
        if args.live or any(v is not None for v in budget.values()):
            if any(v is None for v in budget.values()) or budget["max_total_tokens"] < frozen["required_reserved_tokens"] or budget["max_transport_attempts"] < frozen["max_transport_attempts"]:
                raise ValueError("frozen budgets cannot accommodate the complete inventory")
        if args.preflight:
            _write(args.output, frozen)
            if args.budget_record:
                _write(args.budget_record, {"preflight_hash": frozen["preflight_hash"], "budget": budget})
            print(f"PREFLIGHT: {frozen['max_logical_calls']} logical calls, {frozen['required_reserved_tokens']} reserved tokens")
            return 0
        gateway = None
        if args.live:
            if json.loads(args.preflight_report.read_text(encoding="utf-8")) != frozen:
                raise ValueError("preflight manifest/config/budget hash mismatch")
            if json.loads(args.budget_record.read_text(encoding="utf-8")) != {"preflight_hash": frozen["preflight_hash"], "budget": budget}:
                raise ValueError("frozen budget record mismatch")
            from app.core.llm.gateway import default_llm_gateway
            actual = default_llm_gateway()
            if actual.transport.model_name != args.model_name:
                raise ValueError("configured model differs from frozen model")
            gateway = BudgetedGateway(actual, config, budget)
        report = evaluate(manifest, config, gateway=gateway)
        report.update(schema_version="1.0", preflight=frozen, report_hash=canonical_hash(report))
        _write(args.output, report)
        print(f"{report['mode']}: {len(report['observations'])} observations; fixture={report['fixture_policy_gate']}; quality={report['quality_gate']}; combined disabled")
        return 0 if (report["quality_gate"] == "PASS" if args.live else report["fixture_policy_gate"] == "PASS") else 1
    except (ValueError, KeyError, OSError) as exc:
        print(f"RESOURCE_REVIEW_EVAL_REJECTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
