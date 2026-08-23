"""Deterministic checks for a recorded courseware release observation window."""

from __future__ import annotations

from datetime import datetime
from typing import Any


LEARNING_DOCUMENT_TYPES = ("text", "practice", "assessment", "case_study", "checklist")
REQUIRED_METRICS = ("success_rate", "fallback_rate", "retry_count", "input_tokens", "output_tokens", "total_tokens", "cost", "latency_ms", "recovery")
SOURCE_HARD_GATE_CODES = {"EVIDENCE_PROVENANCE_INVALID", "UNKNOWN_SOURCE_BLOCK_REF", "COURSEWARE_SOURCE_TRACE_FAILED"}


def _valid_time(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _observation_missing(metadata: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    if not events:
        missing.append("OBSERVATION_EVIDENCE_MISSING")
    if not _valid_time(metadata.get("started_at")) or not _valid_time(metadata.get("ended_at")):
        missing.append("OBSERVATION_WINDOW_MISSING")
    elif metadata["started_at"] >= metadata["ended_at"]:
        missing.append("OBSERVATION_WINDOW_INVALID")
    if not all(isinstance(metadata.get(name), str) and metadata[name] for name in ("build_version", "config_version", "environment", "evidence_export_hash")):
        missing.append("OBSERVATION_METADATA_MISSING")
    if not metadata.get("evidence_paths"):
        missing.append("OBSERVATION_EVIDENCE_PATH_MISSING")
    metrics = metadata.get("metrics") or {}
    if not all(isinstance(metrics.get(name), (int, float, dict)) for name in REQUIRED_METRICS):
        missing.append("OBSERVATION_METRICS_MISSING")
    learning = metadata.get("learning_documents_regression") or {}
    if not all(learning.get(name) == "passed" for name in LEARNING_DOCUMENT_TYPES):
        missing.append("LEARNING_DOCUMENT_REGRESSION_UNMEASURED")
    return missing


def assess_release_cycle(events: list[dict[str, Any]], *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess sanitized events by run, never mistaking an empty smoke for a cycle."""
    metadata = metadata or {}
    ordered = sorted(events, key=lambda item: (str(item.get("run_id") or ""), int(item.get("event_sequence") or 0)))
    violations = _observation_missing(metadata, ordered)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in ordered:
        run_id = str(event.get("run_id") or "")
        if not run_id:
            violations.append("EVENT_RUN_ID_MISSING")
            continue
        grouped.setdefault(run_id, []).append(event)

    releases: list[str] = []
    release_hashes: list[str] = []
    for run_id, run_events in grouped.items():
        sequences = [int(item.get("event_sequence") or 0) for item in run_events]
        if sequences != list(range(1, len(sequences) + 1)):
            violations.append(f"EVENT_SEQUENCE_GAP:{run_id}")
        rejected = False
        seen_release_keys: set[tuple[str, str]] = set()
        for event in run_events:
            payload = event.get("payload") or {}
            status = str(event.get("status") or "")
            stage = str(event.get("stage") or "")
            if stage in {"quality_gate", "source_trace", "admission"} and status in {"rejected", "failed", "quarantined"}:
                rejected = True
            if str(payload.get("code") or "") in SOURCE_HARD_GATE_CODES:
                violations.append("SOURCE_MISMATCH")
            if stage == "publishing" and status == "released":
                release_id = str(payload.get("release_id") or event.get("release_id") or "")
                candidate_id = str(payload.get("candidate_id") or event.get("candidate_id") or release_id)
                if not release_id:
                    violations.append(f"RELEASE_ID_MISSING:{run_id}")
                    continue
                if rejected:
                    violations.append("HARD_GATE_BYPASS")
                key = (candidate_id, release_id)
                if key in seen_release_keys:
                    violations.append("DUPLICATE_RELEASE")
                seen_release_keys.add(key)
                releases.append(release_id)
                if payload.get("artifact_hash"):
                    release_hashes.append(str(payload["artifact_hash"]))

    violations = sorted(set(violations))
    complete_inputs = not _observation_missing(metadata, ordered)
    observation_mode = str(metadata.get("observation_mode") or "SMOKE_ONLY")
    complete = complete_inputs and observation_mode == "COMPLETE" and not violations
    return {
        "schema_version": "1.1",
        "status": "LOCAL_READY" if complete_inputs and not violations else "PARTIAL",
        "observation_status": "COMPLETE" if complete else "EXTERNAL_PENDING",
        "observation_mode": observation_mode,
        "event_count": len(ordered),
        "released_release_ids": releases,
        "violations": violations,
        "window": {"started_at": metadata.get("started_at"), "ended_at": metadata.get("ended_at"), "timezone": metadata.get("timezone")},
        "build": {"build_version": metadata.get("build_version"), "config_version": metadata.get("config_version")},
        "metrics": {key: (metadata.get("metrics") or {}).get(key) for key in REQUIRED_METRICS},
        "artifacts": {"release_hashes": sorted(set(release_hashes)), "evidence_paths": list(metadata.get("evidence_paths") or []), "evidence_export_hash": metadata.get("evidence_export_hash")},
        "learning_documents_regression": {name: (metadata.get("learning_documents_regression") or {}).get(name, "not_measured") for name in LEARNING_DOCUMENT_TYPES},
        "required_metrics": list(REQUIRED_METRICS),
    }
