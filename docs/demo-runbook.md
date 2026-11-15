# 比赛演示手册

部署操作见 [部署指南](deployment.md)，金标与正式质量口径见 [比赛评测](testing/competition.md)。

## 演示前检查

1. 使用独立演示数据，完成数据库迁移演练。确认 Web、文本 Worker 和课件 Worker 就绪，默认知识库可检索。
2. 启用新轮次创建，确认 `GET /api/generate/capabilities` 返回 `round_creation_enabled=true`。准备有权限读取的画像、发布资源和冻结测评题组。
3. 检查 P0-09 preflight 为 `READY`、离线 Scenario A–J 均为 `PASS`，并在目标环境完成实际浏览器闭环。可预先准备固定资源供断网或供应商异常时回放。
4. 正式放行还需有效的 P0-09 runtime 证据。当前源码探针的 `formal_attempt_api` 与 `claim_evidence_details_used` 仍匹配旧前端标记，无法据此放行现行轮次。运行时检查使用隔离演示库，它会执行正常应用初始化和对账。

```powershell
npm --prefix frontend run build
python scripts/p0_09_preflight.py --output output/test-runs/demo/preflight.json
python scripts/run_p0_09_acceptance.py --offline --output output/test-runs/demo/offline.json
```

离线模式总状态可能是 `PARTIAL`，逐项核对 A–J。`DEGRADED` 仅用于排障或受控预演。按 [测试指南](testing/README.md) 选相关专项，真实 Provider 演示须获得明确授权并单独留档。

## 演示顺序

| 操作 | 核对事实 |
|---|---|
| 创建学习方向并完成诊断 | 推荐的学习阶、主节点和画像归属 |
| 创建资源轮次 | 轮次、阶段、成员、实际 Run ID，以及轨迹中的冻结来源 |
| 展示普通审核与 Claim | 版本化的问题和证据，必要时展示补检与定向返工 |
| 阅读已发布版本，开启 Tutor 或课件 | 查看来源、课程运行效果与实际发布版本 |
| 提交阶段测评，确认下一步 | 持久化节点成绩、反馈建议及用户确认后创建的新任务 |
| 查看学习历史和学情报告 | 轮次、掌握度、路径及资源质量来源，未测数据正确标示 |

## 故障演示

- **断开 SSE 或刷新页面**。保留 Run ID，用 timeline 与事件游标恢复已持久化记录。
- **证据不足或审核失败**。用失败 fixture 展示阻断原因，核对当前版本的发布状态。
- **课件 Worker 中断**。在隔离环境重启 Worker，核对 checkpoint、候选及 release，验证同一任务未重复发布。
- **文本任务中断**。检查最终状态与失败原因，在生成页按任务或资源显式重试，验证新 Run 与已发布资源版本。

保存本次放行清单、实际运行 ID 和脱敏日志。复用离线回放时在演示中说明数据来源。真实测试按 [评测记录约定](evaluations/README.md) 归档。
