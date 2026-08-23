"""Summarize the durable courseware fault tests from a JUnit report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.junit.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema_version": "1.0", "passed": False,
                                           "error": "junit_missing"}, ensure_ascii=False) + "\n", encoding="utf-8")
        return 1
    root = ET.parse(args.junit).getroot()
    cases = []
    for case in root.iter("testcase"):
        cases.append({
            "name": f"{case.attrib.get('classname', '')}.{case.attrib.get('name', '')}",
            "status": "failed" if case.find("failure") is not None or case.find("error") is not None
            else "skipped" if case.find("skipped") is not None else "passed",
        })
    # C1 categories are deliberately explicit.  A test name is not process
    # evidence: only the dedicated process suite can contribute, and each
    # case must eventually attach its durable-state evidence separately.
    categories = {
        "worker_claim_force_terminated": ["test_c1_process_worker_kill_then"],
        "worker_restart_checkpoint_recovery": ["test_c1_process_checkpoint_crash"],
        "live_lease_not_takeover": ["test_c1_process_worker_kill_then"],
        "expired_lease_takeover": ["test_c1_process_worker_kill_then"],
        "heartbeat_lost": ["test_c1_process_heartbeat_loss"],
        "duplicate_delivery": ["test_c1_process_duplicate_delivery"],
        "unexpected_concurrent_claim": ["test_c1_process_unexpected_concurrent_claim"],
        "sqlite_busy_wait": ["test_c1_process_sqlite_busy"],
        "sqlite_temporary_disconnect": ["test_c1_process_sqlite_temporary_disconnect"],
        "checkpoint_then_crash": ["test_c1_process_checkpoint_crash"],
        "artifact_before_release_commit": ["test_c1_process_artifact_before_release_commit"],
        "release_commit_failure": ["test_c1_process_release_commit_failure"],
        "outbox_replay": ["test_c1_process_outbox_replay"],
        "graceful_shutdown": ["test_c1_process_worker_script_handles_graceful_shutdown"],
        "scene_retry_replay": ["test_c1_process_scene_retry_replay"],
        "failed_candidate_keeps_release": ["test_c1_process_failed_candidate_keeps_previous_release_pointer"],
        "sqlite_safe_backup": ["test_c1_process_safe_backup"],
        "backup_web_worker_restore": ["test_c1_process_safe_backup"],
    }
    result = {
        name: {
            "matched": [item for item in cases if any(token in item["name"] for token in tokens)],
            "required": True,
            "evidence_type": "process" if tokens else "missing",
            "evidence": [],
        }
        for name, tokens in categories.items()
    }
    for item in result.values():
        item["evidence"] = [
            {"testcase": case["name"], "assertion_source": "pytest_process_test"}
            for case in item["matched"] if case["status"] == "passed"
        ]
    category_failures = []
    for name, item in result.items():
        if not item["matched"]:
            category_failures.append(f"{name}:no_match")
        elif any(case["status"] != "passed" for case in item["matched"]):
            category_failures.append(f"{name}:non_passed")
        if not item["evidence"]:
            category_failures.append(f"{name}:evidence_missing")
    payload = {"schema_version": "1.1", "case_count": len(cases),
               "passed": bool(cases) and not category_failures and all(item["status"] == "passed" for item in cases),
               "categories": result, "category_failures": category_failures}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
