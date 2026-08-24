# 动态学情报告任务书（Luna 执行版）

> 分发对象：Luna 执行者
> 文档状态：待执行
> 更新时间：2026-08-24
> 工作性质：在已完成画像能力闭环基础上，升级动态学情报告；本文是执行授权，不是完成证明。

## 1. 任务目标

在不改变画像掌握度公式、正式反馈事务和资源发布策略的前提下，将现有静态学情报告升级为可持续反映真实学习事实的动态报告。

最终报告必须能够：

- 在报告页打开期间感知正式反馈、掌握状态和文本资源质量变化；
- 使用服务端验证的题目结果计算真实学习活动与正确率；
- 从规范能力节点投影展示当前掌握度、趋势和薄弱点；
- 区分已验证薄弱点、学习中退步和仅需进一步验证的节点；
- 为五类已发布文本资源展示透明、可解释的可信证据；
- 明确区分 `not_measured`、legacy、失败和通过，不用 `0` 冒充未测量；
- 在 SSE 不可用时安全降级到条件轮询；
- 保持现有报告接口和旧字段 additive 兼容。

本轮不使用模型生成报告。报告聚合、可信等级、revision 和前端状态转换均必须是确定性的。

## 2. 已完成基础与审计结论

### 2.1 画像能力闭环完成基线

上一轮已完成：

- `knowledge_states` 规范能力节点当前投影；
- `AbilityMasteryStateV2`、能力证据事件和置信度；
- 问卷低置信先验、服务端诊断和正式反馈更新；
- 正式 Attempt 的幂等、CAS、事务和 SQLite 重启恢复；
- `WeaknessPriorityV1` 和下一批文本资源 focus snapshot；
- `GET /api/profiles/{learner_id}/ability-nodes`；
- `ReportResponse` 2.0 的能力节点 additive 字段；
- learner mastery 本地 journey `LOCAL_READY`。

上一轮记录的验证结果：

- learner mastery 核心：`44 passed`；
- knowledge + migration：`31 passed`；
- restart/persistence/API：`16 passed`；
- 非课件后端全量：`435 passed, 4 skipped`；
- 后端完整全量：`575 passed, 5 skipped, 2 failed`，两个失败均位于互动课件；
- 前端 `test:learner-mastery`、`test:workflow-events`、`test:tutor` 和 build 通过。

本任务分发前复跑报告直接相关专项：`4 passed`。该结果只证明现有报告基础接口未回归，不证明动态报告已经实现。

### 2.2 当前真实缺口

当前实现已经接入部分规范能力投影，但仍存在：

1. `frontend/src/features/reports/ReportView.vue` 只在首次进入、切换画像或手动点击时请求报告；界面“实时更新”文案与行为不一致。
2. `as_of_profile_version` 只能表达画像变化，资源审核和 Claim 指标更新不会改变报告版本。
3. 当前平均正确率按 Attempt 简单平均，而不是按服务端验证题目总数加权。
4. `blind_spot_heatmap` 等兼容字段仍可能从 `theory_scores/knowledge_states` 旧缓存取值，与规范能力投影冲突。
5. 自评、客观证据和旧主观反馈没有在所有统计中严格分层。
6. 资源质量只有审核通过数和平均幻觉率；没有测量样本时返回 `0.0`，会被误解为零风险。
7. 报告没有事实 revision、ETag、一致性重试、SSE、断线恢复或轮询降级。
8. 当前知识文档没有来源机构权威性元数据。系统只能验证生成资源的审核、Claim 支持和来源可追溯性，不能验证来源机构权威性或绝对事实正确。

## 3. 执行边界

### 3.1 允许修改

执行者可以修改：

- `backend/app/api/reports/**`；
- `backend/app/services/reports/**`；
- `backend/app/models/reports/**`；
- 为报告新增的 `backend/app/db/reports/**` 只读聚合实现；
- 现有 learner、feedback、resource、review、claim repository 的 additive 只读方法；
- `backend/app/containers.py`、报告 SSE 相关配置和公开错误码；
- `frontend/src/features/reports/**`；
- `frontend/src/api/index.js` 中的报告 API；
- 报告专项 fixture、测试、journey 和本地浏览器验证脚本；
- `docs/api.md`、`docs/architecture.md`、`docs/features.md` 和本文。

### 3.2 禁止修改

执行者不得修改：

- 掌握度更新公式、状态阈值、置信度晋级和薄弱点排序规则；
- 问卷、诊断和正式反馈的写事务；
- 正式 Attempt 的判分、幂等、CAS 和来源验证规则；
- 五类文本资源的生成、审核、Claim 判定或发布策略；
- 互动课件生成、课件质量汇总、课件 progress 或课件学习事件；
- 知识库来源模型、来源机构评级或来源权威性策略；
- 既有迁移文件，尤其不得修改 `p0_19`；
- 管理员或人工审核工作流。

本轮资源可信证据只覆盖五类文本资源：`text`、`practice`、`assessment`、`case_study`、`checklist` 对应的现有中文规范类型。互动课件可以继续出现在统一资源库，但不得进入本任务的可信度分母。

### 3.3 数据真实性原则

- 真实学习活动只来自服务端验证的 run/batch Attempt。
- 旧主观反馈可以作为说明展示，但不得进入正确率、掌握度或已验证薄弱点统计。
- 客户端上传的聚合正确率不得成为报告事实。
- 无可靠学习时长事件，本轮不得展示或推算“学习时长”。
- 无测量值返回 `null + status/reason`，不得使用 `0` 代替。
- 来源类型、文件名和检索分数不得被推断为来源权威性。

## 4. 固定执行顺序

严格按以下顺序推进：

1. H0：新增失败反例；
2. H1：Report 3.0 读模型和一致性快照；
3. H2：真实学习活动、掌握度和薄弱点；
4. H3：文本资源可信证据；
5. H4：revision、ETag 和条件读取；
6. H5：SSE、前端动态更新和浏览器恢复；
7. H6：journey、分层回归和文档同步。

每阶段必须先让新增反例失败，再实现，再运行该阶段专项和直接上层回归。不得一次性实现全部功能后补测试。

## 5. H0：冻结失败反例

先新增测试证明以下现状或风险：

### 5.1 报告真实性

- 正式反馈提交后，已打开的报告不会自动更新；
- 两个 Attempt 分别为 `1/1` 和 `1/9` 时，正确率必须是 `2/10 = 0.2`，不得是两个 Attempt 比率的平均 `0.55`；
- 无服务端验证题目时，正确率必须为 `null` 且状态为 `not_measured`；
- 自评 prior 不得进入客观正确率；
- 旧画像缓存与规范投影冲突时，雷达、强弱点和热力图必须以规范投影为准；
- 低置信自评不得出现在 `verified_weak`。

### 5.2 revision 和动态更新

- 资源 Review 或 Claim 指标改变但 profile version 不变时，报告 revision 必须改变；
- 无事实变化的重复读取不得改变 revision；
- 相同正式反馈的幂等重放不得改变 revision；
- 不同 `window_days` 必须生成不同 ETag；
- 相同事实的 `generated_at` 变化不得改变 revision；
- SSE 快速连续通知不得导致重复并发请求或旧响应覆盖新响应；
- 切换 learner 后，旧 learner 的事件不得刷新当前页面。

### 5.3 资源可信证据

- 无 Claim 测量时不得返回幻觉率 `0`；
- 未发布、已被 supersede、已被同批同类型新版本替换或非最终叶子资源不得进入统计；
- legacy 来源、缺失 evidence ID 或 incomplete Claim 不得标记为 `trusted`；
- 已测量的 contradicted/not-in-evidence Claim 必须标记为 `attention`；
- `difficulty_match` 不得改变可信等级；
- 互动课件不得进入文本资源可信度总数。

### 5.4 安全和恢复

- 无认证请求不能读取或订阅报告；
- 当前用户不能读取或订阅其他用户的 learner；
- 非法 `Last-Event-ID`、`after_revision` 和分页 cursor 返回稳定 400；
- SSE 断开只停止读循环，不写库、不修改画像或 revision；
- 重连后以当前 snapshot 收敛，不要求伪造 Durable Event 回放。

H0 完成门：所有新增反例在实现前能够稳定失败，失败原因与本任务缺口一致；现有通过测试没有被删除或放宽。

## 6. H1：Report 3.0 一致读模型

### 6.1 公开响应

保持：

```http
GET /api/report/{learner_id}
```

增加可选查询参数：

```text
window_days = 7 | 30 | 90
default = 30
```

窗口使用 UTC 半开区间：

- current：`[now - window_days, now)`；
- previous：`[now - 2×window_days, now - window_days)`。

当前掌握状态始终读取最新规范投影，不受窗口裁剪；学习活动和趋势受窗口约束。

`ReportResponse` additive 升级为 `report_schema_version="3.0"`，保留 2.0 和旧字段，新增：

```text
report_revision
data_as_of
window
freshness
learning_activity
mastery_overview
mastery_trends
weakness_groups
resource_credibility_summary
recent_resource_credibility
```

`report_revision` 格式固定为：

```text
rpt_<64 lowercase hex sha256>
```

### 6.2 revision 组成

新增 `ReportRevisionPartsV1`，至少包含四个稳定子 hash：

```text
profile
mastery
activity
text_resources
```

子 hash 输入必须使用字段 allow-list、稳定 ID 排序和规范 JSON 编码，不得包含 `generated_at`、日志、Prompt、原始全文或运行时对象地址。

- `profile`：learner ID、knowledge base ID、profile version 和会影响报告展示的当前用户维护字段；
- `mastery`：当前能力状态、row version、能力事件稳定 ID、事件状态和当前路径版本；
- `activity`：正式 Attempt/Decision 的稳定 ID、题目分子分母、发生时间和幂等结果；
- `text_resources`：当前可见文本资源 ID/version/status、Review、Claim metric、Judgement 摘要和 SourceRef 可追溯字段。

顶层 revision 同时包含 `window_days`。同一事实和同一窗口必须得到相同 revision。

### 6.3 一致性快照

新增报告专用只读聚合边界。SQLite 实现应尽量在同一只读 session 中获取 revision 输入和报告所需数据；不得把聚合 SQL 放进 API 层。

构建流程固定为：

1. 读取 `before_revision_parts`；
2. 构建报告快照；
3. 读取 `after_revision_parts`；
4. 相等则返回；
5. 不相等则丢弃结果并重建；
6. 首次构建后最多重建两次，共最多三次构建；
7. 仍不稳定时返回 HTTP 503：

```json
{
  "detail": {
    "code": "REPORT_SNAPSHOT_UNSTABLE",
    "message": "报告数据正在更新，请稍后重试"
  }
}
```

不得返回混合 profile version、能力状态和资源质量的快照。

### 6.4 时间语义

- `generated_at`：本次响应构建时间；
- `data_as_of`：参与当前 revision 的最新事实时间；
- `as_of_profile_version`：报告中的画像版本；
- `freshness.source_revisions`：四个子 hash 和安全计数；
- `freshness.warnings`：仅返回用户可理解或机器可识别的安全原因码。

H1 完成门：Report 3.0 contract、稳定 hash、窗口、并发重建和 503 测试通过；旧字段仍可被现有调用者解析。

## 7. H2：真实学习情况、掌握度和薄弱点

### 7.1 LearningActivitySummaryV1

新增版本化 DTO：

```text
schema_version = "1.0"
status = measured | not_measured
window_start
window_end
verified_attempt_count
practiced_resource_count
active_day_count
answered_item_count
correct_item_count
verified_accuracy: float | null
previous_period_accuracy: float | null
accuracy_delta: float | null
reason_codes[]
```

计算规则：

- 只统计服务端验证且已经持久化成功的 run/batch Attempt；
- `answered_item_count = sum(total_count)`；
- `correct_item_count = sum(correct_count)`；
- `verified_accuracy = correct / answered`；
- answered 为 0 时 accuracy 为 `null`；
- active day 使用 UTC 日期去重；
- practiced resource 使用正式 Attempt 的 source resource ID 去重；
- previous period 使用相同公式；任一周期未测量时 delta 为 `null`；
- 不读取旧主观 FeedbackRecord 的客户端 `correct_rate` 作为真实活动指标。

旧 `metric_summary.average_correct_rate` 为兼容字段，但必须改为同一加权客观正确率；没有客观题目时返回 `null`。

### 7.2 掌握度一致性

所有能力字段从 `MasteryService.ability_nodes()` 的同一快照派生：

- radar；
- weak/strong points；
- difficulty curve；
- blind spot heatmap；
- `knowledge_mastery`；
- `mastery_overview`；
- 下一资源 focus 展示。

不得在能力投影可用时回退读取 `profile.theory_scores`、名称键 `profile.knowledge_states` 或旧 weak/strong 缓存。只有历史画像确实无法建立规范投影时才返回兼容数据，并增加明确 `data_warnings`，不得静默混合两套状态源。

### 7.3 MasteryTrendSeriesV1

每个节点返回：

```text
skill_node_id
name
current_score
current_status
confidence
points[]
  event_id
  before_score
  after_score
  delta
  source_type
  verified
  occurred_at
```

规则：

- 按 `occurred_at, event_id` 稳定排序；
- 同一 evidence/event 只出现一次；
- 自评事件可展示，但必须 `verified=false`；
- 客观趋势 delta 只比较连续客观状态；
- 空分数保持 `null`，不得补 0；
- 默认只返回当前窗口内点，节点 current state 仍为最新值。

### 7.4 WeaknessGroupsV1

固定三组：

```text
verified_weak
regressing_learning
needs_evidence
```

每项包含节点 ID、名称、状态、分数、confidence、trend delta、客观证据数、priority rank 和现有 `WeaknessPriorityV1.reason_codes`。

- `verified_weak`：有客观证据且当前 status=weak；
- `regressing_learning`：由现有 priority 投影判定的 learning 退步节点；
- `needs_evidence`：低置信自评或阻塞后继节点的未评估前置节点；
- 报告只消费 `WeaknessPriorityV1`，不得复制或重写其排序算法。

H2 完成门：加权正确率、not-measured、自评隔离、趋势去重和所有能力兼容字段一致性测试通过。

## 8. H3：五类文本资源可信证据

### 8.1 纳入范围

只统计满足全部条件的资源：

- 属于当前 learner；
- `publication_status=published`；
- 属于五类文本资源；
- 未被 generation job supersede；
- 同一 batch/type 存在有效 replacement 时只保留最新发布 replacement；
- 不是仍有已发布子版本的父资源，即只统计最终发布叶子。

继续复用现有 `_visible_resources` 语义或抽取唯一共享实现，不复制两份可能分叉的可见性算法。

### 8.2 TextResourceCredibilityV1

每个资源返回：

```text
schema_version = "1.0"
resource_id
resource_type
topic
run_id
batch_id
resource_version
published_at
grade = trusted | attention | insufficient_evidence
publication_review
claim_support
source_traceability
source_authority
difficulty_fit
reason_codes[]
```

#### publication_review

返回 `status=passed|failed|not_measured`、publication status、review status、review ID、blocking issue count。

- 当前规范 `approved` 且存在对应 review record、没有 high/critical issue：passed；
- 已发布但 rejected/human-review/revision-requested，或存在 blocking issue：failed；
- legacy `passed` 只有在能关联 review record 且记录也通过时才视为 passed；否则 not_measured。

#### claim_support

返回：

```text
status = passed | failed | not_applicable | not_measured
metric_status
factual_claim_count
supported_claim_count
contradicted_claim_count
not_in_evidence_claim_count
incomplete_claim_count
unsupported_rate: float | null
```

只使用同一 `resource_id + resource_version + review_id` 的 Claim/Judgement，不得跨版本拼接。

- `complete` 且 contradicted/not-in-evidence/incomplete 均为 0：passed；
- `complete` 且存在 contradicted 或 not-in-evidence：failed；
- `not_applicable`：not_applicable，视为已完整测量；
- `incomplete`、`legacy_unavailable`、缺失记录：not_measured；
- not_measured 时 unsupported rate 必须为 `null`。

#### source_traceability

返回：

```text
status = passed | partial | failed | not_measured
source_ref_count
verified_source_ref_count
evidence_bound_count
unique_document_count
```

- 至少一个 SourceRef，且每个 distinct ref 都是 `provenance_status=verified`，具有 evidence ID、knowledge base ID、document ID/version 和 chunk ID：passed；
- 有引用但只有部分满足完整绑定：partial；
- 引用显式指向不存在或跨知识库 Evidence：failed；
- 没有可核验引用或仅有无法证明的 legacy 引用：not_measured。

#### source_authority

固定返回：

```json
{
  "status": "not_measured",
  "reason_code": "SOURCE_AUTHORITY_NOT_MEASURED"
}
```

该维度不参与总体 grade。不得根据 PDF、网站、标题、文件名、检索分数或模型判断推测权威性。

#### difficulty_fit

显示现有 `difficulty_match` 及其测量状态，但不参与总体 grade。

### 8.3 总体等级规则

按以下确定性优先级计算：

1. 任一 required 维度为 failed：`attention`；
2. publication_review=passed、source_traceability=passed，且 claim_support 为 passed 或 not_applicable：`trusted`；
3. 其他没有 measured failure 的情况：`insufficient_evidence`。

required 维度仅为 publication review、claim support 和 source traceability。source authority 和 difficulty fit 不参与 grade。

用户界面必须展示：

> 可信等级表示平台可验证的生成质量证据，不等价于来源机构权威性或绝对事实正确。

### 8.4 汇总和分页

主报告新增：

```text
resource_credibility_summary
  total_count
  trusted_count
  attention_count
  insufficient_evidence_count
  fully_measured_count
  measurement_coverage: float | null
  excluded_courseware_count = 0 或不返回
```

主报告只内嵌按发布时间排序的最近 10 项。

新增：

```http
GET /api/report/{learner_id}/resource-credibility?limit=20&cursor=...
```

- limit 默认 20，范围 1–100；
- 排序固定为 `published_at DESC, resource_id ASC`；
- cursor 为 `{published_at, resource_id}` 规范 JSON 的 base64url 编码；
- 非法、缺字段或不属于当前排序边界的 cursor 返回 400 `REPORT_CURSOR_INVALID`；
- 响应返回 `items` 和 `next_cursor`；
- 继续使用与报告相同的 learner 访问控制。

旧 `review_summary.average_hallucination_rate` 仅对 `claim_metric_status=complete` 的当前可见最终文本资源计算；无样本时返回 `null`，不得回退为 `0.0`。

H3 完成门：三等级、版本隔离、来源追溯、not-measured、可见性和分页稳定性测试通过。

## 9. H4：ETag 与条件读取

### 9.1 GET 行为

报告响应增加：

```http
ETag: "<report_revision>"
Cache-Control: private, no-cache
```

支持：

```http
If-None-Match: "<report_revision>"
```

- revision 相同：返回 304、ETag 和 Cache-Control，不返回响应体；
- revision 不同：返回 200 和完整 Report 3.0；
- 弱 ETag、多个 ETag 和非法值按 HTTP 规范安全解析；只接受与当前 learner/window 匹配的 revision；
- 304 前仍必须完成认证和 learner 访问控制；
- `generated_at` 不参与 ETag。

### 9.2 变化域

比较 `ReportRevisionPartsV1` 得到：

```text
changed_domains = profile | mastery | activity | text_resources
```

只返回域名，不返回原始证据、题目、全文、Prompt 或内部错误。

H4 完成门：200/304、窗口隔离、资源质量独立变化、幂等重放、鉴权和缓存头测试通过。

## 10. H5：SSE 和前端动态报告

### 10.1 SSE 接口

新增：

```http
GET /api/report/{learner_id}/events?window_days=30&after_revision=...
Accept: text/event-stream
Last-Event-ID: rpt_...
```

cursor 优先级：

```text
Last-Event-ID > after_revision > empty
```

revision 必须匹配 `rpt_<64 lowercase hex>`；非法 cursor 返回 400 `REPORT_STREAM_CURSOR_INVALID`。

增加独立配置并提供安全默认值：

```text
report_sse_poll_interval_seconds = 2
report_sse_heartbeat_seconds = 15
```

事件协议：

```text
event: report_snapshot
data: {schema_version, learner_id, report_revision, as_of_profile_version,
       data_as_of, window_days, replay_mode="current_snapshot"}

id: rpt_...
event: report_changed
data: {schema_version, learner_id, report_revision, as_of_profile_version,
       data_as_of, window_days, changed_domains[]}

event: ping
data: {learner_id, report_revision, server_time}

event: stream_error
data: {code, safe_message, report_revision}
```

该流是当前状态失效通知，不是 Durable Event ledger：

- 初次连接始终发送当前 snapshot；
- 重连只需用当前 snapshot 收敛，不补造历史通知；
- 每 2 秒读取轻量 revision parts；
- revision 变化时发送一次 `report_changed`；
- 每 15 秒无变化时发送 ping；
- 断开只停止读循环，不写数据库、不更改画像或资源状态；
- payload 必须使用 allow-list，禁止原始题目、反馈正文、证据 excerpt、资源全文、Prompt、模型响应、路径和异常栈。

### 10.2 前端客户端

在报告 feature 内实现独立客户端或 composable，不把报告逻辑塞入全局 store。

固定状态：

```text
connecting
live
reconnecting
polling
offline
closed
```

行为：

1. 进入页面或切换 learner：关闭旧 EventSource 和 timer；请求报告；使用返回 revision 建立新 SSE。
2. 收到 snapshot：若 revision 与当前不同，执行条件 GET。
3. 收到 changed：250ms 内合并连续通知，只发一次条件 GET。
4. 请求进行中又收到新 revision：记录 pending revision；当前请求完成后最多补取一次。
5. 响应应用前核对 learner ID、window 和请求 generation；旧请求不得覆盖新 learner。
6. 连续三次 SSE transport error：关闭 SSE，降级为每 30 秒一次条件 GET。
7. `visibilitychange` 变为 visible：立即条件刷新，并尝试恢复 SSE；hidden 时停止轮询。
8. `online` 时立即恢复；`offline` 时停止自动请求并保留当前快照。
9. 组件卸载时关闭 EventSource、timer 和待处理回调。
10. 手动刷新始终可用，并使用无条件 GET 获取当前报告。

原生 EventSource 使用现有同源认证 Cookie，不把 token 放入 URL。

### 10.3 页面结构

报告页调整为五个主要区域：

1. 真实学习活动：窗口、正式 Attempt、题目数、加权正确率、与前周期变化；
2. 能力掌握：节点状态、分数、confidence、客观证据覆盖；
3. 薄弱点：已验证薄弱、学习中退步、待验证重点；
4. 掌握趋势：按节点展示客观和自评证据的区别；
5. 文本资源可信证据：三等级、各维度和 not-measured 解释。

顶部显示：

- 自动更新状态；
- `data_as_of`；
- 当前 7/30/90 天窗口选择；
- 手动刷新。

不得展示内部 checkpoint、模型错误、数据库表名或原始错误码。机器错误码映射为用户友好状态，详细错误只进入安全日志。

必须验证：keyboard、focus、screen-reader label、touch、移动端、空状态、长节点名、200% zoom、reduced-motion 和断线提示。

H5 完成门：前端状态机、请求合并、learner 隔离、SSE 降级、恢复和 Playwright 交互测试通过。

## 11. H6：动态报告 journey 和验收

新增 `backend/scripts/learning_report_journey.py` 或仓库脚本体系中的等价入口，使用脱敏 fixture、临时 SQLite 和真实服务层，不调用外部模型。

### 11.1 正向 journey

依次证明：

1. 创建 learner，只有自评先验；报告 accuracy 为 null，自评不在 verified weak；
2. 获取初始 Report 3.0、ETag 和 SSE snapshot；
3. 提交服务端诊断或正式 run/batch feedback；
4. revision 改变，SSE 发出 changed，条件 GET 返回 200；
5. 报告掌握度、薄弱点和 ability-nodes API 对同一节点一致；
6. 创建两个正式 Attempt，验证按题目数加权；
7. 重放相同幂等反馈，revision 和统计不变；
8. 创建完整审核、完整 Claim 和 verified SourceRef 的文本资源，等级为 trusted；
9. 创建 legacy/incomplete 资源，等级为 insufficient evidence；
10. 创建 measured contradictory/not-in-evidence 资源，等级为 attention；
11. 只改变 Review/Claim 事实而不改变 profile version，revision 仍改变；
12. 断开 SSE，条件轮询获取同一最新 revision；
13. 重启 repository/app，报告 revision、趋势、等级和排序保持一致。

### 11.2 负向 journey

至少证明：

- 未认证报告 GET/SSE 拒绝；
- 跨用户 learner GET/SSE 拒绝；
- 非法 ETag、revision 和分页 cursor 安全处理；
- 并发变化无法构建稳定快照时返回 `REPORT_SNAPSHOT_UNSTABLE`；
- 未发布、被替换和父版本资源不进入可信度；
- 互动课件不进入文本资源可信汇总；
- SSE payload 不含敏感字段；
- 页面切换 learner 后忽略旧响应和旧事件。

### 11.3 journey 报告

本地产物不得提交。报告至少包含：

```text
schema_version
status = LOCAL_READY | PARTIAL
initial/final report_revision
as_of_profile_version
window_days
weighted activity numerator/denominator
mastery consistency assertions
weakness group assertions
resource grade assertions
etag 200/304 assertions
sse snapshot/change/reconnect assertions
authorization assertions
restart consistency
test_duration
```

只有所有确定性门通过时才能返回 `LOCAL_READY`。该状态不等于生产部署完成。

## 12. 测试与验证顺序

执行者根据真实新增路径补全命令，但必须覆盖以下层级：

```powershell
# Report contract、聚合、可信度和 revision
python -m pytest backend/tests/unit/reports backend/tests/integration/services/test_feedback_report.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/learning-report-unit

# API、ETag、SSE、鉴权和分页
python -m pytest backend/tests/integration/api/test_report_api.py backend/tests/integration/services/test_report_stream.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/learning-report-api

# Mastery/feedback/report 一致性和重启
python -m pytest backend/tests/integration/api/test_ability_nodes_api.py backend/tests/integration/services/test_feedback_loop_service.py backend/tests/e2e/test_learning_report_restart.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/learning-report-e2e

# 本地动态报告 journey
python backend/scripts/learning_report_journey.py --output backend/.pytest-tmp/learning-report-journey.json

# 前端专项与浏览器
npm --prefix frontend run test:learning-report
npm --prefix frontend run test:learning-report-browser
npm --prefix frontend run build

# 非课件后端全量
python -m pytest backend/tests -q -p no:cacheprovider --basetemp backend/.pytest-tmp/learning-report-non-courseware --ignore-glob='*courseware*'

# 完整后端全量
python -m pytest backend/tests -q -p no:cacheprovider --basetemp backend/.pytest-tmp/learning-report-all

git diff --check
git status --short
```

若执行时测试文件名与上述建议不同，使用真实路径并同步修改本文。不得用 build 代替前端行为测试，不得用 Memory repository 结果代替 SQLite 验证。

## 13. 最终完成门

本任务完成必须同时满足：

- H0–H6 全部完成；
- Report 3.0 additive contract 通过；
- 真实学习活动只来自正式服务端验证 Attempt；
- 报告与 ability-nodes API 对同一节点值一致；
- 自评没有被标记为客观薄弱；
- 三类文本资源可信等级按固定规则产生；
- 所有 not-measured 指标保持 null；
- 资源质量变化在不改变画像版本时仍能触发 revision；
- ETag 200/304、SSE、重连和轮询降级通过；
- SQLite 重启后结果稳定；
- 报告专项、前端专项和 build 全绿；
- 非课件后端全量无非预期失败；
- 完整后端全量已实际运行并准确报告；
- 未提交数据库、报告、截图、缓存、构建目录或凭据。

如果完整后端仍只有任务开始前已记录的课件失败，执行者不得修改课件代码。必须列出精确失败测试，并将“跨分支集成完成”标为未完成；不能据此否定已经全绿的报告专项，也不能把报告分支描述为全仓完成。

## 14. Luna 执行规则

1. 开始前阅读根 `AGENTS.md`、`README.md`、`git-workflow.md`、本文、`docs/api.md` 和 `docs/architecture.md`。
2. 先运行 `git status --short`；所有已有 dirty worktree 修改默认属于用户。
3. 不切换、重置、清理、提交、推送或合并，除非用户另行授权。
4. 每阶段先写失败测试，再实现，再运行专项和上层回归。
5. 不删除、跳过或放宽测试制造通过。
6. 报告服务只做确定性聚合，不调用 LLM。
7. 不复制掌握度公式、薄弱点排序或资源可见性算法；从唯一公开服务/投影消费。
8. 不把旧主观反馈、客户端分数或 self-report 当作客观学习事实。
9. 不把 `not_measured` 变成数值 0。
10. 不把资源可信等级描述为来源权威性或绝对事实保证。
11. 不接入互动课件学习事件，不修改课件业务代码和测试。
12. 不建设管理员或人工审核工作流。
13. 不提交临时数据库、journey JSON、浏览器截图、构建产物、日志、缓存或凭据。
14. 每完成一个阶段，在本文“执行记录”追加真实文件、命令、计数和剩余缺口；不得预填完成。

## 15. 最终报告模板

Luna 最终报告必须列出：

- H0–H6 完成状态；
- Report 3.0、分页接口、ETag 和 SSE 的公开契约；
- revision 四个组成域和一致性重建结果；
- 学习活动分子、分母、窗口和前周期比较；
- 与 ability-nodes API 的节点一致性证据；
- verified weak、regressing learning 和 needs evidence 的逐组结果；
- 每个文本资源的总体等级、维度状态和 reason codes；
- not-measured、legacy 和 source authority 的处理；
- SSE 重连、条件轮询、鉴权和 payload allow-list 结果；
- SQLite 重启前后 revision、趋势、等级和排序；
- 实际执行的全部命令、准确通过数、跳过项和失败项；
- 未完成的 CI、跨分支集成、浏览器环境或生产观察事项。

不得把单元测试、Memory repository、mock EventSource、本地 SQLite、单浏览器或单分支结果描述为生产就绪。

## 16. 执行记录

执行者从 H0 开始追加记录。任务分发前不得预填“已完成”。
