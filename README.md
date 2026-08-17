# 领域知识个性化生成与多智能体协同决策系统

> 提交代码前，请先仔细阅读 [`git-workflow.md`](./git-workflow.md)，并按其中的分支、提交信息和协作规范操作。

题目编号：XH-202630  
文档版本：2.0

本项目面向多领域技能学习者，构建“学习者画像输入 → 能力诊断 → 多 Agent 协同决策 → 个性化资源生成 → 审核纠偏与知识溯源 → 学情报告 → 学习反馈 → 动态调整学习路径”的领域知识个性化生成系统。RAG 工程训练是当前示例知识库和比赛分工中的一个方向，实际生成方向由用户输入的学习主题、学习者画像和所接入的知识库共同决定。

## 项目亮点

- 多智能体协同：基于 LangGraph 实现学情诊断、知识库检索、学习路径规划、个性化资源生成、审核纠偏、反馈决策等 Agent 的协同闭环。
- 反馈真实闭环：正式 Attempt 会原子更新知识点掌握度、画像版本和持久化学习路径；补救或进阶决策复用异步生成任务，并保留父子 Run 来源关系。
- 实时 Agent 轨迹：生成页通过 SSE 只读持久化 WorkflowEvent，支持 queued snapshot、断线续传、事件去重、terminal close 与轮询降级。
- 幻觉防控：引入冻结 Evidence、独立 Claim 抽取/判定、审核纠偏与可复核指标。
- 个性化适配：基于学习者画像动态匹配资源难度、生成学习路径与分阶测试。
- 可视化决策：提供 Agent 调度过程、学情报告、资源难度匹配曲线等可视化能力。
- 可回放运行记录：Run 在模型调用前建档，节点 Step/Event/Evidence/Checkpoint 持续落库，可跨进程只读查询并识别中断。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Element Plus + ECharts |
| 后端 API | FastAPI (Python 3.11+) |
| Agent 编排 | LangChain + LangGraph |
| 大模型 | 国产大模型 API（通义千问 / 文心一言 / DeepSeek 等，可配置） |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 部署 | Docker / 直接部署 |

## 快速开始

> 当前项目仍处于基础架构阶段，仅支持后端框架导入、接口文档访问、单元测试和基础 service 链路验证；不支持完整业务运行或生产部署。

配置文件默认读取 `backend/.env`，运行时数据统一落在 `backend/data/` 和 `backend/chroma_db/`。  
默认 `KNOWLEDGE_BASE_DIR` 指向 RAG 工程训练示例知识库；接入其他领域时，将该配置改为对应知识库目录即可，后端 Agent 不会把生成方向固定为 RAG。

```bash
# 1. 进入后端并安装依赖
cd backend
pip install -r requirements.txt

# 2. 初始化知识库与学习画像示例数据
cd ..
# 在项目根目录执行，脚本会自动定位 backend/ 与 examples/
python scripts/ingest_knowledge.py
python scripts/init_db.py

# 3. 启动后端
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. 启动前端（新终端）
cd frontend
npm install
npm run dev
```

知识索引异常后，可按知识库 ID 显式重新入库并对账 SQL/Chroma：

```bash
python scripts/ingest_knowledge.py --knowledge-base-id rag_engineering_training
```

运行模式和退出语义：

| 模式 | degraded fallback | 存储建议 | 启动/生成语义 |
|---|---|---|---|
| `development` | 默认禁止，可显式开启 | SQLite | not-ready 时保留 `/health`，生成返回 503 |
| `demo` | 仅显式 `ALLOW_DEGRADED_GENERATION=true` | SQLite | fallback 必须标记 degraded |
| `production` | 永远禁止 | SQLite/PostgreSQL | 核心依赖或默认 KB not-ready 时 fail-fast |

`scripts/check_environment.py` 不调用计费 LLM、不下载 Embedding，退出码为 0=ready、2=degraded、1=not-ready。公共 `/health` 与 `/health/ready` 只检查默认 KB 和核心依赖；其他 KB 的异常不会轻易把整个服务变成 503。全 KB 详情位于 token 保护的管理员接口，见 `docs/api.md`。

数据库迁移或比赛联调前，可在项目根目录执行只读完整性预检：

```powershell
python scripts/check_database_integrity.py
```

该脚本检查 SQLite 外键开关、现有 FK 违规、资源版本重复/NULL、数据库唯一约束和 Resource 到 Run、Step、父版本的真实外键。退出码为 0=ready、2=约束缺失警告、1=存在阻塞迁移的数据问题；脚本不会修改或删除数据。

`LLM_STRUCTURED_OUTPUT_MODE=auto` 会先尝试 function calling。若所用 OpenAI-compatible 服务明确不支持该能力，请在本地 `.env` 显式设为 `text`，避免每个 Agent 固定产生一次 BAD_REQUEST 后再回退；不要提交真实 `.env` 或 API Key。

四个生成 Agent 统一通过可注入的 `LLMGateway` 调用模型。默认单次请求预算为 30 秒、同步工作流预算为 105 秒、总尝试次数为 2；SDK 自带重试关闭，技术重试和资源返工分别计数。结构化输出会经过严格 Pydantic 校验，Reviewer 的异常或非法输出不会被自动批准。配置项及模式说明见 `backend/.env.example` 和 `docs/deployment.md`。

## 后端目录说明

```text
backend/
├── app/                          # 后端应用核心代码
│   ├── api/                      # HTTP 路由层：仅负责请求校验、协议转换与响应组装
│   │   ├── onboarding.py         # 初始画像问卷接口
│   │   ├── admin.py              # Token 保护的全 KB 运行状态接口
│   │   ├── users.py              # 用户基础资料接口
│   │   ├── profiles.py           # 学习者画像接口
│   │   ├── knowledge.py          # 领域、方向与知识库目录接口
│   │   ├── skills.py             # 技能图谱接口
│   │   ├── diagnosis.py          # 诊断接口
│   │   ├── generate.py           # 资源生成接口
│   │   ├── learning_history.py   # 学习历史时间线接口
│   │   ├── resources.py          # 资源历史与文件下载接口
│   │   ├── reviews.py            # 审核摘要接口
│   │   ├── feedback.py           # 学习反馈接口
│   │   ├── report.py             # 学情报告接口
│   │   └── evaluation.py         # 评测摘要接口
│   ├── services/                 # 业务逻辑层：封装完整业务用例
│   │   ├── knowledge_service.py
│   │   ├── onboarding_service.py
│   │   ├── profile_service.py
│   │   ├── user_service.py
│   │   ├── diagnosis_service.py
│   │   ├── generation_service.py
│   │   ├── generation_job_service.py
│   │   ├── learning_history_service.py
│   │   ├── resource_service.py
│   │   ├── review_service.py
│   │   ├── feedback_service.py
│   │   └── report_service.py
│   ├── agents/                   # 多智能体层：LangGraph 工作流与各 Agent 节点
│   │   ├── workflow.py           # 工作流状态机编排
│   │   ├── state.py              # 多智能体共享状态定义
│   │   ├── diagnosis.py          # 学情诊断 Agent
│   │   ├── retriever.py          # 知识库检索 Agent
│   │   ├── planner.py            # 学习路径规划 Agent
│   │   ├── generator.py          # 个性化资源生成 Agent
│   │   ├── reviewer.py           # 内容审核与幻觉检测 Agent
│   │   └── feedback.py           # 反馈决策 Agent
│   ├── core/                     # 基础设施层：封装底层技术能力
│   │   ├── llm.py                # 大模型客户端封装
│   │   ├── llm_gateway.py        # 超时、重试、deadline、错误映射与调用遥测
│   │   ├── structured_output.py  # 统一 JSON 提取与严格结构校验
│   │   ├── embeddings.py         # 中文 Embedding 模型加载
│   │   ├── vector_store.py       # ChromaDB 向量存储
│   │   ├── knowledge_base.py     # 知识库文档加载与切片
│   │   ├── file_storage.py       # 生成资源文件存储（支持文本与多媒体）
│   │   ├── health.py             # 脱敏运行时健康检查与 readiness 聚合
│   │   └── errors.py             # 稳定错误码与显式 degraded 策略
│   ├── db/                       # 数据访问层：按实体划分子包
│   │   ├── learner/              # 画像仓储
│   │   ├── questionnaire/        # 问卷仓储
│   │   ├── diagnosis/            # 诊断仓储
│   │   ├── resource/             # 资源仓储
│   │   ├── feedback/             # 反馈仓储
│   │   ├── knowledge/            # 学习目录与知识库仓储
│   │   ├── audit/                # Agent/审核相关仓储
│   │   ├── models.py             # SQLAlchemy ORM 模型（共享）
│   │   └── database.py           # 数据库引擎与会话管理（共享）
│   ├── models/                   # 数据模型层：Pydantic 数据结构与共享状态
│   │   └── schemas.py
│   ├── utils/                    # 通用工具函数层：项目内部复用工具
│   ├── config.py                 # 应用配置（从 .env 加载）
│   └── main.py                   # FastAPI 应用入口
├── tests/                        # 单元测试与集成测试
├── data/                         # 运行时数据目录（自动生成，不进入版本控制）
│   ├── domain_knowledge.db       # SQLite 数据库文件
│   ├── generated_resources/      # 生成的资源文件
│   └── .gitkeep
├── chroma_db/                    # ChromaDB 向量索引目录（自动生成，不进入版本控制）
├── logs/                         # 应用日志目录（不进入版本控制）
├── .env.example                  # 环境变量模板
└── requirements.txt              # Python 依赖
```

## 项目目录

```text
version1/
├── .venv/                       # 本地 Python 虚拟环境（不进入版本控制）
├── backend/                     # FastAPI 后端与多智能体核心实现
├── frontend/                    # Vue3 前端可视化界面
│   ├── src/
│   │   ├── api/                 # axios 接口封装
│   │   ├── assets/
│   │   ├── components/          # 可复用组件
│   │   ├── router/              # Vue Router 路由配置
│   │   ├── stores/              # Pinia 全局状态
│   │   ├── styles/
│   │   ├── utils/
│   │   └── views/               # 首页、学习方向、诊断、资源、历史等页面
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── knowledge_base/              # 领域知识库原文档与元数据
│   ├── learning_catalog_seed.json
│   ├── questionnaire_common.json
│   ├── rag_engineering_training/
│   └── demo_industrial_internet/
├── examples/                    # 示例学习者画像等示例数据（仅用于初始化演示）
│   ├── learner_profiles/
│   └── generated_samples/
├── docs/                        # 设计实现方案、部署说明、API 文档
│   ├── architecture.md
│   ├── knowledge_base_database.md
│   ├── api.md
│   └── ...
├── scripts/                     # 初始化与辅助脚本
│   ├── ingest_knowledge.py
│   ├── init_db.py
│   └── check_environment.py      # 只读、脱敏的运行环境检查
├── Dockerfile
├── git-workflow.md
├── README.md
└── .gitignore
```

### 运行时数据说明

| 目录/文件 | 用途 | 是否进入版本控制 |
|-----------|------|------------------|
| `.venv/` | 项目根目录下的本地 Python 虚拟环境 | 否 |
| `backend/data/domain_knowledge.db` | SQLite 数据库文件 | 否 |
| `backend/data/generated_resources/` | 运行时生成的资源文件 | 否（保留目录结构） |
| `backend/chroma_db/` | ChromaDB 向量索引 | 否（保留目录结构） |
| `backend/logs/` | 应用日志文件 | 否（保留目录结构） |
| `examples/` | 示例学习者画像等静态示例数据 | 是 |
| `knowledge_base/` | 领域知识库原文档 | 是 |

## 核心指标

- 专业知识幻觉率 < 5%
- 学习者画像-资源难度适配准确率 ≥ 85%
- 核心知识点覆盖率 ≥ 90%

## 协作开发入口

当前处于架构搭建与并行开发准备阶段，分发任务时优先阅读：

- `docs/architecture.md`：统一系统分层、模块职责、运行时路径和主流程口径。
- `docs/api.md`：当前真实接口契约。
- `docs/knowledge_base_database.md`：当前知识库、问卷、诊断与数据库落库说明。
- `git-workflow.md`：Git 分支、提交信息、禁止提交内容和文档同步规则。
