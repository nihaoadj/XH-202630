"""P0-09 acceptance runner with deterministic offline and read-only runtime modes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_OUTPUT = PROJECT_ROOT / "wzx" / "out" / "p0-09-acceptance-manifest.json"

SCENARIOS = {
    "A": [
        "backend/tests/integration/workflow/test_evidence_workflow.py::test_available_valid_evidence_is_the_only_route_to_generation",
        "backend/tests/integration/workflow/test_claim_workflow.py::test_supported_claim_completes_and_approves",
        "backend/tests/integration/services/test_generation_finalization.py::test_sql_finalization_uses_recorder_owned_review_and_is_idempotent",
    ],
    "B": [
        "backend/tests/integration/workflow/test_evidence_workflow.py::test_evidence_gate_prevents_all_fact_generation_paths",
    ],
    "C": [
        "backend/tests/integration/workflow/test_p0_05_review_revision.py::test_generator_revision_only_creates_targeted_resource_version",
        "backend/tests/integration/workflow/test_p0_05_review_revision.py::test_artifact_recorder_persists_versions_reviews_and_timeline",
    ],
    "D": [
        "backend/tests/integration/workflow/test_p0_09_acceptance_contract.py::test_claim_revision_preserves_v1_and_v2_audits",
    ],
    "E": [
        "backend/tests/integration/services/test_feedback_loop_service.py::test_low_attempt_atomically_updates_profile_path_and_queues_followup",
        "backend/tests/integration/persistence/test_feedback_events.py::test_feedback_facts_append_sanitized_events_to_source_run",
    ],
    "F": [
        "backend/tests/integration/services/test_feedback_loop_service.py::test_practice_updates_state_without_unnecessary_generation",
        "backend/tests/integration/services/test_feedback_loop_service.py::test_same_idempotency_key_replays_without_second_profile_update_or_job",
    ],
    "G": [
        "backend/tests/unit/policies/test_learning_path_policy.py::test_high_score_completes_current_and_unlocks_challenge",
        "backend/tests/unit/models/test_feedback_loop_contracts.py::test_weak_knowledge_point_blocks_high_overall_score",
    ],
    "H": [
        "backend/tests/integration/services/test_run_event_stream.py::test_replay_order_after_sequence_reconnect_and_multiple_clients",
        "backend/tests/integration/services/test_run_event_stream.py::test_terminal_closes_after_backlog_and_disconnect_is_read_only",
    ],
    "I": [
        "backend/tests/e2e/test_run_replay.py::test_cross_process_replay_uses_database_snapshots_only",
        "backend/tests/e2e/test_feedback_restart_e2e.py::test_sqlite_feedback_state_survives_repository_reconstruction",
        "backend/tests/integration/persistence/test_claim_repository.py::test_sql_claim_repository_persists_judgement_and_frozen_evidence_binding",
    ],
    "J": [
        "backend/tests/unit/core/test_llm_gateway.py::test_gateway_retries_timeout_without_changing_call_identity",
        "backend/tests/unit/core/test_llm_gateway.py::test_gateway_schema_repair_uses_same_global_attempt_budget",
        "backend/tests/unit/core/test_llm_gateway.py::test_gateway_does_not_retry_auth_error",
        "backend/tests/unit/agents/test_llm_failure_policy.py::test_reviewer_never_approves_gateway_failure",
        "backend/tests/integration/workflow/test_claim_workflow.py::test_forged_evidence_fails_closed_without_leaking_claim_text",
        "backend/tests/unit/agents/test_evidence_failure_policy.py::test_no_hit_is_business_result_even_when_degraded_mode_is_forbidden",
        "backend/tests/unit/agents/test_evidence_failure_policy.py::test_production_retrieval_error_fails_closed",
        "backend/tests/integration/workflow/test_run_failure_policy.py::test_create_run_failure_prevents_workflow_invocation",
        "backend/tests/integration/services/test_run_event_stream.py::test_terminal_closes_after_backlog_and_disconnect_is_read_only",
        "backend/tests/integration/services/test_feedback_loop_service.py::test_stale_profile_version_is_rejected_without_mutation",
        "backend/tests/integration/services/test_feedback_loop_service.py::test_same_key_with_different_payload_is_409_conflict",
    ],
}


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _pytest(selectors: list[str]) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *selectors, "-q"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    summary = (result.stdout + "\n" + result.stderr).strip().splitlines()
    return ("PASS" if result.returncode == 0 else "FAIL", summary[-1] if summary else "no output")


def _offline(
    suite_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.reports.p0_09_acceptance import (
        evaluate_official_metrics,
        load_suite,
        safe_fixture_summary,
    )

    suite = load_suite(suite_path)
    scenarios = []
    for scenario_id, selectors in SCENARIOS.items():
        status, evidence = _pytest(selectors)
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "status": status,
                "mode": "deterministic_offline",
                "evidence": evidence,
            }
        )
    metrics = [item.as_dict() for item in evaluate_official_metrics(suite)]
    return scenarios, metrics, safe_fixture_summary(suite)


def _frontend_source_checks(project_root: Path = PROJECT_ROOT) -> dict[str, bool]:
    """Probe current frontend source wiring; this is not full frontend validation."""

    def read_source(relative_path: str) -> str:
        try:
            return (project_root / relative_path).read_text(encoding="utf-8")
        except OSError:
            return ""

    api_source = read_source("frontend/src/api/index.js")
    feedback_view = read_source("frontend/src/features/feedback/FeedbackView.vue")
    feedback_evaluation = read_source("frontend/src/features/feedback/useFeedbackEvaluation.js")
    report_view = read_source("frontend/src/features/reports/ReportView.vue")
    report_api = read_source("frontend/src/features/reports/api.js")
    generation_view = read_source("frontend/src/features/generation/GenerateView.vue")
    generation_claims = read_source("frontend/src/features/generation/useGenerationClaims.js")
    resources_view = read_source("frontend/src/features/learning-documents/ResourcesView.vue")
    source_view = read_source("frontend/src/features/learning-documents/ResourceViewer.vue")
    source_refs = read_source("frontend/src/features/learning-documents/SourceRefList.vue")
    resource_library_api = read_source("frontend/src/features/resource-library/api.js")
    run_events_api = read_source("frontend/src/features/runs/api.js")
    generation_progress = read_source("frontend/src/features/generation/useGenerationProgress.js")
    courseware_api = read_source("frontend/src/features/courseware/api.js")
    courseware_tracking = read_source("frontend/src/features/courseware/useCoursewareTracking.js")

    return {
        "formal_attempt_api": all(
            marker in api_source
            for marker in (
                "submitRunAttempt:",
                "submitBatchAttempt:",
                "'/feedback/attempts/run/submit'",
                "'/feedback/attempts/batch/submit'",
            )
        ),
        "formal_attempt_used_by_feedback_view": all(
            marker in feedback_view
            for marker in (
                "useFeedbackEvaluation",
                "feedbackApi,",
                "submitEvaluation",
            )
        ) and all(
            marker in feedback_evaluation
            for marker in ("feedbackApi.submitRunAttempt", "feedbackApi.submitBatchAttempt")
        ),
        "profile_mastery_path_visible": all(
            marker in report_view
            for marker in (
                "learningReportApi",
                "learningReportApi.get(learnerId",
                "report.learning_node_mastery_map",
                "report.learning_path_graph",
                "LearningNodeMasteryChart",
                "LearningPathGraph",
            )
        ) and "`/report/${encodeURIComponent(learnerId)}`" in report_api,
        "claim_evidence_details_used": all(
            marker in generation_claims
            for marker in ("runApi.claims(runId)", "payload.claims", "issue")
        ) and all(
            marker in api_source
            for marker in ("claims: (runId)", "`/runs/${runId}/claims`")
        ) and all(
            marker in generation_view
            for marker in (
                "useGenerationClaims",
                ":claim-reports=\"claimReports\"",
                "selectedClaimReport.issues",
                "issue.claim_text",
                "issue.reason",
            )
        ) and all(
            marker in source_view
            for marker in ("res.source_refs", "SourceRefList")
        ),
        "source_ref_v2_visible": all(
            marker in source_refs
            for marker in ("ref.evidence_id", "ref.normalized_score", "ref.chunk_id", "ref.page")
        ) and all(
            marker in source_view
            for marker in ("res.source_refs", "SourceRefList")
        ) and all(
            marker in resources_view
            for marker in ("resourceLibraryApi.listByLearner(learnerId)", "<ResourceViewer", "selectedResource")
        ) and "`/resource-library/${encodeURIComponent(learnerId)}`" in resource_library_api,
        "workflow_sse_present": all(
            marker in run_events_api
            for marker in (
                "function runEventsUrl",
                "`/api/runs/${encodeURIComponent(runId)}/events${query}`",
                "createRunEventClient",
            )
        ) and all(
            marker in generation_progress
            for marker in ("createRunEventClient", "../runs/api.js")
        ) and all(
            marker in courseware_api
            for marker in ("eventsUrl:", "/resources/courseware/jobs/", "/events?after_sequence=")
        ) and all(
            marker in courseware_tracking
            for marker in ("coursewareApi.eventsUrl(runId)", "courseware_progress")
        ),
    }


def _runtime() -> dict[str, Any]:
    from p0_09_preflight import build_preflight

    result = build_preflight()
    sys.path.insert(0, str(BACKEND_DIR))
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        health_response = client.get("/health")
        ready_response = client.get("/health/ready")
        endpoint_checks = {
            "health_http": health_response.status_code,
            "health_status": health_response.json().get("status"),
            "ready_http": ready_response.status_code,
            "ready_status": ready_response.json().get("status"),
            "openapi_paths": len(app.openapi().get("paths", {})),
        }
    frontend_checks = _frontend_source_checks()
    frontend_gate = "PASS" if all(frontend_checks.values()) else "FAIL"
    database_checks = result["checks"]["database"]
    database_gate = (
        "PASS"
        if database_checks["migration_latest"]
        and database_checks["foreign_keys_enforced"] is not False
        and database_checks["resource_version_unique"]
        else "FAIL"
    )
    endpoints_ready = (
        endpoint_checks["health_http"] == 200
        and endpoint_checks["ready_http"] == 200
        and endpoint_checks["health_status"] == "ready"
        and endpoint_checks["ready_status"] == "ready"
    )
    status = "PASS" if result["status"] == "READY" and frontend_gate == database_gate == "PASS" and endpoints_ready else "FAIL"
    return {
        "status": status,
        "preflight_status": result["status"],
        "endpoint_checks": endpoint_checks,
        "database_gate": database_gate,
        "frontend_gate": frontend_gate,
        "frontend_checks": frontend_checks,
        "checks": result["checks"],
        "note": "runtime health may be ready while DB readiness or frontend source-wiring probes fail; frontend probes are not full frontend validation",
    }


def _live() -> dict[str, Any]:
    enabled = os.getenv("RUN_LIVE_LLM") == "1" or os.getenv("RUN_LIVE_LLM_TESTS") == "1"
    if not enabled:
        return {"status": "SKIP", "reason": "live provider smoke requires explicit RUN_LIVE_LLM=1"}
    status, evidence = _pytest(["backend/tests/live/test_live_llm.py"])
    return {"status": status, "evidence": evidence}


def build_manifest(
    *,
    run_offline: bool,
    run_runtime: bool,
    run_live: bool,
    suite_path: Path | None = None,
) -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.config import get_settings
    from app.services.reports.p0_09_acceptance import FIXTURE_VERSION, SUITE_ID, SUITE_VERSION

    settings = get_settings()
    scenarios: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    from app.services.reports.p0_09_acceptance import load_suite, safe_fixture_summary
    fixture: dict[str, Any] = safe_fixture_summary(load_suite(suite_path))
    if run_offline:
        scenarios, metrics, fixture = _offline(suite_path)
    runtime = _runtime() if run_runtime else {"status": "SKIP", "reason": "runtime mode not requested"}
    live = _live() if run_live else {"status": "SKIP", "reason": "live mode not requested"}
    failed = any(item["status"] == "FAIL" for item in scenarios) or runtime["status"] == "FAIL" or live["status"] == "FAIL"
    partial = (
        any(item["status"] in {"SKIP", "NOT_MEASURABLE"} for item in metrics)
        or runtime["status"] == "SKIP"
        or live["status"] == "SKIP"
    )
    overall = "FAIL" if failed else "PARTIAL" if partial else "PASS"
    known_limitations = [
        "fixture suite has fewer than the official 50-profile high-score test plan",
        "BackgroundTasks is not a distributed durable queue",
        "Replay is not automatic Resume",
        "PostgreSQL migration and concurrency are not validated",
    ]
    if runtime.get("frontend_gate") == "FAIL":
        known_limitations.append(
            "frontend Claim/Evidence, SourceRef V2, or profile/path report alignment is incomplete"
        )
    if runtime.get("database_gate") == "FAIL":
        known_limitations.append(
            "the selected demo database has not passed the P0-09 integrity gate"
        )
    return {
        "suite_id": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "fixture_version": FIXTURE_VERSION,
        "git_sha": _git_sha(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_mode": settings.app_mode,
        "db_type": settings.db_type,
        "knowledge_base_id": fixture.get("knowledge_base_id"),
        "fixture": fixture,
        "scenarios": scenarios,
        "metrics": metrics,
        "runtime": runtime,
        "live_provider_smoke": live,
        "overall_status": overall,
        "known_limitations": known_limitations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P0-09 competition acceptance")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--suite",
        type=Path,
        help="path to a registered p0-09-demo-suite/v1 JSON fixture",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not any((args.offline, args.runtime, args.live)):
        args.offline = True
    manifest = build_manifest(
        run_offline=args.offline,
        run_runtime=args.runtime,
        run_live=args.live,
        suite_path=args.suite,
    )
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2}[manifest["overall_status"]]


if __name__ == "__main__":
    raise SystemExit(main())
