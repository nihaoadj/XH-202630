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
    # 覆盖率只来自普通审核逐知识点结果；Claim 指标不再输出任何覆盖口径。
    assert report.claim_metrics.claim_hallucination_rate < thresholds["hallucination_rate_max"]
    assert report.difficulty.accuracy >= thresholds["difficulty_match_accuracy_min"]
    assert report.ordinary_coverage.metric.status.value == "complete"
    assert report.ordinary_coverage.metric.value >= thresholds["knowledge_coverage_min"]

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


def test_coverage_comes_from_ordinary_review_targets_only():
    from app.models.reviews.quality_metrics import QualityMetricId

    report = _report()
    coverage = report.ordinary_coverage
    # 覆盖定义已升版：已覆盖冻结目标数 / 冻结目标总数，fixture 刻意保留 3 个缺失目标。
    assert coverage.planned_unit_total == 54
    assert coverage.covered_unit_total == 51
    assert coverage.metric.value == 51 / 54
    assert coverage.metric.metric_id is QualityMetricId.CORE_KNOWLEDGE_COVERAGE
    assert coverage.metric.status.value == "complete"
    assert coverage.missing_unit_total == 3
    assert coverage.observed_case_total == coverage.planned_case_total == 54
    # Claim 聚合不再携带任何覆盖字段。
    assert not hasattr(report.claim_metrics, "knowledge_coverage_rate")
    assert not hasattr(report.claim_metrics, "target_skill_total")


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
