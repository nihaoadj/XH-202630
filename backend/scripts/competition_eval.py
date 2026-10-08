"""离线/实时两种模式执行比赛金标评测套件，输出三项指标报告 JSON。

- offline（默认）：不调用大模型，Claim verdict 来自人工金标标注，难度预测来自确定性策略。
- live：走生产生成链路真实评测；要求 RUN_LIVE_LLM=1 与真实 LLM_API_KEY，
  未就绪时显式报告 SKIP 并以退出码 2 结束，不静默降级为离线结论。

报告是本地运行产物，不要提交到仓库。

用法（从仓库根目录）：
    python backend/scripts/competition_eval.py --output backend/competition-eval-report.json
    python backend/scripts/competition_eval.py --mode live --max-cases 54
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.reports.competition_suite import (  # noqa: E402
    default_suite_path,
    evaluate_competition_metrics,
    evaluate_live_metrics,
    is_live_ready,
    load_suite,
)

LIVE_NOT_READY_EXIT_CODE = 2


def _render_report(report) -> dict:
    return {
        "suite_id": report.suite_id,
        "suite_version": report.suite_version,
        "mode": report.mode,
        "case_count": report.case_count,
        "evidence_scope": report.evidence_scope,
        "source_snapshot_hash": report.source_snapshot_hash,
        "suite_data_hash": report.suite_data_hash,
        "selected_case_count": report.selected_case_count,
        "completed_generation_count": report.completed_generation_count,
        "failed_case_count": report.failed_case_count,
        "independent_quality_review": report.independent_quality_review,
        "case_results": report.case_results,
        "metrics": {
            "hallucination_rate": report.claim_metrics.claim_hallucination_rate,
            "factual_claim_total": report.claim_metrics.factual_claim_total,
            "unsupported_claim_total": report.claim_metrics.unsupported_claim_total,
            "knowledge_coverage_rate": report.claim_metrics.knowledge_coverage_rate,
            "covered_skill_total": report.claim_metrics.covered_skill_total,
            "target_skill_total": report.claim_metrics.target_skill_total,
            "difficulty_match_accuracy": report.difficulty.accuracy,
            "difficulty_correct_total": report.difficulty.correct_total,
            "difficulty_case_total": report.difficulty.case_total,
            "difficulty_confusion_matrix": report.difficulty.confusion_matrix,
        },
        "gates": [gate.as_dict() for gate in report.gates],
        "official_gates": [gate.as_dict() for gate in report.official_gates],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the competition gold evaluation suite")
    parser.add_argument("--suite", default=str(default_suite_path()), help="path to suite.json")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--max-cases", type=int, default=None, help="live 模式限制执行用例数")
    parser.add_argument("--require-official", action="store_true", help="正式质量证据不足时退出 2；离线回归不能满足")
    parser.add_argument("--output", default=str(BACKEND_ROOT / "competition-eval-report.json"), help="report output path")
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be a positive integer")

    if args.mode == "live":
        ready, reason = is_live_ready()
        if not ready:
            print(f"SKIP: live evaluation is not ready ({reason}); no model was called")
            return LIVE_NOT_READY_EXIT_CODE

    suite = load_suite(args.suite)
    if args.mode == "live":
        report = evaluate_live_metrics(suite, max_cases=args.max_cases)
    else:
        report = evaluate_competition_metrics(suite)

    output = Path(args.output)
    if args.mode == "live":
        output = output.with_name(output.stem + "-live" + output.suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_render_report(report), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"suite: {report.suite_id} ({report.mode})")
    print(f"cases: {report.case_count}")
    print(f"evidence: {report.evidence_scope}")
    print(f"generation: {report.completed_generation_count}/{report.selected_case_count}; failed={report.failed_case_count}")
    for gate in report.gates:
        value = "n/a" if gate.actual_value is None else f"{gate.actual_value:.4f}"
        print(f"{gate.metric_id}: value={value} threshold={gate.official_threshold} status={gate.status} evidence={gate.evidence}")
    print(f"report written to: {output}")
    failed = [gate for gate in report.gates if gate.status == "FAIL"]
    if failed or report.failed_case_count:
        return 1
    if args.require_official and any(gate.status != "PASS" for gate in report.official_gates):
        return 2
    if args.mode == "live" and any(gate.status == "NOT_MEASURABLE" for gate in report.gates):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
