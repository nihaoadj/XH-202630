# 可视化个人学情与资源匹配报告功能更新任务书

> 任务范围：实现“生成可视化的个人学情与资源匹配度报告”，包含知识盲区定位、资源难度匹配曲线和学习路径规划图。  
> 领域边界：`reports` 负责只读聚合和展示投影；`learners/mastery`、正式 Attempt、已发布资源和持久化学习路径继续作为事实来源。  
> 文档性质：本文是后续实现任务书，不代表所列能力已经完成。仓库当前代码与测试结果才是完成状态依据。  
> 非本次范围：动态反馈决策、降阶讲解、进阶挑战生成、多 Agent 策略改造和互动课件学习结果接入。

## 1. 背景与目标

当前项目已具备学习者画像、规范掌握度、正式 Attempt、资源记录、反馈路径和 Report 3.0 基础页面，但现有可视化尚不能完整回答：

1. 学习者在哪些知识点、哪些能力维度存在经过证据验证的盲区？
2. 当前资源相对学习者能力是偏简单、适配、适度挑战还是过难？
3. 学习者当前位于哪个学习节点，受到哪些前置条件阻塞，下一步应沿主路径、补救分支还是验证节点前进？

目标链路：

```text
LearnerProfile / Mastery canonical projection
+ Formal Attempt evidence
+ Published learning resources
+ Current LearningPath / Curriculum progress
                         ↓
                    ReportService
                         ↓
Knowledge blind-spot map / Difficulty match curve / Learning path graph
                         ↓
             GET /api/report/{learner_id}
                         ↓
                   Vue + ECharts
```

报告只解释和展示现有事实，不直接更新画像、掌握度、资源、路径或生成任务。

## 2. 当前基础与真实缺口

### 2.1 可复用基础

- `MasteryService.ability_nodes()`：能力节点、掌握度、置信度、关系和薄弱优先级投影；
- `MasteryService.next_generation_options()`：强化薄弱点和学习新知识候选；
- `ReportService`：聚合画像、正式 Attempt、资源、反馈决策、路径和报告 revision；
- `ReportResponse`：已有 `difficulty_curve`、`blind_spot_heatmap`、`current_learning_path`、`ability_nodes` 等兼容字段；
- `GET /api/report/{learner_id}`：认证、ETag、条件读取和稳定报告响应；
- `GET /api/report/{learner_id}/events`：报告 revision SSE 更新；
- `ReportChart.vue`：能力雷达图和当前单线“学习节奏曲线”；
- curriculum 进度基础：区分未规划、已安排、已暴露、待验证、已完成和待强化。

### 2.2 必须补齐的缺口

1. 当前“难度匹配”图主要绘制知识点掌握分数，没有同时显示学习者准备度和资源难度。
2. 资源难度仍以初级/中级/高级标签为主，缺少标准化分数、评分来源和匹配差值。
3. 当前盲区数据主要是薄弱节点列表，缺少知识节点 × 能力维度的二维定位。
4. 未测量、证据不足、已验证薄弱和学习中需要在契约与视觉上明确区分。
5. 当前路径展示未完整投影前置、当前、补救、后继、挑战节点和阻塞原因。
6. 报告 revision 需要覆盖路径及资源匹配变化，保证 ETag/SSE 正确刷新。

以上均是待实现缺口，不得在完成测试前写成“已支持”。

## 3. 设计原则

### 3.1 单一事实来源

- 学习者身份、目标和偏好来自 `LearnerProfile`。
- 节点掌握度、状态、置信度和证据计数来自 `MasteryService` 规范投影。
- 题目表现只采信服务端正式判分 Attempt；客户端自报分数、停留和浏览行为不得成为客观掌握事实。
- 资源匹配只使用对当前学习者可见、已发布的最终资源版本。
- 路径状态来自持久化 LearningPath、知识图谱关系和 curriculum progress。
- ReportService 只生成派生展示数据，不建立与画像平行的第二套能力事实。

### 3.2 未测量不等于薄弱

| 状态 | 含义 | 可视化建议 |
|---|---|---|
| `verified_weak` | 有充分客观证据且低于掌握阈值 | 红色 |
| `learning` | 有客观证据，处于学习区间 | 黄色 |
| `mastered` | 有客观证据且达到掌握阈值 | 绿色 |
| `needs_evidence` | 存在风险信号但客观覆盖不足 | 橙色或虚线 |
| `unassessed` | 没有足够证据进行判断 | 灰色或斜纹 |

`unassessed` 和 `needs_evidence` 的 `score` 允许为 `null`，不得用 `0` 填充。

### 3.3 增量兼容

- 保留当前 HTTP 路径、认证、状态码、ETag 和 SSE 语义。
- Report 3.0 现有字段继续返回；新能力通过 additive V1 字段接入。
- 第一阶段不删除或改变旧字段结构。
- 新前端优先消费 V1 字段；字段缺失时安全回退到当前展示或空态。
- 新投影稳定排序，使相同事实产生相同 payload 和 revision。

### 3.4 前后端职责

- 后端计算状态、分数、匹配差值、路径角色、阻塞关系和 reason code。
- 前端只做格式化、颜色映射、图表布局和交互展示。
- 前端不得重新计算掌握度、改变阈值或自行推断后继节点。

## 4. 目标数据契约

新 DTO 放入 `backend/app/models/reports/contracts.py`，并从 reports 领域公开入口导出。

### 4.1 知识盲区定位 `KnowledgeBlindSpotMapV1`

```text
schema_version = "1.0"
dimensions[]
nodes[]
cells[]
summary
```

`BlindSpotNodeV1`：

```text
skill_node_id
name
stable_order
prerequisite_ids[]
```

`BlindSpotCellV1`：

```text
skill_node_id
dimension = concept | scenario | misconception | practice
score: float | null
status = verified_weak | learning | mastered | needs_evidence | unassessed
confidence
objective_evidence_count
reason_codes[]
```

`summary` 至少包含：

```text
verified_weak_count
learning_count
mastered_count
needs_evidence_count
unassessed_count
measurement_coverage: float | null
```

约束：

- 缺少维度证据时，该维度必须是 `needs_evidence` 或 `unassessed`；
- 节点总掌握度不得伪装成每个维度的独立分数；
- 没有逐维度证据时允许只输出节点级兼容视图，不得制造虚假热力格。

### 4.2 资源难度匹配 `ResourceDifficultyCurveV1`

```text
schema_version = "1.0"
strategy_version
points[]
summary
```

`ResourceDifficultyPointV1`：

```text
skill_node_id
skill_name
learner_readiness_score: float | null
resource_difficulty_score: float | null
difficulty_gap: float | null
match_status = too_easy | matched | challenging | too_hard | not_measured
confidence
difficulty_source = declared_band | deterministic_features | calibrated_history
resource_ids[]
reason_codes[]
```

第一版标准化映射：

```text
初级 / beginner      -> 0.35
中级 / intermediate -> 0.65
高级 / advanced      -> 0.85
未知                 -> null
```

第一版匹配策略：

```text
gap = resource_difficulty_score - learner_readiness_score

gap < -0.15          -> too_easy
-0.15 <= gap <= 0.10 -> matched
0.10 < gap <= 0.25   -> challenging
gap > 0.25           -> too_hard
```

约束：

- 阈值集中定义并带 `strategy_version`，不得散落在 ReportService 和前端；
- 任一输入为 `null` 时，gap 必须为 `null`，状态必须为 `not_measured`；
- 同一节点存在多份资源时，返回资源级点或按明确规则聚合，不能无说明取最后一条；
- “匹配准确率达到 85%”需要固定金标和足够样本，本地曲线可用不代表指标达标。

### 4.3 学习路径规划 `LearningPathGraphV1`

```text
schema_version = "1.0"
path_id: string | null
path_version: int | null
nodes[]
edges[]
current_node_ids[]
recommended_next_node_ids[]
summary
```

`LearningPathGraphNodeV1`：

```text
skill_node_id
name
progress_status
mastery_status
mastery_score: float | null
confidence
role = prerequisite | current | remedial | next | challenge | verification
blocked
blocked_by_node_ids[]
recommended_resource_types[]
reason_codes[]
stable_order
```

`LearningPathGraphEdgeV1`：

```text
source_skill_node_id
target_skill_node_id
relation = prerequisite | remedial | next | challenge | verification
```

投影规则：

- 已验证薄弱节点进入 `remedial` 或保持 `current`；
- 学习中节点保持 `current`，并可推荐强化练习；
- 掌握且前置满足的节点可以解锁 `next`；
- 主路径完成后才显示 `challenge`；
- 证据不足时显示 `verification`，不得直接标记进阶；
- 缺失前置、自环、环路、重复节点和未知节点必须由后端拒绝或以安全 warning 隔离。

## 5. 后端实施任务

### 5.1 报告契约

在 `ReportResponse` 中 additive 增加：

```text
knowledge_blind_spot_map: KnowledgeBlindSpotMapV1 | null
resource_difficulty_curve: ResourceDifficultyCurveV1 | null
learning_path_graph: LearningPathGraphV1 | null
```

必要时将 `report_schema_version` 增加为 `3.1`，但必须保留 3.0 全部字段和语义。

### 5.2 确定性投影

在 `ReportService` 中增加：

```text
_build_blind_spot_map(...)
_build_resource_difficulty_curve(...)
_build_learning_path_graph(...)
```

要求：

- 输入来自本次报告读取到的同一事实窗口；
- 不调用 LLM、不写数据库、不修改画像或路径；
- 输出稳定排序且可序列化；
- 缺失数据返回显式空态和 warning，不产生无意义 500。

### 5.3 难度策略

将难度标准化和 gap 分类放入 reports 领域的确定性策略模块，例如：

```text
backend/app/services/reports/difficulty_matching.py
```

该模块只接受规范输入并返回匹配结果，便于单元测试和以后版本化校准。

### 5.4 Revision 与 SSE

扩展报告 revision，使以下事实变化能够生成新 revision：

- mastery/ability evidence；
- 正式 Attempt；
- 可见最终资源及其难度；
- current learning path；
- curriculum progress。

SSE 的 `changed_domains` 可 additive 增加 `resource_match` 和 `path`。不得在 SSE 中发送完整画像、题目答案、Prompt、自由文本或完整报告正文。

### 5.5 文档同步

同步 `docs/api.md`：三个新增字段及空态、`null` 与 `0` 的差异、difficulty strategy version、ETag/SSE 更新域和兼容说明。

## 6. 前端实施任务

### 6.1 组件拆分

在 `frontend/src/features/reports/` 新增：

```text
KnowledgeBlindSpotHeatmap.vue
ResourceDifficultyCurve.vue
LearningPathGraph.vue
```

`ReportView.vue` 负责布局和空态编排；图表组件只消费后端 V1 投影。

### 6.2 知识盲区热力图

- 使用 ECharts Heatmap；
- 横轴为知识节点，纵轴为 concept、scenario、misconception、practice；
- Tooltip 展示节点、维度、分数、状态、置信度、证据数和原因；
- 未测量使用灰色/斜纹或独立图例，不纳入红色弱项；
- 节点较多时提供 dataZoom；
- 提供可访问的文本摘要。

### 6.3 资源难度匹配曲线

- 使用双折线：蓝线为 learner readiness，橙线为 resource difficulty；
- 使用背景或 markArea 表达合理挑战区间；
- 点位区分 too easy、matched、challenging、too hard；
- `not_measured` 不连接成 0 分折线；
- Tooltip 展示 gap、状态、置信度、资源数量和评分来源。

当前 `ReportChart.vue` 的单线掌握度曲线应保留兼容或逐步迁移，不能继续将其描述为完整难度匹配。

### 6.4 学习路径规划图

- 使用 ECharts Graph 或小规模稳定 DAG；
- 主路径实线、补救分支橙色、验证节点紫色/虚线、挑战蓝色、完成绿色、阻塞灰色；
- 当前节点高亮；
- 点击节点展示掌握度、置信度、角色、前置、阻塞原因和推荐资源。

### 6.5 响应式与降级

- 窄屏转换为纵向卡片；
- Canvas 图表之外提供文本摘要；
- V1 字段缺失时显示兼容视图或明确空态，不产生运行时异常。

## 7. 固定实施顺序

### M0：冻结反例与契约

先增加失败反例：

- 未测量节点被显示为 0 分薄弱；
- 只有掌握线却标记为资源难度匹配；
- 未知难度被强行映射成初级；
- 路径包含未知节点、自环或缺失前置；
- 相同事实因无稳定排序产生不同 revision；
- 路径或资源变化后 SSE 不刷新；
- V1 字段缺失导致旧页面崩溃。

完成门：契约测试和反例稳定描述旧实现缺口，现有 Report 3.0 测试继续通过。

### M1：知识盲区定位

1. 新增 blind-spot DTO；
2. 实现节点和维度证据投影；
3. 增加 summary 与 warning；
4. 实现热力图和文本摘要；
5. 运行后端报告专项、前端专项和 build。

完成门：verified weak、needs evidence 与 unassessed 在 API 和页面中完全可区分。

### M2：资源难度匹配

1. 新增难度标准化策略及版本；
2. 实现资源到知识节点的稳定关联；
3. 计算 readiness、difficulty、gap 和 match status；
4. 实现双曲线和合理挑战区间；
5. 增加边界值、未知难度和多资源测试。

完成门：图表包含两条有真实数据来源的曲线，缺失输入不伪造分数。

### M3：学习路径规划图

1. 新增路径图 DTO；
2. 聚合知识图谱、持久化路径、Mastery 和 curriculum；
3. 实现节点角色、阻塞关系和稳定边；
4. 实现路径图、Tooltip 和文本摘要；
5. 增加环路、未知节点、补救、验证、进阶和挑战测试。

完成门：报告能够明确展示“当前在哪里、为什么被阻塞、下一步去哪”。

### M4：Revision、SSE 与集成验收

1. 扩展 revision 变化域；
2. 验证 ETag/304；
3. 验证 SSE snapshot、changed domains、重连和轮询降级；
4. 完成浏览器响应式和交互检查；
5. 更新 API、架构和功能文档。

## 8. 测试要求

### 8.1 后端单元测试

- 难度中英文别名标准化；
- gap 在 `-0.15`、`0.10`、`0.25` 边界的分类；
- 任一输入为 null 时返回 not measured；
- 盲区五种状态及 measurement coverage；
- 维度证据不足时不复制节点总分；
- 路径稳定排序、自环、环路、未知节点和缺失前置；
- 相同输入产生相同序列化结果与 revision。

### 8.2 后端集成/API 测试

- ReportResponse additive 兼容；
- 三个 V1 字段的完整、部分和空数据响应；
- learner 鉴权与不存在 learner 的 404；
- ETag、If-None-Match 和 304；
- mastery、资源、路径变化触发正确 revision；
- SSE 不泄露敏感信息；
- SQLite 重启后路径节点、匹配状态和稳定排序不变化。

### 8.3 前端测试

- 三类图表 option 对完整、部分和空数据均可构建；
- null 分数不被转换为 0；
- V1 字段缺失时兼容回退；
- 图例、Tooltip、reason code 文案和文本摘要；
- SSE 更新后只重新获取当前 learner、当前 window 的报告；
- 组件销毁后关闭 stream；
- 360px、768px、1440px 关键宽度布局；
- 前端 build。

### 8.4 建议验证命令

```powershell
python -m pytest backend/tests/unit/reports -q
python -m pytest backend/tests/integration/services/test_feedback_report.py -q
python -m pytest backend/tests/integration/api/test_report_api.py -q
npm --prefix frontend run test:learning-report
npm --prefix frontend run test:learning-report-browser
npm --prefix frontend run build
```

若实际 `package.json` 中脚本名不同，以当前脚本为准并在执行记录中写明。浏览器验证与本地单元测试必须分开报告。

## 9. 固定验收场景

1. 新学习者：全部节点未测量，正常显示灰色空态，不出现“0 分薄弱”。
2. 局部证据：一个节点已验证薄弱、一个学习中、一个已掌握、一个待补证据。
3. 适配资源：准备度与中级资源接近，显示 matched。
4. 过难资源：资源难度明显高于准备度，显示 too hard 和稳定原因码。
5. 多资源：同一节点存在不同难度资源，不无说明覆盖其中一条。
6. 补救路径：当前节点低于阈值，显示补救分支且后继仍阻塞。
7. 验证路径：节点已学习但无正式证据，显示 verification 而非 weak。
8. 进阶路径：当前节点已掌握且前置满足，后继节点解锁。
9. 报告刷新：新增 Attempt、发布资源或路径 mutation 后 revision 改变，页面自动更新。
10. 重启一致性：SQLite 重启后相同事实产生相同节点、边、状态和排序。

## 10. 完成定义

- API 返回知识盲区、资源难度匹配和学习路径三个版本化投影；
- 三个投影均来源于现有规范事实，不建立第二套画像或掌握事实；
- 未测量、待补证据、已验证薄弱、学习中和已掌握可明确区分；
- 难度匹配图真实包含学习者准备度和资源难度两条序列；
- 路径图展示前置、当前、补救、验证、后继、挑战和阻塞关系；
- 旧 Report 3.0 消费者不因新增字段失效；
- ETag、SSE、鉴权、空态和重启稳定性测试通过；
- 相关前端专项测试和 build 通过；
- `docs/api.md`、`docs/architecture.md` 和 `docs/features.md` 与真实实现同步；
- 未运行的浏览器、真实数据校准或部署验证准确列为未验证。

## 11. 文件边界建议

预计涉及：

```text
backend/app/models/reports/contracts.py
backend/app/services/reports/reports.py
backend/app/services/reports/difficulty_matching.py
backend/app/api/reports/report.py
backend/tests/unit/reports/
backend/tests/integration/services/test_feedback_report.py
backend/tests/integration/api/test_report_api.py
frontend/src/features/reports/ReportView.vue
frontend/src/features/reports/ReportChart.vue
frontend/src/features/reports/KnowledgeBlindSpotHeatmap.vue
frontend/src/features/reports/ResourceDifficultyCurve.vue
frontend/src/features/reports/LearningPathGraph.vue
frontend/tests/learningReport.test.mjs
frontend/tests/learningReportBrowser.test.mjs
docs/api.md
docs/architecture.md
docs/features.md
```

默认不涉及：

```text
backend/app/agents/resource_workflows/interactive_courseware/
backend/app/core/courseware/
backend/app/services/courseware/
backend/app/agents/learning_agents/feedback_policy_agent.py
backend/app/services/feedback/
```

如果实现过程中发现必须改变掌握度、反馈策略、生成流程或数据库事实模型，应停止扩大范围，先单独评审契约与迁移影响。

## 12. 交付记录模板

每个里程碑完成后在本文末尾追加：

```text
### YYYY-MM-DD / Mx

- 实现文件：
- 契约变化：
- 执行命令：
- 实际结果：
- 未运行项及原因：
- 剩余缺口：
- 是否影响其他领域：
```

交付前必须检查 `git diff` 和 `git status`，不得覆盖工作区已有修改，不提交数据库、日志、截图、构建产物、临时报告或凭据。

## 执行记录

### 2026-08-24 / M0-M4

- 实现文件：`backend/app/models/reports/contracts.py`、`backend/app/services/reports/reports.py`、`backend/app/services/reports/difficulty_matching.py`、三个 reports 前端图表组件及相关测试。
- 契约变化：在保持顶层 `report_schema_version="3.0"` 的前提下，additive 增加 `knowledge_blind_spot_map`、`resource_difficulty_curve`、`learning_path_graph`；三个嵌套投影各自使用 `schema_version="1.0"`。
- 执行命令：`python -m pytest backend/tests/unit/reports backend/tests/integration/services/test_feedback_report.py backend/tests/integration/api/test_report_api.py backend/tests/integration/services/test_report_stream.py -q`、`npm --prefix frontend run build`、`npm --prefix frontend run test:learning-report`、`npm --prefix frontend run test:learning-report-browser`。
- 实际结果：后端 22 passed；前端构建、报告流测试和浏览器专项通过。`git diff --check` 通过。
- 未运行项及原因：未运行后端全量、真实模型、真实学习者数据校准或部署验证；本任务仅修改报告领域并采用专项回归。难度策略首版仅使用声明难度带，尚无金标样本，因此不报告“匹配准确率”。
- 剩余缺口：多资源的难度曲线按资源级点位呈现；后续如需节点级聚合或历史校准，应另行版本化 `difficulty_matching` 策略。
- 是否影响其他领域：仅消费 mastery、资源、路径和 Attempt 的既有只读事实；未改变反馈、生成、课件或数据库写入语义。
