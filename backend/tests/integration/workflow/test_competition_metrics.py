"""比赛三项指标离线评测端到端：金标套件 -> 指标计算 -> 比赛门结论。"""

from __future__ import annotations

import json

from app.services.reports.competition_suite import (
    evaluate_competition_metrics,
    load_suite,
)


def _report():
    return evaluate_competition_metrics(load_suite())


def test_offline_gold_metrics_meet_competition_thresholds():
    report = _report()
    thresholds = load_suite()["competition_thresholds"]

    # 比赛口径：幻觉率 < 5%、难度适配 >= 85%、核心知识点覆盖率 >= 90%。
    assert report.claim_metrics.claim_hallucination_rate < thresholds["hallucination_rate_max"]
    assert report.difficulty.accuracy >= thresholds["difficulty_match_accuracy_min"]
    assert report.claim_metrics.knowledge_coverage_rate >= thresholds["knowledge_coverage_min"]

    # 样本量达到比赛要求的 50 组后，门状态必须是可测量结论而非 NOT_MEASURABLE。
    assert report.case_count >= thresholds["minimum_case_count"]
    assert report.mode == "offline_gold"
    assert {gate.status for gate in report.gates} == {"PASS"}
    assert {gate.metric_id for gate in report.gates} == {"M-HALLUCINATION", "M-DIFFICULTY", "M-COVERAGE"}
    for gate in report.gates:
        assert gate.sample_count == report.case_count
        # 离线金标结论必须显式标注 live 评测前提，不得冒充真实模型数值。
        assert "RUN_LIVE_LLM=1" in gate.evidence


def test_difficulty_confusion_matrix_localizes_background_gap():
    report = _report()
    # 系统策略仅按目标节点 tier 定难度：data 背景 tier1 画像期望中级而被预测为初级，
    # 混淆矩阵应精确定位这 6 个低估用例，其余 48 组匹配。
    assert report.difficulty.case_total == 54
    assert report.difficulty.correct_total == 48
    assert report.difficulty.accuracy == 48 / 54
    matrix = report.difficulty.confusion_matrix
    assert matrix["中级"]["初级"] == 6
    assert matrix["初级"]["初级"] == 12
    assert matrix["中级"]["中级"] == 18
    assert matrix["高级"]["高级"] == 18


def test_non_factual_claims_excluded_from_hallucination_denominator():
    report = _report()
    claims_payload = load_suite()["claims_payload"]
    non_factual_total = sum(
        1 for item in claims_payload["claims"] if item["claim_type"] != "factual"
    )
    assert non_factual_total == 4
    # 分母只含事实 Claim；分子是 contradicted + not_in_evidence。
    assert report.claim_metrics.factual_claim_total == 74
    assert report.claim_metrics.unsupported_claim_total == 3
    assert report.claim_metrics.claim_hallucination_rate == 3 / 74


def test_coverage_counts_target_nodes_with_supported_claims():
    report = _report()
    assert report.claim_metrics.target_skill_total == 13
    assert report.claim_metrics.covered_skill_total == 13
    assert report.claim_metrics.knowledge_coverage_rate == 1.0


def test_metric_report_serializes_for_submission():
    report = _report()
    payload = json.dumps(
        {
            "suite_id": report.suite_id,
            "mode": report.mode,
            "case_count": report.case_count,
            "claim_metrics": report.claim_metrics.model_dump(mode="json"),
            "difficulty": report.difficulty.model_dump(mode="json"),
            "gates": [gate.as_dict() for gate in report.gates],
        },
        ensure_ascii=False,
    )
    assert "M-HALLUCINATION" in payload
    assert "offline_gold" in payload
