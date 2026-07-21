# 总体架构文档

> 项目编号：XH-202630  
> 项目名称：领域知识个性化生成与多智能体协同决策系统  
> 文档定位：团队协作时的统一架构口径与模块边界  
> 当前阶段：架构搭建与并行开发准备

## 使用原则

本文档描述的是当前阶段的架构基线，用于统一分层、路径和协作边界，不是不可更改的最终定稿。并行开发中如果出现职责重叠、实现冲突或更优方案，允许按实际情况调整实现方式；只要保持整体方向一致、接口口径清晰、模块职责可追踪即可。

本文档只覆盖基础架构和基础约束，后续实现可以在不破坏职责清晰的前提下修改、替换或重构具体代码。

## 1. 架构结论

当前项目架构基本符合开发初期标准：前端、后端、知识库、初始化脚本、部署文档已经分层；后端内部也已按 API 层、服务层、Agent 层、基础设施层、数据访问层拆分，适合多人并行开发。

现阶段需要统一遵守以下边界：

| 层级 | 目录 | 核心职责 | 不应承担的职责 |
|------|------|----------|----------------|
| 前端可视化层 | `frontend/src` | 页面交互、状态管理、图表展示、API 调用封装 | 不写业务判定规则，不直接拼后端存储路径 |
| API 路由层 | `backend/app/api` | HTTP 参数接收、Pydantic 校验、状态码、响应模型、后端接口骨架、联调入口 | 不写复杂业务逻辑，不直接操作数据库 |
| 业务服务层 | `backend/app/services` | 组织完整业务用例，串联仓库、Agent、报告、反馈逻辑 | 不直接处理 HTTP 请求对象 |
| 多智能体层 | `backend/app/agents` | LangGraph 工作流、Agent 节点、共享状态、协同决策 | 不负责数据库细节和前端展示格式 |
| 基础设施层 | `backend/app/core` | LLM、Embedding、向量库、知识库读取、文件存储 | 不承载业务流程编排 |
| 数据访问层 | `backend/app/db` | ORM、仓库接口、内存/SQLite/PostgreSQL 实现 | 不写业务规则和 Agent 推理逻辑 |
| 数据模型层 | `backend/app/models` | Pydantic 请求/响应/领域数据结构 | 不写持久化与外部调用逻辑 |
| 脚本层 | `scripts` | 初始化数据库、知识库入库、开发辅助任务 | 不依赖当前命令执行目录 |
| 文档层 | `docs` | 需求、功能、API、部署、任务拆分、验收标准 | 不记录与代码冲突的正式路径 |

## 2. 运行时路径标准

本项目已统一路径口径：

| 类型 | 标准路径 | 说明 |
|------|----------|------|
| 后端运行根目录 | `backend/` | 配置、数据库、日志、生成资源的基准目录 |
| 环境变量文件 | `backend/.env` | `app/config.py` 固定读取该文件 |
| SQLite 数据库 | `backend/data/domain_knowledge.db` | `DB_TYPE=sqlite` 时使用 |
| 生成资源 | `backend/data/generated_resources/` | 文本、PPT、PDF、视频、音频、图片资源统一落点 |
| 向量库索引 | `backend/chroma_db/` | ChromaDB 持久化目录 |
| 日志 | `backend/logs/` | 后端日志目录 |
| 原始知识库 | `knowledge_base/` | 进入版本控制，作为可复现数据源 |
| 示例数据 | `examples/` | 初始化和演示使用 |

禁止新增 `backend/app/data/`、项目根目录 `data/` 作为正式运行目录。

## 3. 后端调用链

```text
frontend
  ↓ HTTP
backend/app/api
  ↓ 调用服务
backend/app/services
  ├─ learner/report/feedback 业务逻辑
  ├─ generation_service 调用 Agent 工作流
  ↓
backend/app/agents
  ├─ diagnosis: 学情诊断
  ├─ retriever: 知识检索
  ├─ generator: 内容生成
  ├─ reviewer: 审核纠偏
  └─ workflow: 工作流编排与重试决策
  ↓
backend/app/core + backend/app/db
  ├─ LLM / Embedding / ChromaDB / 文件存储
  └─ Repository / ORM / SQLite or Memory
```

## 4. 前端调用链

```text
frontend/src/views
  ↓ 用户操作
frontend/src/api/index.js
  ↓ Axios
backend API
  ↓ JSON 响应
frontend/src/components
  ├─ AgentVisualization.vue
  ├─ ReportChart.vue
  └─ ResourceViewer.vue
```

当前代码可参考页面：`HomeView.vue`、`GenerateView.vue`、`FeedbackView.vue`、`ReportView.vue`。  
当前代码可参考组件：`AgentVisualization.vue`、`ReportChart.vue`、`ResourceViewer.vue`。  
`LearnerView.vue`、`ProfileForm.vue`、`TraceTimeline.vue` 属于功能基线中的可建设项，后续可以按实际需要新增、合并或替换。

## 5. API 建设状态口径

`docs/api.md` 同时承担设计接口和开发契约的作用。为避免把当前代码误认为最终交付，接口建设状态分为两类：

| 状态 | 含义 | 验收方式 |
|------|------|----------|
| 当前参考路由 | 当前代码中存在对应 FastAPI 路由，可作为早期联调参考 | 总架构组牵头接口测试和前后端联调验证，后续仍可替换 |
| 设计待建设 | 为后续开发保留的设计接口，代码可能尚未接入 | 总架构组先补路由骨架和模型，再由对应业务组补服务实现 |

当前参考路由：

| 方法 | 路径 | 负责模块 |
|------|------|----------|
| GET | `/` | 总架构组 |
| POST | `/api/learner/profile` | 总架构组负责 API 联调，知识库数据库组负责画像服务与仓库能力 |
| GET | `/api/learner/profile/{learner_id}` | 总架构组负责 API 联调，知识库数据库组负责画像服务与仓库能力 |
| POST | `/api/generate/` | 总架构组负责 API 联调，多智能体开发组负责生成服务与 Agent 工作流 |
| POST | `/api/feedback/` | 总架构组负责 API 联调，多智能体开发组负责反馈决策，知识库数据库组配合持久化 |
| GET | `/api/report/{learner_id}` | 总架构组负责 API 联调，前端可视化+功能测试组负责展示验收，后端服务配合 |

设计待建设接口包括：系统统计、画像列表、画像删除、画像 PATCH、资源列表、文件下载、知识库信息。

## 6. 协作规则

| 规则 | 标准 |
|------|------|
| 接口优先 | 修改 API 请求/响应字段前，先更新 `docs/api.md` 与 `backend/app/models/schemas.py` |
| API 牵头 | 后端 API 路由骨架、状态码、响应模型和联调验收由总架构组负责 |
| 模型统一 | 前后端共享字段名以 Pydantic schema 为准，前端不得自定义另一套字段语义 |
| 业务下沉 | 路由只做协议转换，业务规则放在 `services/` 或 `agents/` |
| 数据隔离 | 仓库实现放在 `db/`，服务层通过接口或工厂调用 |
| 路径统一 | 所有运行时文件只写入 `backend/data/`、`backend/chroma_db/`、`backend/logs/` |
| 测试伴随 | 新增服务、Agent 节点、仓库实现、前端关键流程时必须补对应测试或测试说明 |

## 7. 当前架构风险

| 风险 | 等级 | 说明 | 建议 |
|------|------|------|------|
| 文档接口多于代码接口 | 中 | 设计阶段允许，但必须标清建设状态 | `docs/api.md` 持续维护接口建设状态 |
| 功能基线页面多于实际页面 | 中 | 设计阶段允许，但可能导致任务分配误解 | 在任务文档中标清参考文件和开发任务 |
| Agent 与服务层边界后续可能膨胀 | 中 | 生成、反馈、审核逻辑容易互相耦合 | 由 `GenerationService` 只负责用例编排，Agent 专注节点逻辑 |
| 测试覆盖仍偏轻 | 中 | 当前以服务和 Agent 基础测试为主 | 功能测试组补端到端场景和接口测试 |

## 8. 架构验收标准

进入正式并行开发前，总架构组需要确认：

- `README.md`、`docs/deployment.md`、`backend/.env.example` 的路径口径一致。
- `docs/api.md` 中每个接口都标明接口建设状态。
- 规划接口至少有明确的路由骨架设计、请求/响应模型和负责业务组。
- API 联调由总架构组收口，前端组、Agent 组、数据库组按问题归属修复。
- 每个新增模块都有明确所属小组、输入、输出和验收标准。
- 后端新增业务遵守 `api -> services -> agents/core/db` 的调用方向。
- 前端新增页面只通过 `frontend/src/api/index.js` 调用后端。
- 初始化脚本可以从项目根目录执行。
