# 总体架构文档

> 项目编号：XH-202630  
> 项目名称：领域知识个性化生成与多智能体协同决策系统  
> 文档版本：2.0  
> 文档更新时间：2026-07-26  
> 文档定位：描述当前代码库的真实分层、模块边界、运行路径与主流程。

## 1. 架构目标

系统当前面向“多领域培训”场景，围绕以下闭环组织：

```text
领域选择
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
- 问卷负责构建初始画像。
- 诊断负责测量真实掌握情况并回写画像。

## 2. 当前代码分层

| 层级 | 目录 | 当前职责 |
|---|---|---|
| 前端界面层 | `frontend/src/` | 领域/方向选择、问卷、诊断、历史记录、资源查看、报告展示 |
| API 路由层 | `backend/app/api/` | FastAPI 路由、参数接收、响应模型与错误映射 |
| 业务服务层 | `backend/app/services/` | 问卷组装、画像创建、诊断判分、资源生成、反馈处理、报告构建 |
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

- `onboarding.py`
- `profiles.py`
- `knowledge.py`
- `skills.py`
- `diagnosis.py`
- `generate.py`
- `resources.py`
- `reviews.py`
- `feedback.py`
- `report.py`
- `evaluation.py`

说明：

- 旧的 `learner.py` 已不再是当前接口主入口。
- 当前画像接口统一收敛为 `/api/profiles/*`。

### 3.2 服务层

`backend/app/services/` 当前真实文件为：

- `knowledge_service.py`
- `onboarding_service.py`
- `profile_service.py`
- `diagnosis_service.py`
- `generation_service.py`
- `resource_service.py`
- `review_service.py`
- `feedback_service.py`
- `report_service.py`
- `evaluation_service.py`

职责划分：

- `knowledge_service`：学习目录、知识库信息、技能图谱、诊断题选择
- `onboarding_service`：问卷组装、问卷提交、初始画像创建
- `profile_service`：画像查询、分页、局部更新、删除
- `diagnosis_service`：诊断判分与画像回写
- `generation_service`：生成工作流和资源落库
- `feedback_service`：学习反馈处理与画像更新
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

- Agent 负责协同推理和多步生成
- 服务层负责把 Agent 与数据库、画像、资源记录串起来

## 4. 当前主流程调用链

### 4.1 画像与诊断

```text
frontend
-> GET /api/knowledge/domains
-> GET /api/onboarding/questions?learning_direction_id=...
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> learner_profiles / questionnaire_* / diagnostic_* 落库
```

### 4.2 生成与反馈

```text
frontend
-> POST /api/generate/
-> generation_service
-> agents/workflow.py
-> generated_resources / agent_runs / agent_steps / resource_reviews 落库

frontend
-> POST /api/feedback/
-> feedback_service
-> learner_profiles / feedback_records 更新
```

## 5. 当前接口闭环

当前实际对外闭环接口为：

```text
GET /api/knowledge/domains
-> GET /api/onboarding/questions
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> POST /api/generate/
-> GET /api/resources/{learner_id}
-> POST /api/feedback/
-> GET /api/report/{learner_id}
```

补充接口：

- `GET /api/knowledge/directions`
- `GET /api/knowledge/info`
- `GET /api/skills/nodes`
- `GET /api/diagnosis/questions`
- `GET /api/resources/file/{resource_id}`
- `GET /api/reviews/{resource_id}`
- `GET /api/feedback/history/{learner_id}`
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

### 8.2 文档约束

当以下内容变更时，应同步文档：

- 路由文件名或接口路径
- 服务命名
- 主流程步骤
- 数据库存储位置
- 问卷与诊断的数据边界

### 8.3 运行约束

- 项目本地接口基地址统一为 `http://127.0.0.1:8000`
- Vite 前端代理应指向 `8000`
- 文档与联调口径均以 `8000` 为准

