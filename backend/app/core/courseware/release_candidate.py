"""Redacted release-candidate evidence aggregation for courseware acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _json_evidence(path: Path | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if path is None or not path.is_file():
        return None, {"status": "missing"}
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, {"status": "invalid", "sha256": hashlib.sha256(raw).hexdigest()}
    return payload, {"status": "present", "sha256": hashlib.sha256(raw).hexdigest()}


def build_release_candidate_report(
    *,
    evaluator_path: Path,
    artifact_summary_path: Path,
    fault_matrix_path: Path,
    journey_summary_path: Path,
    browser_summary_path: Path,
    live_model_path: Path | None = None,
) -> dict[str, Any]:
    """Verify local evidence without copying raw artifacts or sensitive input.

    A release candidate is intentionally never elevated to ``DONE`` here:
    hosted CI, a permitted real model run, target deployment, and a full
    observed release period need separately recorded evidence.
    """
    evaluator, evaluator_file = _json_evidence(evaluator_path)
    artifacts, artifacts_file = _json_evidence(artifact_summary_path)
    matrix, matrix_file = _json_evidence(fault_matrix_path)
    journey, journey_file = _json_evidence(journey_summary_path)
    browser, browser_file = _json_evidence(browser_summary_path)
    live, live_file = _json_evidence(live_model_path)

    reports = (evaluator or {}).get("reports") or []
    evaluator_ok = bool(
        evaluator and evaluator.get("schema_version") == "2.0" and evaluator.get("passed") is True
        and evaluator.get("case_count") == 20 and len(reports) == 20
        and len({item.get("fixture") for item in reports}) == 20
        and all(
            item.get("outcome_matches_manifest") is True
            and item.get("workflow_actual_match") is True
            and item.get("expected_status") == item.get("status")
            and item.get("artifact_policy") in {"required", "forbidden"}
            and isinstance(item.get("budget"), dict)
            for item in reports
        )
    )
    artifact_rows = (artifacts or {}).get("artifacts") or []
    covered_cases = (artifacts or {}).get("covered_cases") or []
    by_case = {item.get("fixture"): item for item in reports}
    produced = [item for item in artifact_rows if item.get("status") == "produced"]
    artifacts_by_case: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifact_rows:
        artifacts_by_case.setdefault(str(artifact.get("case") or ""), []).append(artifact)
    artifact_policy_ok = bool(by_case) and all(
        (
            {"html", "zip"} <= {item.get("format") for item in artifacts_by_case.get(case, []) if item.get("status") == "produced"}
            and all(item.get("sha256") for item in artifacts_by_case.get(case, []) if item.get("status") == "produced")
        ) if report.get("artifact_policy") == "required" else not any(
            item.get("status") == "produced" for item in artifacts_by_case.get(case, [])
        )
        for case, report in by_case.items()
    )
    artifacts_ok = bool(
        artifacts and artifacts.get("schema_version") in {"1.0", "1.1"} and artifacts.get("case_count") == 20
        and len(set(covered_cases)) == 20 and set(covered_cases) == set(by_case)
        and produced and artifact_policy_ok
        # A renderer-blocked fixture is valid negative evidence when the
        # evaluator expects release rejection; it must remain explicitly
        # recorded, never be turned into a synthetic artifact hash.
        and all(item.get("status") in {"produced", "not_applicable", "blocked"} for item in artifact_rows)
    )
    matrix_categories = (matrix or {}).get("categories") or {}
    matrix_ok = bool(matrix and matrix.get("schema_version") == "1.1" and matrix.get("passed") is True
                     and len(matrix_categories) == 18 and all(
                         item.get("required") is True and item.get("evidence_type") == "process" and item.get("evidence")
                         for item in matrix_categories.values()))
    required_journey_cases = set((journey or {}).get("required_case_ids") or [])
    journey_cases = {str(item.get("case_id")): item for item in (journey or {}).get("cases") or []}
    journey_ok = bool(
        journey and journey.get("schema_version") == "1.1"
        and journey.get("external_services") == "not_called"
        and journey.get("status") == "LOCAL_READY"
        and required_journey_cases <= set(journey_cases)
        and journey_cases.get("q5_local_user_journey", {}).get("status") == "passed"
        and all(journey_cases[case].get("status") == "passed" for case in required_journey_cases)
    )
    matrix_components = (browser or {}).get("component_theme_matrix") or []
    component_names = {str(item.get("component") or "") for item in matrix_components}
    theme_names = {str(item.get("theme") or "") for item in matrix_components}
    component_theme_pairs = {(item.get("component"), item.get("theme")) for item in matrix_components}
    browser_ok = bool(browser and browser.get("schema_version") == "1.4" and browser.get("consoleErrors") == []
                      and len(matrix_components) == 45 and len(component_names) == 15 and len(theme_names) == 3
                      and len(component_theme_pairs) == len(matrix_components)
                      and component_theme_pairs == {(component, theme) for component in component_names for theme in theme_names}
                      and all(item.get("screenshot_sha256") and item.get("computed_checks") for item in matrix_components)
                      and {"320x640", "desktop", "200%", "forced-colors"} <= set(browser.get("viewports") or [])
                      and all(browser.get(name) is True for name in ("http_origin_iframe", "nonce_guard", "artifact_restore", "forced_colors_active", "zoom_200_active"))
                      and all(browser.get(name) for name in ("keyboard", "focusEvidence", "touch", "reducedMotion", "contrast", "a11y")))
    live_status = str((live or {}).get("status") or "NOT_RUN")
    live_quality_gate = ((live or {}).get("metrics") or {}).get("quality", {}).get("gate") or {}
    quality_ready = live_status == "DONE" and live_quality_gate.get("passed") is True
    quality_status = "LOCAL_QUALITY_READY" if quality_ready else (
        "QUALITY_PARTIAL" if live_status in {"DONE", "LOCAL_READY"} else "LIVE_MODEL_PENDING"
    )

    live_evidence_status = (
        "passed" if quality_ready
        else "quality_partial" if live_status in {"DONE", "LOCAL_READY"}
        else "external_pending"
    )
    evidence = {
        "evaluator": {**evaluator_file, "status": "passed" if evaluator_ok else "failed"},
        "artifact_manifest": {**artifacts_file, "status": "passed" if artifacts_ok else "failed"},
        "fault_matrix": {**matrix_file, "status": "passed" if matrix_ok else "failed"},
        "journey": {**journey_file, "status": "passed" if journey_ok else "failed"},
        "browser": {**browser_file, "status": "passed" if browser_ok else "failed"},
        "live_model": {**live_file, "status": live_evidence_status},
    }
    local_ready = evaluator_ok and artifacts_ok and matrix_ok and journey_ok and browser_ok
    external_pending = ["CI_REQUIRED", "DEPLOYMENT_REQUIRED", "RELEASE_CYCLE_REQUIRED"]
    if live_status not in {"DONE", "LOCAL_READY"}:
        external_pending.insert(0, "LIVE_MODEL_REQUIRED")
    return {
        "schema_version": "1.2",
        "status": "LOCAL_READY" if local_ready else "PARTIAL",
        "quality_status": quality_status,
        "quality_gate": {
            "status": "passed" if quality_ready else "not_met",
            "source": "live_model.metrics.quality.gate",
        },
        "evidence": evidence,
        "external_pending": external_pending,
        "limits": {
            "scorm_xapi": "basic_export_package_only",
            "sqlite_worker_topology": "one_web_process_plus_one_durable_worker",
        },
    }
