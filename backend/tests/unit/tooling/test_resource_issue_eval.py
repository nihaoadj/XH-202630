"""Frozen resource_issue_v1 eval gate: offline engine replay, zero model calls."""

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts/resource_issue_eval.py"
spec = importlib.util.spec_from_file_location("resource_issue_eval", PATH)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_manifest_runs_production_engine_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("offline attempted network"))
    output = tmp_path / "report.json"
    assert evaluation.main(["--mode", "offline", "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS" and len(result["results"]) >= 60
    assert result["real_model_quality"] == "NOT_RUN_LIVE" and result["end_to_end"] == "NOT_RUN"
    assert result["evidence_type"] == "offline_scripted_policy"
    assert all(row["passed"] for row in result["results"])
    with pytest.raises(SystemExit) as error:
        evaluation.main(["--output", str(output)])
    assert error.value.code == 2


def test_manifest_covers_every_resource_type_and_label():
    data = json.loads(evaluation.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0" and len(data["cases"]) >= 60
    by_type = Counter(c["resource_type"] for c in data["cases"])
    for resource_type in ("讲义", "实操指南", "分阶测试题", "案例分析", "复习清单", "个性化纠错训练包"):
        assert by_type[resource_type] >= 10
    labels = Counter(c["label"] for c in data["cases"])
    for label in ("正确可批准", "真实缺陷", "证据外增补", "全修复", "部分未修复",
                  "误报纠正", "新缺陷重开", "同产物", "无效核销"):
        assert labels[label] == 6
    # 讲义 has no deterministic structure/projection gate: its tenth scenario is
    # the coverage gate, so the program gate appears for the other five types.
    assert labels["专业硬门"] == 5 and labels["专业覆盖门"] == 1


def test_fixture_tamper_and_duplicate_case_fail_closed(tmp_path):
    data = json.loads(evaluation.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    data["cases"][0]["resource"]["content_text"] = "modified"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        evaluation.evaluate(path)
    data = json.loads(evaluation.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    data["cases"][0] = data["cases"][1]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        evaluation.evaluate(path)
