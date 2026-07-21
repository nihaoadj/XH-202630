# 开发任务分工文档

> 文档用途：把当前架构拆成 4 个可并行开发的任务包，便于分发给不同成员。  
> 分工口径：总架构 1 人/组，多智能体开发 1 人/组，知识库数据库 1 人/组，前端可视化+功能测试 1 人/组。

## 使用原则

本分工是开发初期的方向性分工，不是不可变更的强制边界。并行开发中必然会出现接口、数据、Agent、前端展示等边界重叠的情况，实际执行时应根据进度、能力和问题归属灵活调整；只要大体遵守“架构/API 收口、Agent 能力、数据知识库、前端可视化测试”四条主线即可。

本文档只覆盖项目基础功能和基础协作口径。后续具体开发时，可以根据比赛需求、技术验证结果和团队实现情况，对功能、模块和代码实现进行修改、替换或重构。目前架构的主要目的，是让职责边界更清晰、协作起点更明确，而不是限制后续实现方式。

## 0. 文档边界

本文件只回答“谁来做、做哪些开发任务、输出什么、如何验收”。  
系统功能范围和用户侧能力见 `docs/features.md`，不要在本文重复维护功能说明细节。

## 1. 分工总览

| 小组 | 主要目标 | 主要目录 | 交付物 |
|------|----------|----------|--------|
| 总架构组 | 维护架构边界、接口契约、后端 API 骨架、API 联调、配置部署、文档一致性 | `backend/app/main.py`、`backend/app/api/`、`backend/app/config.py`、`backend/app/models/schemas.py`、`docs/`、`Dockerfile` | 架构文档、API 契约、后端路由骨架、接口联调记录、部署可运行、路径口径统一 |
| 多智能体开发组 | 实现生成闭环、Agent 协同、幻觉防控、反馈决策 | `backend/app/agents/`、`backend/app/services/generation_service.py`、`backend/app/services/feedback_service.py`、`backend/app/core/llm.py` | 可运行 Agent 工作流、生成结果、执行轨迹、审核报告 |
| 知识库数据库组 | 实现画像/资源数据管理、知识库入库、向量检索、仓库持久化 | `backend/app/db/`、`backend/app/core/knowledge_base.py`、`backend/app/core/vector_store.py`、`backend/app/core/embeddings.py`、`scripts/` | 数据表、仓库实现、知识库索引、初始化脚本 |
| 前端可视化+功能测试组 | 实现用户界面、图表展示、前端 API 调用封装、端到端测试 | `frontend/src/`、`backend/tests/`、后续 `frontend/tests/` | 页面、组件、图表、前端联动、测试报告 |

## 2. 总架构组任务包

### 2.1 职责边界

- 负责系统分层、模块边界、目录命名、配置管理。
- 负责 `docs/api.md` 中请求/响应字段的最终口径。
- 负责 `backend/app/models/schemas.py` 的公共 Pydantic 模型。
- 负责 `backend/app/api/` 的后端 API 路由骨架、统一状态码、统一错误响应和响应模型绑定。
- 牵头 API 联调：组织前端组、Agent 组、数据库组按接口契约完成联调和问题归因。
- 负责部署脚本、Dockerfile、README 与部署文档一致性。
- 负责代码合并时检查是否跨层调用混乱。

### 2.2 架构参考文件

以下文件仅作为架构理解与后续开发参考，不作为最终交付依据；后续开发允许在保持职责边界和接口契约清晰的前提下修改或替换。

| 文件 | 参考用途 |
|------|----------|
| `backend/app/main.py` | FastAPI 应用入口、路由注册、生命周期管理参考 |
| `backend/app/api/` | 后端 API 路由拆分方式参考 |
| `backend/app/config.py` | 配置项、路径解析、`.env` 加载方式参考 |
| `backend/app/models/schemas.py` | Pydantic 请求/响应模型集中定义参考 |
| `Dockerfile` | Docker 构建上下文与后端启动方式参考 |
| `README.md`、`docs/deployment.md` | 启动顺序、路径口径和部署说明参考 |

### 2.3 开发任务清单

| 优先级 | 任务 | 输出 |
|--------|------|------|
| P0 | 搭建并维护 FastAPI 应用入口、路由注册和生命周期管理 | `backend/app/main.py` |
| P0 | 搭建并维护后端 API 路由目录结构 | `backend/app/api/` |
| P0 | 搭建并维护配置管理、`.env` 加载和运行时路径解析 | `backend/app/config.py` |
| P0 | 搭建并维护公共 Pydantic 请求/响应模型 | `backend/app/models/schemas.py` |
| P0 | 维护 API 建设清单，标明设计、开发、联调、验收状态 | `docs/api.md` 状态更新 |
| P0 | 搭建设计接口的后端路由骨架 | `backend/app/api/` 中新增路由与占位实现 |
| P0 | 为设计接口补 Pydantic 请求/响应模型 | `schemas.py` 新增模型 |
| P0 | 约束错误响应格式和 HTTP 状态码 | API 文档与路由实现一致 |
| P0 | 牵头 API 联调并记录问题归属 | 接口联调清单、问题归因和修复状态 |
| P0 | 维护 Docker、README、部署文档和路径口径一致 | `Dockerfile`、`README.md`、`docs/deployment.md` |
| P1 | 增加接口版本策略，如 `/api/v1` 或文档版本号 | 架构决策记录 |
| P1 | 制定代码提交检查清单 | PR/合并检查标准 |

### 2.4 验收标准

- 新增接口前必须先能在 `docs/api.md` 找到字段定义。
- 新增后端接口时，总架构组先完成路由、请求/响应模型、状态码和最小可运行返回；业务实现由对应业务组接入服务层。
- API 联调问题由总架构组统一收口，判定属于接口契约、前端调用、服务逻辑、Agent 流程还是数据层能力。
- `schemas.py` 不包含数据库会话、文件读写、LLM 调用等逻辑。
- 任何路径变更都同步更新 `README.md`、`docs/deployment.md`、`backend/.env.example`。

## 3. 多智能体开发组任务包

### 3.1 职责边界

- 负责 `diagnosis -> retriever -> generator -> reviewer -> decision` 的完整闭环。
- 负责 Agent 共享状态字段与 LangGraph 节点衔接。
- 负责幻觉防控：RAG 约束、审核评分、来源引用、失败重生成。
- 负责反馈决策：根据正确率更新画像，形成降维/保持/进阶逻辑。

### 3.2 架构参考文件

以下文件仅作为多智能体协同架构参考，不作为最终 Agent 逻辑交付依据；后续可以重写节点实现、Prompt、状态字段和工作流策略，但需要保持对外接口契约清晰。

| 文件 | 参考用途 |
|------|----------|
| `backend/app/agents/state.py` | 工作流共享状态结构参考 |
| `backend/app/agents/workflow.py` | LangGraph 工作流编排和重试决策参考 |
| `backend/app/agents/diagnosis.py` | 学情诊断 Agent 节点参考 |
| `backend/app/agents/retriever.py` | 知识检索 Agent 节点参考 |
| `backend/app/agents/generator.py` | 内容生成 Agent 节点参考 |
| `backend/app/agents/reviewer.py` | 审核纠偏 Agent 节点参考 |
| `backend/app/services/generation_service.py` | 生成业务用例编排参考 |
| `backend/app/services/feedback_service.py` | 反馈决策业务参考 |

### 3.3 开发任务清单

| 优先级 | 任务 | 输出 |
|--------|------|------|
| P0 | 设计并实现 Agent 共享状态结构 | `backend/app/agents/state.py` |
| P0 | 设计并实现 LangGraph 工作流编排 | `backend/app/agents/workflow.py` |
| P0 | 实现学情诊断 Agent | `backend/app/agents/diagnosis.py` |
| P0 | 实现知识检索 Agent | `backend/app/agents/retriever.py` |
| P0 | 实现内容生成 Agent | `backend/app/agents/generator.py` |
| P0 | 实现审核纠偏 Agent | `backend/app/agents/reviewer.py` |
| P0 | 实现生成业务用例编排 | `backend/app/services/generation_service.py` |
| P0 | 实现反馈决策业务 | `backend/app/services/feedback_service.py` |
| P0 | 稳定 Agent 输入输出字段 | 与 `GenerateResponse.trace/report/resources` 对齐 |
| P0 | 强化 reviewer 的审核指标 | `hallucination_score`、`coverage_rate`、`difficulty_match` |
| P0 | 让 source_refs 覆盖每个资源 | 每条资源可追溯到知识片段 |
| P0 | 补 LLM 异常降级策略 | API Key 缺失、模型超时、返回格式异常时有明确错误 |
| P1 | 支持多轮重生成策略 | 达到最大迭代次数后输出风险说明 |
| P1 | 增加 Agent trace 时间戳和节点状态 | 前端可视化可直接消费 |

### 3.4 验收标准

- 调用 `POST /api/generate/` 能返回 `resources`、`trace`、`report`。
- 每个 Agent 节点只读写共享状态中的约定字段。
- reviewer 不通过时，工作流能按最大迭代次数停止，不会无限循环。
- 没有 LLM Key 时，测试可以通过 mock 或降级路径运行。

## 4. 知识库数据库组任务包

### 4.1 职责边界

- 负责学习者画像、生成资源、反馈数据的持久化方案。
- 负责知识库文档加载、切片、向量化、检索。
- 负责 SQLite/PostgreSQL/内存仓库实现的一致接口。
- 负责初始化脚本可重复执行。

### 4.2 架构参考文件

以下文件仅作为数据层和知识库架构参考，不作为数据库模型、仓库实现或入库脚本的最终交付依据；后续可以替换实现，但需要保持仓库接口、路径标准和初始化流程可复现。

| 文件 | 参考用途 |
|------|----------|
| `backend/app/db/models.py` | ORM 模型组织方式参考 |
| `backend/app/db/database.py` | 数据库连接、会话和初始化方式参考 |
| `backend/app/db/learner/` | 学习者画像仓库拆分方式参考 |
| `backend/app/db/resource/` | 生成资源仓库拆分方式参考 |
| `backend/app/core/knowledge_base.py` | 知识库文档加载与切片参考 |
| `backend/app/core/vector_store.py` | ChromaDB 向量库封装参考 |
| `backend/app/core/embeddings.py` | Embedding 模型加载参考 |
| `scripts/init_db.py` | 数据库初始化脚本参考 |
| `scripts/ingest_knowledge.py` | 知识库入库脚本参考 |

### 4.3 开发任务清单

| 优先级 | 任务 | 输出 |
|--------|------|------|
| P0 | 设计并实现 ORM 模型和数据库会话管理 | `backend/app/db/models.py`、`backend/app/db/database.py` |
| P0 | 设计并实现学习者画像仓库接口和实现 | `backend/app/db/learner/` |
| P0 | 设计并实现生成资源仓库接口和实现 | `backend/app/db/resource/` |
| P0 | 实现知识库文档加载、切片和元数据处理 | `backend/app/core/knowledge_base.py` |
| P0 | 实现向量库封装和语义检索 | `backend/app/core/vector_store.py` |
| P0 | 实现 Embedding 模型加载与配置 | `backend/app/core/embeddings.py` |
| P0 | 实现数据库初始化脚本 | `scripts/init_db.py` |
| P0 | 实现知识库入库脚本 | `scripts/ingest_knowledge.py` |
| P0 | 完成反馈记录持久化模型和仓库 | feedback repository 与测试 |
| P0 | 实现资源列表接口所需查询能力 | 按 learner、type、difficulty 查询 |
| P0 | 实现知识库信息统计 | 文档数量、切片数量、更新时间 |
| P0 | 保证初始化脚本幂等 | 重复执行不产生脏数据或重复索引 |
| P1 | PostgreSQL 兼容验证 | 生产环境迁移说明 |
| P1 | 补数据备份/清理脚本 | 演示前可重置数据 |

### 4.4 验收标准

- `DB_TYPE=sqlite` 时，数据写入 `backend/data/domain_knowledge.db`。
- 生成资源文件写入 `backend/data/generated_resources/`。
- 知识库索引写入 `backend/chroma_db/`。
- 仓库接口在 memory 与 sqlite 两种模式下行为一致。

## 5. 前端可视化+功能测试组任务包

### 5.1 职责边界

- 负责前端页面、组件、交互体验、图表可视化。
- 负责 `frontend/src/api/index.js` 中的前端调用封装，按总架构组提供的 API 契约联动页面。
- 负责端到端流程测试和演示验收。
- 负责把后端 `trace`、`report`、`resources` 转成用户可读展示。

### 5.2 架构参考文件

以下文件仅作为前端页面和组件拆分参考，不作为最终界面、交互和测试交付依据；后续可以重构页面结构和组件实现，但需要保持 API 调用统一封装、核心流程可演示。

| 文件 | 参考用途 |
|------|----------|
| `frontend/src/views/HomeView.vue` | 首页入口和导航参考 |
| `frontend/src/views/GenerateView.vue` | 资源生成页面参考 |
| `frontend/src/views/FeedbackView.vue` | 学习反馈页面参考 |
| `frontend/src/views/ReportView.vue` | 学情报告页面参考 |
| `frontend/src/components/AgentVisualization.vue` | Agent 轨迹展示组件参考 |
| `frontend/src/components/ReportChart.vue` | 报告图表组件参考 |
| `frontend/src/components/ResourceViewer.vue` | 资源内容展示组件参考 |
| `frontend/src/api/index.js` | 前端 API 调用封装参考 |

### 5.3 开发任务清单

| 优先级 | 任务 | 输出 |
|--------|------|------|
| P0 | 设计并实现首页入口和导航 | `frontend/src/views/HomeView.vue` |
| P0 | 设计并实现资源生成页面 | `frontend/src/views/GenerateView.vue` |
| P0 | 设计并实现学习反馈页面 | `frontend/src/views/FeedbackView.vue` |
| P0 | 设计并实现学情报告页面 | `frontend/src/views/ReportView.vue` |
| P0 | 设计并实现 Agent 轨迹展示组件 | `frontend/src/components/AgentVisualization.vue` |
| P0 | 设计并实现报告图表组件 | `frontend/src/components/ReportChart.vue` |
| P0 | 设计并实现资源内容展示组件 | `frontend/src/components/ResourceViewer.vue` |
| P0 | 维护前端 API 调用封装 | `frontend/src/api/index.js` |
| P0 | 增加学习者画像独立页面 | `LearnerView.vue` 与路由 `/learner` |
| P0 | 抽出画像表单组件 | `ProfileForm.vue`，供生成页和画像页复用 |
| P0 | 完善 Agent trace 视觉层 | 可选新增 `TraceTimeline.vue` 或增强现有组件 |
| P0 | 增加接口错误提示与 loading 状态 | 按总架构组 API 契约展示失败原因，页面不直接 `alert` |
| P0 | 编写端到端测试清单 | 覆盖画像创建、资源生成、报告查看、反馈提交 |
| P1 | 增加资源库页面 | 对接总架构组定义的资源接口 `/api/resources/{learner_id}` |
| P1 | 增加前端组件测试 | 表单校验、图表渲染、资源展示 |

### 5.4 验收标准

- 前端只通过 `frontend/src/api/index.js` 调用后端接口。
- 页面能完整跑通：创建画像 -> 生成资源 -> 查看 Agent 轨迹 -> 查看报告 -> 提交反馈。
- 尚未通过总架构组联调验收的接口，前端不能当成稳定接口直接上线。
- API 联调由总架构组牵头，前端组负责复现页面调用问题并提供请求参数、响应内容和页面状态。

## 6. 跨组接口契约

| 契约 | 负责方 | 使用方 | 文档位置 |
|------|--------|--------|----------|
| Pydantic 请求/响应模型 | 总架构组 | 后端各组、前端组 | `backend/app/models/schemas.py`、`docs/api.md` |
| 后端 API 路由骨架与联调验收 | 总架构组 | 后端各组、前端组 | `backend/app/api/`、`docs/api.md` |
| 画像仓库接口 | 知识库数据库组 | 服务层、反馈逻辑 | `backend/app/db/learner/base.py` |
| 资源仓库接口 | 知识库数据库组 | 生成服务、资源接口 | `backend/app/db/resource/base.py` |
| Agent 状态字段 | 多智能体开发组 | 生成服务、前端可视化 | `backend/app/agents/state.py` |
| 前端展示字段 | 前端可视化+功能测试组 | 总架构组审核 | `frontend/src/api/index.js`、页面组件 |

## 7. 集成里程碑

| 阶段 | 完成标志 |
|------|----------|
| M1 架构冻结 | 目录、路径、API 建设清单、任务分工文档完成 |
| M2 后端 API 闭环 | 总架构完成路由骨架与联调验收，业务组完成服务/Agent/数据接入 |
| M3 数据持久化 | SQLite 模式下画像、资源、反馈可持久化 |
| M4 前端闭环 | 前端能完成核心用户流程 |
| M5 测试验收 | 单元测试、接口测试、端到端测试、演示脚本完成 |

## 8. 每组提交前检查

- 是否改了跨组接口？如果改了，是否同步 `docs/api.md` 和 `schemas.py`？
- 是否新增或变更后端 API？如果是，是否由总架构组完成路由骨架、响应模型和联调记录？
- 是否新增了运行时路径？如果新增，是否仍在 `backend/data/`、`backend/chroma_db/`、`backend/logs/` 范围内？
- 是否新增了页面或接口？如果新增，README 或相关文档是否能找到入口？
- 是否新增了业务逻辑？是否补了单元测试或至少补了测试说明？
- 是否依赖其他组未完成能力？是否在文档中标成阻塞项或规划项？
