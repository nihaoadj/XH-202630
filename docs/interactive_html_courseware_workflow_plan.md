# 审核后互动 HTML 课件工作流方案（简单版）

> 状态：方案评审稿，**本次只更新文档，不实现代码**。  
> 结论：可行；“互动 HTML 课件”仍是一份与讲义、实操指南、分阶测试题**同级的学习资源**。建议新建的是它的生产工作流；它以已经审核发布的资源为唯一输入，不接入当前资源生成主流程。

## 1. 决策摘要

### 1.1 是否可行

可行，且与当前系统的“证据约束 → 内容生成 → 审核/Claim 校验 → 发布”的设计相容。当前系统已经具备三项关键前提：

- 每份资源有稳定的 `run_id`、`resource_id`、版本、发布状态和证据范围；
- 实操指南的规范文本是审核的唯一内容源，并记录了 `canonical_text_hash`；
- 已发布资源才允许读取、下载和 HTML 预览。

因此，可以在“讲义、实操指南、分阶测试题均完成审核并发布”之后，冻结这些版本，生成一份同级、可互动、可下载的 HTML 课件资源。

### 1.2 是否应当新建工作流

**应当新建课件生产工作流，但不应新建第二套资源库或知识生成系统。**

推荐结构如下：

```text
现有资源生成工作流（保持职责不变）
诊断 → 检索 → 规划 → 资源生成 → 审核 / Claim → 发布
                                      │
                                      │ 仅允许已发布、版本一致的资源进入
                                      ▼
新增课件生产工作流（按需人工发起）
课件准入 → 源资源快照 → 课件结构规划 → 场景生成 → 受控渲染
→ 课件校验 → 发布 → 课件播放器 / HTML 下载
```

这里的“新工作流”是领域工作流，而不是必须新部署一个服务、消息队列或模型供应商。第一期可以复用现有后端、任务执行机制、LLM Gateway、文件存储和 SSE 能力；其最终产物仍写入现有资源模型、出现在现有资源库、使用现有资源详情/下载/授权能力。独立的是课件的来源快照、编排和渲染过程，不是资源身份。

### 1.3 本期产品边界

首版目标是“由已审核内容组装的一份单主题互动 HTML 课件资源”，而不是完整复刻 OpenMAIC 的多人实时课堂。

首版包含：

- 封面、学习目标、章节导航、知识讲解卡；
- 来自已发布讲义和实操指南的步骤化学习内容；
- 来自已发布分阶测试题的单选/多选/简答式自测（首版可先支持客观题即时反馈）；
- 步骤完成勾选、章节进度、复习总结和完成页；
- 单一自包含 HTML 文件，可在隔离 `iframe` 中预览和下载后离线打开；
- 内容来源、资源版本和证据来源的可追溯信息。

首版不包含：

- AI 教师/同学实时对话、TTS、白板、语音识别；
- 3D 模拟、在线编程运行环境、PBL 多角色协作；
- 允许模型直接生成并执行任意 JavaScript；
- 自动跟随每一次资源生成，无人工确认地持续生成课件。

## 2. 参考 OpenMAIC 后应借鉴与不应照搬的内容

OpenMAIC 的可借鉴点不是“让模型一次输出一个巨大 HTML 文件”，而是把课堂拆为可管理的层次：先生成结构化大纲，再按场景生成内容，并由独立播放/渲染层呈现。其公开说明将课程生成描述为“Outline → Scenes”两阶段，并把幻灯片、测验、互动模块和 PBL 作为不同场景；同时将播放状态机、动作引擎、导出层分离。详见 [OpenMAIC 项目说明](https://github.com/THU-MAIC/OpenMAIC) 与 [其中文说明](https://github.com/THU-MAIC/OpenMAIC/blob/main/README-zh.md)。

对本项目的对应取舍：

| OpenMAIC 能力层 | 本项目简单版对应 | 当前是否应实现 |
| --- | --- | --- |
| 课堂大纲 | `CoursewareSpec`：课件、章节、场景和来源资源的结构化规格 | 是 |
| 场景 | 讲解、步骤、测验、复盘四种受控场景 | 是 |
| 互动组件 | 内置测验、勾选清单、进度条、折叠提示 | 是 |
| 渲染/播放器 | 平台固定模板 + 平台固定 JS runtime + sandbox iframe | 是 |
| 多智能体课堂与实时讨论 | 无 | 否 |
| 动作引擎、白板、TTS、语音 | 无 | 否 |
| 3D/游戏/在线代码执行 | 后续可作为独立互动组件类型 | 否 |

本项目应借鉴其“结构化内容与运行时分离”的方向，而不是直接复制其代码、DSL 或完整架构。两者技术栈、产品范围和现有资源治理边界不同；本方案只参考其公开架构思想。

## 3. 为什么不把课件放进当前资源生成流程

当前流程中的资源是围绕学习路径生成的同级学习产物。新课件也应属于这一层。尤其是现有“实操指南 HTML”，本质是同一实操指南的第二种表示：它从已审核的规范 Markdown 派生，必须与源资源的版本和哈希一致。它适合增强一份指南的阅读与清单交互，不适合承担完整课件的编排职责。

若将完整课件作为第四种普通资源类型直接加入当前流程，会产生以下问题：

| 风险 | 原因 | 课件专用工作流的处理方式 |
| --- | --- | --- |
| 审核对象混淆 | 课件包含多个资源的组合、顺序和交互，不是单资源正文 | 先审核源资源；课件审核的是编排、来源完整性和渲染安全 |
| 生成成本被放大 | 每次生成讲义/指南/测试题都额外生成一次大型 HTML | 仅由用户在源资源审核完成后按需发起 |
| 返工范围不清 | 一个源资源返工时，课件、其他资源和旧 HTML 容易相互覆盖 | 课件冻结来源快照；源资源更新后标记课件“可更新/已过期” |
| 安全模型失配 | 当前 HTML 指南明确限制模型脚本和外部访问 | 课件交互由平台受控 runtime 提供，模型只产出结构化内容 |
| 历史可追溯性变差 | 课件会混入不同 Run 或不同版本的内容 | 每份课件持久化全部源资源版本、哈希、证据快照 |

因此，用户提出的“课件不进入当前生成流程，只能在讲义、实操指南等审核完成后，基于已审核内容在新链路实现”是正确的推荐方案；但**新链路的输出应回到当前资源体系，作为同级资源展示和管理**。

## 4. 简单版的目标架构

### 4.1 课件来源准入

用户从资源库中选择一个已完成的资源批次，点击“生成互动课件”。服务端先执行确定性准入，而不是立即调用模型。

准入规则：

1. 至少选择一份已发布的讲义；建议同时存在已发布的实操指南和分阶测试题。
2. 所有选中的资源必须属于同一学习者、同一学习方向，并优先要求同一 `run_id`。
3. 每份源资源必须为 `publication_status=published`；实操指南只读取其 `representation=text` 的规范文本，不能反向以 HTML 为内容源。
4. 读取时冻结 `resource_id`、`version`、`canonical_text_hash`（适用时）、知识点、证据 ID 和内容哈希。
5. 若同一资源族有新版本，旧版仍可用于历史课件，但新建课件默认选取当前已发布版本。
6. 源资源不满足条件时返回具体原因，不创建课件任务。

推荐首版采用“同一 `run_id` 的完整三资源组合”作为一个课件包。这样教学目标、难度、证据和生成上下文最一致；后续再支持跨批次手动选材。

### 4.2 课件工作流

```text
用户在资源库选择“生成互动课件”
  → Courseware Admission Gate
      - 发布状态、归属、run、版本、哈希、最小资源组合校验
  → Source Snapshot Builder
      - 写入不可变 source snapshot，不写回源资源
  → CoursewareSpec Builder
      - 由已审核内容抽取章节、场景顺序、互动槽位和来源映射
  → Scene Composer（受控并发）
      - 讲解场景 / 实操场景 / 测验场景 / 复盘场景
  → Courseware Reviewer
      - 覆盖率、来源映射、题目答案、教学顺序、结构完整性
  → Deterministic Renderer
      - 结构化 JSON + 固定模板 + 固定 runtime → self-contained HTML
  → Security & Package Validation
      - CSP、禁外链、禁模型脚本、资源大小、可打开、哈希与元数据
  → 发布课件
```

每一阶段的职责应明确：

- LLM 可以参与“课件规格”和“场景内容”的结构化生成，但只能引用快照中的内容；
- 服务端负责资源来源绑定、场景类型路由、版本冻结、准入、审核结论与发布；
- 渲染器负责 HTML/CSS/JavaScript 产物，模型不得直接控制可执行 JavaScript；
- 播放器负责运行、进度和受限事件通信，不能给课件页面应用 API 的登录上下文或网络权限。

### 4.3 受控场景模型

首版只注册以下四种场景。以类型注册表路由，禁止模型自行发明场景或要求浏览器执行代码。

| 场景类型 | 输入来源 | 首版交互 | 必须保存的内容 |
| --- | --- | --- | --- |
| `explain` 讲解 | 讲义 | 分段展开、重点标记 | 标题、正文块、知识点、来源段落 ID |
| `practice` 实操 | 实操指南规范文本 | 步骤勾选、提示折叠、完成检查 | 步骤、命令/预期结果、清单、来源步骤 ID |
| `quiz` 自测 | 分阶测试题 | 客观题即时判定、解析显示 | 题目、选项、答案、解析、题目 ID |
| `recap` 复盘 | 三类已审核资源 | 知识点回顾、学习完成页 | 目标、知识点、下一步建议、来源 ID |

建议 `CoursewareSpec` 的核心形态如下（示意，不是最终 API 契约）：

```json
{
  "resource_id": "resource_...",
  "schema_version": "1.0",
  "title": "RAG 工程实践入门",
  "learning_objectives": ["..."],
  "source_snapshot_id": "cws_...",
  "chapters": [
    {
      "chapter_id": "chapter-01",
      "title": "核心概念",
      "scenes": [
        {
          "scene_id": "scene-01",
          "type": "explain",
          "blocks": [],
          "source_refs": [{"resource_id": "...", "version": 1, "block_id": "..."}]
        }
      ]
    }
  ]
}
```

`source_refs` 是硬性要求。课件中的每个可见内容块、步骤和题目都必须能追溯到一个源资源快照；无法映射的模型新增事实必须被拒绝或转人工复核。

## 5. 数据、版本和状态设计

### 5.1 课件是标准资源，链路是专用链路

互动 HTML 课件应新增为资源 vocabulary 中的第四个类型，例如 `互动HTML课件`；其最终产物使用现有 `generated_resources`、`resource_specs`、`resource_executions`、资源文件存储和资源版本机制：

```text
resource_type        = 互动HTML课件
representation       = html
mime_type            = text/html
resource_family_id   = 课件自己的 family ID
publication_status   = 与其他资源相同的 published / unpublished 规则
```

但当前“用户在诊断后可直接勾选生成”的资源类型集合必须与“资源库中允许存在的类型集合”拆开：

```text
ALL_RESOURCE_TYPES / RESOURCE_TYPE_REGISTRY
  = 讲义、实操指南、分阶测试题、互动HTML课件

PRIMARY_GENERATION_RESOURCE_TYPES
  = 讲义、实操指南、分阶测试题

POST /api/generate/jobs
  只接受 PRIMARY_GENERATION_RESOURCE_TYPES

POST /api/resources/courseware/jobs
  只接受已发布源资源，且只创建 互动HTML课件
```

这样，课件可与当前资源并列显示、下载、查看历史和进入学习记录，但不会在现有诊断后的默认资源选择中出现，更不会被普通 `Generator` 误生成。

首版建议新增的仅是“多源资源谱系”数据，而不是另一套课件资源表：

| 数据对象 | 责任 |
| --- | --- |
| `generated_resources`（复用） | 保存课件 HTML 正文/文件、资源类型、版本、发布状态和资源级权限 |
| `resource_specs`（复用并扩展） | 保存课件的目标、场景数量、渲染预算和 `schema_version` |
| `resource_executions`（复用并扩展） | 保存课件专用链路的快照、编排、审核、渲染和校验状态 |
| `resource_source_links`（新增） | 一份课件连接多份源资源，保存源 `resource_id`、version、hash、role 和快照时间 |
| 课件 JSON 规格（存于 artifact metadata） | 保存 `CoursewareSpec`、来源映射、渲染器/runtime 版本和 artifact hash |
| `courseware_attempts`（第二期，可选） | 保存学习完成度、作答和进度；首版可先仅保存在浏览器本地 |

课件任务可以是 `generation_jobs` 的一个明确 `job_kind=courseware`，也可以是单独的任务投影；无论任务表如何实现，成功产物必须落为标准资源记录，并复用资源列表和授权路径。课件执行应有自己的 `run_id`，同时在资源元数据和 `resource_source_links` 中记录 `source_run_id`，以保持“新链路执行”与“来源批次追溯”两种语义都清晰。首版不要求立刻引入独立 Worker/消息队列。

### 5.2 状态机

```text
draft
  → queued
  → snapshotting
  → composing
  → reviewing
  → rendering
  → validating
  → published

任一非终态 → failed | human_review
published → stale（源资源出现更高已发布版本时）
stale → queued（用户明确选择“基于最新审核资源重新生成”）
```

规则：

- `published` 课件是一份标准已发布资源，且永远指向它创建时的源资源快照，不会因源资源更新而被静默覆盖；
- 源资源有新版时，只把旧课件标为 `stale`，仍可阅读和下载，并清晰提示“基于旧审核版本”；
- 重新生成创建新的课件资源版本和快照，不能覆写旧课件；
- 课件 HTML 渲染失败不得改变已发布的讲义、实操指南或测试题状态；
- 只有 `published` 课件可预览、下载和作为学习记录入口。

## 6. HTML 与安全设计

### 6.1 现有实操指南 HTML 不能直接承担课件

现有 `HtmlPracticeGuideAgent` 的 HTML 是受严格清洗的片段：后端会移除 `script`、`iframe` 等高风险元素，前端再以固定脚本将清单与测验交互挂载到隔离 iframe。这是正确的“受控 HTML 指南”策略，但无法安全地容纳模型生成的完整课件程序。

课件首版应采用：

```text
模型：只输出 CoursewareSpec / 场景 JSON
平台：固定 renderer 把 JSON 编译为 HTML
平台：固定 courseware runtime 提供导航、进度、测验判分
浏览器：在 sandbox iframe 内运行编译产物
```

不采用：

```text
模型：直接输出 <script> + 任意第三方库 + 任意网络请求的完整 HTML
```

### 6.2 安全基线

- HTML 使用平台固定 CSP：默认拒绝网络、表单提交、弹窗、顶层跳转和第三方 iframe。
- 不允许课件读取宿主的 Cookie、LocalStorage、鉴权头或应用 DOM；iframe 保持无 `allow-same-origin` 的沙箱隔离。
- 课件脚本只能是构建时内联的、带明确 `runtime_version` 的平台代码；模型产物只能是经过 schema 验证的 JSON 数据。
- 首版不引用 CDN、远程图片、字体、视频或第三方脚本；所有所需资源必须内联或由平台受控打包。
- 宿主和 iframe 间仅使用严格 allow-list 的 `postMessage`：`ready`、`height`、`progress`、`quiz_result`、`completed`。事件不得包含正文、Prompt、证据原文、用户身份信息或令牌。
- 下载前与预览前均校验 artifact hash、schema/runtime 版本和发布状态。

### 6.3 学习进度

首版推荐“课件内本地进度 + 宿主只展示会话状态”：

- 勾选、章节位置和客观题作答可保存在课件沙箱自己的 `localStorage` 或内存中；
- 宿主只接收已完成数量、总数量和是否完成；
- 不把未设计好的作答记录直接写入当前反馈/画像闭环。

第二期如需把进度正式进入学习历史，应新增受鉴权保护的 `courseware_attempts`，用独立 API 接收最小化事件，并经过服务端校验后再影响学习报告或学习路径。

## 7. 与当前项目的集成点

以下是后续实现需要新增或调整的范围；它们是计划项，非本次改动。

| 层 | 建议变更 | 保持不变 |
| --- | --- | --- |
| 资源类型 | 增加 `互动HTML课件`，并分离“全量资源类型”与“主生成可选类型”注册表 | `讲义`、`实操指南`、`分阶测试题`继续由现有专用 Agent 生成/审核 |
| 后端模型与迁移 | 新增课件多源关联和课件规格元数据字段 | `generated_resources` 继续保存所有资源（包括课件）的谱系、状态与文件 |
| 工作流 | 新增 `courseware_workflow`，按课件状态机运行 | 现有 `workflow.py` 中的诊断、检索、生成、审核主链 |
| LLM Agent | 新增 `CoursewareSpecAgent` 与按场景的 `SceneComposer` | 不让通用 Generator 生成完整课件 HTML |
| 渲染 | 新增确定性 `CoursewareRenderer`、固定 CSS/JS runtime | 现有 `html_practice_sanitizer` 仍服务于实操指南 HTML |
| API | 新增课件创建接口；产物仍经 `/api/resources/...` 列表、详情、预览和下载读取 | `/api/generate/jobs` 与 `/api/resources/...` 对既有资源的契约 |
| 前端 | 资源库增加“生成课件”入口；在现有资源阅读页按资源类型加载课件播放器 | 现有资源库、任务分组、资源阅读和实操指南双表示切换 |
| SSE | 课件事件使用资源级事件投影，并带 `pipeline=courseware` 或同等 allow-list 标识 | 现有资源级事件重放、序列去重、断线恢复机制 |

建议前端入口：

```text
资源库 → 选择一个已完成任务 → “生成互动课件”
     → 展示源资源与版本确认
     → 创建课件专用任务
     → 当前任务的资源进度中出现“互动HTML课件”
     → 发布后，课件与讲义/指南/测试题并列出现在当前资源库
     → 在同一资源阅读页进入“课堂播放”视图或下载 HTML
```

入口必须显式展示“源资源已审核发布”的状态与版本，避免用户误以为课件内容会自动追随草稿或未审核修改。

### 7.1 推荐的文件系统组织

**现有主工作流必须保持原样，不移动、不改名、不重组。** 这包括现有的 `backend/app/agents/workflow.py`、`resource_agents/`、`resource_spec_builder.py`、`validators.py`、`reviewer.py`、`claim_review.py` 及其既有 import、测试和文档。它们继续服务于“诊断后生成讲义/实操指南/分阶测试题”的当前链路。

`resource_agents/` 的名称从长期看仍有歧义：它实际包含的是当前主链的“学习材料生成 Agent”，而不是系统全部资源的 Agent。建议在**独立批准的命名重构**中将其改为 `learning_material_agents/`；这只改目录、import、测试与文档名称，不改 `workflow.py` 的节点、路由或业务行为。课件工作流实现本身不包含这次重命名，以免与“新增工作流”混为同一变更。

推荐按“资源工作流”在 `backend/app/agents/` 下新增 `resource_workflows/` 文件夹。它只承载**新增的、非主资源工作流**；当前主工作流仍停留在既有 `agents/workflow.py`。课件是其中第一个子工作流，未来的视频、仿真等复杂资源也可各自增加并列目录。此安排不创建顶层 `workflows/`，不迁移 `resource_agents/`，也不把现有审核 Agent 改名或移动。

注意：新目录在 `agents/` 下不意味着每个文件都调用 LLM。准入、快照、渲染和安全校验是课件工作流节点；只有命名为 `*_agent.py` 的文件才是模型驱动 Agent。两类任务都由新课件工作流的 `workflow.py` 调度。

推荐增量目录如下（`# 保持不变` 表示不是本次课件工作要修改的内容）：

```text
backend/app/
├── agents/
│   ├── workflow.py                       # 保持不变：当前主资源生成工作流
│   ├── resource_agents/                  # 保持不变：现有三类资源的专用内容 Agent
│   ├── resource_spec_builder.py          # 保持不变：当前主链的 ResourceSpec 构建
│   ├── validators.py                     # 保持不变：当前主链的审核指令和谱系校验
│   ├── reviewer.py                       # 保持不变：当前资源审核 Agent
│   ├── claim_review.py                   # 保持不变：当前 Claim 审核闭环
│   └── resource_workflows/               # 新增：非主资源的独立生成工作流集合
│       ├── __init__.py
│       ├── registry.py                   # resource_type → workflow key / 入口的受控路由表
│       └── interactive_courseware/       # 新增：审核后互动HTML课件生产工作流
│           ├── __init__.py
│           ├── workflow.py               # 只负责编排以下节点、路由和 state reducer
│           ├── state.py
│           ├── source_admission_node.py  # 确定性：已发布源资源、归属、版本、run 准入
│           ├── source_snapshot_node.py   # 确定性：冻结多源资源版本、哈希和证据引用
│           ├── courseware_spec_agent.py  # AI：生成/修订 CoursewareSpec JSON
│           ├── scene_composer_agent.py   # AI：按受控场景类型编排内容
│           ├── source_trace_review_agent.py # AI：审核每个内容块是否能回溯到源快照
│           ├── courseware_quality_review_agent.py # AI：审核目标覆盖、顺序、题目与反馈
│           ├── render_node.py            # 确定性：固定模板/runtime 编译 self-contained HTML
│           ├── safety_validation_node.py # 确定性：CSP、禁外链、包大小和元数据校验
│           ├── publish_node.py           # 确定性：写入同级资源、来源链接和发布状态
│           ├── contracts.py              # CoursewareSpec、Scene、SourceRef 等契约
│           └── prompts.py                # 版本化 Prompt；不包含浏览器 runtime
├── services/
│   ├── courseware_generation_service.py  # 新增：创建/查询课件任务、驱动 agents 中的工作流
│   └── resource_service.py              # 扩展：读取资源的多源关联和课件详情
├── models/
│   └── courseware.py                     # 新增：课件领域/API DTO；或按现有惯例并入 schemas.py
├── db/
│   ├── models.py                        # 扩展：resource_source_links ORM
│   ├── migrations/
│   │   └── p0_xx_courseware_resource.py # 新增：资源类型、链路表、元数据字段迁移
│   └── resource/                        # 扩展：多源关联的仓储接口及 SQL/内存实现
├── api/
│   └── resources.py                     # 扩展：创建课件任务；资源读取接口继续复用
└── core/
    └── courseware_security.py           # 新增：课件包的 CSP、HTML/元数据校验（可选）

frontend/src/
├── components/
│   ├── ResourceViewer.vue               # 按 resource_type 路由到课件播放器
│   └── CoursewareViewer.vue             # 新增：隔离 iframe、受限 postMessage、下载
├── assets/
│   └── courseware_runtime.js            # 新增：平台固定互动 runtime，非模型生成
└── views/
    └── ResourcesView.vue                # 扩展：从已完成资源批次发起课件生成
```

边界如下：

| 位置 | 应放内容 | 不应放内容 |
| --- | --- | --- |
| `agents/workflow.py`、`resource_agents/`、`resource_spec_builder.py`、`validators.py`、`reviewer.py`、`claim_review.py` | 当前主资源生成、审核与 Claim 闭环 | 本次课件目录重组或重命名 |
| `agents/resource_workflows/registry.py` | 受控映射“资源类型 → 新工作流入口”；不由模型决定路由 | 修改当前主工作流的业务节点 |
| `agents/resource_workflows/interactive_courseware/` | 新课件工作流及准入、快照、AI 编排、双重审核、渲染、安全校验、发布节点 | 变更现有资源生成工作流 |
| `services/courseware_generation_service.py` | 创建/查询课件任务、事务边界、驱动课件工作流 | Prompt、图路由与节点业务规则 |
| `db/resource/` | 资源及 `resource_source_links` 的读写、版本查询 | 课件教学内容生成 |
| `frontend/` | 资源内课件阅读/播放体验 | 课件内容或安全策略的最终裁决 |

资源类型的工作流路由应按**语义资源类型**决定，而不是按最终文件后缀决定：

| 语义资源类型 | 工作流 | 说明 |
| --- | --- | --- |
| 讲义 | 现有 `agents/workflow.py` | 保持当前流程 |
| 实操指南 | 现有 `agents/workflow.py` | 仍先生成和审核规范 Markdown；其派生 HTML 不视为另一条资源工作流 |
| 分阶测试题 | 现有 `agents/workflow.py` | 保持当前专用 Agent 与审核逻辑 |
| 互动HTML课件 | `resource_workflows/interactive_courseware/workflow.py` | 只从已发布资源快照生成 |
| 未来视频课件/仿真等 | `resource_workflows/<resource_workflow>/workflow.py` | 各资源类型独立新增，不修改现有主链 |

`registry.py` 应显式维护这张映射。创建任务时，API/服务先根据 `resource_type` 选择入口；模型不能改变路由。对于已有 `POST /api/generate/jobs`，仅继续接收前三种主资源类型；互动 HTML 课件走课件专用创建入口。

课件工作流的调用关系应为：

```text
agents/resource_workflows/interactive_courseware/workflow.py
  → source_admission_node.py
  → source_snapshot_node.py
  → courseware_spec_agent.py
  → scene_composer_agent.py
  → source_trace_review_agent.py
  → courseware_quality_review_agent.py
  → render_node.py
  → safety_validation_node.py
  → publish_node.py
  → db/resource/（写入同级资源和多源关联）
```

这里的两类审核应分开：`source_trace_review_agent.py` 只审核“课件是否忠实使用已审核源内容”；`courseware_quality_review_agent.py` 只审核“课件编排和交互是否完整可用”。它们不重新审核讲义/指南/测试题本身的事实正确性，因为该职责已由上一条资源生成工作流完成。

如果后续实施现有“资源级 Worker”升级方案，可仅在 `agents/resource_workflows/interactive_courseware/` 下新增 `workers/` 子目录；首版不必预先创建这一层。这个扩展不会改变课件是同级资源、也不会改变现有主工作流。

本课件方案的文件系统更新是纯新增：新增课件目录、必要的资源关联迁移、课件任务服务、资源 API 分支和前端播放器。除非有一份独立、明确批准的“主工作流目录重构”需求，否则不得移动、改名或删除任何现有 `agents` 文件。

## 8. 首版接口草案

以下接口命名仅用于定义边界，后续实现前再冻结 OpenAPI 契约。

```text
POST /api/resources/courseware/jobs
  body: {
    learner_id,
    source_run_id,
    source_resource_ids: [...],
    title?: string,
    mode: "simple_interactive_html"
  }

GET  /api/resources/courseware/jobs/{courseware_job_id}
POST /api/resources/items/{resource_id}/regenerate-courseware

GET  /api/resources/{learner_id}?run_id=...     # 课件与其他资源一起返回
GET  /api/resources/items/{resource_id}         # 返回课件资源详情和来源链接
GET  /api/resources/items/{resource_id}/preview # 根据 resource_type 选择受控课件预览
GET  /api/resources/file/{resource_id}          # 复用已有下载入口
```

`POST /api/resources/courseware/jobs` 不接受任意正文、任意 HTML 或 URL；它只接受已授权、已发布的源资源标识。服务器自行读取并冻结源内容，成功后返回的仍是一个标准资源 ID。

## 9. 验收标准

简单版完成时，至少满足以下条件：

1. 未发布、审核返工、人工复核或不同学习者的资源不能创建课件任务。
2. 一个已完成批次的讲义、实操指南和测试题可生成一份可打开的自包含 HTML 课件。
3. 课件包含至少一个讲解、一个实操步骤清单、一个自测和一个总结场景。
4. 任一课件场景均能回查到源资源 ID、版本和内容块/步骤/题目 ID。
5. HTML 中不存在模型生成的可执行脚本、外链脚本、网络请求、表单提交或顶层导航能力。
6. 课件在宿主播放器的 sandbox iframe 与本地文件打开两种方式下均能完成基本导航、勾选和客观题反馈。
7. 课件生成失败或重新生成不会改变任何已发布源资源。
8. 已发布课件和讲义、实操指南、测试题在同一资源库和同一学习历史中以同级资源显示；课件展示其 `source_run_id`，并使用专用播放器视图。
9. 源资源发布新版本后，旧课件被标记为“可更新”，但历史课件与其来源快照仍可读取。
10. 预览和下载接口只返回已发布课件，且复用资源接口的所属学习者授权校验。
11. 覆盖准入、版本冻结、源追溯、JSON schema、渲染安全、iframe 通信、离线打开和过期标记的自动化测试。

## 10. 分阶段实施建议

### 阶段 0：契约与样例冻结

- 选定一个真实的、已审核完成的资源批次作为样例；
- 定义 `CoursewareSpec` JSON Schema、四类场景的最小字段和来源映射字段；
- 产出一个手写 JSON 样例并使用固定模板渲染，先验证播放器和离线包。

### 阶段 1：最小可用课件（建议首个实现目标）

- 后端实现源资源准入、快照、课件任务、确定性渲染与发布；
- 初期可用规则/模板把审核资源映射到场景，LLM 只负责受限的章节标题和摘要；
- 前端实现任务进度、课件列表、隔离播放和下载；
- 只支持一套默认视觉主题、四种场景和浏览器内即时反馈。

### 阶段 2：结构化 AI 编排与课件审核

- 引入 `CoursewareSpecAgent`、`SceneComposer` 和 `CoursewareReviewer`；
- 强制所有场景满足来源覆盖、教学顺序和题目正确性检查；
- 增加“源资源更新 → 课件过期 → 用户确认再生成”的完整体验。

### 阶段 3：可选的高级能力

- 持久化学习进度并接入学习历史/报告；
- 增加图表、流程图、可配置仿真等**平台内置组件**；
- 再评估 TTS、教师引导和更复杂课堂运行时。每一种新组件都需单独的安全模型、数据契约和测试，不应通过放开任意 HTML/JS 来快速实现。

## 11. 本次结论与下一步

结论：采用“审核完成后的课件专用链路、输出回归同级资源”的方案是正确且可落地的。它能复用本项目最有价值的部分——审核、证据、版本和资源谱系——同时避免让完整互动课件破坏当前资源生成与审核边界。

下一次实现建议从阶段 0/1 开始：先用一份已发布资源批次做一个受控、离线可运行的 HTML 课件样例，验证数据契约、渲染器和 sandbox，再接入 AI 场景编排。不要先尝试复刻 OpenMAIC 的多人课堂、语音和深度互动模式。
