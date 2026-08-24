# 批次能力反馈与结构化反馈报告任务书

> 任务性质：功能设计与实现任务书  
> 交付对象：后端、前端、测试执行者  
> 目标：使反馈题严格来自本批次已发布资源覆盖的能力节点；在反馈结果页生成并渲染可信、结构化、可行动的反馈报告；由学习者选择下一轮是“强化薄弱点”还是“学习新知识”，系统再在该意图范围内安全地选择能力节点并生成资源。

## 1. 已审计基线与本任务边界

当前系统已有以下可复用基础，不得另起平行实现：

- 正式反馈入口已支持资源、Run 和批次提交；`FeedbackService` 已保存 Attempt、知识点逐题结果、学习路径、分析和后续资源选项。
- `LearningResource` 已带有 `knowledge_points`、`run_id`、`batch_id`、版本和发布状态；`MasteryService` 是能力掌握投影和生成 focus snapshot 的唯一策略入口。
- Report 3.0 已输出 `ability_nodes`、`mastery_summary`、`weakness_priorities`、`weakness_groups`、ETag 和 SSE；反馈页已有题目作答、学习感受和结果区。
- 现有页面存在多段覆盖式 CSS，反馈结果与学习报告都容易形成重复卡片、信息层级不清的问题。本任务要求整理为一套组件层级和单一响应式规则，而不是继续追加覆盖样式。

本任务只覆盖文本学习资源和反馈闭环；不得改动互动课件目录、课件运行时或把课件浏览行为当作客观掌握证据。现有 HTTP 路径、鉴权、旧 DTO、Attempt 幂等和已发布资源语义必须保持兼容；新字段和新接口只能 additive。

## 2. 核心定义（必须实现为独立事实，禁止互相推断）

| 事实 | 定义 | 可作为“薄弱/未掌握”吗 | 可进入下一批第 1 优先级吗 |
|---|---|---:|---:|
| 未学习 `unlearned` | 当前知识库能力节点从未被该学习者纳入已发布资源的能力范围，且无开始/完成学习暴露记录 | 否 | 否，属于第 2 优先级 |
| 已学习、未测 `learned_unmeasured` | 已有发布资源覆盖或明确学习暴露，但没有有效正式测评 | 否 | 否；只提示补测，不与未掌握混合 |
| 学习后未掌握 `learned_not_mastered` | 资源发布/学习暴露在先，随后有服务端正式判分；当前规范掌握状态为 `weak` 或 `learning`，或最新有效 Attempt 低于掌握阈值 | 是，但必须显示证据和置信度 | 是，第 1 优先级 |
| 已掌握 `mastered` | 有足够客观证据，规范状态为 `mastered` | 否 | 否 |
| 自评/待补证据 | 仅有 onboarding 自评、覆盖不足或低置信证据 | 否 | 否；不得伪装成已学未掌握或未学习 |

“学习后未掌握”必须同时证明 **先学习、后测评、尚未掌握**。不能用 `unassessed`、资源浏览、LLM 判断、用户感受、客户端传入分数或历史 `weak_points` 替代。掌握阈值、证据覆盖、趋势判定必须只由 `MasteryService` 的一个公开策略函数给出，`FeedbackService`、`ReportService`、生成服务和前端不能各自复制排序或阈值。

## 3. 目标闭环

```text
已发布同一批文本资源
  → 冻结批次资源与能力节点快照
  → 从该快照对应的正式题库选题
  → 服务端判分 + 保存学习感受
  → 更新掌握投影与学习暴露投影
  → 生成结构化反馈报告
  → 反馈页渲染“事实 / 感受 / 下一步”
  → 下一次生成消费同一 priority snapshot
```

下一轮不再用系统自动把“薄弱点”和“新知识”混合成一个生成目标。反馈报告必须给用户两个互斥的学习意图：

1. `reinforce_weakness`（强化薄弱点）：候选仅为 `learned_not_mastered`，按规范弱度、证据置信度、先修阻塞度、最近一次有效测评时间、节点 ID 稳定排序；最多取产品规定上限（默认 3）。没有候选时禁用确认生成，并提示先完成一次有效反馈测评。
2. `learn_new_knowledge`（学习新知识）：候选仅为 `unlearned`，按先修可用性、当前学习路径顺序、下游影响、节点 ID 稳定排序。若目标节点的未学习前置节点未被同时选择，则阻止越级生成并给出可选前置节点；不得以“新知识”绕过先修关系。

`learned_unmeasured` 不属于任一自动候选集合：报告展示“已学习待测”，并提供回到反馈题的行动入口。只有产品以后明确增加“再次学习”意图时才能单独放开，当前不得通过任一模式暗中纳入。

用户可在系统给出的候选中选择 1–3 个节点和允许的资源类型/难度；前端传递意图和节点 ID，服务端必须重新验证候选集合、先修关系、画像版本和 snapshot hash。有效且未过期的已确认处方 > 本次用户意图确认 > 用户显式 `target_skill_nodes` > 默认 focus；冲突必须 422，不得静默合并。

## 4. 后端实施要求

### M1：批次反馈会话和选题

新增或扩展批次反馈会话（可复用现有 batch evaluation session，但必须补齐以下契约）：

```text
FeedbackBatchSessionV1
session_id, learner_id, knowledge_base_id, batch_id, source_run_ids[]
resource_snapshot[] = {resource_id, version, resource_type, knowledge_point_ids[]}
capability_snapshot[] = {skill_node_id, name, source_resource_ids[]}
question_bank_version, question_snapshot_hash, issued_at, expires_at, status
questions[] = {question_id, skill_node_id, type, stem, options?}  # 永不含答案/解析
```

选题规则：

- 仅选择该 learner 可见、`published`、且属于所选 `batch_id` 的当前可见资源；被 supersede/replaced 的资源不得混入。
- 能力范围为该批次资源 `knowledge_points` 的去重并集，再与当前知识库 skill catalog 求交；没有有效节点时返回可解释的 422/空态，不生成泛化题。
- 题目必须来自服务端版本化正式题库，并冻结题目 ID、节点、题库版本、排序和答案快照 hash；模型不得现场编题、不得向客户端下发答案或解析。
- 每个能力节点至少一题；超过题量上限时先保证每节点一题，再按“本批资源覆盖次数少、先修节点、节点 ID”稳定取舍。低于最小题库覆盖时返回 `insufficient_question_coverage`，不能以其他节点题补齐。
- `question_trace` 与 `point_trace` 必须由 session 生成；提交时服务端核对题目集合、节点集合、learner、资源版本、session 生命周期、幂等键和 profile CAS。客户端不得提交 `score`、`correct_count`、`knowledge_point_id` 映射作为可信事实。

新增 SQLite additive 表（或等价仓储）用于 session、冻结 item、submission 和 `learning_exposures`。`learning_exposures` 至少记录 learner、KB、节点、首次/最近发布资源、batch、published_at、首次开始与完成时间；资源重复发布和重放不可重复计数。持久化、Memory repository 和迁移均要同步。

### M2：反馈报告契约和生成

在 `FeedbackLoopResult` additive 返回 `feedback_report`，并可通过稳定的 `GET /api/feedback/reports/{attempt_id}` 重读；旧 attempt 接口响应不移除字段。报告应使用 `FeedbackReportV1`：

```text
report_id, attempt_id, learner_id, batch_id?, generated_at
objective_summary = {answered_count, correct_count, accuracy, evidence_status}
capability_results[] = {
  skill_node_id, name, batch_resource_ids[],
  learning_state, mastery_status, mastery_score?, confidence,
  answer_summary, evidence_label, reason_codes[], next_action
}
strengths[]
reinforcement_targets[]       # 仅 learned_not_mastered，已排序
unlearned_candidates[]        # 仅第二优先级候选
measurement_gaps[]            # learned_unmeasured / coverage insufficient
reflection = {completion?, difficulty?, time_feeling?, free_text?} # 原样或脱敏摘要
reflection_insight            # LLM/fallback，只解释、不改变事实
next_generation_focus = {snapshot_id/hash, ordered_targets[], reason_codes}
learner_actions[]
generation_status = llm | fallback
```

`capability_results` 必须将客观信息与学习感受分栏：客观分数、掌握状态和优先级均由确定性服务生成；LLM 只可根据 allow-list 的结果和脱敏感受生成 `reflection_insight`、鼓励性解释、学习建议。调用失败时返回确定性 fallback，`generation_status=fallback`；不能把失败当作通过，不能让 LLM 改写分数、状态、原因码、排序或下轮目标。

自由文本只允许写入受限 metadata/专用字段，不进入 Prompt 之外的日志、SSE、资源生成 Prompt 或公开错误信息；设置长度上限、基本敏感信息脱敏策略和审计标记。

### M3：用户学习意图、能力优先级与生成集成

在 `MasteryService` 新建一个唯一入口，例如 `build_next_generation_options(profile, exposure_projection, ...)`，一次生成两个隔离的候选集合：`reinforce_weakness` 与 `learn_new_knowledge`。再由 `confirm_next_generation_intent(...)` 验证用户选择并输出版本化 `NextGenerationFocusV1`。它必须携带：`learning_intent`、知识库 ID、profile version、mastery/exposure snapshot hash、两类完整候选清单、用户请求节点、最终采纳节点、跳过原因、先修校验结果和排序规则版本。生成 Job 创建时冻结已确认 snapshot；重试只复用原 snapshot。

原有 `WeaknessPriorityV1` 及报告 `weakness_groups` 保持兼容，但新增明确的 priority group：`learned_not_mastered`、`unlearned`、`learned_unmeasured`、`insufficient_evidence`。历史 `confirmed_weak` / `unassessed_prerequisite` 通过适配层映射，不能让旧数据在没有暴露记录时自动成为“学习后未掌握”。`unlearned` 只在 `learn_new_knowledge` 意图中可生成，不是薄弱点的回退候选。

五类文本资源工作流只接收冻结后的目标节点、原因码、必要的失败维度和教学策略；不得注入答案、题面、用户原始感受或无关历史。生成结束后，新资源的能力节点必须能再次被反馈会话识别，形成可追溯闭环。

### M4：学习报告扩展

Report 3.x 保持字段兼容，新增 `learning_coverage_summary`、`next_generation_focus` 和按上述四类分组的 `capability_priority_groups`。页面/API 必须明确显示：

- “已学习但未掌握（可选择强化）”：展示客观证据、最近测评、置信度和下一步；
- “已学习待测”：显示补测行动，绝不显示为弱点；
- “尚未学习（后续覆盖）”：显示它只是尚未覆盖，不能显示成绩、掌握率或“薄弱”；
- “待补证据”：自评/覆盖不足，显示事实缺口。

Report revision、ETag 和 SSE 必须在 exposure、batch session、attempt、反馈报告、priority snapshot 改变时更新；SSE 只传 revision/allow-list 元数据，完整报告仍由受鉴权 GET 取得。

## 5. 前端与交互要求

### 反馈页

保留“选择批次 → 答题 → 感受 → 结果 → 下一步”单向结构：

1. 批次选择卡显示资源数、能力节点数、题量、题库覆盖状态；用户开始后冻结上下文。
2. 题目按能力节点分组，显示“本题对应：节点名”，不把正确率、弱点标签预先暴露给用户。
3. 学习感受只作为补充输入，旁注“不会改变客观得分与掌握判断”。
4. 结果页以反馈报告为唯一数据源：顶部为本次客观结果；中部按四类能力状态展开；底部先让用户二选一“强化薄弱点”/“学习新知识”，再显示该模式下可选的 1–3 个节点、先修提示和资源组合。
5. 选择“强化薄弱点”时仅展示 `reinforcement_targets`；选择“学习新知识”时仅展示 `unlearned_candidates`，并对不可越过的先修节点给出明确说明。没有对应候选时，不以另一组替代，显示空态与回退行动。
6. “确认生成”只携带服务端返回的意图、节点选择、`next_generation_focus`/处方 ID 与 snapshot hash；刷新、回退、重复点击均幂等。

### 视觉整理

- 重构 `FeedbackView.vue` 和 `ReportView.vue` 的局部样式：移除同一选择器多次覆盖的历史样式，保留单一基础规则和按断点排列的 media query；不做全局样式清理。
- 结果页面桌面端使用“报告摘要 + 能力明细”的单列主流；仅在能力明细内部使用两栏，窄屏降为一列。不要同时出现多个英雄区、重复指标或嵌套大卡片。
- 使用语义标题、状态文字和非颜色区分；键盘焦点可见，移动端 390px 宽度不横向溢出。显示 `null`/未测量，而不是 `0%`。
- 更新报告页与反馈页专项浏览器测试，覆盖桌面、390px、空态、LLM fallback、四类能力状态和重复提交。

## 6. 验收测试（先写失败反例）

至少新增并通过以下断言：

- 选中 batch 外资源、未发布/被替代资源、跨 learner/KB 资源不能进入反馈范围；多资源同一节点只测一次且可追溯到全部资源。
- 批次能力节点与题目节点严格一致；题库不足、额外/遗漏/重复题、过期 session、题库版本变化、CAS 冲突和同 key 不同 payload 均被拒绝且不部分写状态。
- 自评、感受和客户端分数不会改变 objective mastery；LLM 输出无论内容为何不能改变确定性目标顺序。
- 已发布资源 + 有效低分 Attempt 被归为 `learned_not_mastered`；只有未暴露节点才是 `unlearned`；已发布但无有效测评是 `learned_unmeasured`，三者互斥。
- 对同时存在三类节点的 fixture，`reinforce_weakness` 只能选择 `learned_not_mastered`，`learn_new_knowledge` 只能选择 `unlearned`；两种意图都具有稳定排序、snapshot hash 和重启一致性。
- 用户在“学习新知识”中选择有未完成前置节点的后继能力时返回明确错误/可选前置节点；切换意图、伪造节点 ID、过期 snapshot、重复确认和同幂等键不同 payload 都不能创建错误或重复的生成任务。
- 报告、反馈报告和 generation job 对同一 attempt 返回同一个 focus snapshot、节点顺序和 reason codes；旧报告字段、304 和 SSE 行为仍通过。
- SQLite migration 可对旧库升级；Memory/SQL 仓储、服务/API、反馈重启 e2e、报告 stream、前端 build 和浏览器专项均通过。

建议最低命令：

```powershell
python -m pytest backend/tests/unit/models/test_learner_mastery_contracts.py backend/tests/unit/policies/test_learner_mastery_policy.py -q
python -m pytest backend/tests/integration/api/test_feedback_loop_api.py backend/tests/integration/services/test_feedback_loop_service.py backend/tests/integration/services/test_feedback_report.py backend/tests/integration/api/test_report_api.py -q
python -m pytest backend/tests/migrations/test_p0_07_feedback_migration.py backend/tests/migrations/test_p0_19_learner_mastery_migration.py backend/tests/e2e/test_feedback_restart_e2e.py -q
npm --prefix frontend run test:learning-report
npm --prefix frontend run build
npm --prefix frontend run test:learning-report-browser
```

执行者应根据新增测试脚本名称调整命令；不得启用真实 LLM，除非环境已有凭据且任务委托方明确授权。

## 7. 交付清单与完成口径

- 后端：版本化 DTO、session/暴露/报告/priority snapshot 仓储与可回滚 migration、唯一 priority service、反馈与生成集成、兼容 API、鉴权和事件更新。
- 前端：批次能力反馈题、学习感受声明、结构化反馈报告、下一步确认入口，以及整理后的反馈/报告布局。
- 测试：上述反例、契约、SQL/Memory、API、重启、SSE、前端和浏览器测试。
- 文档：更新 `docs/api.md`、`docs/architecture.md`、`docs/features.md`，说明新增状态、字段、错误码、隐私边界和验证结果。

交付前执行 `git diff` 与 `git status --short`，只提交本任务涉及文件；不得覆盖当前工作区中其他执行者的报告和课件改动。报告实际测试结果与未验证项，不将本地测试描述成生产级队列、真实模型或完整浏览器矩阵证明。
