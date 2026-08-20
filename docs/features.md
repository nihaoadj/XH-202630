# 功能文档

> 项目编号：XH-202630
> 项目名称：领域知识个性化生成与多智能体协同决策系统
> 文档版本：2.1
> 文档更新时间：2026-08-16
> 文档定位：说明当前系统已经落地的能力边界、核心流程和页面职责。

## 1. 当前产品定位

系统面向特定学习方向的个性化学习资源生成场景，围绕“用户资料 -> 入门问卷 -> 能力诊断 -> 资源生成 -> 反馈复盘”构建最小闭环。

当前阶段重点不是扩展复杂的多 Agent 工作流编排，而是先把以下基础支撑打通：

- 用户长期稳定资料独立建模
- 问卷只采集当前学习方向的动态信息
- 诊断结果可用于后续资源生成
- 资源生成改为异步任务模式
- 学习过程可通过时间线统一查看

## 2. 当前闭环

```text
创建用户资料
-> 选择学习方向
-> 填写通用问卷
-> 生成初始画像
-> 进入能力诊断
-> 发起资源生成任务
-> 查看资源列表或下载资源
-> 提交学习反馈
-> 查看学习历史时间线与学习报告
```

## 3. 已完成的核心重构

### 3.1 用户资料与问卷拆分

当前已经完成职责拆分：

- 用户资料负责维护稳定信息：
  `display_name`、`identity`、`education`、`major`、`job_role`、`experience_years`
- 通用问卷只负责维护当前学习方向下的动态信息：
  `learning_goals`、`learning_modes`、`difficulty_preference`、`weekly_time_budget`

已经移出问卷的字段：

- `identity`
- `education`
- `major`
- `desired_resource_types`

### 3.2 用户 ID 自动生成

当前用户资料创建流程中：

- `user_id` 由后端自动生成
- 前端不应让用户手动填写或编辑 `user_id`

### 3.3 异步资源生成

资源生成已经切换为异步任务模式：

- 创建任务：`POST /api/generate/jobs`
- 查询任务列表：`GET /api/generate/jobs?learner_id={learner_id}`
- 查询状态：`GET /api/generate/jobs/{run_id}`
- 查看结果：`GET /api/resources/{learner_id}?run_id={run_id}`
- 下载文件：`GET /api/resources/file/{resource_id}`

同步生成接口 `POST /api/generate/` 已移除。

当前前端已补充任务维度展示：

- 资源生成页默认展示当前 `running/queued` 任务
- 支持切换查看历史成功任务
- 任务内再选择具体资源阅读或下载

### 3.4 学习历史时间线

系统已经提供学习历史统一入口：

- `GET /api/learning-history/{learner_id}/timeline`

该接口用于把问卷、诊断、资源生成任务、反馈等过程串成一条时间线，供前端做“历史学习记录”页面。

## 4. 当前功能模块

| 编号 | 模块 | 当前状态 | 说明 |
|---|---|---|---|
| F01 | 用户资料管理 | 已完成基础版 | 独立管理用户稳定信息 |
| F02 | 入门问卷 | 已完成基础版 | 面向学习方向采集动态信息 |
| F03 | 初始画像生成 | 已完成基础版 | 根据问卷更新学习者画像 |
| F04 | 能力诊断 | 已完成基础版 | 返回能力结果与推荐路径 |
| F05 | 异步资源生成 | 已完成基础版 | 通过任务方式触发生成 |
| F06 | 资源列表与下载 | 已完成基础版 | 支持按 `run_id` 过滤、按任务切换与下载 |
| F07 | 学习反馈 | 已完成 P0-07 闭环 | Attempt、知识状态、画像版本、路径 mutation 与后续生成均可持久化追溯 |
| F08 | 学习历史时间线 | 已完成基础版 | 汇总学习全过程 |
| F09 | 学习报告 | 已完成基础版 | 提供学习结果摘要 |

## 5. 页面职责

| 页面 | 建议路由 | 当前职责 |
|---|---|---|
| 首页 | `/` | 系统入口 |
| 用户资料页 | `/user-profile` | 创建和维护用户稳定资料 |
| 新建学习方向页 | `/onboarding` | 选择方向、填写问卷、进入诊断 |
| 资源生成页 | `/generate` | 提交生成任务、默认查看当前任务并切换历史任务 |
| 资源列表页 | `/resources` | 查看和下载本次或历史资源 |
| 历史学习记录页 | `/learning-history` | 按时间线查看问卷、诊断、生成记录 |
| 反馈页 | `/feedback` | 按任务完成测评、查看反馈历史并主动重新生成 |
| 报告页 | `/report` | 查看学习报告 |

## 6. 当前前端交互约定

### 6.1 用户资料

- 用户先创建或选择用户资料
- 不展示 `user_id` 输入框
- 用户仅维护自己可理解的资料项

### 6.2 问卷

- 问卷不再采集身份、学历、专业等长期信息
- 问卷仅采集本次学习方向相关的动态偏好和目标

### 6.3 资源生成

推荐交互方式如下：

```text
用户点击“生成”
-> 页面提示“资源正在生成”
-> 当前页持续轮询当前任务状态
-> 默认定位当前生成任务
-> 用户可切换查看历史成功任务
-> 在任务内选择资源阅读或下载
```

这也是当前文档和接口设计默认支持的前端模式。

## 7. 当前数据库侧对应关系

已经与当前实现同步的关键数据对象：

- `users`
  存用户长期稳定资料
- `learner_profiles`
  存学习者画像
- `questionnaire_templates`
  存问卷模板定义
- `questionnaire_questions`
  存问卷题目
- `questionnaire_submissions`
  存问卷提交记录
- `diagnostic_questions`
  存诊断题
- `generation_jobs`
  存异步生成任务
- `generated_resources`
  存生成资源
- `feedback_records`
  存反馈记录

## 8. 当前已知边界

已经完成：

- 用户资料与问卷拆分
- `user_id` 自动生成
- 通用问卷精简为 4 题
- 异步生成主流程落地
- 资源结果按 `run_id` 查看
- 学习历史时间线接口提供
- 本地数据库已按当前结构重建并同步
- WorkflowEvent SSE replay/live tail、断线续传和前端轮询降级

尚未完成：

- 诊断结果展示后的“第五步资源类型选择”完整前端体验
- 独立消息队列或任务队列
- 任务取消与任务恢复
- 更复杂的扩展 Agent 工作流
- 前端 Profile/Mastery/Path 完整报告与 Claim/Evidence/SourceRef V2 的比赛对齐

## 9. 当前阶段结论

截至 2026-08-12，后端已经具备可重复验证的 P0-00～P0-08 业务闭环：

- 可以创建用户资料
- 可以提交问卷并生成初始画像
- 可以进入诊断
- 可以发起异步资源生成任务
- 可以查询和下载生成资源
- 可以从历史时间线查看学习过程
- 可以通过 SSE 观察并断线续传持久化 WorkflowEvent
- 可以回放 Evidence、审核版本、Claim 判定和反馈后的画像/路径变化

当前进入比赛级 Gate 收敛，重点是：

- 补齐前端 Claim/Evidence 与画像/路径报告，并完成浏览器人工 E2E 和正式数据迁移演练
- 扩大真实/金标评测样本；样本不足时保持 `NOT_MEASURABLE`

## 10. 审核返工、版本与发布能力

当前资源生成闭环在异步任务之内提供以下可靠能力：

- Reviewer 输出 approve、revise、reject、human_review 四类决策。
- 问题和返工要求采用结构化 code、severity、目标资源、action 与 priority。
- Generator 只修改指令命中的资源类型；每次返工创建新 resource_id/version 并连接 parent_resource_id。
- 每轮资源和审核均可从 Run 时间线回放，旧版本不会被 WorkflowState 覆盖后丢失。
- 草稿、旧版本、返工、拒绝和人工审核资源保留用于审计，但不进入学习者默认资源库。
- 只有最终审核通过的当前叶子版本可下载。
- 混合检索和 Rerank 的结果仍需通过 KB、Chunk 版本与内容哈希验证后才能用于生成。

## 11. Claim 级知识溯源与评测（P0-06）

- 独立 Claim Extractor 不依赖 Generator 自报，按资源版本生成稳定 `clm_*` ID。
- Claim Judge 只允许使用当前 Run 已冻结的 Evidence；跨 Run、未知或伪造 ID 会拒绝。
- 支持 `supported`、`contradicted`、`not_in_evidence`、`non_factual` 四类判定。
- 自动发布要求事实 Claim 完整判定，且当前版本不存在 contradicted/not_in_evidence。
- 问题 Claim 会生成带 `target_claim_ids` 的返工指令，新版本重新抽取和判定。
- Run 回放只记录 Claim ID、数量、判定计数和指标；全文通过专用 Claims 接口查询。
- 比赛幻觉率按最终发布叶子版本做事实 Claim 微平均；覆盖率仅认绑定稳定技能节点且
  判为 supported 的事实 Claim。
- 难度适配评测要求固定 `fixture_version` 金标，输出准确率和混淆矩阵；不把 Reviewer
  自评分当作金标。

## 12. 反馈后画像与学习路径闭环（P0-07）

- 正式入口为 `POST /api/feedback/attemptsattempts`；旧反馈写入接口已移除，新闭环事实源统一为 attempt。
- 总分由后端按逐知识点题数加权重算，边界为 `<0.60 remediate`、`0.60~0.85 practice`、`>0.85 advance`，任一知识点低于 0.60 会阻止整体进阶。
- 一次本地事务写入 Attempt、Decision、知识状态变更、画像 N+1 和路径 mutation。
- 低分激活补救节点，中分保持主路径并避免重复练习节点，高分完成当前节点并解锁后继或挑战节点。
- 补救/进阶通过当前 `GenerationJobService` 创建真实异步任务；父子 Run 可追溯，失败状态与反馈成功状态分离。
- Report 读取持久化掌握度、最近 Attempt、画像版本和当前路径；重启后不回退。

## 13. WorkflowEvent SSE 与 Agent 实时轨迹（P0-08）

- `GET /api/runs/{run_id}/events` 将已提交的 WorkflowEvent 以 snapshot + replay + live tail 形式输出。
- 浏览器断线通过 Last-Event-ID 补齐缺失事件，前端 reducer 按 sequence/event ID 去重，不产生重复 Agent Step。
- 生成页以 SSE 为实时主通道；连续传输错误后才启用现有 Job/timeline 轮询，不同时高频运行两套机制。
- 页面刷新从 local run_id、Job 和持久化 timeline 恢复，再从最后 sequence 继续订阅。
- Agent 轨迹展示 running/success/degraded/failed/human_review/skipped、耗时、重试、Evidence/Claim 计数和返工轮次。
- P0-07 follow-up event 可跳转并订阅 child Run；不创建跨 Run 全局合并流。
- Evidence/Claim/资源正文仍使用专用详情 API，SSE 不暴露内部推理或大对象。

## 14. P0-09 比赛验收边界

- `p0-09-demo-suite/v1` 固定 KB、稳定 DocumentVersion/Chunk/knowledge point，以及三档 learner、Attempt、Review、Claim、SSE 和 failure injection。
- acceptance runner 分开执行 deterministic offline、local runtime 与显式 opt-in live smoke，manifest 不保存 Key、Prompt、模型原始响应或完整画像。
- 比赛方案数值阈值为幻觉率 `<5%`、难度适配准确率 `>=85%`、核心知识点覆盖率 `>=90%`；正式口径不用 Reviewer 自评分。
- 当前 fixture 只有 3 个 learner，未达到比赛高分测试计划所要求的至少 50 组用例，因此三项 fixture 实际值只作管线校验，正式结论为 `NOT_MEASURABLE`。
- SQLite 外键 hook、资源版本唯一约束和迁移演练脚本已同步；当前 runtime Gate 仍会因前端 Claim/Evidence、SourceRef V2 和画像/路径报告缺口而 `FAIL`。公共 health ready 不能替代比赛 Gate。

## 15. 证据约束 Tutor 导学

- 已发布资源页提供“向 Tutor 提问”，测评页每题提供“需要提示”；抽屉支持活动会话恢复、多轮求助、loading/error 状态和引用展示。
- 提示阶段由服务端确定性策略控制：首次求助为方向提示，明确继续困惑时升级为结构化拆解，第三轮及以后才允许完整的 grounded explanation。
- Tutor 只使用题目对应真实 Run 的 Frozen Evidence、兼容 SourceRef 或 Ready 知识库上的受控检索；无证据时 fail closed，不使用模型常识兜底。
- Tutor 不修改画像、Mastery、LearningPath 或 Resource。批次测评提交时，服务端按 `batch_id` 汇总持久化的题目求助轮次并映射到现有 Attempt `hint_count` 审计字段；旧 Run 调用保持兼容。
- 会话与轮次具备访问控制、唯一序列、`client_message_id` 幂等、引用子集校验和脱敏 LLM 遥测。
