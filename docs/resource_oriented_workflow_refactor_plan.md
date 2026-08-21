# 资源级 Agent 工作流改造方案

> 当前已实施方案采用“专用 Agent + 节点级统一汇总”。如需升级为每个资源即时持久化、即时 SSE 推送的 Worker 流水线，请评审 [资源级 Worker 与即时持久化升级方案](resource_worker_realtime_persistence_upgrade_plan.md)。

## 1. 目标与边界

将当前“一个 Run 内一次生成全部资源、整体审核”的工作流，改为“共享决策上下文、按资源类型调用专用 Agent、按节点统一汇总”的工作流。当前阶段不引入 LangGraph 的资源级 Worker 流水线；资源生成、审核与 Claim 仍分别在统一节点内汇总返回。改造后，用户仍看到易理解的高层 Agent 流程；在“生成资源”和“审核资源”阶段可展开查看每份资源的持久化状态和返工结果。

本次改造的目标：

- 降低单次大模型输出过长、结构化 JSON 截断和单项失败拖累整批的风险。
- 为每份资源分配明确的学习目标、知识点、证据范围和输出预算。
- 支持资源级生成、审核、Claim 审核、重试与持久化，并只返工失败资源。
- 前端在任务运行中展示资源级进度；仅已批准且发布的资源可提前阅读。
- 保留 `run_id`、`batch_id`、证据快照、版本谱系、SSE 回放与现有历史资源查询能力。

不在本次范围内：改变学习者画像、知识库入库/检索算法、引入新的消息队列基础设施、改变正式发布的证据门禁原则。

## 2. 当前基线

当前 LangGraph 拓扑为：

```text
诊断 → 检索 → 证据门禁 → 规划 → 批量生成 → 整体审核
                                           │
                                  （可选）Claim 抽取/判定
                                           │
                                     定向返工后回到生成
                                           │
                                        汇总终结
```

`Generator` 在一条 Prompt 中要求模型一次返回所有 `resource_types`，并要求返回集合与请求集合完全一致。`Reviewer` 与 Claim Extractor 再把该集合的全部正文输入模型。默认三类短资源可运行，但资源数、单篇长度和 Claim 数增加时，输入、输出、审核与失败恢复会被同一批次放大。

## 3. 目标架构

### 3.1 总体流程

```text
Run 创建
  → Diagnosis / Retrieval / Evidence Gate / Planner       （共享阶段，只执行一次）
  → ResourceSpec Builder                                  （确定性拆解）
  → Generator Node：按 resource_type 调用 Specialized Agent × N（节点内受控并发、统一返回）
  → Reviewer Node：逐资源审核并确定性汇总
  → [Claim Nodes：逐资源处理并统一汇总]
  → Batch Supervisor                                      （聚合状态、指标、发布结论）
       → 必要时仅重新调用目标 resource 的专用 Agent
  → Run 终结
```

其中 `ResourceSpec` 是语义资源工作单元，而不是仅有名称的 `resource_type`。一个 Spec 可以拥有一个或多个受控表示执行单元（`ResourceRepresentationSpec`）：讲义和测试题各有一个表示；实操指南有 `text` 与 `html` 两个表示。每一个工作单元至少包含：

```json
{
  "resource_spec_id": "stable UUID within run",
  "resource_type": "讲义",
  "learning_objective": "完成后能够……",
  "knowledge_points": ["…"],
  "evidence_ids": ["…"],
  "difficulty": "中级",
  "representations": [
    {"representation": "text", "max_output_tokens": 8192}
  ],
  "dependencies": [],
  "display_order": 1
}
```

`Planner` 负责给出学习路径与资源需求；新增的确定性 `ResourceSpec Builder` 根据请求资源类型、路径、规划要求、证据和系统预算生成可校验的 Specs。`resource_spec_id` 是一个 Run 内工作单元的稳定 UUID；它不同于资源产物落库后生成的 `resource_id`，也不同于可跨 Run 关联的 `batch_id`。资源类型仍须去重，避免同一 Run 产生歧义版本。

表示执行单元的唯一性与数量规则：

```text
讲义 Spec       → ResourceRepresentationSpec(text)
分阶测试题 Spec  → ResourceRepresentationSpec(text)
实操指南 Spec   → ResourceRepresentationSpec(text)
               → ResourceRepresentationSpec(html, derives_from_representation=text)
```

因此，“默认三种资源类型”仍是三个 Spec、三个学习语义资源；在实操指南审核通过后会物化为四份资源产物（讲义文本、实操指南文本、实操指南 HTML、测试题）。`ResourceExecution` 与数据库唯一约束的粒度必须是 `(run_id, resource_spec_id, representation)`，而非仅 `(run_id, resource_spec_id)`。

### 3.2 资源类型专用 Agent 与确定性路由

第一期只支持以下三种已注册资源类型；它们均由独立的生成 Agent、提示词和输出契约处理。HTML 实操指南第一期采用提示词约束为主、最小技术准入为辅的策略，避免严格校验导致反复生成失败。

| `resource_type` | 专用 Agent | 产物 | 输出契约 |
| --- | --- | --- | --- |
| `讲义` | `TextResourceAgent()` | Markdown/纯文本 | 标题层级、概念解释、示例、知识点和练习建议 |
| `实操指南` | `HtmlPracticeGuideAgent()` | 一份经审核的文本指南 + 一份互动 HTML 派生指南 | 学习目标、步骤、代码块、检查清单、常见错误和验收标准 |
| `分阶测试题` | `AssessmentAgent()` | 结构化题目数据 | 题目、选项、答案、解析、难度和能力节点 |

路由不是由模型决定，而是由服务端的受控注册表完成：

```python
RESOURCE_AGENT_REGISTRY = {
    "讲义": TextResourceAgent(),
    "实操指南": HtmlPracticeGuideAgent(),
    "分阶测试题": AssessmentAgent(),
}
```

`ResourceSpec Builder` 只能为注册表中的类型创建 Spec；`Resource Router` 以 `ResourceSpec.resource_type` 精确查表并调用对应 Agent。输入先经过唯一受控别名表规范化：第一期至少支持 `定制讲义 → 讲义`，其余映射必须显式登记、审计并有测试覆盖。规范化后未知、空白或未注册的类型必须在模型调用前以 `WORKFLOW_CONTRACT_INVALID` 拒绝，**不得**静默回退到通用 Agent，也不得依据模型返回的 `resource_type` 改变路由。

为控制改造范围和保留现有 LangGraph 节点名、审计事件及测试引用，`backend/app/agents/generator.py` **暂不改名或删除**。它改造后的唯一职责是资源级生成编排：读取冻结 Spec、调用注册表、统一处理预算/超时/降级、物化资源并记录 trace。它不再保存通用生成 Prompt，也不直接生成任何一种资源正文。

所有生成正文的专用 Agent 统一放在 `backend/app/agents/resource_agents/`，禁止再次散落在 `agents/` 根目录。推荐目录结构：

```text
backend/app/agents/
├── generator.py                    # 保留文件名：资源级路由与编排入口
└── resource_agents/
    ├── __init__.py                 # 仅导出公共类型和受控 Agent
    ├── base.py                     # ResourceGenerationAgent 共同协议/DTO
    ├── registry.py                 # 唯一类型→Agent 注册表与校验
    ├── text.py                     # TextResourceAgent
    ├── html_practice.py            # HtmlPracticeGuideAgent
    └── assessment.py               # AssessmentAgent
```

该目录只承载“按类型生成内容”的实现；共享的证据检索、工作流路由、审核、Claim 判定、文件存储与权限控制继续留在各自现有模块，避免专用 Agent 形成新的跨层依赖。

每一个专用 Agent 实现同一服务端协议：

```python
class ResourceGenerationAgent(Protocol):
    resource_type: str
    prompt_version: str

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact: ...
    def validate(self, artifact: GeneratedArtifact) -> ValidatedArtifact: ...
```

其中 `context` 只包含该 Spec 被允许使用的证据、画像摘要、学习路径片段和有界批次摘要。`GeneratedArtifact` 的实际 Schema 由专用 Agent 决定；共同字段（`resource_spec_id`、证据 ID、版本、类型）由服务端补齐与校验，不信任模型自行声明的身份字段。

HTML Agent 是一个复合 Agent。它不再直接把未经审核的学习内容写入 HTML，而是分两次调用模型，生成同一实操指南的两种表示：

```text
第 1 次模型调用：生成 canonical_text（标准文本实操指南）
  → 保存为 representation=text 的资源
  → 当前通用 Reviewer + Claim 审核只审核该文本资源
  → 文本审核通过并发布后，才允许继续

第 2 次模型调用：以已批准的 canonical_text 为唯一内容依据生成 interactive_html
  → 保存为 representation=html 的派生资源
  → 不重复调用通用 Reviewer/Claim 审核
  → 执行最小技术准入与隔离预览准备，不执行阻断式内容/互动/一致性复核
  → 发布为同一实操指南的 HTML 表示
```

两个资源的 `resource_type` 均为 `实操指南`，但必须拥有相同的 `resource_family_id`，并通过 `representation=text|html` 区分；HTML 资源额外记录 `derived_from_resource_id` 指向其已批准的文本资源。不得把这条派生关系塞入既有 `parent_resource_id`，后者仍只表示同一表示的版本谱系。

#### 文本指南作为 HTML 的规范源文件

`canonical_text` 不是任意 Markdown，而是 HTML 转换的唯一规范源文件（canonical source）。第 1 次模型调用必须同时输出：

- `markdown_content`：可直接给学习者阅读的标准实操指南；
- `guide_manifest`：结构化目录，含 `guide_version`、`section_id`、`step_id`、步骤顺序、代码块 ID、检查项 ID、题目 ID 与对应知识点；
- `source_evidence_ids`：文本中事实性单元允许使用的冻结 Evidence ID。

服务端基于规范化后的 `markdown_content + guide_manifest` 计算不可变 `canonical_text_hash`。审核、Claim 审核、HTML 转换、HTML 发布和前端文本/HTML切换均以该 hash 和文本资源版本为依据，而不以模型自行声称的版本为依据。

规范 Markdown 的固定结构如下；所有章节、步骤和互动源单元都必须具备稳定 ID，禁止仅以自然语言标题猜测关联：

````markdown
# 实操指南标题

<!-- section:overview -->
## 1. 学习目标与完成标准

<!-- section:prerequisites -->
## 2. 前置条件与环境准备

<!-- section:practice -->
## 3. 分步实践

<!-- step:step-01 -->
### 步骤 1：……
- 操作：……
- 预期结果：……
- 验证方法：……
- 失败排查：……

<!-- code:step-01-main -->
```language
...
```

<!-- checklist:setup -->
## 4. 完成检查清单

<!-- quiz:review-01 -->
## 5. 自测与复盘
````

文本 Prompt 必须要求每一个步骤完整输出“操作、预期结果、验证方法、失败排查”，并要求命令、代码、参数、预期输出、题目答案仅出现一次且归属明确。文本资源不得直接夹带 HTML、JavaScript、未声明互动组件、无 ID 的关键代码块或无来源的技术补充。这样第二次调用不需要猜测结构，也不需要重新创造教学内容。

文本版本与 HTML 派生版本的联动规则：

```text
文本 v1（approved, canonical_text_hash=A）
  → HTML v1（published, derived_from=text v1, canonical_text_hash=A）

文本 v2 生成或进入返工
  → 与文本 v1 关联的 HTML v1 标记为 superseded / 不可切换
  → 文本 v2 审核通过后，才可生成 HTML v2（canonical_text_hash=B）
```

前端只有在文本与 HTML 的 `resource_family_id` 相同、`derived_from_resource_id` 指向当前已发布文本、`source_resource_version` 相等、`canonical_text_hash` 相等时，才显示“互动实践”切换按钮。任一条件不成立时，只显示当前文本指南和“互动版本正在更新”的状态；不得让学习者看到内容已过期的 HTML。

第一期 HTML 只执行最小技术准入：非空输出、可解析为 HTML fragment、未超过文件大小上限、可写入受控目录。清洗器以**修复优先**方式移除明显不允许的 `script`、事件属性、`iframe` 和危险 URL，并记录脱敏告警；除空内容、不可解析或无法安全存储外，不因结构细节、互动组件完整性或文本差异阻断发布或自动重试。产物保存为受控目录的 `.html` 文件，`storage_type=file`、`mime_type=text/html`。只有文本源资源已批准且 HTML 通过最小准入时，才可在前端沙箱化预览或下载。

#### `HtmlPracticeGuideAgent()` 的互动与提示词设计

HTML 实操指南不能只是把 Markdown 包进 HTML 标签，而应形成可操作的“目标 → 环境准备 → 分步实践 → 每步验证 → 故障排查 → 小测/复盘”体验。第 1 次调用输出标准文本指南及稳定的章节/步骤 ID；第 2 次调用只将这些已批准章节转换成**语义化 HTML 片段和声明式互动标记**，不得新增、删除或改变事实性学习内容。模型不允许生成 JavaScript；平台在清洗后注入固定、版本化的互动运行时，以实现已允许的交互组件。

第一期允许的互动组件与约束：

| 组件 | 模型生成形式 | 平台的固定行为 |
| --- | --- | --- |
| 分步实践 | `data-practice-step`、步骤编号与验收条件 | 上一步完成后解锁下一步，显示完成进度 |
| 检查清单 | `data-practice-checklist`、受控 checkbox 项 | 本地标记完成状态，不写入服务端学习记录 |
| 知识自测 | `data-practice-quiz`、选项与正确答案标记 | 即时判定、显示解析、允许重新作答 |
| 代码示例 | `pre > code`，标注语言 | 一键复制、折叠/展开，不执行代码 |
| 常见错误 | `details` 与错误/原因/修复建议 | 折叠显示，不执行外链或命令 |

第 1 次调用（文本指南）的系统提示词采用“规范 Markdown 实操指南 Prompt”，输出可供当前通用 Reviewer 和 Claim 审核的 Markdown/文本资源及 `guide_manifest`。它必须严格遵循上一节的固定结构，明确产出稳定 `section_id`、`step_id`、代码/清单/题目 ID 与每一步的操作、预期结果、验证方法、失败排查；所有事实性技术结论、命令、参数、版本要求、预期输出和题目答案必须可由冻结 Evidence 支持。它必须知道：该文本将作为后续 HTML 的唯一源文件，因此不得省略结构、合并步骤、使用含混引用或把关键内容只写在段落中。

第 2 次调用（HTML 转换）的系统提示词必须包含以下不可省略的约束：

```text
角色：将一份已审核、已批准的规范 Markdown 实操指南及其 guide_manifest 转换为互动式 HTML 表示。
目标：逐项消费 manifest 中的 section_id、step_id、代码、检查项和题目，忠实保留源指南的学习内容与顺序；不得自行归纳、补充或省略。

输出：仅输出符合 HtmlPracticeGuideArtifact Schema 的 HTML fragment 和结构化元数据；
不要输出 Markdown 围栏、解释文本、JavaScript、script/style/link/iframe 标签、事件属性或外部 URL。

内容映射：必须为 guide_manifest 中的每个 section_id/step_id 输出对应 data-source-section-id/data-source-step-id，并保留代码/清单/题目 ID；
不得新增、删除、改写或重排任何事实性结论、命令、参数、预期结果、故障原因、题目答案和解析。
可新增的仅限平台允许的呈现包装和互动标记，例如步骤进度、检查清单、折叠区和对已审核自测题的交互展示。

输入边界：唯一的内容来源是已批准 canonical_text、guide_manifest 和服务端提供的 canonical_text_hash；不得利用记忆、外部知识或提示中的其他信息补充内容。
交互：只使用平台规定的 data-practice-* 标记；不要创造新组件、脚本或网络请求。
```

第 2 次调用的专用输出 Schema 至少包括 `html_fragment`、`source_section_ids`、`source_step_ids`、`source_code_ids`、`source_checklist_ids`、`source_quiz_ids`、`interactive_component_counts` 和 `canonical_text_hash`；它不接收也不输出新的 `knowledge_points`、命令、答案或 Evidence。第一期只校验必要字段存在、`html_fragment` 可解析、源文本哈希存在和文件大小；章节覆盖、步骤顺序、互动组件完整性以及文本/HTML逐句一致性主要由转换 Prompt 强制约束并记录为后续增强项。HTML 最小准入失败时仅自动重试 HTML 派生资源一次，不影响已发布文本指南；其余质量问题不触发自动重试。

固定互动运行时 `html_practice_runtime.js` 只能由前端或后端随应用发布并版本化；它不得访问网络、Cookie、父窗口 DOM、LocalStorage 或学习者隐私数据。预览使用 `iframe sandbox="allow-scripts"`，不得添加 `allow-same-origin`、`allow-forms`、`allow-popups` 或 `allow-top-navigation`。父页面与 iframe 若需通信，只允许版本化、白名单化的 `postMessage` 事件（例如完成进度），并校验来源和 payload。

### 3.3 证据和上下文规则

- 证据门禁仍在所有事实型生成之前执行，且仍失败关闭。
- 每个 Spec 持有允许使用的 `evidence_ids`；Generator 只接收该 Spec 的最小相关证据集，而不是默认的前五条证据。
- 批次关联上下文只传递摘要：已完成资源的类型、知识点、目标、摘要和版本，不传递全量历史正文。
- 对 Prompt 和结构化输出同时实施预算校验。按预估输入 token、预估输出 token、资源类型与模型上下文窗口做分派，不以“资源数量”作为唯一阈值。

### 3.4 统一汇总、并发和一致性规则

- 共享阶段串行执行一次。当前使用一个 Generator 节点在其内部按 Spec 调用专用 Agent；初始并发上限配置为 2，允许在压测后提高到 4。该并发只是节点内部的模型调用并发，不是独立的 LangGraph Worker 流水线。
- 节点内部的调用不得修改共享 workflow state。Generator、Reviewer 与 Claim 节点在全部目标资源处理完成后一次性返回 state，由既有 durable checkpoint 边界统一持久化。
- 每个 Spec 从已冻结的 `resource_type` 完成一次路由；返工使用原 Spec 的 `resource_type` 与 `agent_name`，禁止在资源版本之间换 Agent。
- 每份资源的 Spec、`agent_name`、`prompt_version`、输出格式、校验结论和渲染器版本必须写入审计投影，以便回放时确认实际路由。
- 持久化采用“资源产物先落库、再接受检查点”的现有原则。资源执行记录以 `(run_id, resource_spec_id, representation)` 幂等更新；`worker_step_id` 仅作为一次资源调用的可追踪内部标识，不形成独立工作流步骤或独立 SSE 序列。
- 一个资源失败不会回滚已成功资源。批次状态由成功、审核中、待人工、失败、未开始的资源状态确定。
- 同一 Spec 的自动返工次数受现有 `max_iterations` 约束；不得因某一资源返工而重新生成已通过资源。

### 3.5 进度推送边界（当前阶段）

- SSE 的游标、重放、断线续传和去重以持久化 `WorkflowEvent.event_sequence` 为准。
- 当前资源状态会在 Generator、Reviewer、Claim 或 HTML 派生节点完成并持久化后推送；不承诺“某一次模型调用刚结束”即出现单资源事件。
- 前端显示为“节点级同步”，而不是逐 token 或逐模型调用的实时进度。收到 `resource_published` 后必须刷新该 Run 的 Job 摘要和资源列表，使已批准且已发布的资源在整批完成前即可阅读。
- 将来如确有“单资源完成即落库/即推送”的产品要求，再引入 Resource Worker fan-out/fan-in 或等价的资源级持久化回调；这属于后续演进，不是本期前置条件。

## 4. 功能变化

| 能力 | 当前行为 | 改造后行为 |
| --- | --- | --- |
| 生成 | 一个模型响应产出全部资源 | 一个 Generator 节点按 Spec 调用专用 Agent；节点内可受控并发、节点末统一汇总 |
| 生成策略 | 所有类型共用一个 Prompt 和 Schema | 每个 `resource_type` 使用已注册专用 Agent、提示词、Schema 与校验器 |
| HTML 实操 | 当前前端仅按文本资源展示 | 已发布 HTML 在沙箱预览器中以统一视觉规范展示，并提供受控步骤、清单、自测和代码复制互动 |
| 审核 | 一个审核结论覆盖整批资源 | 资源级审核结论、问题与返工指令；实操指南只审核其 canonical text，HTML 仅做最小技术准入 |
| Claim | 一次抽取全部资源 Claim | 按资源生成 Claim/判定结果，再在 Claim 节点统一汇总；单资源失败不污染其余指标 |
| 返工 | 按类型返工，但再次以批量输入审核 | 当前每类型唯一 Spec 时按 `resource_type` 定位即等价于资源级返工；后续允许同类型多 Spec 时必须升级为精确按 `resource_spec_id` / 资源版本返工 |
| 批次结果 | `completed` 或 `failed` 为主 | 保留任务生命周期，增加资源聚合摘要和部分完成语义 |
| 前端流程 | 线性节点 + 完成后一次性展示资源 | 高层节点不变，生成/审核节点可展开为资源卡片 |
| 资源读取 | 按 Run 获取全量正文 | 支持分页列表/摘要；正文按资源详情读取 |

## 5. 对外契约设计

### 5.1 保持兼容

- `POST /api/generate/jobs` 的必填字段保持不变；默认三种资源仍会产生一份讲义、一份实操指南和一份分阶测试题。
- `run_id`、`batch_id`、资源版本、来源证据、审核 API、历史 Run 查询继续有效。
- 现有 SSE 事件不删除字段；新增字段为可选字段，旧前端可忽略。

### 5.2 新增或扩展的数据模型

新增资源工作单元模型：

- `ResourceSpec`：资源任务规格与稳定 `resource_spec_id`。
- `ResourceRepresentationSpec`：一个 Spec 下的表示执行定义，包含 `representation`、`max_output_tokens`、`derives_from_representation` 和显示顺序。
- `ResourceAgentDefinition`：受控注册表项，包含 `resource_type`、`agent_name`、`prompt_version`、输出格式、预算和渲染/校验器版本。
- `ResourceRepresentation`：`text` 或 `html`；用于同一 `resource_family_id` 下的多表示资源。
- `ResourceExecutionState`：资源表示执行的当前状态枚举：`queued`、`generating`、`generated`、`reviewing`、`revision_requested`、`claim_checking`、`approved`、`human_review`、`failed`。该名称刻意区别于既有的资源发布/审核状态；它不是独立 LangGraph Worker 的生命周期。
- `ResourceExecutionProgress`：资源表示执行单元的当前状态、尝试次数、更新时间、错误码（脱敏）、对应 `resource_spec_id`、`representation`、`resource_id` 与 `review_id`。
- `RunResourceProgressSummary`：当前 `run_id` 下的资源总数及上述状态的计数；通过/待人工/失败数量；是否可终结。不得命名为 Batch Summary，以免和可包含多个 Run 的既有 `batch_id` 混淆。

扩展接口：

1. `GET /api/generate/jobs/{run_id}`：在保持现有字段基础上，增加 `resource_progress_summary`（类型为 `RunResourceProgressSummary`）。
2. `GET /api/runs/{run_id}/timeline` 与 SSE：新增 `resource_spec_id`、`resource_id`、`resource_type`、`resource_execution_state`、`attempt`。当前这些事件在节点持久化边界产生；事件仍不得包含 Prompt、资源全文、原始模型响应或敏感信息。
3. `GET /api/resources/{learner_id}`：新增 `page`、`page_size`、`summary_only`；默认保持旧行为以兼容现有调用，前端切换为显式分页和摘要请求。
4. 新增 `GET /api/resources/items/{resource_id}`：返回经授权的单份资源详情及其审核摘要。使用固定 `items` 路径段，避免与现有 `GET /api/resources/{learner_id}` 动态路由冲突。大正文仅由该接口获取。
5. 新增 `GET /api/resources/items/{resource_id}/preview`：仅允许已发布、`representation=html` 的资源调用，返回已清洗 HTML fragment 与受控预览元数据；不得返回原始模型输出、运行时源码或草稿 HTML。`HtmlPracticeGuideViewer` 将 fragment 放入 `srcdoc`，注入前端固定运行时并设置 CSP meta 与 iframe sandbox。
6. 可选新增 `POST /api/generate/jobs/{run_id}/resource-specs/{resource_spec_id}/representations/{representation}/retry`：仅重试用户有权限查看且处于 `failed` 或 `human_review` 的指定表示。若第一期仅支持自动返工，可延后实现此接口。

所有新增响应模型必须 Pydantic 化、明确 schema version/默认值，并在 `docs/api.md` 记录兼容与弃用策略。

路由可观测性要求：资源级 timeline 事件和资源详情摘要额外返回 `agent_name`、`prompt_version`、`artifact_format` 与 `validation_status`，但不返回完整 Prompt。这样前端、测试和审计记录都能验证“讲义确实走了 TextResourceAgent，HTML 实操指南确实走了 HtmlPracticeGuideAgent”。

## 6. 后端改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/app/models/agent_contracts.py` | 新增 `ResourceSpec`、专用 Agent 输入/输出、资源级审核/Claim 契约、`PracticeGuideManifest`、文本/HTML派生契约和预算校验；移除“批次输出必须完全覆盖所有资源类型”的旧约束。 |
| `backend/app/agents/resource_agents/base.py`（新增） | 定义 `ResourceGenerationAgent`、`ResourceGenerationContext`、`GeneratedArtifact` 和专用 Agent 的共同协议。 |
| `backend/app/agents/resource_agents/text.py`（新增） | 实现 `TextResourceAgent()`：独立讲义 Prompt、文本 Schema 与 Markdown/纯文本校验。 |
| `backend/app/agents/resource_agents/html_practice.py`（新增） | 实现 `HtmlPracticeGuideAgent()` 的两阶段链路：生成 canonical text、在文本审核通过后生成 HTML 派生物；包含两套 Prompt、HTML Artifact Schema、源 ID 映射、清洗、文件写入和受控预览元数据。 |
| `backend/app/agents/resource_agents/assessment.py`（新增） | 实现 `AssessmentAgent()`：独立题目 Prompt、题目 Schema、答案/选项/能力节点校验。 |
| `backend/app/agents/resource_agents/registry.py`（新增） | 定义唯一的 `RESOURCE_AGENT_REGISTRY`、受控别名表（至少 `定制讲义 → 讲义`）、类型规范化、精确查找和启动时注册完整性校验；禁止业务代码散落 `if/else` 路由。 |
| `backend/app/models/schemas.py` | 新增资源进度、分页、详情和 Job 聚合摘要模型；扩展 Job 状态响应。 |
| `backend/app/models/workflow.py` | 增加资源级状态和批次聚合状态枚举，不重载既有资源发布状态的含义。 |
| `backend/app/agents/planner.py` | 让规划输出资源需求的可执行字段：学习目标、知识点、顺序和依赖；保持 Planner 只做规划，不直接分配不可验证资源 ID。 |
| `backend/app/agents/resource_spec_builder.py`（新增） | 确定性生成、验证和预算化 `ResourceSpec`；完成证据 ID 绑定、类型去重、顺序和预算计算。 |
| `backend/app/agents/generator.py` | **保留文件名**，改为统一 Generator 节点的资源编排入口：解析冻结 Spec、调用 `resource_agents/registry.py`、在节点内执行专用 Agent 的生成/校验/物化并统一返回；不再持有通用资源 Prompt 或直接生成正文。 |
| `backend/app/agents/reviewer.py` | 改为单资源审核，返回资源级结论与针对当前版本的返工指令。 |
| `backend/app/agents/claim_review.py` | Claim 抽取和判定按资源运行、按资源落库与汇总，保留现有最终发布判定口径。对 `实操指南/text`，若请求启用 Claim 审核，必须在 HTML 派生前完成。 |
| `backend/app/agents/workflow.py` | 保持高层 LangGraph 节点拓扑；Generator、Reviewer 与 Claim 节点分别进行资源级处理后统一汇总，增加部分完成发布与资源级返工策略。 |
| `backend/app/services/workflow_artifact_recorder.py` | 按 `resource_spec_id`/表示持久化资源、审核、Claim 和事件；在节点完成的耐久边界写入资源当前态并加强幂等性与版本冲突检查。 |
| `backend/app/services/generation_service.py` | 构建共享上下文、批次聚合结果和 Job 摘要；终结时计算资源级结果而不是只依赖全局 Reviewer 结论。 |
| `backend/app/services/generation_job_service.py` | 支持部分完成聚合、资源级重试（若启用）和任务状态转换校验。 |
| `backend/app/api/generate.py` | 返回扩展后的 Job 状态。 |
| `backend/app/api/resources.py` | 实现资源分页、摘要、单资源详情和已发布 HTML 预览 fragment；续生上下文继续保持有界，并改用 Spec 摘要。 |
| `backend/app/api/runs.py`、`backend/app/services/run_event_stream_service.py` | 投影、校验和流式下发资源级事件字段。 |
| `backend/app/config.py`、`backend/.env.example` | 增加 `RESOURCE_WORKER_MAX_CONCURRENCY`、`LLM_RESOURCE_GENERATOR_MAX_INPUT_TOKENS`、`LLM_RESOURCE_GENERATOR_MAX_OUTPUT_TOKENS`、`LLM_HTML_PRACTICE_GUIDE_MAX_OUTPUT_TOKENS`、`LLM_HTML_PRACTICE_GUIDE_REQUEST_TIMEOUT_SECONDS`、`RESOURCE_CONTINUATION_MAX_ITEMS`、`RESOURCE_CONTINUATION_SUMMARY_MAX_CHARS` 等受范围校验的配置。工作流 deadline 与 Run lease 必须按“文本生成 + 审核/Claim + HTML 生成”的最长串行路径校验，不得沿用短资源的默认值。 |
| `backend/app/core/llm_gateway.py` | 将 `HtmlPracticeGuideAgent` 的模型选项、16,384 输出 token 预算和专项请求超时实际应用到 provider 调用；记录两次调用各自的 token、耗时、模型和 prompt version。 |
| `backend/app/core/html_practice_sanitizer.py`（新增） | 第一阶段只做非空/可解析/大小/受控路径检查，以及修复优先的危险标签与属性移除；注入固定互动运行时。严格组件、语义和一致性校验列为后续增强，不作为第一期发布前门禁。 |
| `backend/app/db/models.py`、`backend/app/db/migrations/` | 新增 `resource_specs` 与 `resource_executions`（当前执行态表），并向资源模型增加 `resource_family_id`、`representation`、`derived_from_resource_id`、`source_resource_version`、`canonical_text_hash` 和 `guide_manifest`；为 `(run_id, resource_spec_id, representation)`、表示关联、源版本/hash 与状态查询建唯一索引。状态变化继续复用现有审计事件，避免把当前态表误命名为历史 `states` 表。迁移必须可重复执行。 |
| `docs/api.md`、`docs/architecture.md`、`docs/features.md` | 更新接口、架构图、事件语义、状态机和运行说明。 |

数据库不应把临时 Prompt 或原始模型响应落库。应持久化稳定 Spec、预算、状态、证据 ID、产物 ID、审计 ID、时间与脱敏错误码。

## 7. 前端改动清单

高层流程维持为“诊断 → 检索 → 规划 → 资源生成 → 审核/Claim → 完成”，避免用户面对 N 条复杂 Agent 线。生成和审核步骤变成可展开的资源级子项。

| 文件 | 改动 |
| --- | --- |
| `frontend/src/api/index.js` | 增加资源详情、分页列表、可选资源级重试 API；为 Job 状态与 timeline 请求传递分页参数。 |
| `frontend/src/utils/workflowEventReducer.js` | 识别并归并资源级 SSE/timeline 事件；按 `resource_spec_id` 去重，处理乱序和补发。 |
| `frontend/src/components/AgentVisualization.vue` | 保留高层节点，增加“生成资源”“审核资源”的可展开子树、聚合进度、失败和返工标识。 |
| `frontend/src/components/ResourceExecutionProgressList.vue`（新增） | 资源卡片列表：类型、学习目标、执行状态、轮次、错误提示、打开详情和重试入口。 |
| `frontend/src/components/ResourceViewer.vue` | 支持正文按需加载、加载骨架和资源级审核/Claim 摘要。 |
| `frontend/src/components/HtmlPracticeGuideViewer.vue`（新增） | 仅渲染已发布 HTML 指南；使用 sandboxed iframe、加载固定互动运行时、展示加载/错误态，并实现严格的 `postMessage` 白名单。 |
| `frontend/src/components/html-practice-guide.css`（新增） | 定义 HTML 指南专用的受控视觉层，复用应用已有的色彩、圆角、间距、字体和状态设计 token；禁止全局 CSS、`body` 重置或覆盖父应用样式。 |
| `frontend/src/assets/html_practice_runtime.js`（新增） | 固定、版本化的互动运行时；仅识别允许的 `data-practice-*` 标记，实现步骤、清单、自测和代码复制，不读取网络、Cookie、父页面或学习者数据。 |
| `frontend/src/views/GenerateView.vue` | 任务运行中读取 `resource_progress_summary` 与资源摘要，不再等待整个 Job `completed` 才展示已有资源；完成后继续保留现有“任务资源”体验。 |
| `frontend/src/views/ResourcesView.vue` | 切换到分页/摘要读取，选中后请求单资源详情；当 `resource_type=实操指南` 且同一 `resource_family_id` 有多个已发布表示时，提供“文本指南 / 互动实践”切换按钮。文本使用现有查看器，`representation=html` 使用 `HtmlPracticeGuideViewer`；HTML 尚未完成或失败时保持文本指南可用。 |
| `frontend/src/utils/generationDisplay.js` | 新增资源状态文案、颜色、排序规则和批次聚合状态。 |
| `frontend/src/api/runEvents.js` | 为资源事件补充类型守卫、重连后的状态合并和未知字段兼容。 |
| `frontend/tests/unit/utils/workflowEvents.test.mjs` | 覆盖资源事件乱序、重复、重连、失败重试和旧事件兼容。 |

交互规则：

- `generated`、`reviewing`、`revision_requested` 等草稿资源不得向学习者展示正文；前端只显示脱敏的执行状态、资源类型和下一步处理说明。
- 只有 `approved + published` 的资源允许进入正式学习/下载路径。
- 单资源失败不清空已完成资源；卡片显示可理解的失败状态和下一步操作。
- 批次为部分完成时，首页显示“已完成 X/Y”，不伪装为全部成功。
- HTML 资源预览保持与现有应用一致的标题栏、状态标签、卡片圆角、间距、色彩和响应式宽度；实操指南在文本/互动表示之间切换时维持同一资源标题、学习进度和审核状态。交互内容只在查看器的受控 iframe 内变化，不影响页面导航、表单或全局样式。

## 8. 实施阶段

### 阶段 0：基线与契约冻结

1. 为当前批量模式补齐 token、时延、结构化输出失败率、审核返工率、Claim 失败率指标。
2. 固定现有 Generate、Run、Resource、SSE 响应 fixture，作为兼容性回归输入。
3. 编写资源级状态机与允许转换表，评审后冻结。

验收：现有测试全绿；可以得到当前三资源请求的成本、时延与失败基线。

### 阶段 1：数据模型与只读展示

1. 增加数据库迁移、Spec/Progress 模型和仓储接口。
2. 仍使用当前批量 Generator，但在产物落库后回填资源级进度。
3. 扩展 Job、timeline、SSE 的只读投影；前端完成高层流程下的可展开资源进度视图。

验收：不改变生成结果；运行中的页面可看到资源级状态，刷新/重连不重复或丢失状态。

### 阶段 2：资源级生成与审核

1. 引入 `ResourceSpec Builder` 与单 Spec Generator。
2. 引入三种专用 Agent 和唯一注册表：`TextResourceAgent()`、`HtmlPracticeGuideAgent()`、`AssessmentAgent()`；完成启动时注册完整性校验。
3. 在 Generator 节点内部实现受限并发调用和安全聚合；节点完成后统一持久化。
4. 将 Reviewer 与 Claim 改为资源级审核结果与返工；对实操指南，`text` 表示必须先完成当前通用 Reviewer，且在 `include_claim_check=true` 时先完成资源级 Claim 链路，二者通过后才派发 HTML 转换。
5. 启用分资源失败隔离和批次聚合。

验收：三资源中人为注入一个生成/审核失败时，另两项仍可完成、可查询、事件可回放；返工只产生目标资源新版本。实操指南文本审核或已启用的 Claim 审核失败时不生成 HTML；文本审核通过、HTML 派生失败时文本仍可发布和学习。每个 Run 必须能证明类型与专用 Agent 的精确映射：`讲义 → TextResourceAgent`、`实操指南 → HtmlPracticeGuideAgent`、`分阶测试题 → AssessmentAgent`。

### 阶段 3：Claim 聚合、读取性能与受控重试

1. 完善资源级 Claim 指标聚合、审计查询与失败恢复；实操指南文本的资源级 Claim 前置链路已在阶段 2 完成。
2. 增加资源详情、分页/摘要读取、HTML 隔离预览和按资源重试接口。
3. 压测 Generator 节点内部并发、输入/输出预算与超时，单独验证 HTML 实操指南的长输出和最小清洗耗时。

验收：长资源、六种以上资源类型及 Claim 审核不出现全批次输入膨胀；失败资源不影响已完成资源的 Claim 指标和发布状态。已发布 HTML 指南可完成步骤、清单、自测与代码复制互动；预览必须与父页面隔离，且不执行模型生成脚本或影响父页面样式。

### 阶段 4：正式切换与回归

1. 新工作流作为唯一的新 Run 创建路径直接启用，不提供运行时切换按钮或旧/新模式开关。
2. 保留旧 Run 的读取、回放与资源详情兼容；历史数据不迁移为新的资源执行记录，也不补造资源级事件。
3. 部署前完成离线端到端演练、真实模型受控冒烟和前端回归；部署后以指标告警监测完成率、时延、token 成本和人工复核率。

## 9. 测试与质量门禁

必须新增或更新的测试：

- 单 Spec 合法/非法、类型去重、预算超限、证据范围错误。
- 注册表完整性、大小写/别名规范化、未知类型拒绝、类型到 Agent 的一对一映射，以及返工时路由不可变。
- 三种专用 Agent 分别验证 Prompt 版本、输入范围、输出 Schema 和持久化元数据；HTML 第一期只测试非空、可解析、大小上限、受控路径、危险标签/属性的修复移除和隔离预览。
- 实操指南两阶段链路：验证规范 Markdown 与 `guide_manifest` 的固定结构和稳定 ID；文本先生成/审核/Claim，HTML 仅在文本批准后生成；验证 `resource_family_id`、`representation`、`derived_from_resource_id`、源文本版本/hash、HTML 失效联动和文本/HTML切换。
- HTML 专项 Prompt 回归：检查转换 Prompt 明确禁止新增事实、代码、命令、答案和网络行为；检查源 ID 映射、互动组件要求和 16,384 token 输出预算。第一期不因这些内容规则自动判失败。
- 前端 HTML 预览：sandbox 属性、固定运行时版本、跨页面样式隔离、窄屏布局、代码复制、步骤/清单/测验互动，以及草稿不可预览。
- Generator 节点内部并发调用不覆盖共享 state、资源版本不冲突、节点边界重放幂等。
- 一个资源超时、模型 JSON 不合规、审核失败、Claim 不完整时的隔离与批次汇总。
- 资源级返工只影响目标资源及其版本谱系。
- 数据库迁移升级、重复执行、旧 Run/旧资源只读兼容。
- SSE 事件重放、断线续传、乱序、重复与前端状态归并。
- 授权：资源详情、资源重试和草稿状态均只能由当前用户访问；草稿正文不得由任何学习者读取。
- 分页：大批次资源列表不返回完整正文，详情接口才返回正文。

质量门禁：后端 `pytest`、前端单元测试、类型/静态检查（如项目已配置）、API 契约测试、一次离线端到端演练与一次受控真实模型冒烟。新增逻辑不得通过吞掉异常把失败资源误标为成功。

## 10. 最终用户效果

用户看到的主流程不会变复杂：仍然是诊断、检索、规划、生成、审核和完成。不同的是，生成页会在“资源生成”和“审核”节点下显示每份材料的节点级持久化进度；讲义通过审核并发布后，无需等待测试题即可阅读。某一份资源出现问题时，界面只提示该资源需要重试/人工复核，其他已批准资源保持可用。

系统层面，长文本和多资源请求不再依赖一次超大的模型 JSON 返回；审计、证据、审核、Claim 和版本都能精确落到单份资源，且批次仍能给出统一的学习路径和最终报告。

## 11. 评审决策项

开始实施前需要确认：

1. 已确认：草稿资源不允许预览；仅 `approved + published` 的资源允许阅读、学习或下载。
2. 已确认：批次部分完成时，已批准资源立即发布；UI 必须明确“批次尚未全部完成”。
3. 已确认：单资源默认输出预算为讲义 `8,192 tokens`、分阶测试题 `8,192 tokens`、实操指南 canonical text `8,192 tokens`、实操指南 HTML 派生表示 `16,384 tokens`。HTML 指南因包含完整互动结构、步骤验证与复盘，拥有独立更高上限；所有值均须受模型上下文窗口与工作流总预算约束。
4. 已确认：不提供旧/新流程切换开关；所有新 Run 直接采用资源级工作流，历史 Run 保持兼容读取。
