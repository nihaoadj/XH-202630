# 比赛评测

使用 RAG 工程技能培训方向。当前冻结套件是 [suite_v2.json](../../backend/tests/fixtures/competition/suite_v2.json)，包括三类背景、18 份虚构画像和 54 个唯一用例。每个用例固定输入、目标节点和资源类型。来源文件、章节及摘要见同目录的 [sources.json](../../backend/tests/fixtures/competition/sources.json)。

## 指标与门槛

| 指标 | 计算 | 目标 |
|---|---|---|
| 幻觉率 | 最终发布叶子资源的 `(contradicted + not_in_evidence) / factual_claim_total`，全体事实 Claim 合并后计算 | <5% |
| 难度适配准确率 | 期望难度与实际难度一致的用例数 ÷ 全部选中用例。失败和未生成用例保留在分母 | ≥85% |
| 核心知识覆盖率 | 有效普通审核判为 covered 的 `(case_id, target_id)` 数 ÷ 全部选中用例的冻结目标数 | ≥90% |

判定不完整、证据不足或缺少正式样本时，按指标标记不可测。报告保留统计分母、样本失败与未覆盖项。金标期望难度用于策略回归，独立复核还要按先修、术语、任务复杂度和可执行性判断实际正文难度。

## 执行方式

离线计算与脚本化工作流回放：

```powershell
python scripts/run_tests.py --suite competition
python -m pytest backend/tests/integration/workflow/test_competition_replay.py
```

金标使用冻结 Claim 标注、编排策略和普通审核模拟结果。回放通过实际工作流编排保存输入、协同轨迹和产物，但使用 Scripted Agent。两者的真实生成数均为 0。演示可选取至少两组回放，标明证据类型。

更改来源或标注后，审阅受影响的用例、章节、行号和原始出处，再用 `python backend/scripts/competition_snapshot.py` 显式更新来源快照。从测试套件重新核对哈希和金标，运行中遇到漂移应停止。

## 真实结果与正式判定

只有用户明确授权且有效凭据、预算和隔离环境就绪时才用 live 模式。以下是在限定授权下运行 3 个样本的 PowerShell 示例：

```powershell
$env:RUN_LIVE_LLM = "1"
try {
    python backend/scripts/competition_eval.py --mode live --max-cases 3 --output output/test-runs/competition-smoke/report.json
} finally {
    Remove-Item Env:RUN_LIVE_LLM
}
```

真实结果自动使用 `-live` 后缀。小样本只验证调用路径。正式范围至少需要 50 个完成用例，覆盖三类背景及三类资源，并有冻结来源、完整事实判定与独立复核。独立复核针对最终发布版本，记录每例资源版本和 output hash、证据与事实判断、难度理由、覆盖和分歧裁决。

CLI 的 `gates` 记录所选运行模式的结果，`official_gates` 表示正式判定；缺完整证据时为 `NOT_MEASURABLE`。退出码 0 表示本次运行检查通过，1 表示运行或指标失败，2 表示真实模式未就绪或所要求的正式证据不足。真实调用、失败、复验和费用按 [评测记录约定](../evaluations/README.md) 留档。
