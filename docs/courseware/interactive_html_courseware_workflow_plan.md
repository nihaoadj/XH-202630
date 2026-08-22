# 下一次互动 HTML 课件更新计划

> 用途：本文件只定义下一次迭代的工作范围、验收标准和文件边界。已完成能力仅作简短基线说明，不重复记录实施过程。

## 1. 当前基线（不在本轮重做）

已具备独立课件资源链路：已发布资源准入与冻结、确定性多场景课件、受控 LLM `CoursewareSpec` / `CoursewareSceneSpec`、固定 HTML renderer、安全预览与离线下载、来源规则审核、资源库展示、任务事件和基础重试。

课件 LLM 调用已集中在 `backend/app/agents/resource_workflows/interactive_courseware/`；但课件状态机仍在服务层，且 `backend/app/agents/workflow.py` 的名称容易被误解为全局工作流。下一轮先完成 Agent/工作流目录重构，再迁移课件编排；不改变五类学习文档的业务语义、API 或发布结果。

当前缺口：真实模型验收不足、评测集不足、场景重试仍会回到总任务、浏览器自动化覆盖不足、互动组件偏少、缺少审核修订工作台。

## 2. 本轮目标与边界

目标：把当前“能安全生成”的课件链路升级为“可评测、可局部返工、可审核发布”的稳定生产链路。

不在本轮范围：多人课堂、实时语音、白板、3D、在线代码执行、外部学习平台对接。不得让模型输出 HTML、CSS、JavaScript、URL 或未注册互动组件。

成熟项目借鉴：采用 OpenMAIC 的生成、编辑、持久化和端到端测试分层，以及 H5P 的内容参数、组件库和固定运行时分层；不复制其多人课堂或媒体能力。[OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) [H5P 技术概览](https://h5p.org/technical-overview)

## 3. P0：发布可信度（必须完成）

### 3.1 P0-0：Agent 与工作流目录重构（先做）

目标是在**保持现有顶层目录不变**的前提下完成分层内重构：让 `agents/` 明确承担模型调用、Agent 节点和工作流编排；在 `api/`、`services/`、`db/`、`core/` 等现有层级内部按领域聚合。不要再让 `agents/workflow.py` 看起来像所有领域的唯一总工作流，也不要让同一领域在同一层内的文件无规则散落。

**不可突破的前提：重构期间与完成后，现有五类学习文档的生成、审核、Claim、发布、API 响应和 Markdown 阅读行为必须保持一致。** 这是路径重构，不是学习文档能力重写；课件工作流新增或迁移失败时，也不得影响学习文档链路。

目标目录：

```text
backend/app/agents/
├── shared/                              # 跨工作流可复用的纯能力
│   ├── policies.py
│   ├── validators.py
│   └── retrieval.py
├── resource_workflows/
│   ├── learning_documents/              # 现有五类文本学习文档的独立工作流
│   │   ├── workflow.py                  # 原 agents/workflow.py 的正式归属
│   │   ├── state.py
│   │   ├── planner_agent.py
│   │   ├── generator_agent.py
│   │   ├── reviewer_agent.py
│   │   └── claim_review_agent.py
│   └── interactive_courseware/          # 互动课件的独立工作流
│       ├── workflow.py                  # 准入→快照→规格→场景→审核→渲染→发布
│       ├── state.py                     # CoursewareWorkflowState
│       ├── planner_agent.py
│       ├── scene_composer_agent.py
│       ├── quality_reviewer_agent.py
│       ├── validators.py
│       └── contracts.py
├── learning_agents/                     # 不属于资源生产工作流的学习闭环 Agent
│   ├── diagnosis_agent.py
│   ├── feedback_agent.py
│   ├── feedback_policy_agent.py
│   └── tutor_agent.py
```

`learning_agents/` 与 `resource_workflows/` 并列：前者服务诊断、反馈与答疑，后者服务可持久化的资源生成工作流。不要为了目录整齐而把反馈、Tutor 或报告硬塞进学习文档/课件工作流。

“学习文档 / 课件”只属于**资源生成域**，不是整个系统的全部功能。保留现有后端顶层，只在层内按完整业务域收敛子目录（内部文件可以逐步迁移，外部只依赖各子包公开入口）：

```text
backend/app/
├── api/
│   ├── auth/                            # 登录、用户身份与访问控制
│   ├── users/                           # 用户账户与管理
│   ├── onboarding/                      # 初始建档与问卷流程
│   ├── learners/                        # 学习画像、问卷、学习历史、诊断
│   ├── knowledge/                       # 知识库、检索与素材管理
│   ├── generation/                      # 学习文档生成任务与进度
│   ├── learning_documents/              # 学习文档详情、阅读、下载
│   ├── courseware/                      # 课件创建、SSE、重试、预览、下载
│   ├── feedback/                        # 生成后反馈、反馈闭环与再生成
│   ├── tutor/                           # Tutor 会话与资源答疑
│   ├── reports/                         # 学习报告与评估结果
│   ├── reviews/                         # 人工审核与审核查询
│   ├── runs/                            # 工作流运行记录与事件查询
│   ├── resource_library/                # 跨资源领域的只读聚合
│   └── admin/                           # 仅管理员能力
├── services/
│   ├── auth/                            # 身份与权限门面
│   ├── users/                           # 用户门面
│   ├── onboarding/                      # 初始建档门面
│   ├── learners/                        # 画像、问卷、历史、诊断门面
│   ├── knowledge/                       # 知识库与入库门面
│   ├── generation/                      # 学习文档任务与工作流调用
│   ├── learning_documents/              # 学习文档发布与读取
│   ├── courseware/                      # 调用课件 workflow、持久化协调、发布门面
│   ├── feedback/                        # 反馈及再生成闭环
│   ├── tutor/                           # 答疑会话门面
│   ├── reports/                         # 报告与评估门面
│   ├── reviews/                         # 审核门面
│   ├── runs/                            # 运行状态/事件查询门面
│   └── resource_library/                # 跨资源只读投影
├── db/
│   ├── users/                           # 用户仓储
│   ├── learners/                        # 画像、问卷、诊断、历史仓储
│   ├── knowledge/                       # 知识与向量目录仓储
│   ├── generation/                      # 生成任务仓储
│   ├── learning_documents/              # 学习文档仓储
│   ├── courseware/                      # jobs/specs/scenes/reviews/artifacts
│   ├── feedback/                        # 反馈及闭环仓储
│   ├── tutor/                           # 会话仓储
│   ├── audit/                           # 工作流运行、审核事件与 Claim 审计
│   └── shared/                          # 数据库会话、通用基类与迁移基础设施
├── core/
│   ├── llm/                             # 模型传输、网关、结构化输出
│   ├── retrieval/                       # 检索、证据与向量检索能力
│   ├── security/                        # 通用安全与授权支撑
│   ├── storage/                         # 文件与对象存储能力
│   ├── events/                          # 事件、幂等与可观测性
│   └── courseware/                      # 课件 renderer/runtime/security/packaging
└── models/
    ├── auth/                            # 身份与访问 DTO
    ├── users/                           # 用户 DTO
    ├── learners/                        # 画像、问卷、诊断、历史 DTO
    ├── knowledge/                       # 知识库和检索 DTO
    ├── generation/                      # 生成任务 DTO
    ├── learning_documents/              # 学习文档 DTO
    ├── courseware/                      # 课件公开 DTO/契约
    ├── feedback/                        # 反馈及闭环 DTO
    ├── tutor/                           # 答疑 DTO
    ├── reports/                         # 报告与评估 DTO
    ├── reviews/                         # 审核 DTO
    └── shared/                          # 跨领域基础契约

frontend/src/features/
├── auth/                                # 登录、注册与会话界面
├── onboarding/                          # 初始建档界面
├── learners/                            # 画像、问卷、诊断、历史界面
├── knowledge/                           # 知识库界面
├── generation/                          # 学习文档生成与进度界面
├── learning-documents/                  # 学习文档阅读界面
├── courseware/                          # SourceSelector、任务进度、Viewer、API client
├── feedback/                            # 反馈与再生成界面
├── tutor/                               # Tutor 界面
├── reports/                             # 报告与评估界面
└── resource-library/                    # 跨资源列表与路由选择
```

资源生成域的边界是：`generation` 负责学习文档生成任务，`learning_documents` 负责五类文本学习文档的读取，`courseware` 负责互动课件独立工作流；课件同样是学习资源，但不是学习文档。`feedback`、`tutor`、`reports` 是生成后的学习闭环，不应被放进资源生成或课件目录。认证、学习者和知识库也保持独立。

结构本身不保证功能不受影响；以下兼容约束才是迁移的安全边界：公开 HTTP 路径、请求/响应 DTO、状态码、认证依赖、容器 provider 名称、数据库表名、存储路径和事件 payload 默认保持不变。仅改变内部 Python/Vue 导入路径；任何确需变更的公开契约必须另行版本化，不能夹带在目录迁移中。以上是层内目标边界，不要求首个提交一次性移动所有物理文件。迁移期间由现有层级内的旧路径保留兼容转发；禁止复制两份会逐渐分叉的业务实现，也不得新增新的顶层领域目录。

迁移规则：

1. **先固化基线，不先移动文件**：建立全功能域清单（认证、学习者、知识库、生成、资源、课件、反馈、Tutor、报告、资源库），并为受影响域记录公开导入、API 响应 fixture、错误码和关键 artifact 哈希；资源工作流额外记录节点顺序与路由。补齐端到端回归后才允许开始迁移。
2. 先建立新包与明确导出，再逐步迁移实现；第一阶段 `agents/workflow.py` 必须保留为兼容转发，所有旧导入和原容器注册均继续可用，不能要求其他模块同步修改。
3. 学习文档节点必须原样迁移并保持输入/输出契约、路由顺序、错误码、Prompt 版本和 API 不变；每个迁移提交只做一个节点或一个入口的路径调整，禁止同时修改 Prompt、依赖注入或业务逻辑。
4. 每迁移一个节点/入口，必须先运行学习文档单元、工作流、API、Claim 与 Markdown 阅读回归；任一差异立即停止后续迁移，恢复到兼容转发路径，定位后以独立提交修复。
5. 新建 `interactive_courseware/workflow.py`：工作流节点调用课件专用 Agents 和 `core/courseware` 的确定性能力；`CoursewareService` 只创建/恢复任务、注入仓储与工作流依赖、执行工作流、提供查询/发布接口。课件依赖注入不得改写学习文档容器实例或工作流注册。
6. 在每个既有层级内按领域迁移 API、Service、模型、仓储、渲染/安全能力与前端功能模块：先创建层内子包的公开入口和适配层，再移动一个职责组；同一职责在任一时刻只能有一个真实实现。
7. `courseware` service 不得再定义工作流节点、Prompt 或模型调用；课件 presentation 不得访问数据库或模型；跨领域的资源库只读聚合不得反向拥有生成逻辑；共享模块不依赖具体资源领域。
8. 所有旧导入先改为公开包入口，再删除兼容转发；兼容层至少跨越一次完整发布验证周期。删除前使用静态导入扫描阻止新代码重新导入旧路径，并重新运行全量学习文档与课件回归。

迁移闸门：

```text
全域行为基线通过
  → 各层内子包公开入口 + 兼容转发
  → 认证/学习者/知识库等基础域按层归类 + 回归
  → 学习文档 workflow/节点单元迁移 + 主链回归
  → 课件 workflow/节点迁移 + 双链回归
  → 反馈/Tutor/报告等学习闭环按层归类 + 回归
  → 资源库聚合与前端 feature 模块迁移
  → 完整发布验证周期
  → 删除旧路径兼容层
```

验收：学习文档和课件各自有唯一、可发现的 `workflow.py` 与各层内子包公开入口；在兼容期内旧入口与新入口对学习文档和课件结果等价；迁移期间学习文档回归零失败、课件回归通过、导入兼容测试通过。只有在完整发布验证周期无差异后，才允许删除 `agents/workflow.py` 及旧层级兼容入口。

### 3.2 真实模型生产就绪检查与可观测性

- 在部署前使用脱敏冻结快照执行课程设计、两个场景生成和教学审核，确认模型、密钥、超时和结构化输出可用。
- 记录模型、prompt 版本、输入/输出哈希、耗时、token、重试、fallback 原因；不得记录源正文或密钥。
- 指标：规格成功率、场景成功率、schema 修复率、来源拒绝率、fallback 率、时延、成本。
- 部署完成后全局开启 `courseware_ai_enabled`：所有通过现有权限校验、能够创建课件的用户均直接使用 AI 课件生成。
- 监控仅用于故障定位和全局回退决策；单次模型失败继续使用该场景的确定性 fallback，不因用户身份限制功能。

验收：可从任务详情回答每个场景是否调用模型、为何 fallback、来源是否完整、耗时与成本。

### 3.3 固定评测集与质量门

- 新增 `backend/tests/fixtures/courseware/evals/`；首批 30 组脱敏 fixture，逐步扩展至 50 组。
- 覆盖短/长讲义、多资源、缺少测验、重复/冲突/空来源、超长内容、模型超时/限流/空输出/截断、未知组件/来源块、单场景失败、重启恢复与重复幂等请求。
- 硬门：零未知来源块、零危险输出、零未知组件、必需场景不可缺失。
- 趋势指标：schema 成功率、无 fallback 成功率、人工抽检来源正确率、成本、时延；阈值版本化保存。

验收：任一硬门失败不得发布；评测结果在 CI 可重复比较。

### 3.4 真正场景级工作器与局部返工

每个场景必须成为独立持久化任务：

```text
scene_id + input_snapshot_hash + attempt
  → compose Agent
  → schema/source rule gate
  → advisory quality Agent
  → approved | revision_required | failed
```

- 为场景持久化 `input_snapshot_hash`、`agent_version`、`review_instruction`、`approved_at`，并提供数据库迁移。
- `retry_scene` 仅重跑目标场景，复用其他输入未变化且已批准场景；不重新请求整课模型内容。
- 必需场景失败进入 `human_review` / `revision_requested`；可选场景可跳过，但 UI、artifact 和事件必须解释原因。
- fan-in 只合并同一规格、顺序完整、输入哈希一致且已批准的必需场景。
- 使用租约/outbox 或等价机制，避免重启、重复消费者和并发重试造成双发布。

验收：故障注入后，只重试一页时其他场景的内容哈希、attempt 和模型调用次数不变。

### 3.5 浏览器自动化与无障碍回归

- 引入 Playwright 或同等浏览器驱动；保留现有 Edge 启动冒烟。
- 同时验证 sandbox 预览和离线 artifact：无外联、无 CSP 违规、导航、步骤、答题反馈、进度消息。
- 覆盖 Tab / Enter / Space、焦点、标题层级、控件标签、阅读顺序、错误反馈、320px 和桌面宽度。
- 验证伪造 `postMessage` 不能改变宿主 UI 状态。

验收：浏览器失败阻断发布候选；CI 输出截图、控制台错误和失败组件名。

## 4. P1：互动与审核体验

### 4.1 ComponentCatalog v1

每个组件必须同步拥有：Pydantic schema、renderer、runtime 行为、来源映射规则、fixture、无障碍断言和版本迁移。新增组件不能只靠修改 Prompt。

| 批次 | 组件 | 本轮策略 |
| --- | --- | --- |
| 1 | `callout`、`key_point`、`compare`、`ordered_steps`、`recap` | 实现并完成来源粒度与浏览器测试 |
| 2 | `single_choice`、`multiple_choice`、`ordering`、`matching` | 在评测集稳定后逐项开放 |
| 3 | `timeline`、`process_flow`、`decision_tree`、`scenario_branch` | 仅立接口和 fixture 需求，不在本轮全部实现 |

题干、选项、答案、解析以及流程/分支节点均须单独映射来源块。图片、音频、视频仅在平台资产注册、审核和离线打包准备好后再评估；模型不可提供媒体 URL。

### 4.2 审核与修订工作台

- 展示课程目标、场景顺序、来源块、审核问题、浏览器结果和成本摘要。
- 支持单场景：接受 fallback、请求模型按指令修订、改用模板、标记为可选跳过。
- 每次修改创建 `scene_revision`，记录操作者、时间、原因、前后哈希；普通学习者不能读取 Prompt、原始输出或内部备注。

验收：审核者不编辑 HTML 即可定位来源问题、修订一个场景并发布新版，且全程可审计。

## 5. P2：受控体验增强

在 P0/P1 通过后增加主题 token、封面/章节过渡、受控 SVG 图示、进度本地保存、断点恢复、打印版和低动效模式。

预算：单文件 HTML 默认 ≤ 1.5 MB；基准设备首屏 ≤ 2 秒；单场景文本遵守既定阅读负荷。超过预算时压缩或拆分组件，不降低安全策略。

## 6. 实施顺序与文件边界

```text
1. 全功能域清单、行为基线、各层子包公开入口与兼容层
2. 认证/学习者/知识库等基础域归类 + 回归
3. 学习文档与课件 `workflow.py` 分域迁移 + 双链回归
4. 反馈/Tutor/报告/资源库与前端 feature 分域迁移 + 回归
5. 课件 scene worker、评测集、生产就绪检查与浏览器质量门
6. ComponentCatalog v1、审核工作台、主题与断点恢复
```

- `agents/resource_workflows/learning_documents/`：现有五类文本学习文档的工作流和节点。
- `agents/resource_workflows/interactive_courseware/`：课件工作流、Prompt、LLM 调用、Agent 契约与 AI 审核。
- `agents/learning_agents/`：诊断、反馈策略、反馈处理和 Tutor 等非资源生产 Agent。
- `api/<domain>/`、`services/<domain>/`、`db/<domain>/`、`core/<domain>/`、`models/<domain>/`：保持现有分层，在层内以领域子包作为唯一公开入口；迁移完成前由该层旧路径转发到新子包。
- `services/courseware/`：调用课件工作流、持久化、规则审核、发布和谱系；不编排节点。
- `core/courseware/`：renderer、runtime、安全、离线打包；不访问数据库或模型。
- `frontend/src/features/<domain>/`：按领域组织 API client、composable、组件和页面协作代码；跨领域资源列表仅保留在 `resource-library` feature。
- 现有学习文档工作流、Claim 审核和 Markdown 阅读链不得改动；任何跨域修改先补回归测试。

## 7. 本轮最终验收

1. 所有功能域均已在既有层级内拥有明确归属；学习文档与课件工作流均迁移至各自专用目录，兼容层删除前的导入检查和全量回归均通过。
2. 部署前生产就绪检查通过后，全局启用 LLM 课件生成；所有具备现有课件创建权限的用户均可直接使用。
3. 一页失败只能影响该页；必需页未批准不能发布，可选页跳过有明确提示。
4. 每个发布块和互动参数均可追溯到冻结来源块。
5. 生成产物在预览和离线环境均通过安全、交互、键盘和无障碍回归。
6. 现有五类学习文档的生成、审核、API 和阅读回归全部通过。
