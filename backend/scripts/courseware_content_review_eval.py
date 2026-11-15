"""Offline content-policy evaluation. Production quality requires a verified model profile."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import ceil
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"backend"))
from app.models.courseware.content_review import canonical_json, json_hash

DEFAULT_MANIFEST = ROOT/"backend/tests/fixtures/courseware/content_review/manifest.json"


def load_manifest(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    body = {k: v for k, v in raw.items() if k != "manifest_hash"}
    if raw.get("schema_version") != "1.0" or raw.get("manifest_hash") != json_hash(body) or raw.get("repeats") != 3:
        raise ValueError("manifest version/hash/repeats mismatch")
    cases = raw["cases"]
    if len(cases) != 36 or len({c["id"] for c in cases}) != 36:
        raise ValueError("36 unique frozen candidates required")
    for group in ("review", "practice_code", "practice_noncode"):
        selected = [c for c in cases if c["group"] == group]
        counts = Counter(c["primary_defect"] for c in selected)
        if counts != {None: 4, "factual_conflict": 2, "scope_exaggeration": 2, "misleading_guidance": 2, "mixed_facts": 2}:
            raise ValueError("incomplete source/defect matrix")
    for case in cases:
        if case["source_hash"] != json_hash(case["frozen_source"]) or case["candidate_hash"] != json_hash(case["candidate"]):
            raise ValueError("frozen candidate/source hash mismatch")
        if bool(case["primary_defect"]) != case["critical_for_gate"] or (case["primary_defect"] and not case["item_id"]):
            raise ValueError("incomplete annotation locator")
    return raw


def aggregate_observations(manifest, observations, *, annotations_complete=False):
    expected = {(c["id"], r, strategy) for c in manifest["cases"] for r in range(3) for strategy in ("baseline", "candidate")}
    actual = [(o["sample_id"], o["repeat"], o["strategy"]) for o in observations]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        return {"quality_gate": "INCOMPLETE_OBSERVATIONS", "enabled": False}
    if any(o.get("over_budget") for o in observations):
        return {"quality_gate": "INCOMPLETE_BUDGET", "enabled": False}
    if any(o.get("input_tokens") is None or o.get("output_tokens") is None for o in observations):
        return {"quality_gate": "INCONCLUSIVE_USAGE", "enabled": False}
    if not annotations_complete:
        return {"quality_gate": "INCOMPLETE_ANNOTATION", "enabled": False}
    by_id = {c["id"]: c for c in manifest["cases"]}
    metrics = {}
    for strategy in ("baseline", "candidate"):
        selected = [o for o in observations if o["strategy"] == strategy]
        groups = defaultdict(lambda: {"tp": 0, "bad": 0, "false_rejections": 0, "clean": 0})
        for o in selected:
            case = by_id[o["sample_id"]]
            for key in ("overall", "source:"+case["group"], "defect:"+str(case["primary_defect"])):
                entry = groups[key]
                if case["primary_defect"]:
                    entry["bad"] += 1
                    entry["tp"] += bool(o.get("valid_detection") and o.get("located_item") == case["item_id"] and o.get("valid_structure"))
                else:
                    entry["clean"] += 1; entry["false_rejections"] += not bool(o.get("approved"))
        latencies = sorted(o["duration_ms"] for o in selected)
        metrics[strategy] = {"groups": dict(groups), "mean_tokens": sum(o["input_tokens"]+o["output_tokens"] for o in selected)/len(selected), "p95_ms": latencies[ceil(.95*len(latencies))-1]}
    candidate, baseline = metrics["candidate"], metrics["baseline"]
    bad_approved = any(o.get("approved") and by_id[o["sample_id"]]["critical_for_gate"] for o in observations if o["strategy"] == "candidate")
    majority = all(sum(bool(o.get("valid_detection") and o.get("valid_structure") and o.get("located_item") == c["item_id"]) for o in observations if o["sample_id"] == c["id"] and o["strategy"] == "candidate") >= 2 for c in manifest["cases"] if c["primary_defect"])
    structure = all(o.get("valid_structure") for o in observations if o["strategy"] == "candidate")
    detection = all(candidate["groups"][g]["tp"] >= baseline["groups"][g]["tp"] for g in candidate["groups"])
    false_reject = candidate["groups"]["overall"]["false_rejections"] <= baseline["groups"]["overall"]["false_rejections"]
    denominator = baseline["mean_tokens"] > 0 and baseline["p95_ms"] > 0
    costs = denominator and candidate["mean_tokens"] <= 2*baseline["mean_tokens"] and candidate["p95_ms"] <= 2*baseline["p95_ms"]
    passed = not bad_approved and majority and structure and detection and false_reject and costs
    return {"quality_gate": "PASS" if passed else "FAIL", "enabled": False, "metrics": metrics}


def offline(manifest):
    from app.agents.resource_workflows.interactive_courseware.content_review import review_content
    from app.agents.resource_workflows.interactive_courseware.content_review.persistence import freeze_policy
    from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import review_courseware_quality_decision
    from app.agents.resource_workflows.interactive_courseware.stages import prepare_design
    from app.agents.resource_workflows.interactive_courseware.composition import compose_scenes, resource_courseware_title
    from app.agents.resource_workflows.interactive_courseware.planner_agent import _platform_spec
    from app.core.courseware.content_review import resolve_adapter
    from app.models.courseware.snapshots import LearnerContextSnapshot
    from tests.fakes.courseware_content_review import ContentReviewGateway, fixture_settings, fixture_environment
    observations = []
    settings = fixture_settings(courseware_auto_revision_max_attempts=0)
    with tempfile.TemporaryDirectory(prefix="content-review-eval-") as temp, fixture_environment(temp, settings):
        for repeat in range(3):
            for index, case in enumerate(manifest["cases"]):
                source, values = case["frozen_source"], case["candidate"]
                adapter = resolve_adapter(source)
                learning = adapter.refine_design(source, prepare_design([source], LearnerContextSnapshot(), {}).design)
                design = {"learning_design": learning.model_dump(mode="json"), "source_payload": source[adapter.source_key], "user_title": None}
                plan, _, _ = _platform_spec(learning, [source]); setattr(plan, adapter.candidate_slot, adapter.candidate_model.model_validate(values))
                scenes, _ = compose_scenes([source], plan, learning_design=learning, plan_enrichment=plan.enrichment)
                document = {"schema_version": "2.0", "title": resource_courseware_title(values["course_title"], [source]), "scenes": scenes}
                for strategy in (("baseline", "candidate") if (repeat+index)%2 == 0 else ("candidate", "baseline")):
                    gateway = ContentReviewGateway(case["group"])
                    policy = freeze_policy(settings, gateway, datetime.now(timezone.utc)+timedelta(minutes=10))
                    record = None
                    if strategy == "candidate":
                        record = review_content(run_id=f"eval-{case['id']}-{repeat}", snapshot=source, design=design, candidate=values, adapter=adapter, policy=policy, gateway=gateway)
                        approved = record.status == "approved"
                    else:
                        decision, _ = review_courseware_quality_decision(gateway, "baseline", document)
                        approved = decision.decision == "approved"
                    if strategy == "candidate" and approved:
                        decision, _ = review_courseware_quality_decision(gateway, "candidate", document)
                        approved = decision.decision == "approved"
                    located = next((r.item_id for r in (record.results if record else []) if any(x.verdict != "pass" for x in r.rules)), None)
                    observations.append({"sample_id": case["id"], "repeat": repeat, "strategy": strategy, "approved": approved,
                        "status": record.status if record else decision.decision, "valid_structure": True, "located_item": located,
                        "valid_detection": bool(case["primary_defect"] and located == case["item_id"]), "logical_calls": len(gateway.calls),
                        "input_tokens": 128*len(gateway.calls), "output_tokens": 128*len(gateway.calls), "duration_ms": len(gateway.calls)})
        from scripts.courseware_content_review_fixtures import generate_browser_fixtures
        workflow_evidence = generate_browser_fixtures(Path(temp)/"workflow")
    candidate_obs = [o for o in observations if o["strategy"] == "candidate"]
    by_id = {c["id"]: c for c in manifest["cases"]}
    fixture_pass = all((not o["approved"] and o["located_item"] == by_id[o["sample_id"]]["item_id"]) if by_id[o["sample_id"]]["primary_defect"] else o["approved"] for o in candidate_obs)
    return {"schema_version": "1.0", "execution": "actual_engine_and_workflow_scripted_gateway", "manifest_hash": manifest["manifest_hash"],
        "fixture_policy_gate": "PASS" if fixture_pass else "FAIL", "quality_gate": "NOT_RUN_OFFLINE", "production_enabled": False,
        "sample_count": 36, "observations_count": len(observations), "observations": observations,
        "workflow_groups": [{k: a[k] for k in ("group", "record_status", "workflow_status", "artifact_sha256", "calls")} for a in workflow_evidence["artifacts"]]}


def positive_int(value):
    result = int(value)
    if result <= 0: raise ValueError("finite positive integer budget required")
    return result


def preflight(args, manifest):
    for key in ("max_total_tokens", "max_transport_attempts", "max_seconds"):
        if getattr(args, key) is None: raise ValueError("explicit finite token/attempt/time budgets required")
    if args.max_transport_attempts > 6480 or args.max_seconds > 7200:
        raise ValueError("budget exceeds frozen safety maximum")
    try:
        amount, inp, out = map(Decimal, (args.max_cost_amount or "", args.input_price or "", args.output_price or ""))
    except InvalidOperation as exc: raise ValueError("explicit Decimal prices and cost cap required") from exc
    if not all(v.is_finite() and v > 0 for v in (amount, inp, out)) or not all((args.currency, args.price_version, args.effective_date, args.billing_basis)):
        raise ValueError("finite positive prices, currency/version/date/billing basis required")
    datetime.fromisoformat(args.effective_date)
    config = {k: getattr(args, k) for k in ("max_total_tokens", "max_transport_attempts", "max_seconds", "max_cost_amount", "input_price", "output_price", "currency", "price_version", "effective_date", "billing_basis")}
    return {"schema_version": "1.0", "manifest_hash": manifest["manifest_hash"], "config": config, "config_hash": json_hash(config),
            "status": "NOT_READY_MODEL_PROFILE", "reason": "No verified production tokenizer/chat-wrapper profile is installed; fixture estimator is offline only.", "production_enabled": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(); mode.add_argument("--preflight", action="store_true"); mode.add_argument("--live", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST); parser.add_argument("--output", type=Path, required=True)
    for name in ("max-total-tokens", "max-transport-attempts", "max-seconds"): parser.add_argument("--"+name, type=positive_int)
    for name in ("max-cost-amount", "input-price", "output-price", "currency", "price-version", "effective-date", "billing-basis"): parser.add_argument("--"+name)
    args = parser.parse_args(argv)
    try:
        if args.live and os.environ.get("COURSEWARE_LIVE_EVAL") != "1": raise ValueError("explicit --live and COURSEWARE_LIVE_EVAL=1 authorization required")
        manifest = load_manifest(args.manifest)
        if args.live or args.preflight:
            report = preflight(args, manifest)
            if args.live: raise ValueError(report["reason"])
        else:
            report = offline(manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists(): raise ValueError("output must be new; preserve previous evidence")
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        if args.preflight:
            budget = {"preflight_hash": json_hash(report), "manifest_hash": manifest["manifest_hash"], "config_hash": report["config_hash"], "logical_calls_limit": 2160, "reserved_tokens": 0, "reserved_cost": "0", "status": "NOT_STARTED"}
            target = args.output.with_name("budget.json")
            if target.exists(): raise ValueError("budget file already exists")
            target.write_text(json.dumps(budget, indent=2), encoding="utf-8")
        print(f"Content review evaluation: {report.get('fixture_policy_gate', report.get('status'))}; quality={report.get('quality_gate', 'NOT_RUN')}")
        return 0 if report.get("fixture_policy_gate") in {None, "PASS"} else 1
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
