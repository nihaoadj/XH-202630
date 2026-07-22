# 领域知识个性化生成与多智能体协同决策系统

> 提交代码前，请先仔细阅读 [`git-workflow.md`](./git-workflow.md)，并按其中的分支、提交信息和协作规范操作。

题目编号：XH-202630

本项目面向垂直领域技能培训，构建“学情诊断 → 知识检索 → 内容生成 → 审核纠偏 → 决策输出 → 反馈迭代”的全流程多智能体协同系统，实现高保真、个性化的领域知识资源按需生成。

## 项目亮点

- 多智能体协同：基于 LangGraph 实现学情诊断、知识检索、内容生成、审核纠偏等 Agent 的协同工作流。
- 幻觉防控：引入 RAG 知识约束、审核纠偏、知识溯源等机制。
- 个性化适配：基于学习者画像动态匹配资源难度、生成学习路径与分阶测试。
- 可视化决策：提供 Agent 调度过程、学情报告、资源难度匹配曲线等可视化能力。

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

配置文件默认读取 `backend/.env`，运行时数据统一落在 `backend/data/` 和 `backend/chroma_db/`。

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

## 后端目录说明

```text
backend/
├── app/                          # 后端应用核心代码
│   ├── api/                      # HTTP 路由层：仅负责请求校验、协议转换与响应组装
│   │   ├── learner.py            # 学习者画像接口
│   │   ├── generate.py           # 资源生成接口
│   │   ├── feedback.py           # 学习反馈接口
│   │   └── report.py             # 学情报告接口
│   ├── services/                 # 业务逻辑层：封装完整业务用例
│   │   ├── learner_service.py    # 学习者画像业务
│   │   ├── generation_service.py # 个性化资源生成业务
│   │   ├── feedback_service.py   # 反馈处理与画像更新业务
│   │   └── report_service.py     # 学情报告构建业务
│   ├── agents/                   # 多智能体层：LangGraph 工作流与各 Agent 节点
│   │   ├── workflow.py           # 工作流状态机编排
│   │   ├── state.py              # 多智能体共享状态定义
│   │   ├── diagnosis.py          # 学情诊断 Agent
│   │   ├── retriever.py          # 知识检索 Agent
│   │   ├── generator.py          # 领域知识生成 Agent
│   │   └── reviewer.py           # 内容审核与幻觉检测 Agent
│   ├── core/                     # 基础设施层：封装底层技术能力
│   │   ├── llm.py                # 大模型客户端封装
│   │   ├── embeddings.py         # 中文 Embedding 模型加载
│   │   ├── vector_store.py       # ChromaDB 向量存储
│   │   ├── knowledge_base.py     # 知识库文档加载与切片
│   │   └── file_storage.py       # 生成资源文件存储（支持文本与多媒体）
│   ├── db/                       # 数据访问层：按实体划分子包
│   │   ├── models.py             # SQLAlchemy ORM 模型（共享）
│   │   ├── database.py           # 数据库引擎与会话管理（共享）
│   │   ├── learner/              # 学习者画像仓库
│   │   │   ├── base.py           # 抽象接口
│   │   │   ├── memory.py         # 内存实现
│   │   │   ├── sql_repository.py # SQLAlchemy 实现
│   │   │   └── repository.py     # 仓库工厂（按配置自动选择实现）
│   │   └── resource/             # 生成资源仓库
│   │       ├── base.py           # 抽象接口
│   │       ├── memory.py         # 内存实现
│   │       ├── sql_repository.py # SQLAlchemy 实现
│   │       └── repository.py     # 仓库工厂（按配置自动选择实现）
│   ├── models/                   # 数据模型层：Pydantic 数据结构与共享状态
│   │   └── schemas.py
│   ├── utils/                    # 通用工具函数层：项目内部复用工具
│   ├── config.py                 # 应用配置（从 .env 加载）
│   └── main.py                   # FastAPI 应用入口
├── tests/                        # 单元测试与集成测试
├── data/                         # 运行时数据目录（自动生成，不进入版本控制）
│   ├── domain_knowledge.db       # SQLite 数据库文件
│   ├── generated_resources/      # 生成的资源文件（文本/PPT/视频/PDF/音频/图片）
│   └── .gitkeep
├── chroma_db/                    # ChromaDB 向量索引目录（自动生成，不进入版本控制）
├── logs/                         # 应用日志目录（不进入版本控制）
├── .env.example                  # 环境变量模板
└── requirements.txt              # Python 依赖
```

## 项目目录

```text
version1/
├── backend/                      # FastAPI 后端与多智能体核心实现
├── frontend/                     # Vue3 前端可视化界面
│   ├── src/
│   │   ├── api/                  # axios 接口封装
│   │   ├── components/           # 可复用组件（Agent 轨迹、报告图表、资源查看器）
│   │   ├── views/                # 页面视图（首页、生成、反馈、报告）
│   │   ├── router/               # Vue Router 路由配置
│   │   ├── stores/               # Pinia 全局状态
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── knowledge_base/               # 垂直领域专业知识库原文档与元数据
│   └── demo_industrial_internet/
│       ├── metadata.json         # 知识库元数据
│       └── raw/                  # 原始 Markdown 文档
├── examples/                     # 示例学习者画像等示例数据（仅用于初始化演示）
│   ├── learner_profiles/         # 学习者画像 JSON 示例
│   └── generated_samples/        # 生成资源样例目录
├── docs/                         # 设计实现方案、部署说明、API 文档
│   ├── architecture.md           # 总体架构、模块边界、协作规则
│   ├── task-allocation.md        # 四组开发任务分工与验收标准
│   ├── requirements.md           # 需求分析文档
│   ├── features.md               # 功能文档
│   ├── api.md                    # API 接口文档
│   └── deployment.md             # 部署说明文档
├── scripts/                      # 初始化与辅助脚本
│   ├── ingest_knowledge.py       # 知识库文档切片并写入向量库
│   └── init_db.py                # 初始化数据库表并导入示例数据
├── Dockerfile                    # Docker 镜像构建文件
├── git-workflow.md               # Git 分支、提交和协作规范
├── README.md
└── .gitignore
```

### 运行时数据说明

| 目录/文件 | 用途 | 是否进入版本控制 |
|-----------|------|------------------|
| `backend/data/domain_knowledge.db` | SQLite 数据库文件 | 否 |
| `backend/data/generated_resources/` | 运行时生成的资源文件 | 否（保留目录结构） |
| `backend/chroma_db/` | ChromaDB 向量索引 | 否（保留目录结构） |
| `backend/logs/` | 应用日志文件 | 否（保留目录结构） |
| `examples/` | 示例学习者画像等静态示例数据 | 是 |
| `knowledge_base/` | 领域知识原文档 | 是 |

## 核心指标

- 专业知识幻觉率 < 5%
- 学习者画像-资源难度适配准确率 ≥ 85%
- 核心知识点覆盖率 ≥ 90%

## 协作开发入口

当前处于架构搭建与并行开发准备阶段，分发任务时优先阅读：

- `docs/architecture.md`：统一系统分层、模块职责、运行时路径和 API 状态口径。
- `docs/task-allocation.md`：按四个小组拆分任务、交付物和验收标准。
- `docs/api.md`：接口契约；其中标明接口建设状态，当前状态仅作为开发参考，不锁定最终实现。
- `git-workflow.md`：Git 分支、提交信息、禁止提交内容和文档同步规则。
