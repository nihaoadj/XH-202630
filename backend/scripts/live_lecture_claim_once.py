"""Create one lecture job with Claim audit, run the production worker once, summarize.

Requires RUN_LIVE_LLM=1 and a real provider key.  The report contains statuses,
token totals and Claim metrics only -- never prompts or generated bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
REPAIR_ROOT = (REPO_ROOT / "output/test-runs/t37-repair-20261105/live").resolve()
REPAIR_BUDGET = (REPO_ROOT / "docs/evaluations/experiments/20261105-claim-density-t37-repair/generation-budget.json").resolve()
# Second, independent acceptance authorization (2026-11-05).  Fixed paths per
# plan: the quota file is not user-selectable, so a new directory can never be
# used to obtain extra generations.
E2E_ROOT = (REPO_ROOT / "output/test-runs/t37-e2e-20261105/live").resolve()
E2E_BUDGET = (REPO_ROOT / "docs/evaluations/experiments/20261105-claim-density-t37-e2e/generation-budget.json").resolve()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.containers import init_container
from app.db.shared.database import get_engine
from app.models.learning_documents.schemas import GenerateRequest
from scripts import acceptance_budget


TERMINAL = {"completed", "failed", "cancelled"}

# A slot counts one complete task. Internal retries/revisions use the normal
# configured contracts and do not consume additional acceptance slots.
MAX_BUSINESS_REWORK = 2
MAX_CLAIM_REWORK = 1


def _queued_jobs() -> int:
    with get_engine().connect() as connection:
        return int(connection.execute(
            text("select count(*) from generation_jobs where status = 'queued'")
        ).scalar() or 0)


def _job_status(run_id: str) -> str:
    with get_engine().connect() as connection:
        row = connection.execute(
            text("select status from generation_jobs where run_id = :run_id"),
            {"run_id": run_id},
        ).first()
    return str(row[0]) if row else "missing"


def _summary(container, run_id: str) -> dict:
    engine = get_engine()
    with engine.connect() as connection:
        job = connection.execute(
            text("select status, created_at, started_at, finished_at, error_message "
                 "from generation_jobs where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().first()
        run = connection.execute(
            text("select status, workflow_status, final_decision, last_error_code, retrieval_status, "
                 "generation_attempt, revision_count, started_at, ended_at "
                 "from agent_runs where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().first()
        steps = connection.execute(
            text("select node_name, status, duration_ms, llm_attempts from agent_steps "
                 "where run_id = :run_id order by step_no"),
            {"run_id": run_id},
        ).mappings().all()
        resources = connection.execute(
            text("select resource_id, parent_resource_id, version, resource_type, review_status, publication_status, "
                 "length(content_text) as chars, claim_metric_status, claim_factual_pass_rate "
                 "from generated_resources where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().all()
        claims = connection.execute(
            text("select claim_type, count(*) c from resource_claims where run_id = :run_id group by 1"),
            {"run_id": run_id},
        ).mappings().all()
        verdicts = connection.execute(
            text("select verdict, count(*) c from claim_judgements where run_id = :run_id group by 1"),
            {"run_id": run_id},
        ).mappings().all()
        extraction_row = connection.execute(text(
            "select policy_json, state_json from claim_extraction_runs where run_id=:run_id"),
            {"run_id": run_id}).mappings().first()
        judged_ids = set(connection.execute(text(
            "select claim_id from claim_judgements where run_id=:run_id and status='completed'"),
            {"run_id": run_id}).scalars())

    nodes: dict[str, dict] = {}
    totals = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    non_extraction_unknown = 0
    for step in steps:
        attempts = json.loads(step["llm_attempts"]) if step["llm_attempts"] else []
        attempts = attempts if isinstance(attempts, list) else []
        observed = attempt_usage(attempts)
        tokens_in, tokens_out = observed['input_tokens'], observed['output_tokens']
        if step['node_name'] != 'claim_extract':
            non_extraction_unknown += observed['unknown_attempts']
        totals["llm_calls"] += len(attempts)
        totals["input_tokens"] += tokens_in
        totals["output_tokens"] += tokens_out
        node = nodes.setdefault(step["node_name"], {
            "steps": 0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "duration_ms": 0, "statuses": [],
        })
        node["steps"] += 1
        node["llm_calls"] += len(attempts)
        node["input_tokens"] += tokens_in
        node["output_tokens"] += tokens_out
        node["duration_ms"] += int(step["duration_ms"] or 0)
        node["statuses"].append(step["status"])

    claim_metrics = {}
    try:
        claim_metrics = container.run_query_service().get_claims(run_id).model_dump(mode="json")
    except Exception as exc:  # projection may lag on a failed run; keep the raw rows
        claim_metrics = {"error": type(exc).__name__}

    extraction = None
    if extraction_row:
        snapshot = container.generation_service().claim_extraction_repository.get(run_id)
        policy = snapshot.policy.model_dump(mode="json")
        ledger = snapshot.state.model_dump(mode="json")
        latest_versions = current_resource_versions(resources)
        extraction = extraction_summary(policy, ledger, judged_ids, latest_versions)
        extraction['current_resources_covered'] = latest_versions == extraction['resource_versions']
        # Claim trace contains at most the last extraction call. Replace that
        # partial observation with the physical ledger rather than adding twice.
        trace = nodes.get("claim_extract", {})
        totals["llm_calls"] += extraction["attempts"] - trace.get("llm_calls", 0)
        totals["input_tokens"] -= trace.get("input_tokens", 0)
        totals["output_tokens"] -= trace.get("output_tokens", 0)
    usage = {**totals, "total_tokens": totals["input_tokens"] + totals["output_tokens"]}
    if extraction and extraction["attempts"]:
        usage.update(non_extraction_input_tokens=totals["input_tokens"],
                     non_extraction_output_tokens=totals["output_tokens"], input_tokens=None, output_tokens=None,
                     total_tokens=usage["total_tokens"] + extraction["known_tokens"],
                     unknown_reserved_tokens=extraction["unknown_reserved_tokens"],
                     complete=extraction["unknown_reserved_tokens"] == 0,
                     split_note="Extraction ledger records total usage only; input/output split unavailable.")
    usage['non_extraction_unknown_attempts'] = non_extraction_unknown
    usage['known_total_tokens'] = usage['total_tokens']
    usage['complete'] = not non_extraction_unknown and (not extraction or not extraction['unknown_reserved_tokens'])
    if not usage['complete']:
        usage['total_tokens'] = None
        usage['input_tokens'] = None
        usage['output_tokens'] = None
    return {
        "run_id": run_id,
        "job": dict(job) if job else None,
        "run": dict(run) if run else None,
        "llm_usage": usage,
        "extraction": extraction,
        "nodes": nodes,
        "resources": [dict(item) for item in resources],
        "claims_by_type": {item["claim_type"]: item["c"] for item in claims},
        "verdicts": {item["verdict"]: item["c"] for item in verdicts},
        "claim_metrics": claim_metrics,
    }


def attempt_usage(attempts):
    return dict(input_tokens=sum(int(a.get('input_tokens') or 0) for a in attempts),
                output_tokens=sum(int(a.get('output_tokens') or 0) for a in attempts),
                unknown_attempts=sum(a.get('input_tokens') is None or a.get('output_tokens') is None for a in attempts))


def current_resource_versions(resources):
    parents = {r['parent_resource_id'] for r in resources if r.get('parent_resource_id')}
    versions = {}
    for resource in resources:
        if resource['resource_id'] not in parents:
            versions[resource['resource_id']] = max(resource['version'], versions.get(resource['resource_id'], 0))
    return versions


def extraction_summary(policy, ledger, judged_ids, resource_versions=None):
    """Private durable evidence; report counters, never source text or prompts."""
    latest = {}
    for result in ledger.get("results", {}).values():
        previous = latest.get(result["resource_id"])
        if previous is None or (result["resource_version"], result["generation_attempt"]) > (
                previous["resource_version"], previous["generation_attempt"]):
            latest[result["resource_id"]] = result
    selected = list(latest.values())
    if resource_versions is not None:
        selected = [r for r in selected if resource_versions.get(r['resource_id']) == r['resource_version']]
    ids = {c["claim_id"] for r in selected for c in r.get("final_claims", [])}
    tickets = list(ledger.get("tickets", {}).values())
    return dict(result_statuses=[r["status"] for r in selected],
                resource_versions={r['resource_id']:r['resource_version'] for r in selected},
                failures=[r.get("failure") for r in selected if r["status"] != "completed"],
                candidates=len(ids), judgements_complete=bool(ids) and ids <= set(judged_ids),
                calls=ledger["calls"], attempts=ledger["attempts"],
                known_tokens=sum(t.get("actual_tokens") or 0 for t in tickets if t["usage_status"] == "known"),
                unknown_reserved_tokens=sum(t["reserved_tokens"] for t in tickets if t["usage_status"] != "known"),
                settled=all(t["settled"] for t in tickets), budget_exhausted=ledger["budget_exhausted"],
                overrun_tokens=ledger["overrun_tokens"], time_ms=ledger["time_ms"],
                replaced_batches=sum(len(r.get("replaced_batches", [])) for r in ledger.get('results',{}).values()),
                initial_batches=sum(len(r.get('batches',[]))-len(r.get('replaced_batches',[]))
                                    for r in ledger.get('results',{}).values()),
                resource_claims=policy["resource_claims"], density_batching=policy.get("density_batching"))


def classify_acceptance(report):
    if report.get("acceptance", {}).get("timed_out"):
        return "UNKNOWN", 5
    extraction = report.get("extraction")
    if not extraction or not extraction.get("result_statuses"):
        return ("FAIL", 2) if "claim_extract" in report.get("nodes", {}) else ("INCONCLUSIVE", 3)
    passed = (all(status == "completed" for status in extraction["result_statuses"])
              and extraction["candidates"] > 0 and extraction["judgements_complete"]
              and extraction["settled"] and not extraction["budget_exhausted"]
              and extraction.get('current_resources_covered', False)
              and extraction["overrun_tokens"] == 0 and (report.get("job") or {}).get("status") == "completed")
    return ("PASS", 0) if passed else ("FAIL", 2)


def _plan_root(plan: str) -> Path:
    return E2E_ROOT if plan == "e2e" else REPAIR_ROOT


def _plan_budget(plan: str) -> Path:
    return E2E_BUDGET if plan == "e2e" else REPAIR_BUDGET


def _parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--learner-id", default=os.getenv("LIVE_LEARNER_ID", "").strip())
    parser.add_argument("--resource-type", default="讲义")
    parser.add_argument(
        "--target-node",
        default="",
        help="Fix the focus node so runs of different resource types stay comparable; "
             "empty keeps the production auto recommendation.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--report-path", default=".live-claim-runs/lecture-claim-run.json")
    parser.add_argument("--max-iterations", type=int, default=MAX_BUSINESS_REWORK)
    parser.add_argument("--claim-max-iterations", type=int, default=MAX_CLAIM_REWORK)
    # T37 acceptance quota. Parsed before the live switch so that
    # --init-acceptance-budget / --preflight-only never require RUN_LIVE_LLM.
    parser.add_argument("--acceptance-budget", default="",
                        help="Path to the single T37 quota file (repo-root relative).")
    parser.add_argument("--acceptance-plan", choices=["repair", "e2e"], default="repair",
                        help="Fixed authorization set; its root and quota path are hard-coded.")
    parser.add_argument("--init-acceptance-budget", action="store_true",
                        help="Create the quota file only; refuses to overwrite an existing one.")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Validate isolation/config/quota without consuming a slot or calling a provider.")
    parser.add_argument("--acceptance-slot", type=int, default=0, choices=[0, 1, 2, 3])
    parser.add_argument("--max-generations", type=int, default=3, choices=[1, 2, 3],
                        help="Complete tasks authorized in a new budget; never resets an existing file.")
    parser.add_argument(
        "--takeover-reason", default="",
        help="Finish a slot left in reserved/running by a killed process. One takeover "
             "per slot; the slot stays consumed and the reason is written to the ledger.")
    return parser.parse_args(argv)


def _budget_path(args) -> Path:
    path = Path(args.acceptance_budget)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _check_authorization(args, data=None):
    if _budget_path(args).resolve() != _plan_budget(args.acceptance_plan):
        raise acceptance_budget.BudgetError("Acceptance authorization requires its fixed budget file; historical budgets are read-only.")
    if args.init_acceptance_budget and args.max_generations != 1:
        raise acceptance_budget.BudgetError("Repair authorization allows one complete task.")
    if data is not None and data['max_generations'] != 1:
        raise acceptance_budget.BudgetError("Repair budget must have cap=1.")


def _isolation_report(root: Path | None = None) -> dict:
    root = REPAIR_ROOT if root is None else root
    settings = os.getenv
    database = settings("DATABASE_URL", "")
    resources = settings("RESOURCES_DIR", "")
    vectors = settings("VECTOR_STORE_DIR", "")
    knowledge = settings("KNOWLEDGE_BASE_DIR", "")
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError
    production = (BACKEND_ROOT / "data").resolve()
    problems = []
    try:
        url = make_url(database)
        if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
            raise ValueError("persistent SQLite required")
        db_path = Path(url.database)
        if not db_path.is_absolute():
            raise ValueError("absolute isolated database path required")
        if not db_path.resolve().is_relative_to(root) or db_path.resolve().is_relative_to(production):
            raise ValueError("database points at production data")
    except (ValueError, TypeError, ArgumentError) as exc:
        problems.append(f"DATABASE_URL invalid: {exc}")
    for name, value in (("RESOURCES_DIR", resources), ("VECTOR_STORE_DIR", vectors),
                        ("KNOWLEDGE_BASE_DIR", knowledge)):
        if not value:
            problems.append(f"{name} not set")
        elif (not Path(value).is_absolute() or not Path(value).resolve().is_relative_to(root)
              or Path(value).resolve().is_relative_to(production)):
            problems.append(f"{name} points at the production data directory")
    return {"ok": not problems, "problems": problems,
            "database": database, "resources": resources, "vector_store": vectors,
            "knowledge_base": knowledge}


def _preflight(args, data: dict) -> dict:
    """No-provider preflight; the production tier gate may initialize isolated state."""
    from app.config import get_settings

    settings = get_settings()
    isolation = _isolation_report(_plan_root(args.acceptance_plan))
    problems = list(isolation["problems"])
    if args.resource_type != "讲义":
        problems.append("budget mode only permits resource_type=讲义")
    if not 0 <= args.max_iterations <= 3:
        problems.append("--max-iterations must be 0..3 (GenerateRequest contract)")
    if not 0 <= args.claim_max_iterations <= 3:
        problems.append("--claim-max-iterations must be 0..3 (GenerateRequest contract)")
    if not args.learner_id:
        problems.append("--learner-id is required")
    if not args.target_node:
        problems.append("--target-node is required")
    from app.config import is_placeholder_api_key
    secret = getattr(settings, "llm_api_key", "")
    key = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
    if is_placeholder_api_key(key):
        problems.append("LLM credential missing (value never printed)")
    if getattr(settings, "claim_extraction_strategy", None) != "neutral_estimate_v1":
        problems.append("T37 acceptance requires neutral_estimate_v1")
    if not getattr(settings, "claim_extraction_density_enabled", False):
        problems.append("T37 acceptance requires density enabled")
    report_path = Path(args.report_path)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    if report_path.exists():
        problems.append("report already exists; refusing overwrite")
    quota = acceptance_budget.summary(data)
    if args.acceptance_slot:
        pending_state = data["slots"][str(args.acceptance_slot)]["state"]
        resumable = bool(args.takeover_reason) and pending_state in {"reserved", "running"}
        if not resumable:
            try:
                acceptance_budget.require_slot_available(data, args.acceptance_slot)
            except acceptance_budget.BudgetError as exc:
                problems.append(str(exc))
    queued = None
    learner_ok = None
    target_tier = None
    policy_hash = None
    policy_summary = None
    if not isolation["ok"]:
        return {"ok": False, "problems": problems, "isolation": isolation, "provider_calls": 0}
    try:
        container = init_container()
        queued = _queued_jobs()
        if queued:
            problems.append(f"{queued} queued generation job(s) present")
        learners = container.profile_service().repo.list_all()
        learner_ok = args.learner_id in learners if args.learner_id else False
        if not learner_ok:
            problems.append(f"learner not found: {args.learner_id}")
        elif args.target_node:
            profile = learners[args.learner_id]
            known = set(getattr(profile, "weak_points", []) or []) | set(
                getattr(profile, "skill_graph_nodes", []) or [])
            if known and args.target_node not in known:
                problems.append(f"target node not available for learner: {args.target_node}")
            else:
                # Run the same hard gate the job uses, so a tier/eligibility
                # rejection is found here instead of after a slot is consumed.
                try:
                    target_tier = container.mastery_service().validate_generation_targets(
                        profile, [args.target_node])
                except Exception as exc:
                    problems.append(f"generation target rejected: {exc}")
        try:
            from app.agents.resource_workflows.learning_documents.claim_extraction.budget import (
                freeze_policy,
            )
            gateway = container.llm_gateway()
            from app.agents.resource_workflows.learning_documents.claim_extraction.profiles import load_counter
            policy = freeze_policy(settings, gateway, load_counter(settings, gateway))
            policy_hash = __import__("app.models.reviews.claim_extraction",
                                     fromlist=["digest"]).digest(policy)
            policy_summary = {name: getattr(policy, name) for name in (
                "strategy", "batch_claims", "resource_claims", "max_calls", "max_attempts", "max_tokens")}
            policy_summary["density_batching"] = policy.density_batching.model_dump(mode="json")
            from app.core.health import build_health_report
            health = build_health_report(settings, index_status_provider=container.knowledge_catalog().get_index_status)
            if health.status != "ready":
                problems.append("isolated dependencies/KB are not ready")
        except Exception as exc:  # frozen identity is reported, never silently skipped
            problems.append(f"frozen policy hash unavailable: {type(exc).__name__}")
    except Exception as exc:
        problems.append(f"container preflight failed: {type(exc).__name__}: {exc}")
    return {
        "ok": not problems,
        "problems": problems,
        "quota": quota,
        "isolation": isolation,
        "learner_id": args.learner_id,
        "target_node": args.target_node,
        "resource_type": args.resource_type,
        "max_iterations": args.max_iterations,
        "claim_max_iterations": args.claim_max_iterations,
        "ordinary_generation_rounds_budget": args.max_iterations + 1,
        "claim_revision_rounds_budget": args.claim_max_iterations,
        "takeover_reason": args.takeover_reason or None,
        "queued_jobs": queued,
        "learner_found": learner_ok,
        "target_tier": target_tier,
        "llm_model": getattr(settings, "llm_model", None),
        "llm_thinking_mode": getattr(settings, "llm_thinking_mode", None),
        "frozen_policy_hash": policy_hash,
        "frozen_policy": policy_summary,
        "body_transport_attempts": getattr(settings, "llm_resource_generation_max_attempts", None),
        "provider_calls": 0,
    }


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.init_acceptance_budget:
        if not args.acceptance_budget:
            print("--init-acceptance-budget requires --acceptance-budget", file=sys.stderr)
            return 4
        try:
            _check_authorization(args)
            data = acceptance_budget.init_budget(_budget_path(args), max_generations=args.max_generations)
        except acceptance_budget.BudgetError as exc:
            print(str(exc), file=sys.stderr)
            return 4
        print(json.dumps(acceptance_budget.summary(data), ensure_ascii=False), flush=True)
        return 0

    budget_mode = bool(args.acceptance_budget) or args.preflight_only
    if budget_mode and not args.acceptance_budget:
        print("--preflight-only requires --acceptance-budget", file=sys.stderr)
        return 4
    if budget_mode:
        try:
            data = acceptance_budget.load(_budget_path(args))
            _check_authorization(args, data)
        except acceptance_budget.BudgetError as exc:
            print(str(exc), file=sys.stderr)
            return 4
    if args.preflight_only:
        report = _preflight(args, data)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 0 if report["ok"] else 4
    if budget_mode:
        if args.takeover_reason:
            print("Unknown/interrupted tasks cannot be replayed in an acceptance slot.", file=sys.stderr)
            return 4
        if str(args.acceptance_slot) not in data["slots"]:
            print("Select an authorized acceptance slot.", file=sys.stderr)
            return 4
        pending_state = data["slots"][str(args.acceptance_slot)]["state"]
        # A slot left unsettled by a killed process may be finished once; the
        # slot is still consumed, so this never grants an extra generation.
        resumable = bool(args.takeover_reason) and pending_state in {"reserved", "running"}
        if not resumable:
            try:
                acceptance_budget.require_slot_available(data, args.acceptance_slot)
            except acceptance_budget.BudgetError as exc:
                print(str(exc), file=sys.stderr)
                return 4
        if (args.resource_type != "讲义"
                or not 0 <= args.max_iterations <= 3
                or not 0 <= args.claim_max_iterations <= 3):
            print(
                "budget mode requires 讲义 + --max-iterations 0..3 "
                "+ --claim-max-iterations 0..3",
                file=sys.stderr)
            return 4

    if os.getenv("RUN_LIVE_LLM") != "1":
        raise SystemExit("set RUN_LIVE_LLM=1")

    if not budget_mode:
        return _run_live(args, None, args.max_iterations, args.claim_max_iterations,
                         args.timeout_seconds)
    return _run_slot(args)


def _run_slot(args) -> int:
    """Hold the plan lock across reserve -> run -> settle so concurrency is 1.

    The lock is deliberately not released between reserving and settling: two
    processes must not be able to run two real generations at the same time.
    """
    path = _budget_path(args)
    try:
        with acceptance_budget.budget_lock(path):
            data = acceptance_budget.load(path)
            _check_authorization(args, data)
            if args.takeover_reason:
                raise acceptance_budget.BudgetError('Interrupted/unknown tasks cannot be replayed.')
            preflight = _preflight(args, data)
            if not preflight["ok"]:
                print(json.dumps(preflight, ensure_ascii=False), flush=True)
                return 4
            entry = data["slots"][str(args.acceptance_slot)]
            if entry["state"] == "unused":
                acceptance_budget.require_slot_available(data, args.acceptance_slot)
                acceptance_budget.reserve_slot(path, args.acceptance_slot, locked=True)
            elif args.takeover_reason and entry["state"] in {"reserved", "running"}:
                acceptance_budget.takeover_slot(
                    path, args.acceptance_slot, reason=args.takeover_reason, locked=True)
            else:
                raise acceptance_budget.BudgetError(
                    f"slot {args.acceptance_slot} is {entry['state']}; "
                    "pass --takeover-reason to finish an unsettled slot")
            budget = {"path": path, "slot": args.acceptance_slot, "locked": True}
            try:
                return _run_live(args, budget, args.max_iterations,
                                 args.claim_max_iterations,
                                 min(args.timeout_seconds, 1800))
            except BaseException:
                try:
                    acceptance_budget.settle_slot(path, args.acceptance_slot,
                                                  outcome="unknown", locked=True)
                except acceptance_budget.BudgetError:
                    pass
                raise
    except acceptance_budget.BudgetError as exc:
        print(str(exc), file=sys.stderr)
        return 4


def _run_live(args, budget, max_iterations, claim_max_iterations, timeout_seconds) -> int:
    container = init_container()
    learners = container.profile_service().repo.list_all()
    if not learners:
        raise SystemExit("no learner profile found")
    learner = learners.get(args.learner_id) if args.learner_id else next(iter(learners.values()))
    if learner is None:
        raise SystemExit(f"learner profile not found: {args.learner_id}")

    queued = _queued_jobs()
    if queued:
        raise SystemExit(f"{queued} queued generation job(s) present; drain them before this run")

    request = GenerateRequest(
        learner_id=learner.learner_id,
        topic=learner.learning_goal or "当前学习主题",
        knowledge_base_id=learner.knowledge_base_id,
        resource_types=[args.resource_type],
        include_review=True,
        include_claim_check=True,
        max_iterations=max_iterations,
        claim_max_iterations=claim_max_iterations,
        profile_focus_mode="auto",
        target_skill_nodes=[args.target_node] if args.target_node else [],
    )
    job = container.generation_job_service().create_job(learner, request)
    run_id = job.run_id
    if budget:
        acceptance_budget.mark_running(budget["path"], budget["slot"], run_id,
                                       locked=budget.get("locked", False))
    print(json.dumps({"created": run_id, "learner_id": learner.learner_id,
                      "slot": budget["slot"] if budget else None}, ensure_ascii=False), flush=True)

    started = time.monotonic()
    timed_out = False
    try:
        subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "scripts" / "generation_worker.py"), "--once"],
            cwd=BACKEND_ROOT,
            check=False,
            timeout=timeout_seconds if budget else None,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
    while time.monotonic() - started < timeout_seconds:
        if _job_status(run_id) in TERMINAL:
            break
        time.sleep(2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "learner_id": learner.learner_id,
        "configuration": {
            "resource_types": [args.resource_type],
            "target_node": args.target_node or "auto",
            "include_review": True,
            "include_claim_check": True,
            "max_iterations": max_iterations,
            "claim_max_iterations": claim_max_iterations,
        },
        "acceptance": {
            "slot": budget["slot"] if budget else None,
            "budget_path": str(budget["path"]) if budget else None,
            "timed_out": timed_out,
        },
        "elapsed_seconds": round(time.monotonic() - started, 2),
        **_summary(container, run_id),
    }
    reached_claim = "claim_extract" in report.get("nodes", {})
    report["acceptance"]["reached_claim"] = reached_claim
    if budget:
        gate, exit_code = classify_acceptance(report)
        report["acceptance"]["technical_gate"] = gate
        report["acceptance"]["effect_gate"] = (
            "PASS" if gate == "PASS" and report["extraction"]["replaced_batches"] == 0
            and report['extraction']['calls'] == report['extraction']['initial_batches'] else "NOT_PASSED")
        outcome = "unknown" if timed_out else ("completed" if gate == "PASS" else "failed")
        report["acceptance"]["outcome"] = outcome

    path = Path(args.report_path)
    if not path.is_absolute():
        path = ((REPO_ROOT if budget else BACKEND_ROOT) / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    if budget:
        acceptance_budget.settle_slot(budget["path"], budget["slot"], outcome=outcome,
                                      run_id=run_id, locked=budget.get("locked", False))
    print(json.dumps({
        "report_path": str(path),
        "job_status": (report["job"] or {}).get("status"),
        "run_status": (report["run"] or {}).get("status"),
        "claims": sum(report["claims_by_type"].values()),
        "verdicts": report["verdicts"],
        "llm_usage": report["llm_usage"],
        "acceptance": report["acceptance"],
    }, ensure_ascii=False), flush=True)
    if timed_out:
        return 5
    if (report["job"] or {}).get("status") != "completed":
        return 2
    return exit_code if budget else (0 if (report["job"] or {}).get("status") == "completed" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
