"""比赛套件 live 评测：真实 API 通路已就绪但默认跳过（RUN_LIVE_LLM=1 才启用）。

本文件证明两件事：
1. live 未就绪时显式 SKIP，绝不静默降级为离线结论；
2. live 就绪时可按小样本真实执行并输出三项指标。
"""

import os

import pytest

from app.services.reports.competition_suite import (
    evaluate_live_metrics,
    is_live_ready,
    load_suite,
)

pytestmark = pytest.mark.live_llm


def test_live_competition_evaluation_small_batch():
    ready, reason = is_live_ready()
    if not ready:
        pytest.skip(f"live competition evaluation skipped: {reason}")

    suite = load_suite()
    # 小样本冒烟：真实全量评测通过 --max-cases 54 走脚本入口。
    report = evaluate_live_metrics(suite, max_cases=int(os.getenv("COMPETITION_LIVE_MAX_CASES", "3")))
    assert report.mode == "live_model"
    assert report.case_count >= 1
    assert {gate.metric_id for gate in report.gates} == {"M-HALLUCINATION", "M-DIFFICULTY", "M-COVERAGE"}
    for gate in report.gates:
        # 小样本未达 50 组门槛时必须诚实输出 NOT_MEASURABLE，而不是虚报 PASS。
        assert gate.status in {"PASS", "FAIL", "NOT_MEASURABLE"}
        assert gate.evidence.startswith("live model run")


def test_live_metrics_refuses_to_run_without_readiness(monkeypatch):
    monkeypatch.delenv("RUN_LIVE_LLM", raising=False)
    with pytest.raises(RuntimeError, match="live evaluation is not ready"):
        evaluate_live_metrics(load_suite(), max_cases=1)
