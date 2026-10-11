"""Execution failures and opt-in isolation are contracts of the suite runner."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("project_test_runner", ROOT / "scripts/run_tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def _suite(command, timeout=10):
    return {"id": "probe", "purpose": "test probe", "evidence_type": "deterministic",
            "command": command, "timeout_seconds": timeout}


def test_profiles_are_deduplicated_and_invalid_suite_rejected():
    catalog = runner.load_catalog()
    suites = runner.select_suites(catalog, "regression", ["competition"])
    assert [item["id"] for item in suites].count("competition") == 1
    with pytest.raises(ValueError):
        runner.select_suites(catalog, None, ["missing"])


def test_live_switches_cannot_be_inherited(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    monkeypatch.setenv("COURSEWARE_LIVE_EVAL", "1")
    env = runner.safe_environment(tmp_path)
    result = runner.run_suite(_suite([sys.executable, "-c",
        "import os; assert os.environ['RUN_LIVE_LLM']=='0'; assert os.environ['COURSEWARE_LIVE_EVAL']=='0'"]), tmp_path, env)
    assert result["status"] == "PASS"
    assert os.environ["RUN_LIVE_LLM"] == "1"  # The caller's environment is preserved.


@pytest.mark.parametrize(("code", "status"), [(0, "PASS"), (7, "FAIL")])
def test_exit_status_is_preserved(tmp_path, code, status):
    result = runner.run_suite(_suite([sys.executable, "-c", f"raise SystemExit({code})"]),
                              tmp_path, runner.safe_environment(tmp_path))
    assert (result["status"], result["exit_code"]) == (status, code)


def test_start_error_and_timeout_cannot_pass(tmp_path):
    env = runner.safe_environment(tmp_path)
    result = runner.run_suite(_suite([str(tmp_path / "missing-program")]), tmp_path, env)
    assert result["status"] == "ERROR" and result["exit_code"] is None
    result = runner.run_suite(_suite([sys.executable, "-c", "import time; time.sleep(30)"], .05), tmp_path, env)
    assert result["status"] == "TIMEOUT"


def test_frontend_inventory_is_complete_and_disjoint():
    groups = runner.load_catalog()["frontend_groups"]
    registered = [item for files in groups.values() for item in files]
    root = ROOT / "frontend/tests"
    actual = {item.relative_to(root).as_posix() for item in root.rglob("*.test.mjs")
              if "test-results" not in item.parts}
    assert len(registered) == len(set(registered))
    assert set(registered) == actual
    assert len(groups["browser"]) == 13
    assert {"historyUiBrowser.test.mjs", "reportUiBrowser.test.mjs",
            "userProfileUiBrowser.test.mjs", "profileRequestBrowser.test.mjs",
            "motionBrowser.test.mjs"} <= set(groups["browser"])


def test_invalid_junit_is_an_error_and_does_not_abort_reporting(tmp_path):
    xml = tmp_path / "probe.xml"
    code = f"from pathlib import Path; Path({str(xml)!r}).write_text('<broken>', encoding='utf-8')"
    result = runner.run_suite(_suite([sys.executable, "-c", code]), tmp_path, runner.safe_environment(tmp_path))
    assert result["status"] == "ERROR" and result["junit_error"] == "invalid_xml"


def test_fail_fast_keeps_unexecuted_suite_visible(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "run_suite", lambda suite, output, env: {
        "id": suite["id"], "evidence_type": suite["evidence_type"], "status": "FAIL",
        "exit_code": 9, "duration_seconds": 0})
    output = tmp_path / "run"
    assert runner.main(["--profile", "quick", "--fail-fast", "--output", str(output)]) == 1
    report = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in report["results"]] == ["FAIL", "NOT_RUN", "NOT_RUN"]
    with pytest.raises(SystemExit) as error:
        runner.main(["--profile", "quick", "--output", str(output)])
    assert error.value.code == 2
