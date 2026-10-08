"""A full-backend JUnit report must not dilute dedicated process evidence."""
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location(
    "courseware_fault_matrix_tool", ROOT / "backend/scripts/courseware_fault_matrix.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

PROCESS_MODULE = "backend.tests.e2e.courseware.test_c1_process_fault_matrix"
PROCESS_TESTS = [
    "test_c1_process_worker_kill_then_lease_takeover_and_checkpoint_recovery",
    "test_c1_process_checkpoint_crash_is_replayed_once_without_duplicate_side_effect",
    "test_c1_process_sqlite_busy_waits_then_has_one_claim_winner",
    "test_c1_process_heartbeat_loss_stops_owner_and_allows_expired_lease_recovery",
    "test_c1_process_safe_backup_and_restored_worker_start",
    "test_c1_process_sqlite_temporary_disconnect_then_fresh_worker_recovers",
    "test_c1_process_worker_script_handles_graceful_shutdown",
    "test_c1_process_duplicate_delivery_has_one_outbox_effective_task",
    "test_c1_process_unexpected_concurrent_claim_has_one_winner",
    "test_c1_process_artifact_before_release_commit_has_no_release_pointer",
    "test_c1_process_release_commit_failure_blocks_candidate_without_pointer",
    "test_c1_process_outbox_replay_keeps_one_delivered_row",
    "test_c1_process_scene_retry_replay_has_one_scene_revision",
    "test_c1_process_failed_candidate_keeps_previous_release_pointer",
]


def _process_suite(module=PROCESS_MODULE):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for name in PROCESS_TESTS:
        ET.SubElement(suite, "testcase", classname=module, name=name)
    return root, suite


def _summarize(monkeypatch, tmp_path, root):
    junit = tmp_path / "full-backend.xml"
    report = tmp_path / "matrix.json"
    ET.ElementTree(root).write(junit, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["fault-matrix", "--junit", str(junit), "--output", str(report)])
    exit_code = tool.main()
    return exit_code, json.loads(report.read_text(encoding="utf-8"))


def test_unrelated_failures_and_skips_do_not_pollute_process_matrix(monkeypatch, tmp_path):
    root, suite = _process_suite()
    for status in ("skipped", "failure", "error"):
        unrelated = ET.SubElement(suite, "testcase", classname="backend.tests.live.test_other",
                                  name=PROCESS_TESTS[0])
        ET.SubElement(unrelated, status)
    code, report = _summarize(monkeypatch, tmp_path, root)
    assert code == 0 and report["passed"]
    assert (report["case_count"], report["process_case_count"], report["ignored_case_count"]) == (17, 14, 3)
    assert len(report["categories"]) == 18 and not report["category_failures"]
    assert all(item["evidence"] and all(case["name"].startswith(PROCESS_MODULE + ".")
               for case in item["matched"]) for item in report["categories"].values())


@pytest.mark.parametrize("module", ["backend.tests.unit.test_other",
    "backend.tests.e2e.courseware.test_c1_process_fault_matrix_extra", ""])
def test_same_names_outside_exact_process_module_cannot_supply_evidence(monkeypatch, tmp_path, module):
    root, _ = _process_suite(module)
    code, report = _summarize(monkeypatch, tmp_path, root)
    assert code == 1 and not report["passed"]
    assert report["process_case_count"] == 0 and report["ignored_case_count"] == 14
    assert all(not item["matched"] and not item["evidence"] for item in report["categories"].values())


@pytest.mark.parametrize("status", ["failure", "error", "skipped"])
def test_nonpassed_dedicated_process_case_blocks_matrix(monkeypatch, tmp_path, status):
    root, suite = _process_suite()
    ET.SubElement(suite[0], status)
    code, report = _summarize(monkeypatch, tmp_path, root)
    assert code == 1 and not report["passed"]
    assert report["process_case_count"] == 14 and report["category_failures"]


def test_missing_required_process_category_blocks_matrix(monkeypatch, tmp_path):
    root, suite = _process_suite()
    suite.remove(suite[-1])
    code, report = _summarize(monkeypatch, tmp_path, root)
    assert code == 1 and not report["passed"]
    assert "failed_candidate_keeps_release:no_match" in report["category_failures"]


def test_empty_junit_cannot_pass(monkeypatch, tmp_path):
    root = ET.Element("testsuites")
    code, report = _summarize(monkeypatch, tmp_path, root)
    assert code == 1 and not report["passed"]
    assert report["case_count"] == report["process_case_count"] == report["ignored_case_count"] == 0
