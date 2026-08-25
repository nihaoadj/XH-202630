# 可信诊断与自适应学习闭环任务书（并行执行版）

> 任务对象：诊断、掌握度、反馈、报告与下一批文本资源生成闭环
> 并行对象：`docs/courseware/courseware_quality.md` 定义的课件体验质量更新
> 工作方式：两位执行者在同一 `feature/architecture` 分支、同一工作区按文件边界独立并行
> 完成口径：本任务达到 `TASK_READY + JOINT_PENDING` 后即独立交付；两项任务结束后的联合回归由仓库负责人执行
> 核心原则：只有服务端正式判分且覆盖充分的诊断/测评可以改变客观掌握度

## 分阶能力节点策略（learner-levels/v1）

能力图谱采用三个有序等级：`零基础=1`、`Python 基础=2`、`进阶 RAG=3`；画像中的初级、中级、进阶/高级分别映射到对应等级。中级和进阶的低阶节点只记录为未验证的自评准入豁免，不能被报告或统计为客观掌握。

- 每次生成最多选择三个、且只能选择同一等级的目标节点；当阶不足三个时不得用高阶节点补位。
- 正式测评总分或任一节点低于60%时，推荐低一阶的直接前置节点；第一阶只进行同阶基础补救。
- 60%至85%保持当阶并推荐补弱；高于85%且没有低分节点时完成当前节点并解锁同阶后继。
- 只有当阶全部节点均已发布资源且经过正式测评高于85%，才可解锁下一阶。第三阶完成后仅推荐同阶综合挑战或复习。
- 目标节点、生成难度、资源规格和审核使用同一冻结阶级契约；客户端不得通过难度字段或自选节点绕过该契约。

## 1. 任务目标

形成以下可验证闭环：

```text
可信诊断
→ 薄弱点与错误维度
→ 冻结学习处方
→ 用户确认资源组合和难度
→ 定向生成五类文本学习资源
→ 隔离复测
→ 报告真实结果
→ 重新计算下一轮处方
```

本任务必须使报告和下一次生成真正消费同一份规范诊断事实，而不是各自从 `weak_points`、客户端分数或模型文本推测。

下一批任务不得自动启动。系统自动形成处方，学习者确认资源类型和难度后才创建生成任务。

本轮只把以下证据视为客观学习事实：

- 服务端诊断会话内正式判分且满足覆盖要求的答案；
- 服务端从已发布正式测评题重新取 answer key 后产生的 run/batch Attempt；
- 服务端隔离复测会话产生的正式 Attempt。

浏览、停留、课件探索、用户自评、旧主观反馈和客户端自报分数不得改变客观掌握度。

## 2. 已审计基线

本任务分发前已在 `feature/architecture`、HEAD `15723d35193fc4d77ac91c2a41b3065e5d171176` 的含未提交完成内容工作区进行只读审计：

- 后端全量：`608 passed, 5 skipped`；
- 报告、反馈、掌握与生成重点专项：`27 passed`；
- 学情报告 journey：`LOCAL_READY / TASK_READY / JOINT_PENDING`；
- 报告前端专项、浏览器专项和 build 通过；
- 当前示例知识库有 39 道诊断题，按节点覆盖 concept、scenario、misconception；
- 当前示例知识库有 130 道正式测评题；
- 正式 run/batch 反馈由服务端判分，直接提交客户端分数会以 `FEEDBACK_EVIDENCE_UNVERIFIED` 拒绝；
- MasteryService 已拥有唯一掌握投影、置信度、弱点优先级和 generation focus snapshot；
- Report 3.0 已拥有稳定 revision、ETag、SSE、正式 Attempt 活动、薄弱点分组和文本资源可信度；
- 反馈结果已提供资源选项，用户选择后才创建下一批生成任务。

当前真实缺口：

1. `GET /api/diagnosis/questions` 不建立服务端会话或冻结实际发题清单。
2. 旧 `POST /api/diagnosis/submit` 接受任意题目子集；单节点只答一道题也可能形成客观分数。
3. 节点诊断目前主要是已提交题目的简单平均，没有覆盖状态、题库版本、错误维度或等价表单。
4. Report 3.0 能展示掌握投影，但没有活动学习处方、诊断覆盖和隔离复测结果。
5. generation focus snapshot 只冻结节点 ID 和排序，五类资源仍主要接收通用生成要求。
6. 当前没有独立于教学内容的后测题池，无法证明掌握提升不是见过相似题造成的。

执行者必须先用失败反例复现这些缺口；不得把本任务书描述直接当作实现事实。

## 3. 不可破坏的边界

### 3.1 数据真实性

- 客观分数必须由服务端使用当前题库 answer key 计算。
- 客户端只提交 question ID 和答案，不提交可信 correct count、score 或 mastery。
- 自评只能作为低置信先验或说明，不得进入 verified weak、accuracy 或学习提升统计。
- 覆盖不足必须是 `screening/needs_evidence/not_measured`，不得转换为 0 分或已掌握。
- 报告、处方和生成使用同一个 MasteryService 投影及同一冻结证据 hash。
- 相同幂等请求不得重复写 evidence、画像版本、处方、路径、Attempt 或生成任务。

### 3.2 兼容性

- Report 3.1 以 additive 方式保留 Report 3.0 全部字段。
- 现有 `/api/diagnosis/questions` 继续作为兼容题目读取入口，不泄露答案或解析。
- 现有 `/api/diagnosis/submit` 保留路径和响应 DTO，但内部必须应用覆盖判定；覆盖不足只产生低置信 screening evidence，不能绕过规范投影成为 verified weak/mastered。
- 现有正式 run/batch evaluation、Attempt、反馈事务、路径和资源发布语义保持不变。
- 处方字段缺失的旧生成任务继续按 explicit target 或 auto focus 工作。
- 数据库只做可回滚、向前兼容的 additive migration，不删除或重命名现有表。

### 3.3 并行业务边界

本执行者可以修改：

- `backend/app/api/learners/diagnosis.py`；
- `backend/app/api/feedback/`、`backend/app/api/reports/`、文本 generation API；
- `backend/app/services/learners/`、`feedback/`、`reports/`、`generation/`；
- `backend/app/agents/learning_agents/`；
- `backend/app/agents/resource_workflows/learning_documents/`；
- 相关 learner、diagnosis、mastery、feedback、reports、generation 模型与仓储；
- 对应 SQLite migration、fixture、journey 和测试；
- `frontend/src/features/` 下 diagnosis/onboarding、feedback、reports、generation；
- `backend/app/containers.py`、通用 `backend/app/config.py`、`backend/.env.example`；
- `docs/api.md`、`docs/architecture.md` 和本任务书。

本执行者禁止修改：

- `backend/app/agents/resource_workflows/interactive_courseware/`；
- `backend/app/core/courseware/`；
- `backend/app/models/courseware/`；
- `backend/app/services/courseware/`；
- `backend/app/api/courseware/`；
- `backend/config/courseware_*.json`；
- `backend/scripts/courseware_*.py`；
- 课件测试、fixture 和前端 courseware feature；
- `docs/courseware/courseware_quality.md`；
- 互动课件事件、progress 或 quality summary 到画像掌握度的接入。

若共享文件已有课件执行者的进行中修改，先完成专属目录工作，待该文件无人写入后只落盘本文允许的闭环改动；必须在执行记录中列出保留的课件内容。

## 4. 固定实施顺序

```text
M0 冻结可信度反例
→ M1 持久化诊断会话 2.0
→ M2 覆盖和置信度判定
→ M3 学习处方
→ M4 处方驱动生成
→ M5 隔离复测
→ M6 报告与下一轮
→ M7 两轮纵向 journey
```

每阶段必须遵循：新增失败反例 → 最小真实实现 → 专项测试 → 上层回归 → 执行记录。不得删除、跳过或放宽测试来制造通过。

## 5. M0：冻结可信度反例

至少冻结以下失败反例：

- 单答一道题就把节点标为 weak 或 mastered；
- 提交未由会话发出的题目；
- 提交另一 learner、另一知识库或另一题库版本的题目；
- 同一 phase 重复 question ID；
- 过期、已完成或被题库更新失效的会话仍写画像；
- 相同 idempotency key 不同答案未冲突；
- stale profile version 部分写入；
- 只完成 baseline 的节点进入 verified weak；
- 自评或客户端 score 进入 objective activity；
- prescription 跨 learner、知识库或画像版本复用；
- held-out question/answer 进入 generation Prompt、resource、Tutor 或日志；
- 相同 follow-up 选择创建两个 child run；
- 报告 revision 未随 diagnosis/prescription/reassessment 变化；
- SQLite 重启后 session、处方、复测结果或排序变化。

M0 完成门：反例在旧实现上稳定失败，现有正式 run/batch 服务端判分测试继续通过。

## 6. M1：持久化诊断会话 2.0

### 6.1 新增公开接口

```http
POST /api/diagnosis/sessions
POST /api/diagnosis/sessions/{session_id}/answers
```

创建请求：

```text
learner_id
knowledge_base_id?          # 缺失时使用画像当前知识库
skill_node_ids[]?           # 缺失时使用当前方向可诊断节点
expected_profile_version
```

创建响应 `DiagnosticSessionV2`：

```text
schema_version = "2.0"
session_id
learner_id
knowledge_base_id
profile_version
question_bank_version
question_bank_hash
phase_no = 1
phase = screening
status = awaiting_answers
questions[]                 # 只含公开题面
coverage_plan
issued_at
expires_at
```

答案请求：

```text
phase_no
idempotency_key
answers[] = {question_id, answer}
```

答案响应仍为 `DiagnosticSessionV2`，状态为：

```text
awaiting_answers             # 当前 phase 尚未完整提交时不允许部分判分
needs_confirmation          # 返回 phase 2 题目
complete                    # 返回 final_result
expired
conflict
```

客户端不得选择 phase 2 节点或题目。

### 6.2 持久化记录

通过 additive migration 增加：

- `diagnostic_sessions`：会话、learner/KB/profile version、题库 hash、phase、状态、过期时间、request hash；
- `diagnostic_session_items`：session、phase、question ID、node、dimension、form、顺序和 answered 状态；
- `diagnostic_session_submissions`：phase、idempotency key、request hash、服务端判分摘要和提交时间。

不得持久化到 SSE、普通日志或报告 payload 的内容：标准答案、解析全文和 learner 原始自由文本。

### 6.3 会话语义

- 会话默认 30 分钟过期；过期后不可写画像，需新建会话。
- 创建时冻结题库 version/hash 和 profile version。
- question bank hash 改变时未完成会话进入 `conflict`，不混用新旧题。
- profile version 改变时提交返回 409，不部分写入。
- 同一 idempotency key 同一 payload 返回原结果；不同 payload 返回 409。

### 6.4 M1 完成门

- API、DTO、鉴权、过期、题库冲突、画像 CAS、幂等和 SQLite 重启测试通过；
- 答案和解析不出现在公开 question、事件、日志和错误响应中。

## 7. M2：两阶段覆盖和置信度判定

### 7.1 phase 1 screening

- 诊断范围默认最多 13 个节点；显式范围必须属于当前知识库。
- 每个节点选择一题 `is_baseline=true` 的题目。
- 排序固定为知识图谱稳定顺序，再按 question ID。
- phase 必须全量提交；缺题、额外题和重复题均拒绝，不产生部分 evidence。

phase 1 只产生 screening signal，不直接形成 weak/learning/mastered。

### 7.2 phase 2 confirmation

按以下优先级选择最多 4 个节点：

1. 当前 `confirmed_weak`；
2. 当前 `regressing_learning`；
3. phase 1 baseline 错误；
4. 有相互冲突的既有客观证据；
5. 阻塞下游最多的先修节点；
6. 最近 evidence 时间和 node ID 稳定排序。

每个选中节点固定使用同一校准版本的 concept、scenario、misconception 三道题。总题量不得超过 25。

未进入 phase 2 的节点：

- baseline 错误或已有风险：`needs_evidence`；
- baseline 正确且无风险：`screened_no_weak_signal`；
- 均不得写成 verified weak/mastered。

### 7.3 正式判定

仅完成三道平衡题的节点计算正式诊断分数：

- `< 0.60`：`weak`；
- `0.60–0.85`：`learning`；
- `> 0.85`：`mastered`。

新增 `DiagnosticCoverageV1`：

```text
status = complete | screening_only | needs_evidence | not_measured
required_item_count
answered_item_count
dimensions_required[]
dimensions_answered[]
question_bank_version
calibration_version
```

新增 `DiagnosticNodeFindingV1`：

```text
skill_node_id
coverage
score: float | null
status = weak | learning | mastered | screened_no_weak_signal | needs_evidence
confidence = none | low | medium | high
failed_dimensions[]
reason_codes[]
source_session_id
```

### 7.4 旧接口兼容

`POST /api/diagnosis/submit` 继续接受原 DTO 并返回原 `DiagnosticResult`：

- 服务端按提交 question IDs 建立一次性 session 并校验 learner、KB、题库和重复题；
- 只有同一节点 concept/scenario/misconception 三维齐全时才能写规范客观 evidence；
- 覆盖不足时兼容响应可展示已答题情况，但 MasteryService 只记录 low-confidence screening，不得进入 verified weak/mastered；
- 前端主链迁移到 session 2.0，不再使用旧 submit 创建正式诊断。

### 7.5 M2 完成门

- 单题、任意子集和 baseline-only 均不能改变 verified mastery；
- 39 题示例库在正常范围内可稳定生成 phase 1/2；
- 报告和 ability-nodes 对同一节点的 score/status/confidence 一致。

## 8. M3：学习处方

### 8.1 `LearningPrescriptionV1`

新增持久化、版本化处方：

```text
schema_version = "1.0"
prescription_id
learner_id
knowledge_base_id
profile_version
mastery_snapshot_hash
source_type = diagnosis | learning_attempt | reassessment
source_id
status = proposed | accepted | superseded | completed
targets[]                    # 最多 3 个
recommended_resource_options[]
reassessment_blueprint
created_at
accepted_at?
superseded_by?
```

`PrescriptionTargetV1`：

```text
skill_node_id
rank
priority_group
current_score: float | null
confidence
coverage_status
failed_dimensions[]
reason_codes[]
blocking_prerequisite_ids[]
downstream_count
difficulty
teaching_strategies[]
success_criteria
```

### 8.2 排序和生命周期

处方目标顺序固定为：

1. `confirmed_weak`；
2. `regressing_learning`；
3. 阻塞性先修节点；
4. 既有 MasteryService downstream count；
5. 最近证据时间；
6. node ID。

只取前三个目标。不得在 FeedbackService、ReportService 或 planner 中复制该排序。

- 新诊断/Attempt/复测改变规范优先级时，旧 proposed 处方变为 `superseded`。
- 用户确认时校验 learner、KB、profile version 和 mastery hash。
- stale 处方返回 409 `LEARNING_PRESCRIPTION_STALE`。
- 相同来源和相同 snapshot hash 幂等返回同一处方。

### 8.3 资源建议

处方只自动建议，不自动创建任务：

- remediate：讲义/复习清单/分阶测试题或实操指南/案例分析/分阶测试题；
- practice：复习清单/实操指南/分阶测试题；
- advance：案例分析/分阶测试题。

用户仍可在允许的五类文本资源中选择 1–3 类并覆盖建议难度；不能通过前端改写处方目标节点和证据。

### 8.4 M3 完成门

- diagnosis、正式 Attempt 和 reassessment 均能幂等生成处方；
- 报告与反馈返回同一 prescription ID、目标顺序和 reason codes；
- 处方重启、supersede、accept 和 stale 冲突测试通过。

## 9. M4：处方驱动文本资源生成

### 9.1 additive 公开契约

`FeedbackLoopResult` additive 返回：

```text
prescription: LearningPrescriptionV1 | null
```

`FeedbackFollowupSelection` additive 接受：

```text
prescription_id: string | null
```

`GenerateRequest` additive 接受：

```text
prescription_id: string | null
```

生成 focus 优先级固定为：

```text
已确认且有效的 prescription
> 用户显式 target_skill_nodes
> MasteryService auto focus
```

如果请求同时传 prescription 和不一致的 target nodes，返回 422，不静默合并。

### 9.2 冻结快照

GenerationJob 创建时冻结：

```text
prescription_snapshot
prescription_hash
mastery_snapshot_hash
profile_version
target node IDs
failed dimensions
teaching strategies
success criteria
```

retry 必须复用原快照；画像后续变化不得改写正在执行或重试的任务。

### 9.3 planner 与五类资源

planner 和资源 Agent 必须消费处方而不是只消费通用 weak points：

- 讲义：解释对应错误维度和误区，补齐阻塞性先修；
- 实操指南：针对失败步骤提供可执行练习和排错；
- 分阶测试题：覆盖 success criteria，但不得使用 held-out item；
- 复习清单：生成对应节点、错误维度和复习动作；
- 新版复习清单的“会/模糊/不会”只是一份本地阅读自评，不创建正式 Attempt，不更新 Mastery、画像或 LearningPath。
- 案例分析：验证跨情境迁移和决策原因。

Prompt 只接收必要的脱敏处方字段，不接收标准答案、held-out 题面或学习者原始自由文本。

### 9.4 用户确认

反馈页和报告页展示：

- 为什么推荐这些节点；
- 当前证据和置信度；
- 建议资源组合、难度和预期目标；
- “确认生成”按钮。

只有确认后调用现有 follow-up 创建流程；刷新或重复点击不得创建第二个 child run。

### 9.5 M4 完成门

- 处方目标和策略可追溯到生成 job、workflow state 和资源要求；
- retry 冻结、stale 冲突、显式目标优先级和用户确认幂等测试通过；
- 五类文本资源工作流、审核、Claim、发布、API 和 Markdown 回归通过。

## 10. M5：隔离复测

### 10.1 题库元数据

示例知识库正式题目增加：

```text
assessment_pool = learning | reassessment
form_id = A | B | C | null
diagnostic_dimension = concept | scenario | misconception
difficulty_band
calibration_version
```

每个能力节点至少冻结三个互不重叠的等价表单：

- A：诊断 phase 2 confirmation；
- B：第一轮处方后测；
- C：第二轮处方后测；
- 每个表单三题，覆盖 concept、scenario、misconception；
- 同一 calibration version 内难度带保持可比。

题库不足时必须返回 `not_measured`，不得复用已暴露题制造提升。

### 10.2 新增接口

```http
POST /api/feedback/reassessments
POST /api/feedback/reassessments/{session_id}/submit
```

创建请求：

```text
learner_id
prescription_id
expected_profile_version
```

创建响应 `ReassessmentSessionV1`：

```text
session_id
prescription_id
form_id
calibration_version
questions[]                 # 无答案和解析
issued_at
expires_at
status
```

提交请求：

```text
idempotency_key
answers[] = {question_id, answer}
```

服务端判分后创建正式 Attempt，`evaluation_source=reassessment_v1`，并通过既有反馈事务更新 mastery、path、profile version 和下一份处方。

### 10.3 防泄漏

reassessment pool 不得进入：

- RAG 检索证据；
- planner/generator/reviewer Prompt；
- 已发布文本资源；
- Tutor evidence；
- 报告公开题面；
- SSE、普通日志、错误响应和 fixture 输出中的 answer/explanation。

记录 learner+node 的 item exposure；A/B/C 表单已使用后不得在同一 learner 的后续学习内容中出现。

### 10.4 `LearningOutcomeV1`

```text
skill_node_id
prescription_id
baseline_form_id
post_form_id
calibration_version
baseline_score: float | null
post_score: float | null
delta: float | null
status = mastered | improved | unchanged | regressed | not_comparable
reason_codes[]
measured_at
```

确定性判定：

- `mastered`：post score `> 0.85`；
- `improved`：可比表单且 delta `>= 0.20`；
- `regressed`：可比表单且 delta `<= -0.20`；
- `unchanged`：可比且介于上述区间；
- 缺少等价表单、版本不同或覆盖不足：`not_comparable`，分数/增量按缺失事实保留 null。

### 10.5 M5 完成门

- A/B/C 不重叠、难度/维度覆盖和题库版本测试通过；
- 防泄漏静态扫描和运行时 payload 测试通过；
- 后测幂等、鉴权、CAS、SQLite 重启和无题 not-measured 测试通过。

## 11. M6：Report 3.1 与下一轮

### 11.1 additive Report 3.1

保留 Report 3.0 全部字段，新增：

```text
diagnostic_evidence_summary
  latest_session_id
  question_bank_version
  complete_node_count
  screening_only_count
  needs_evidence_count
  measurement_coverage: float | null

active_learning_prescription: LearningPrescriptionV1 | null

learning_outcomes[]: LearningOutcomeV1
```

页面必须明确区分：

- 已验证薄弱；
- 学习中退步；
- screening signal；
- 待补证据；
- 复测已改善/已掌握/未变化/退步/不可比较。

### 11.2 revision 与 SSE

Report revision 在既有组成基础上增加变化域：

```text
diagnosis
prescription
reassessment
```

- generated_at 继续不参与 revision；
- ETag、If-None-Match、认证、window_days 和 304 语义保持不变；
- SSE payload 只发送 changed domains、revision 和 allow-list 元数据；
- 不发送题面、答案、处方内部快照、自由文本或错误栈。

### 11.3 下一轮处方

复测提交后只调用唯一 MasteryService：

- mastered 节点退出下一份处方；
- improved 但未 mastered 的节点按新状态重新排序；
- unchanged/regressed 节点继续进入候选；
- not-comparable 和覆盖不足节点进入 needs evidence；
- 新处方 supersede 旧 proposed 处方，但不改写已 accepted 的历史生成快照。

### 11.4 M6 完成门

- Report 3.1、ETag 200/304、SSE、鉴权和 revision 域测试通过；
- report、ability-nodes、feedback 和 generation 对同一节点及 prescription ID 一致；
- 自评和 screening-only 不进入 verified activity 或掌握提升。

## 12. M7：两轮纵向 journey

新增 `backend/scripts/adaptive_mastery_journey.py`，使用脱敏 fixture、临时 SQLite 和真实服务层，不调用外部模型。

### 12.1 正向 journey

依次证明：

1. 创建 learner，问卷自评只形成低置信先验；
2. 创建诊断 session，phase 1 不直接改写 verified mastery；
3. phase 2 用 A 表单确认至少一个 weak 节点；
4. Report 3.1 显示覆盖、错误维度和 proposed prescription；
5. 用户确认资源组合后只创建一个 child generation run；
6. generation job 冻结 prescription，五类要求包含定向策略且不含 B/C 题；
7. 第一次使用 B 表单后测，节点 outcome 为 improved 但未 mastered；
8. 新处方继续保留该节点并更新策略；
9. 第二轮生成继续不泄露 C 表单；
10. 使用 C 表单后测达到 mastered；
11. 节点退出下一份处方，报告、ability-nodes 和 feedback 一致；
12. 重启 app/repository 后 session、outcome、处方、revision 和排序保持一致。

### 12.2 负向 journey

至少证明：

- phase 1 单题或缺题不能改写 mastery；
- 跨 learner/KB、过期、题库 hash 变化和 stale profile 拒绝；
- 幂等冲突不产生部分写入；
- prescription 跨 learner 或 stale version 拒绝；
- 重复确认不创建第二个 child run；
- held-out 内容不进入资源、Prompt、Tutor、报告、SSE 或日志；
- 无未暴露等价表单时 outcome 为 `not_comparable/not_measured`；
- 旧 `/diagnosis/submit` 覆盖不足不产生 verified weak；
- 课件事件不能进入 mastery evidence。

### 12.3 journey 状态

报告至少包含：

```text
schema_version
status = LOCAL_READY | PARTIAL
task_status = TASK_READY | TASK_PARTIAL
joint_status = JOINT_PENDING | JOINT_READY | JOINT_PARTIAL
base_head
initial/final profile_version
initial/final report_revision
diagnostic coverage assertions
prescription assertions
generation snapshot assertions
held-out leakage assertions
round_1 outcome
round_2 outcome
mastery consistency assertions
idempotency and authorization assertions
restart consistency
test_duration
```

本执行者独立完成时必须为 `TASK_READY + JOINT_PENDING`，不得等待或修改课件任务来设置 `JOINT_READY`。

## 13. 验证顺序

执行者根据真实新增路径补全命令，但至少覆盖以下层级：

```powershell
# 诊断会话、覆盖、处方和 outcome 纯策略
python -m pytest backend/tests/unit/learners backend/tests/unit/reports `
  backend/tests/unit/models/test_learner_mastery_contracts.py `
  backend/tests/unit/policies/test_learner_mastery_policy.py `
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/adaptive-mastery-unit

# API、服务、鉴权、ETag 和 SSE
python -m pytest backend/tests/integration/api/test_knowledge_api.py `
  backend/tests/integration/api/test_feedback_api.py `
  backend/tests/integration/api/test_feedback_loop_api.py `
  backend/tests/integration/api/test_report_api.py `
  backend/tests/integration/services/test_feedback_loop_service.py `
  backend/tests/integration/services/test_feedback_report.py `
  backend/tests/integration/services/test_report_stream.py `
  backend/tests/integration/services/test_generation_focus.py `
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/adaptive-mastery-integration

# migration、SQLite restart 和 longitudinal journey
python -m pytest backend/tests/migrations backend/tests/e2e `
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/adaptive-mastery-persistence
python backend/scripts/adaptive_mastery_journey.py `
  --output backend/.pytest-tmp/adaptive-mastery-journey.json

# 前端
npm --prefix frontend run test:learner-mastery
npm --prefix frontend run test:learning-report
npm --prefix frontend run test:learning-report-browser
npm --prefix frontend run build

# 五类文本资源回归
python -m pytest backend/tests -q -p no:cacheprovider `
  --basetemp backend/.pytest-tmp/adaptive-mastery-non-courseware `
  --ignore-glob='*courseware*'

# 完整后端；并行课件失败只记录，不越界修复
python -m pytest backend/tests -q -p no:cacheprovider `
  --basetemp backend/.pytest-tmp/adaptive-mastery-all

git diff --check
git status --short
```

若建议路径尚不存在，执行者应在对应领域目录建立清晰命名的专项测试，不得为了匹配示例命令创建无意义转发文件。

## 14. 独立完成与联合完成

### 14.1 `TASK_READY`

必须同时满足：

- M0-M7 全部完成；
- session 2.0、覆盖和幂等门通过；
- screening-only 不改写 verified mastery；
- LearningPrescriptionV1 在 diagnosis、feedback、report 和 generation 一致；
- 用户确认后只创建一个 generation job；
- A/B/C 等价表单和防泄漏门通过；
- 两轮 journey 证明节点改善并最终退出处方；
- Report 3.1、ETag、SSE 和前端专项通过；
- 五类文本资源回归和非课件全量通过；
- 完整后端已实际运行并准确报告并行课件状态。

完成后设置：

```text
task_status = TASK_READY
joint_status = JOINT_PENDING
```

### 14.2 `JOINT_READY`

两项任务都结束后由仓库负责人运行：

- 课件和 adaptive mastery 两条 journey；
- 课件、报告浏览器专项；
- 前端 build；
- 完整后端；
- 共享文件内容和双方禁止目录审计。

只有该联合门实际通过才能设置 `JOINT_READY`。本执行者不得为了联合通过修改课件代码。

## 15. 执行规则

1. 开始前阅读根 `AGENTS.md`、`README.md`、`git-workflow.md`、本文、`docs/api.md` 和 `docs/architecture.md`。
2. 记录分支、`base_head` 和开始 dirty 状态；已有修改默认属于用户或上一轮任务。
3. 不切换分支、不创建 worktree、不重置或清理工作区。
4. 只修改 3.3 允许范围，不编辑任何课件领域文件。
5. 每阶段先写失败反例，再实现，再运行专项和上层回归。
6. 不删除、跳过或放宽测试制造通过。
7. 不复制 MasteryService 的掌握公式、优先级或下游影响算法。
8. 不把 baseline、自评、客户端分数或旧主观反馈当作 verified mastery。
9. 不把 `not_measured/not_comparable` 转成数值 0。
10. 不把 held-out 题面、答案或解析传给生成、Tutor、报告或日志。
11. 不自动启动下一批资源生成；必须保留用户确认。
12. 不接入互动课件学习事件。
13. 不提交数据库、journey JSON、截图、日志、缓存、构建产物、题库答案导出或凭据。
14. 除非用户另行授权，不提交、推送或合并。
15. 每阶段只在本文执行记录追加真实文件、命令、计数和剩余缺口。

## 16. 最终报告要求

最终报告必须列出：

- M0-M7 状态；
- 分支、base/final HEAD 和开始/结束 dirty 状态；
- `TASK_READY/TASK_PARTIAL` 与 `JOINT_PENDING`；
- session、coverage、finding、prescription、reassessment 和 outcome 公开契约；
- phase 1/2 题量、节点覆盖和 needs-evidence 数量；
- 处方目标、reason codes、排序和 generation snapshot；
- A/B/C 防泄漏和两轮 outcome；
- report、ability-nodes、feedback 和 generation 一致性；
- ETag/SSE、鉴权、幂等、CAS 和 SQLite 重启结果；
- 实际执行的全部命令、通过数、跳过项和失败项；
- 修改过的共享文件、保留的课件内容和课件禁止目录零修改审计；
- 未完成的 CI、目标部署、真实学习者纵向观察和生产效果证据。

本地 fixture 的两轮提升只证明闭环逻辑和测量口径可执行，不等于真实学习者群体已经获得统计显著提升。

## 17. 执行记录

执行者从 M0 开始追加。任务分发前不得预填“已完成”。
# 课件主动回忆自评

`courseware_self_report` 是非验证、低置信度 Evidence 来源。完整节点的“会=1、模糊=0.5、不会=0”等权平均只更新 `self_report_prior`，不会创建 Attempt、增加客观证据计数或替代正式成绩。
