# 总体架构文档

> 项目编号：XH-202630  
> 项目名称：领域知识个性化生成与多智能体协同决策系统  
> 文档版本：2.0  
> 文档更新时间：2026-07-31
> 文档定位：描述当前代码库的真实分层、模块边界、运行路径与主流程。

## 1. 架构目标

系统当前面向“多领域培训”场景，围绕以下闭环组织：

```text
用户资料维护
-> 领域选择
-> 学习方向选择
-> 初始画像问卷
-> 诊断测评
-> 个性化资源生成
-> 审核与证据
-> 学习反馈
-> 学情报告
```

其中：

- “学习方向”是前台和流程入口概念。
- `knowledge_base_id` 是后端内部的稳定知识边界。
- 用户长期稳定信息由用户资料维护，不再放入通用问卷。
- 问卷负责构建初始画像中的动态学习信息。
- 诊断负责测量真实掌握情况并回写画像。

## 2. 当前代码分层

| 层级 | 目录 | 当前职责 |
|---|---|---|
| 前端界面层 | `frontend/src/` | 用户资料、领域/方向选择、问卷、诊断、历史记录、资源查看、报告展示 |
| API 路由层 | `backend/app/api/` | FastAPI 路由、参数接收、响应模型与错误映射 |
| 业务服务层 | `backend/app/services/` | 用户资料、问卷组装、画像创建、诊断判分、资源生成、反馈处理、报告构建 |
| 多智能体层 | `backend/app/agents/` | LangGraph 工作流及诊断、检索、规划、生成、审核、反馈等 Agent 节点 |
| 基础设施层 | `backend/app/core/` | LLM、Embedding、向量存储、知识库读取、文件存储 |
| 数据访问层 | `backend/app/db/` | SQLite/PostgreSQL 仓储工厂、ORM 模型、表初始化与分领域仓储 |
| 数据模型层 | `backend/app/models/` | Pydantic schema 与核心数据结构 |
| 工具层 | `backend/app/utils/` | 项目内部复用工具函数 |
| 脚本层 | `scripts/` | 初始化数据库、导入知识库与问卷/诊断源数据 |
| 知识源层 | `knowledge_base/` | 学习目录源文件、方向知识库元数据、问卷源文件、诊断题源文件 |

## 3. 当前后端模块

### 3.1 API 路由

`backend/app/api/` 当前真实文件为：

- `admin.py`
- `diagnosis.py`
- `evaluation.py`
- `feedback.py`
- `generate.py`
- `knowledge.py`
- `learning_history.py`
- `onboarding.py`
- `profiles.py`
- `report.py`
- `resources.py`
- `reviews.py`
- `skills.py`
- `users.py`

说明：

- 画像接口统一收敛在 `/api/profiles/*`。
- 用户基础资料接口统一收敛在 `/api/users/*`。
- 学习历史时间线接口统一收敛在 `/api/learning-history/*`。

### 3.2 服务层

`backend/app/services/` 当前真实文件为：

- `knowledge_service.py`
- `onboarding_service.py`
- `profile_service.py`
- `user_service.py`
- `diagnosis_service.py`
- `generation_service.py`
- `generation_job_service.py`
- `resource_service.py`
- `review_service.py`
- `feedback_service.py`
- `report_service.py`
- `evaluation_service.py`
- `learning_history_service.py`

职责划分：

- `knowledge_service`：学习目录、知识库信息、技能图谱、诊断题选择
- `onboarding_service`：问卷组装、问卷提交、初始画像创建
- `user_service`：用户资料创建、查询、局部更新
- `profile_service`：画像查询、分页、局部更新、删除
- `diagnosis_service`：诊断判分与画像回写
- `generation_service`：生成工作流和资源落库
- `generation_job_service`：异步生成任务创建、状态查询、后台执行
- `feedback_service`：学习反馈处理与画像更新
- `learning_history_service`：学习过程时间线组装
- `report_service`：报告组装

### 3.3 Agent 层

`backend/app/agents/` 当前真实文件为：

- `workflow.py`
- `state.py`
- `diagnosis.py`
- `retriever.py`
- `planner.py`
- `generator.py`
- `reviewer.py`
- `feedback.py`

当前代码含义：

- Agent 负责协同推理和多步生成。
- 服务层负责把 Agent 与数据库、画像、资源记录串起来。
- `backend/app/models/workflow.py` 定义版本化 `WorkflowState`、状态枚举和脱敏 `ErrorInfo`
- `backend/app/models/agent_contracts.py` 定义各节点 Input/Output DTO、`NodeResult` 与统一 trace 结构
- `backend/app/agents/state.py` 仅保留兼容导出，所有 LangGraph channel 以 `WorkflowState 1.0` 为准

## 4. 当前主流程调用链

### 4.1 用户资料、画像与诊断

```text
frontend
-> POST /api/users/
-> GET /api/knowledge/domains
-> GET /api/onboarding/questions?learning_direction_id=...
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> users / learner_profiles / questionnaire_* / diagnostic_* 落库
```

说明：

- 用户的 `identity`、`education`、`major` 等稳定信息先进入 `users`。
- 通用问卷只负责当前学习方向的动态信息，不再重复采集稳定资料。
- `onboarding_service` 会优先使用用户资料中的 `identity` 回写画像的 `learner_type`。

### 4.2 生成与反馈

```text
frontend
  -> HTTP
backend/app/api
  -> 调用服务
backend/app/services
  |- generation_job_service: 创建异步任务、查询状态、后台执行
  |- generation_service: 先执行 readiness gate，再调用多 Agent 生成闭环并保存资源
  |- feedback_service: 提交正式 Attempt，执行确定性反馈策略并协调事务与后续生成
  |- learning_path_policy: 校验并生成路径状态变更
  |- report_service: 聚合画像、资源、Attempt、版本历史和持久化路径
  ->
backend/app/agents
  |- diagnosis: 学情诊断 Agent
  |- retriever: 知识库检索 Agent（BM25 + Chroma 向量召回 + RRF 融合 + CrossEncoder 精排）
  |- planner: 学习路径规划 Agent
  |- generator: 个性化资源生成 Agent
  |- reviewer: 审核纠偏 Agent
  |- feedback: 反馈决策 Agent
  |- claim_review: 独立 Claim 抽取、冻结 Evidence 判定与确定性指标
  |- workflow: 审核开关、Claim 返工闭环、返工额度与终态决策
  ->
backend/app/core + backend/app/db
  |- RuntimeHealth / failure policy / LLM / Embedding / ChromaDB / 知识库 / 文件存储
  |- Repository / ORM / SQLite or Memory
```

生成请求进入工作流前，由 `generation_service.build_workflow_state()` 完成唯一映射并生成 `run_id`。当前对外生成入口已经统一为异步任务模式：

```text
POST /api/generate/jobs
-> GET /api/generate/jobs?learner_id={learner_id}
-> BackgroundTasks 触发 generation_job_service.run_job(...)
-> 任务状态通过 GET /api/generate/jobs/{run_id} 查询
-> 结果通过 GET /api/resources/{learner_id}?run_id={run_id} 获取
```

运行中遵守以下控制流：

```text
diagnose -> retrieve -> plan -> generate
                                  |- include_review=false -> finalize_draft
                                  |- include_review=true  -> review
                                                               |- approve + include_claim_check=true
                                                               |     -> claim_extract -> claim_judge -> claim_decide
                                                               |            |- 通过 -> finalize
                                                               |            |- 问题 Claim 且有额度 -> prepare_revision -> generate
                                                               |            |- 失败/额度耗尽 -> finalize(human_review)
                                                               |- approve + include_claim_check=false -> finalize
                                                               |- revise 且有额度 -> prepare_revision -> generate
                                                               |- reject/额度耗尽 -> finalize
```

### 4.3 P0-07 反馈后真实闭环

```text
POST /api/feedback/attemptsattempts
-> 校验 learner、published source resource/version、稳定知识点与请求分数
-> 读取 profile_version、knowledge state、最近趋势和当前 path
-> deterministic policy
   |- overall < 0.60 或任一点 < 0.60 -> remediate
   |- 0.60 <= overall <= 0.85       -> practice
   |- overall > 0.85 且无 blocker   -> advance
-> Transaction A
   |- learning_attempts + point_results
   |- feedback_decisions
   |- knowledge_states + mutation history
   |- learner_profiles.profile_version + version history
   |- learning_paths/nodes + path mutation
-> commit
-> remediate/advance 时幂等创建现有 generation job
-> 保存 parent run / attempt / decision / child run 关系
-> BackgroundTasks 调用 GenerationJobService.run_job
-> 新 Run 继续经过 Evidence、Review、Claim Audit 和 Publication Gate
```

知识点掌握度采用可解释 EWMA：已有状态为 `0.7 * old + 0.3 * attempt_score`，首次作答直接取 attempt score。hint 与 duration 仅进入决策上下文和审计，不暗中改变 mastery。每次成功更新将画像版本从 N 变为 N+1，并以 `expected_profile_version` 做 CAS；重复请求不会再次加权。

路径 mutation 由 policy 生成并校验自环、缺失前置条件、环路和重复节点。低分插入/复用 remedial，中分插入/复用 practice，高分完成当前节点并解锁满足前置条件的下一节点；无下一节点时增加 challenge。路径只有实际变化才递增版本。

Follow-up 属于 after-commit 副作用。其 run_id 由 attempt 稳定派生；创建失败时 Attempt 保持 `applied`、关联状态为 `failed`，相同幂等请求可安全对账重试。反馈事件只存稳定 ID、计数、分数摘要、action/reason code 和版本，不保存完整答案、画像、Prompt 或模型原文。

### 4.4 P0-08 WorkflowEvent SSE

```text
业务动作 / Agent step
-> 资源、审核、Claim、状态事实先持久化
-> WorkflowEvent append + commit
-> RunEventStreamService 短事务查询 event_sequence > cursor
-> public allow-list mapper
-> StreamingResponse(text/event-stream)
-> EventSource
-> sequence-deduplicating reducer
-> AgentVisualization realtime timeline
```

WorkflowEvent Ledger 是唯一事件事实源，SSE 只是只读 transport，不创建第二套 UI event 表或进程内 progress ledger。每个 SSE poll 都打开并关闭独立 Repository Session，不在长连接期间持有数据库事务或行锁；同步 SQL 查询通过 thread offload 避免阻塞 ASGI event loop。

连接先发 snapshot，再补发 durable event backlog，最后 live tail。浏览器断线只停止观看，不取消 BackgroundTasks/Workflow；重连使用原 EventSource 的 `Last-Event-ID`，或页面刷新后以 timeline 最后 sequence 作为 `after_sequence`。heartbeat 不进入 Event Ledger。两个客户端独立读取同一 append-only ledger，不存在 delivered/ack 或破坏性消费。

GenerationJob/AgentRun 的 queued 竞态保持现有 ownership：Job 可先存在，SSE snapshot 此时 run_status 为空并等待 AgentRun。P0-08 没有引入 Redis、消息队列、WebSocket、自动 resume/cancel 或 token streaming。

P0-06 的 Claim 抽取器与 Generator 相互独立。模型只能从资源、目标技能节点和当前
Run 的冻结 Evidence ID 白名单中选择；代码负责生成稳定 Claim ID，并校验原文跨度、
资源版本、知识点与 Evidence 边界。判定失败、漏判或伪造 ID 均 fail closed 到
`human_review`。新资源版本必须重新抽取，旧版本判定不会复制。

`max_iterations` 是最大业务返工次数，不包含初次生成；`generation_attempt = revision_count + 1`。技术重试不复用该计数。每次运行、节点执行、资源版本和资源审核分别使用 `run_id`、`step_id`、`resource_id`、`review_id`，ID 在动作开始或结果产生时生成，持久化层不重新生成已有 ID。

### 多 KB collection 与健康检查边界

- 每个 `knowledge_base_id` 通过 `backend/app/core/vector_store.py:_collection_name()` 映射到独立 Chroma collection。
- collection 的创建、写入、查询、删除和 health 均复用该 resolver，`CHROMA_COLLECTION_NAME` 兼容期只作为前缀，不再表示唯一固定集合。
- 公共 `/health` 与 `/health/ready` 只判断默认 KB 和 Python、storage、LLM、Embedding、Chroma 目录、资源目录等核心依赖。
- 管理员 `/api/admin/knowledge-bases/health` 在显式 token 保护下返回所有 KB 的脱敏详情。
- 默认 KB 正常但部分可选 KB 异常时，管理员汇总为 degraded；公共服务不因此返回 503。默认 KB 或 Chroma 核心不可用时才按运行模式进入 degraded/not-ready。

## 5. 当前接口闭环

当前实际对外闭环接口为：

```text
POST /api/users/
-> GET /api/knowledge/domains
-> GET /api/onboarding/questions
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> POST /api/generate/jobs
-> GET /api/generate/jobs?learner_id={learner_id}
-> GET /api/generate/jobs/{run_id}
-> GET /api/resources/{learner_id}
-> GET /api/resources/file/{resource_id}
-> GET /api/feedback/evaluation/run/{learner_id}/{run_id}
-> POST /api/feedback/attemptsattempts/run/submit
-> POST /api/feedback/attempts
-> GET /api/feedback/attempts/{learner_id}
-> GET /api/learning-history/{learner_id}/timeline
-> GET /api/report/{learner_id}
```

补充接口：

- `GET /api/users/`
- `GET /api/users/{user_id}`
- `PATCH /api/users/{user_id}`
- `GET /api/knowledge/directions`
- `GET /api/knowledge/info`
- `GET /api/skills/nodes`
- `GET /api/diagnosis/questions`
- `GET /api/reviews/{resource_id}`
- `GET /api/generate/jobs?learner_id={learner_id}`
- `GET /api/feedback/evaluation/run/{learner_id}/{run_id}`
- `POST /api/feedback/attemptsattempts/run/submit`
- `GET /api/feedback/attempts/{learner_id}`
- `GET /api/evaluation/summary`

## 6. 当前数据与运行目录

| 路径 | 当前用途 |
|---|---|
| `backend/data/domain_knowledge.db` | SQLite 业务数据库 |
| `backend/data/generated_resources/` | 生成资源文件目录 |
| `backend/chroma_db/` | Chroma 向量索引目录 |
| `backend/logs/` | 运行日志目录 |
| `knowledge_base/learning_catalog_seed.json` | 领域与学习方向目录源文件 |
| `knowledge_base/questionnaire_common.json` | 通用问卷源文件 |
| `knowledge_base/<track>/questionnaire.json` | 方向特定问卷源文件 |
| `knowledge_base/<track>/diagnostic_questions.json` | 方向诊断题源文件 |

说明：

- 当前本地数据库已经按最新模型重建。
- `knowledge_base/questionnaire_common.json` 现已收缩为只保存动态学习信息，不再包含用户长期资料字段。

## 7. 当前目录树摘要

```text
backend/
  app/
    api/
    agents/
    core/
    db/
    models/
    services/
    utils/
    config.py
    main.py
  data/
  chroma_db/
  logs/

frontend/
  src/
    api/
    components/
    router/
    stores/
    styles/
    utils/
    views/

knowledge_base/
  learning_catalog_seed.json
  questionnaire_common.json
  rag_engineering_training/
  demo_industrial_internet/

scripts/
  init_db.py
  ingest_knowledge.py
```

## 8. 当前约束

### 8.1 命名约束

- 前台流程入口使用 `learning_direction_id`
- 后端内部知识边界保留 `knowledge_base_id`
- 用户资料主键使用 `user_id`
- 学习者画像主键使用 `learner_id`

### 8.2 文档约束

当以下内容变更时，应同步文档：

- 路由文件名或接口路径
- 服务命名
- 主流程步骤
- 数据库存储位置
- 用户资料、问卷与诊断的数据边界

### 8.3 运行约束

- 项目本地接口基地址统一为 `http://127.0.0.1:8000`
- Vite 前端代理应指向 `8000`
- 文档与联调口径均以 `8000` 为准

### 8.4 当前实现边界

- 当前对外资源生成模式为异步任务模式
- 同步生成接口 `POST /api/generate/` 已移除
- 资源生成页当前按任务维度展示，默认定位当前任务，可切换查看历史成功任务
- 学习反馈页当前按任务维度加载测评题，并支持基于选中反馈主动重新生成
- 学习历史页面应优先依赖 `/api/learning-history/{learner_id}/timeline`
- 通用问卷不再承担用户资料采集职责
## 9. Agent 可靠执行与异步任务整合

dev 的异步 `GenerationJob` 负责排队和面向前端的任务状态；`AgentRun` 负责一次
多 Agent 执行的可信生命周期。两者共享预分配的 run_id，但职责不合并：

```text
GenerationJobService
  -> GenerationService.generate_with_run_id
       -> AgentRun / AgentStep / WorkflowEvent
       -> EvidenceRetriever
            -> hybrid vector + BM25
            -> optional CrossEncoder rerank
            -> KB / Chunk version / content hash validation
       -> Generator
       -> Reviewer
       -> WorkflowArtifactRecorder
       -> WorkflowCheckpoint
       -> publication gate
```

架构约束：

- 混合召回和精排只产生候选；候选必须经过 SQL Chunk 历史版本、KB 范围和内容哈希校验后才能成为 Evidence。
- `RecordedNode` 在节点副作用前创建 running Step；`DurableWorkflowRunner` 在状态合并后、checkpoint 前保存业务制品。
- Generator 定向返工使用上一版本和结构化指令，新版本不可原地覆盖旧正文。
- Reviewer 的模型建议必须经过确定性 policy 二次裁决。
- Resource 的 `run_id` 单一关联 AgentRun；GenerationJob 以同值关联，避免 ORM 中出现两个竞争的 run_id 字段。
- `review_status` 描述审核状态，`publication_status` 描述分发状态；只有最终批准叶子版本发布。
- Run 回放只读数据库，不重新执行模型；自动 resume、SSE、取消仍为后续能力。
