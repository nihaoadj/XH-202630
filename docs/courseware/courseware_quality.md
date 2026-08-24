# 课件质量提升任务书（Luna 执行版）

> 任务性质：互动课件专项实现任务书。按 S0 → S1 → S2 → S3 → S4 → S5 → S6 连续执行，不在阶段之间等待“继续”。
>
> 执行模型：Luna。先阅读仓库根目录 `AGENTS.md`、`README.md`、`git-workflow.md`、本文和 `interactive_html_courseware_workflow_plan.md`，再检查当前代码与 `git status --short`。
>
> 分支：`feature/courseware-quality`。未经用户明确要求，不提交、推送或合并。
>
> 完成口径：本地确定性门与有界真实模型质量门同时通过，才能报告 `LOCAL_READY + LOCAL_QUALITY_READY`。本地通过不等于 CI、部署或生产就绪。

## 1. 任务目标

在不破坏 R0–R5 已完成完整性边界的前提下，提高互动课件的：

- 真实模型主链成功率；
- 教学目标与来源覆盖率；
- 内容深度、跨资源融合和课程连贯性；
- 互动数量、类型多样性和教学目的性；
- 自动审核的定位能力与定向修复成功率；
- 浏览器恢复、离线重放、无障碍和质量证据可信度。

本任务不是重新建设课件链路。批次继承、current release 隔离、progress 2.0 组件实例恢复、Q5 journey、HTTP-origin artifact 恢复和发布候选聚合已经完成，必须保持不回归。

## 2. 当前审计基线

执行前先复核代码和报告，不要仅依据本文假设现状。当前已确认的基线为：

- 核心完整性专项：`6 passed`；
- 课件 integration、e2e 和 migration：`92 passed`；
- Q5 journey schema 1.1：`LOCAL_READY`；
- browser schema 1.3：11 组件 × 3 主题通过；
- 现有 12-case 冻结评测顶层状态通过。

当前质量证据的已知缺口：

- 12 个冻结 case 的 `quality.passed` 全部为 `false`，但顶层报告仍可 `passed=true`；
- 多数正向 fixture 实际只渲染 `callout`，不能证明互动多样性；
- 已有 4 个脱敏真实模型组合仅 1 个可发布，workflow success 为 25%，scene success 为 54.55%；
- 高频失败包括 `AI_PLAN_SLOT_MISMATCH`、`AI_SCENE_FALLBACK`、`COURSEWARE_AUTO_REVIEW_UNRESOLVED` 和预算耗尽；
- Planner 被要求重复输出平台已经冻结的槽位，轻微顺序差异会触发整课降级；
- Reviewer 输入缺少稳定 `scene_id/block_id`，修订路由无法可靠定位；
- Prompt 中维护了与组件注册表不一致的第二份组件列表；
- `expected_duration_minutes` 和 `interaction_intensity` 已持久化，但没有真正控制课程长度、内容密度和互动配额；
- 教学目标主要按资源生成，缺少概念级融合、跨资源综合、示例、误区和迁移练习。

执行者必须先用失败测试复现这些缺口。若代码已经变化，以当前可复现证据为准，并在执行记录中说明差异。

## 3. 不可破坏的边界

### 3.1 批次和来源语义

必须同时保持以下四条，不能互相替换：

1. 一次课件生成所采用的全部文本参考资源必须属于同一个非空反馈批次。
2. 生成课件继承该唯一 `batch_id`，作为该批次的一份资源展示和管理。
3. 上述规则不表示系统中的所有互动课件都属于同一个反馈批次；不同生成任务可以属于不同批次。
4. 互动课件即使继承了批次，也不能成为下一份课件的事实参考源，避免递归引用。

`batch_id` 表示资源归属，`source_resource_ids/source_refs` 表示事实引用。来源冻结后，重试、修订、candidate 和新 release 均不得改变批次。

### 3.2 模型与平台边界

- 模型只能生成版本化、严格校验的结构化契约。
- 模型不得生成或控制 HTML、CSS、JavaScript、URL、CSP 或任意组件名。
- 组件能力清单必须从平台注册表动态生成，Prompt 中不得维护第二份硬编码列表。
- learner-visible 事实、答案、反馈、分支结果和分类关系必须追溯到冻结来源。
- 未知组件、未知来源块、快照混用和危险内容不能进入 renderer。
- `core/courseware` 继续拥有确定性 renderer、runtime、安全策略和 packaging，不访问数据库或模型。
- 不建设管理员审核台、人工审核或人工发布流程。
- SQLite 本地拓扑继续为一个 Web 进程加一个 Durable Worker；不在本任务扩展多 Worker。

### 3.3 并行文件边界

本执行者可以修改：

- `backend/app/agents/resource_workflows/interactive_courseware/**`；
- `backend/app/api/courseware/**`、`backend/app/services/courseware/**`；
- `backend/app/models/courseware/**`、`backend/app/core/courseware/**`、`backend/app/db/courseware/**`；
- `backend/tests/**/courseware/**` 及名称明确属于 courseware 的测试；
- `backend/scripts/courseware_*.py`；
- `backend/tests/fixtures/courseware/**`；
- `frontend/src/features/courseware/**` 及课件专项测试；
- `docs/courseware/**`。

禁止修改：

- learners、onboarding、feedback、reports 和五类文本学习文档的业务实现；
- `p0_19` 或画像掌握状态迁移；
- 画像/反馈/报告 API、共享报告 DTO 和文本资源生成重点策略；
- 互动课件结果到画像掌握度的接入，该事项明确延期。

如果实现确实需要修改未授权共享文件，先停止该修改，在最终报告中列出所需符号、原因和最小补丁，不得自行扩大边界。

## 4. 总体执行顺序

| 阶段 | 目标 | 前置 | 阶段完成门 |
|---|---|---|---|
| S0 | 建立真实质量基线 | 无 | evaluator 2.0 的 20-case 失败反例固定 |
| S1 | 提高真实模型主链成功率 | S0 | enrichment、一次修复、局部 fallback 专项通过 |
| S2 | 构建概念级丰富课程 | S1 | 时长、来源、跨资源和配额专项通过 |
| S3 | 新增四类受控互动 | S2 | 契约、runtime、恢复、安全和 15×3 矩阵通过 |
| S4 | 升级审核与定向修订 | S3 | rubric、定位和定向修复专项通过 |
| S5 | 统一体验与质量汇总 | S4 | quality summary 2.0、UI 和兼容读取通过 |
| S6 | 冻结验收与候选聚合 | S5 | `LOCAL_READY + LOCAL_QUALITY_READY` |

每一阶段都必须遵循：新失败反例 → 最小真实实现 → 专项测试 → 上层回归 → 阶段执行记录。不得删除、跳过或放宽测试来制造通过。

## 5. S0：建立真实质量基线

### 5.1 evaluator 2.0

将冻结 evaluator 升级到 schema 2.0。保留现有 12 个安全、来源、恢复和发布 case，新增 8 个质量 case，共 20 个：

1. 短时低互动；
2. 30 分钟中互动；
3. 60 分钟高互动；
4. 多资源概念融合；
5. 重复来源和互补来源；
6. 来源冲突显式并列呈现；
7. 缺少可判分材料时的互动配额约束降级；
8. 可定位审核与语义修复。

### 5.2 通过语义

- 正向 case 只有在契约硬门、安全硬门、预期状态和 `quality.passed=true` 全部满足时才通过。
- 负向 case 按预期拒绝或隔离，不要求生成课件质量分。
- `not_measured` 和 `external_pending` 不得转换为数值 0 或普通失败。
- 视觉证据由 browser report 单独给出，不在离线 evaluator 中伪造视觉分数。
- 顶层报告分别给出 contract、safety、pedagogy、content richness 和 interaction diversity，不能用单个布尔值掩盖子门失败。
- baseline 只在确定性输出确实变化后逐 case 审核更新，禁止整表自动重写。

### 5.3 S0 完成门

- 20 个 case 均具有明确类型、预期终态、硬门预期和质量预期；
- 旧实现必须在新增正向质量 case 上按预期失败；
- 顶层通过状态不能绕过任一必需子门；
- evaluator 报告和 baseline 都带 schema 2.0。

## 6. S1：提高真实模型主链成功率

### 6.1 Plan enrichment

平台继续拥有 LearningDesign、目标图、storyboard、稳定 `objective_id` 和 `scene_id`。Planner 不再返回完整槽位列表，新增：

```text
CoursewarePlanEnrichmentV2
  schema_version = "2.0"
  course_title
  course_summary
  objectives[]
    objective_id
    title
    teaching_intent
  scenes[]
    scene_id
    title
    teaching_intent
    preferred_component_ids[]
```

约束：

- enrichment 只能引用平台传入的 ID；
- 平台按 ID 合并，不依赖数组顺序；
- 缺少单个 enrichment 时保留平台确定性值，只降级该项；
- 未知 ID、重复 ID 和未注册组件先拒绝该 candidate，不得触发整课 `AI_PLAN_SLOT_MISMATCH`；
- v1 已发布 artifact 继续通过只读适配器读取，不回写旧数据。

### 6.2 有界语义修复

Planner 和 scene composer 均采用固定两步：

1. 第一次结构化生成；
2. 若结构合法但语义违规，返回精确违规字段、允许 ID、允许组件和来源范围，最多进行一次紧凑修复。

第二次仍失败时：

- enrichment 缺项使用平台确定性值；
- 单场景 candidate 失败时，在 resilient 策略下使用通过来源、安全和组件硬门的确定性场景；
- 已通过的其他场景不得被一起隔离；
- 只有来源、安全、必需场景或确定性替代也失败时，才隔离整课。

### 6.3 固定预算

| 阶段 | token 上限 |
|---|---:|
| 总计 | 49,152 |
| planner | 4,096 |
| scene composition | 30,720 |
| quality review | 4,096 |
| revision | 10,240 |

附加限制：

- 单 scene 调用不超过 4,096 token；
- 总运行时限 1,050 秒；
- scene 阶段最多 600 秒；
- 每次模型调用最多两次尝试；
- 不允许无限重试或通过缩小评测分母掩盖预算耗尽。

### 6.4 S1 完成门

- Planner 输出不再负责复制平台槽位；
- 数组顺序变化不会导致整课失败；
- 未知 ID、来源或组件的 candidate 被精确拒绝；
- 一次修复和局部确定性替代均有稳定事件、warning 和计数；
- 已通过场景不会因另一个场景失败而被隔离；
- Prompt 组件清单与注册表只有一个事实源。

## 7. S2：按时长构建更丰富的课程

### 7.1 SourceConceptIndex

新增来源约束的 `SourceConceptIndex`：

```text
SourceConceptIndex
  schema_version = "2.0"
  concepts[]
    concept_id
    label
    source_refs[]
    adopted_source_ids[]
  relations[]
    relation_type = prerequisite | complementary | duplicate | conflict
    from_concept_id
    to_concept_id
    source_refs[]
```

规则：

- 概念只能来自冻结 knowledge points 和 source blocks；
- 每个概念保留来源引用；
- 不允许模型创建第五种关系；
- conflict 必须并列展示各来源观点，模型不得擅自裁决；
- 每个 adopted source 至少进入一个目标和一个场景。

### 7.2 教学组织

场景类型升级为：

- `intro`
- `explain`
- `example`
- `compare`
- `practice`
- `scenario`
- `quiz`
- `recap`

多资源课件必须至少包含：

- 一个跨资源综合或对比场景；
- 一个跨资源 recap；
- 来源支持时的 worked example；
- 来源支持时的 misconception、hint 和 transfer block。

没有可靠答案时，只能生成探索、自评、提示或时间线互动，不能生成可判分答案。

### 7.3 时长和互动配额

| 预计时长 | 场景数 | 低互动 | 中互动 | 高互动 | 最少不同互动类型（低/中/高） |
|---|---:|---:|---:|---:|---:|
| 5–15 分钟 | 4–5 | 1 | 2 | 3 | 1 / 2 / 2 |
| 16–30 分钟 | 6–8 | 2 | 3 | 4 | 2 / 3 / 3 |
| 31–60 分钟 | 8–10 | 3 | 4 | 5 | 2 / 3 / 4 |
| 61–240 分钟 | 10–12 | 3 | 5 | 6 | 3 / 4 / 4 |

配额由平台确定性计算，模型只能在允许槽位内选择组件。冻结来源不足时：

- 设置 `interaction_quota_status="constrained"`；
- 返回机器可识别原因，例如 `INSUFFICIENT_SCORED_EVIDENCE`、`INSUFFICIENT_DISTINCT_CONCEPTS`；
- 报告目标配额、实际配额和差额；
- 不得生成无来源答案以凑配额。

### 7.4 S2 完成门

- 时长和互动强度真实影响场景数量、互动数量和不同类型数量；
- 每个 adopted source 进入目标和场景；
- 多资源课件具有跨资源场景和 recap；
- conflict 不被模型私自合并；
- 配额不足时显式 constrained，不隔离本来安全可学的课程。

## 8. S3：新增四类受控互动组件

组件注册表升级为 v2，并新增以下严格 payload。

### 8.1 `branching_scenario`

```text
start_node_id
nodes[2..8]
  node_id
  node_type = decision | terminal
  title
  body
  source_refs[]
  options[0..4]
    option_id
    label
    next_node_id
    feedback
    source_refs[]
```

决策节点必须有 2–4 个选项；terminal 不得有选项。节点和选项 ID 全局唯一，全部节点从 start 可达，至少一个 terminal，图必须无环。选项和反馈都必须有来源。状态仅保存当前节点 ID、路径 option IDs 和完成标记。

### 8.2 `categorization`

```text
categories[2..5]
  category_id
  label
  source_refs[]
items[3..12]
  item_id
  label
  correct_category_id
  source_refs[]
```

分类、条目和正确关系必须来源可验证；支持拖放和键盘点击归组。状态保存 item ID 到 category ID 的受控映射和完成标记，不保存自由文本。

### 8.3 `word_bank_cloze`

```text
prompt_segments[2..7]
blanks[1..6]
  blank_id
  correct_token_id
  feedback
  source_refs[]
tokens[2..12]
  token_id
  text
  source_refs[]
```

必须满足 `len(prompt_segments) = len(blanks) + 1`。不得通过分隔符字符串表示空位。正确 token、反馈和题意必须有来源。状态只保存 blank ID 到 token ID 的映射、提交和正确标记。

### 8.4 `timeline_explorer`

```text
events[2..10]
  event_id
  sequence
  title
  description
  source_refs[]
```

事件 ID 和 sequence 唯一，sequence 严格递增。该组件属于探索型互动，不强制判分。状态只保存当前 event ID、已展开 event IDs 和完成标记。

### 8.5 每个组件的完整交付

四个组件必须同时完成：

- 版本化 payload 与 catalog 注册；
- 来源子集校验和严格 ID 校验；
- renderer 与 runtime；
- progress 2.0 的 `scene_id + component_id` 实例恢复；
- learning event 和离线重放；
- keyboard、touch、focus、ARIA 和 reduced-motion；
- 三主题视觉 recipe；
- 恶意 ID、重复 ID、跨 scene 和跨实例状态注入测试。

browser matrix 从 11×3 升级为 15×3，共 45 个唯一 `component × theme` 组合，不得用重复组合补足计数。

### 8.6 S3 完成门

- 四个新组件严格 payload 的正反例通过；
- 浏览器中鼠标、键盘、触控和恢复行为一致；
- 多实例互不覆盖；
- 离线 artifact 和 HTTP-origin iframe 都可恢复；
- 15×3 矩阵、forced-colors、200% zoom 和 reduced-motion 通过。

## 9. S4：升级教学审核和定向修订

### 9.1 CoursewareReviewDecisionV2

```text
CoursewareReviewDecisionV2
  schema_version = "2.0"
  status = pass | revise | reject | unavailable
  issues[]
    dimension
    severity = warning | error
    scope = course | scenes | scene | block
    scene_id
    block_id?
    affected_scene_ids[]
    instruction
  rubric_scores
  summary
```

规则：

- 除 `unavailable` 外，error issue 必须至少定位到一个平台已知 `scene_id`；
- block scope 必须同时提供有效 `scene_id` 和 `block_id`；
- 多场景连贯性问题必须列出全部 `affected_scene_ids`；
- 未知 ID 或不可定位 error 不得随机选择场景修订；
- scene/block 问题只重生成目标 scene 或 block，其他已通过内容保持不可变。

### 9.2 九维 rubric

每项 0–4 分：

1. objective alignment；
2. coherence；
3. explanation depth；
4. example usefulness；
5. misconception handling；
6. practice gradient；
7. feedback quality；
8. interaction purpose；
9. cognitive load。

通过条件：

- 平均分不低于 3.0；
- objective alignment、feedback quality、interaction purpose 均不低于 3；
- 其他维度不得低于 2；
- 来源、答案正确性、安全和组件契约仍是独立硬门，不能被平均分抵消。

### 9.3 审核降级

审核不可用或问题无法定位时，在受控策略下执行确定性质量门：

- 确定性产物通过全部硬门和确定性教学门时，带明确 warning 发布；
- 确定性产物失败时隔离；
- 不得把 reviewer unavailable 记录为 reviewer passed；
- fallback 必须进入质量汇总，但不得重复计数。

### 9.4 S4 完成门

- reviewer 输入包含稳定 scene/block ID；
- 定向问题只修改目标内容；
- 多场景问题精确列出受影响场景；
- rubric 边界值、平均值和关键维度门均有测试；
- unavailable 和 unlocatable 路径具有明确且不同的事件和终态。

## 10. S5：统一渲染、体验和质量汇总

### 10.1 渲染和兼容

- 为 example、compare、scenario 和四个新组件增加确定性布局和三主题 recipe；
- 新 schema 只保留组件级互动，移除 scene-level quiz/practice 与 component payload 的重复表达；
- v1 已发布 artifact 使用只读适配器恢复，不修改旧 artifact；
- progress 继续使用 schema 2.0 和 `scene_id + component_id`，不新增自由文本状态；
- current release、component instance、nonce、artifact restore 和 batch 语义不得回归。

### 10.2 quality summary 2.0

至少返回：

- publication success；
- AI full-course success；
- required scene recovery rate；
- deterministic fallback count/rate；
- objective coverage；
- adopted source coverage；
- cross-source scene count；
- scene count；
- interactive scene count；
- unique interaction types；
- interaction quota status、target 和 actual；
- rubric scores 和 rubric passed；
- token、成本、retry 和延迟；
- 所有比例的分子、分母和 not-measured 原因。

重放同一 occurrence/event 不得增加 token、成本、场景、fallback 或成功次数。

### 10.3 用户界面

生成前后向用户展示：

- 预计课程结构；
- 实际时长档和场景数量；
- 互动类型摘要；
- 来源覆盖摘要；
- constrained 或 deterministic fallback 的简明降级提示。

用户界面不得展示 checkpoint、内部模型错误、Prompt、token 细节或候选产物内部状态。

### 10.4 S5 完成门

- quality summary 2.0 的每个指标均有确定性算法和幂等测试；
- 旧 artifact 可读，新 artifact 不再重复表达互动；
- 三主题和响应式布局通过浏览器专项；
- 用户能理解课程规模、互动构成和降级状态，但看不到内部实现细节。

## 11. S6：冻结评测、真实模型验收和候选聚合

### 11.1 报告版本

- evaluator：2.0；
- browser：1.4；
- live workflow：1.1；
- release candidate：1.2；
- journey：继续使用 1.1；
- fault matrix：保持现有契约。

release candidate 1.2 保留：

- `status=LOCAL_READY`：确定性、安全、迁移、journey 和 browser 全部通过；
- `status=PARTIAL`：上述任一项失败。

新增：

- `quality_status=LOCAL_QUALITY_READY`：有界真实模型评测达到阶段目标；
- `quality_status=QUALITY_PARTIAL`：缺少真实证据或未达目标。

本轮最终必须同时达到 `LOCAL_READY + LOCAL_QUALITY_READY`。

### 11.2 有界真实模型评测

固定 10 个脱敏组合，不能在失败后缩小分母。为优先提升首次结构化成功率，首次请求必须携带紧凑 JSON Schema；不得以增加无限重试代替结构约束。

- 总计最多 140 次模型调用、600,000 token、1,200 秒（20 分钟）；
- `spec` 预留最多 20 次、80,000 token；
- `scene` 预留最多 90 次、400,000 token；
- `quality_review` 预留最多 30 次、120,000 token；
- 每次调用最多两次尝试；
- 任一总量或阶段预算耗尽即停止并报告，scene 不得占用 spec/review 预留；实际 token 与预留 token 均写入报告。

真实调用只在全部无计费门通过、运行环境存在预期凭据时执行。不得打印凭据。若缺少凭据，准确标记 `LIVE_MODEL_CREDENTIALS_PENDING`，不能用 fake provider 代替真实质量结论。

### 11.3 阶段质量门

- 可发布课件不少于 8/10；
- 必需 AI scene 经恢复后的成功率不低于 85%；
- AI full-course success 不少于 7/10；
- 使用确定性内容降级的课件不超过 2/10；
- 来源、安全或未知组件错误发布数为 0；
- rubric 通过不少于 8/10；
- 来源足够的组合中，互动配额满足率不低于 90%。

### 11.4 S6 完成门

- 20-case evaluator 2.0 通过；
- 15×3 browser 1.4 通过；
- Q5 journey、fault matrix、前端专项和 build 通过；
- 后端专项与全量回归无非预期失败；
- 真实模型报告保留完整 10 组合分母、预算和失败路径；
- release candidate 1.2 正确区分 readiness 与 quality readiness。

## 12. 接口和兼容要求

- `POST /courseware/jobs` 不新增必填字段，继续使用已有学习目标、预计时长、互动强度和视觉风格。
- LearningDesign、Storyboard、PlanEnrichment、SceneSpec 和组件契约升级到 v2；旧已发布 artifact 必须保持可读。
- 新组件状态继续使用 progress 2.0 的实例边界，不新增自由文本持久化。
- 新契约优先存入已有 JSON 字段，预计不需要数据库迁移。
- 如果确认必须新增数据库列，先停止并报告跨分支影响；禁止修改 `p0_18` 和画像执行者独占的 `p0_19`。
- 不新增图片热点、远程素材、任意 URL、任意组件、自由 HTML 或自由 JavaScript。
- 不改变五类文本学习文档、画像、反馈和学习报告的公开行为。

## 13. 验证顺序

严格按以下顺序执行：

1. 新失败反例；
2. S1–S5 专项单元测试；
3. 课件 integration/e2e/migration；
4. 20-case evaluator 2.0；
5. 15×3 browser 1.4；
6. Q5 journey；
7. fault matrix；
8. 前端课件专项和 build；
9. 后端全量；
10. 10 组合有界真实模型评测；
11. release candidate 1.2 聚合。

基准命令按当前脚本参数校验后执行，报告写入 ignored 临时目录：

```powershell
python -m pytest backend/tests/unit/agents/test_courseware_worker.py backend/tests/unit/core -q -p no:cacheprovider --basetemp backend/.pytest-tmp/courseware-unit

python -m pytest backend/tests/integration/courseware backend/tests/e2e/courseware backend/tests/migrations -q -p no:cacheprovider --basetemp backend/.pytest-tmp/courseware-integration

python backend/scripts/courseware_eval.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --baseline backend/tests/fixtures/courseware/evals/baseline.json --output backend/.pytest-tmp/courseware-eval-2.json

python backend/scripts/courseware_next_journey.py --output backend/.pytest-tmp/courseware-journey.json --basetemp backend/.pytest-tmp/courseware-journey-tests

npm --prefix frontend run test:courseware-source-policy
npm --prefix frontend run test:courseware-events
npm --prefix frontend run test:courseware-journey
$env:COURSEWARE_BROWSER_REQUIRED='1'
npm --prefix frontend run test:courseware-browser
Remove-Item Env:COURSEWARE_BROWSER_REQUIRED
npm --prefix frontend run build

python -m pytest backend/tests -q -p no:cacheprovider --basetemp backend/.pytest-tmp/courseware-all

git diff --check
git status --short
```

脚本参数或测试路径若已改变，使用代码中的当前入口并在报告中列出实际命令，不要创建仅为让旧命令成功的转发文件。

## 14. Luna 执行规则

1. 连续完成 S0–S6；仅在权限、凭据、缺失依赖或需要越过文件边界时停止。
2. 每阶段先写失败测试，再修改真实实现，最后运行专项与上层回归。
3. 不覆盖 dirty worktree 中的既有修改，不整理无关文件。
4. 不修改或删除既有测试来制造通过。
5. 不把 deterministic fallback 描述为 AI 成功。
6. 不把离线 evaluator、fake provider、单 Worker 或浏览器 fixture 单独描述为真实课件质量或生产就绪。
7. 不提交数据库、报告、日志、截图、构建产物、缓存或凭据。
8. 不提交、推送、合并或触发外部系统。
9. 每阶段在本文末尾追加：阶段、关键文件、实际命令、结果、剩余缺口。
10. 两个并行分支各自通过不等于合并后通过；合并后必须重新运行共同门。

## 15. 最终报告模板

Luna 最终报告必须逐项列出：

- S0–S6 完成状态；
- 修改文件和公开契约；
- 20 个冻结 case 的结果；
- 15×3 浏览器矩阵和特殊环境结果；
- 10 个真实模型组合的逐项结果；
- 每个失败阶段和恢复路径；
- 场景数、互动数和不同互动类型；
- rubric 各维度分数；
- AI full-course、scene recovery 和 fallback 指标；
- 实际调用数、token、费用和时长；
- 所有执行命令和准确测试计数；
- 未完成的 CI、部署、凭据和生产观察事项；
- 与 `feature/learner-mastery` 合并后仍需执行的共同回归。

只有真实证据存在时才填写成功值；缺失证据使用 `NOT_MEASURED`、`EXTERNAL_PENDING` 或明确 pending code，不能伪造 0 或通过。

## 16. 执行记录

执行者从 S0 开始追加记录。任务分发前不得预填“已完成”。

### 16.1 2026-08-24 本地自动化执行记录

自动化目标：固定 20-case evaluator、15×3 浏览器矩阵、10 组合有界真实模型评测、S1–S5 失败反例、独立 Web/Worker 故障证据、发布候选聚合和全量回归；所有输出只写入仓库内 ignored 临时目录，不把报告、数据库、日志、截图、构建产物或凭据加入版本控制。

状态结论：

| 阶段 | 状态 | 证据结论 |
|---|---|---|
| S0 | `LOCAL_DONE` | evaluator schema 2.0，20/20 case 通过；self-test 通过。 |
| S1 | `LOCAL_DONE` | enrichment、未知来源/组件拒绝、一次定向修订和局部 fallback 反例通过。 |
| S2 | `LOCAL_DONE` | 时长、强度、来源采用、跨资源比较、冲突关系和互动配额反例通过。 |
| S3 | `LOCAL_DONE` | 四类 v2 互动契约、renderer/runtime、progress 2.0 恢复和 15×3 浏览器矩阵通过。 |
| S4 | `LOCAL_DONE` | 九维 rubric、scene/block 定位、逻辑 scene ID 到 Durable Worker 行 ID 的修订映射通过。 |
| S5 | `LOCAL_DONE` | 质量摘要 v2 和学习者界面展示通过；未测视觉维度仍明确记录为 `not_measured`。 |
| S6 | `PARTIAL` | 本地工具链和真实 DeepSeek 有界调用已完成，但真实质量门未达，不能写 `LOCAL_QUALITY_READY`。 |

本轮实际命令和结果：

- `python -m pytest backend/tests/unit/core -q --basetemp backend/.pytest-tmp/c-round-unit`：147 passed。
- `python -m pytest backend/tests/integration/courseware backend/tests/e2e/courseware backend/tests/migrations -q --basetemp backend/.pytest-tmp/c-round-courseware-final`：93 passed。
- `python backend/scripts/courseware_eval.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --baseline backend/tests/fixtures/courseware/evals/baseline.json --output backend/.pytest-tmp/courseware-c-round-eval-final.json`：schema 2.0，20 case，`passed=true`。
- 从 backend 工作目录执行 `python scripts/courseware_eval.py --self-test`：exit 0，self-test 通过。
- `npm --prefix frontend run test:courseware-events`、`test:workflow-events`、`test:tutor`：分别通过。
- `npm --prefix frontend run test:courseware-browser`：通过；summary schema 1.4，45 个矩阵项、15 个组件、3 个主题、无控制台错误。
- `npm --prefix frontend run build`：成功；仅有既有 Rollup 注释和 chunk size warning。
- `python -m pytest backend/tests -q --basetemp backend/.pytest-tmp/c-round-full`：577 passed，5 skipped。
- `git diff --check`：通过，无 whitespace error。

独立 Worker 与故障证据：

- `test_c1_process_fault_matrix.py`：14 passed；故障矩阵报告 18 类，包含强杀/重启、租约接管、心跳、重复投递、意外并发 claim、SQLite busy/断连、checkpoint 崩溃、artifact/release commit、outbox 重放和 graceful shutdown。
- 进程证据仍限定为一个 Web 进程、一个独立 Durable Worker 和一个文件型 SQLite；部署并发归一化为 1，意外重复消费者只验证幂等保护，不代表支持横向扩容。
- backup/restore、checkpoint、outbox、release pointer、artifact hash 和可读性均在进程故障套件中断言；不复制正在写入的数据库作为备份。
- `courseware_next_journey.py`：四个必需 journey case 全部通过，状态 `LOCAL_READY`。
- release candidate：`backend/.pytest-tmp/courseware-quality-release-candidate-final.json`，schema 1.2，`status=LOCAL_READY`，`quality_status=QUALITY_PARTIAL`，`quality_gate.status=not_met`；evaluator、artifact manifest、fault matrix、journey 和 browser evidence 全部 passed，live-model evidence 为 `quality_partial`（已真实执行但质量门未达），不计为 `LIVE_MODEL_REQUIRED`。

真实 DeepSeek 评测记录：

- 配置：`backend/config/courseware_live_model.deepseek.v2.json`；包含 provider、base URL、`deepseek-v4-flash`、`json_mode`、`thinking_mode=disabled`、120 秒 timeout、最多 2 次尝试、退避、USD/M tokens peak/off-peak 价格、模型版本、价格版本、生效日期和官方价格来源 URL；不含密钥。
- 当前调用命令：`python backend/scripts/courseware_live_workflow_smoke.py --config backend/config/courseware_live_model.deepseek.v2.json --enable --output backend/.pytest-tmp/courseware-quality-live-workflow-status-fixed.json --artifact-root backend/.pytest-tmp/courseware-quality-live-artifacts-status-fixed`。
- 本次真实调用执行固定 10-case 矩阵；其中 8 个组合进入工作流模型调用，2 个组合在来源准入阶段拒绝。每次调用最多 2 次尝试，报告未记录 raw prompt、raw response、Authorization header 或 API key。planner Pydantic 属性访问和报告 `DONE` 状态反例均先失败，修复后重新完成本批次。
- 组合结果：4 个 `published_with_warnings`（均 released）、4 个 `quarantined`、2 个 `rejected_admission`、0 个 clean `published`；隔离和 admission reject 均没有 released pointer 或 artifact。
- 指标：workflow success 4/10=40%，其中 spec success 100%，scene success 58.93%，quality-review success 69.23%；77 次 retry，fallback 80%（8/10），总体 p50 7,834 ms；分阶段 p95 为 spec 25,498 ms、scene 9,351 ms、quality review 11,501 ms。
- token：input 534,053、output 96,444、total 630,497；按当前 peak 价格计算总成本 0.36228940 USD，报告 `cost.complete=true`。各阶段成本为 spec 0.06660764、scene 0.24375032、quality review 0.05193144 USD。
- 质量门仍未达：publishable 4/10（目标 8）、AI full-course 0/10（目标 7）、deterministic fallback 6（上限 2）、rubric pass 0/10（目标 8），required scene recovery 未测量；因此报告和候选保持 `status=LOCAL_READY`、`quality_status=QUALITY_PARTIAL`、`quality_gate.status=not_met`，不能写 `LOCAL_QUALITY_READY` 或生产通过。

外部待验证项：GitHub Actions 尚未实际运行，目标生产环境未部署，完整发布观察周期未观察；因此外部项为 `CI_REQUIRED`、`DEPLOYMENT_REQUIRED`、`RELEASE_CYCLE_REQUIRED`，真实模型质量门还需后续在不改变 hard gate 的前提下重新评测。没有真实发布周期前，不删除 feature flag、旧 release 兼容分支或 HTTP 兼容入口。

本地工作区仍保留任务开始前已有的大量目录重构、兼容迁移和其他 Agent 修改；本轮只在课件质量、评测、Worker 证据、前端质量摘要及其必要测试/配置范围内追加修改。未提交密钥、数据库、日志、评测临时报告、截图运行目录、构建产物或真实生成资源。
