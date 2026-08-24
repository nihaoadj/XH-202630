# 个性化纠错训练包功能更新任务书

## 目标

新增反馈专属文本资源“个性化纠错训练包”（界面名：薄弱点强化包）。它只在学习者完成正式反馈后可选，用于对 1–3 个已学习但未掌握的能力节点进行证据约束的强化学习。

```text
正式反馈 → 选择薄弱节点 → 冻结纠错快照 → 生成/审核/发布强化包
→ 阅读或 Tutor 辅导 → 下一批正式反馈
```

## 产品与安全边界

- 普通生成、Onboarding、报告页和互动课件来源选择器不能创建或选择该资源。
- 一个 Attempt 仅允许一个后续 Run；同一冻结选择重试复用 Run，变更节点必须完成新的反馈。
- 候选只能来自 `reinforce_weakness`，用户选择 1–3 个节点；无候选时入口禁用并说明原因。
- 难度由来源画像/批次锁定；`weak` 使用高脚手架，`learning` 使用中脚手架，不降低达标标准。
- Prompt 只接收目标节点、离散错误模式、策略、达标标准和冻结 Evidence。原题、答案、解析、题号、held-out 内容、自由文本和原始作答一律禁止进入 Prompt、产物、事件、日志或 Tutor。
- 模型、证据或审核失败时不发布通用模板，也不得替换成普通讲义。

## 接口与快照

`FeedbackLoopResult` additive 返回 `correction_package_option`。其候选、推荐节点和 snapshot hash 均由 `MasteryService` 的 `reinforce_weakness` 快照派生。

创建复用 `POST /api/feedback/followups/select`：

```json
{
  "option_id": "personalized-correction-package-v1",
  "learning_intent": "reinforce_weakness",
  "selected_skill_node_ids": ["1 至 3 个候选节点"],
  "next_generation_snapshot_hash": "服务端返回的 hash"
}
```

调用时必须省略 `resource_types` 与 `difficulty`。服务端校验 learner、Attempt、节点候选、快照和一次 follow-up 约束后，写入版本化 `correction_focus_snapshot` 到 Generation Job。普通 `/api/generation/jobs` 请求该资源类型返回 422 `FEEDBACK_ONLY_RESOURCE_TYPE`。

快照至少保存来源 Attempt/Decision/Run、画像与知识库版本、目标节点、难度、脚手架等级、reason codes、教学策略、达标标准和来源资源 ID。

## 内容与审核

专用 Agent 仅产生 Markdown，结构固定为：

```text
# 薄弱点强化包
## 本次强化目标
## 薄弱模式概览
## 强化单元：<节点>
### 错误模式 / 核心概念补救 / 正误对照 / 完整示例
### 引导式练习 / 同构练习 / 迁移练习
## 跨知识点综合挑战（多节点时）
## 参考答案与分层反馈
## 达标标准 / 后续复习动作 / 总结
```

全文目标 6,000–10,000 中文字符，硬上限 14,000。每个节点必须有完整强化单元，答案置于文末；练习仅用于学习，不进入正式题库或客观掌握判定。发布前仍执行现有来源、Claim 与审核门，并额外拒绝结构缺失、目标遗漏和任何泄漏。

## 前端与验证

反馈结果页将“继续学习这批资源”替换为“强化薄弱点”卡片；“学习新知识”保留原五类资源选择。强化包发布后在资源库可阅读、可使用现有 Tutor、可进入下一批正式反馈，但首版不派生互动课件。

验收必须覆盖普通入口绕过、无薄弱候选、0/4 个节点、伪造/过期快照、跨 learner/KB、重复 follow-up、失败不发布、泄漏扫描、再次反馈、Tutor、SQLite 重启、原五类回归和 390px 前端布局。
