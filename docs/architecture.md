# 总体架构文档

> 项目编号：XH-202630  
> 项目名称：领域知识个性化生成与多智能体协同决策系统  
> 文档版本：v1.0  
> 文档定位：统一系统分层、模块边界、调用链和运行路径。

## 1. 架构目标

系统架构支撑通用领域知识生成闭环：

```text
学习者画像输入
→ 能力诊断
→ 知识库检索
→ 学习路径规划
→ 个性化资源生成
→ 审核纠偏与知识溯源
→ 学情报告
→ 学习反馈
→ 反馈决策
→ 动态更新画像与下一轮学习路径
```

领域方向由用户输入、学习者画像和当前接入的知识库决定，后端不硬编码任何特定领域。

## 2. 总体分层

| 层级 | 目录 | 核心职责 |
|------|------|----------|
| 前端可视化层 | `frontend/src/` | 页面交互、画像录入、资源展示、报告图表、Agent 过程可视化 |
| API 路由层 | `backend/app/api/` | HTTP 参数接收、Pydantic 校验、状态码、响应模型、联调入口 |
| 业务服务层 | `backend/app/services/` | 串联画像、生成、反馈、报告等业务用例 |
| 多智能体层 | `backend/app/agents/` | Agent 节点、共享状态、协同决策、审核纠偏 |
| 基础设施层 | `backend/app/core/` | LLM、Embedding、知识库读取、向量库、文件存储、运行时健康检查与稳定错误码 |
| 数据访问层 | `backend/app/db/` | ORM、仓库接口、画像/资源/反馈数据持久化 |
| 数据模型层 | `backend/app/models/` | Pydantic 请求/响应/领域数据结构 |
| 脚本层 | `scripts/` | 数据库初始化、知识库入库、演示数据准备 |
| 知识库层 | `knowledge_base/` | 可替换的领域知识库原始资料 |

## 3. 后端调用链

```text
frontend
  ↓ HTTP
backend/app/api
  ↓ 调用服务
backend/app/services
  ├─ learner_service: 画像创建、查询、更新
  ├─ generation_service: 先执行 readiness gate，再调用多 Agent 生成闭环并保存资源
  ├─ feedback_service: 调用反馈决策 Agent，保存反馈记录并更新画像
  └─ report_service: 聚合画像、资源、反馈生成报告
  ↓
backend/app/agents
  ├─ diagnosis: 学情诊断 Agent
  ├─ retriever: 知识库检索 Agent
  ├─ planner: 学习路径规划 Agent
  ├─ generator: 个性化资源生成 Agent
  ├─ reviewer: 审核纠偏 Agent
  ├─ feedback: 反馈决策 Agent
  └─ workflow: 协同编排与重试决策
  ↓
backend/app/core + backend/app/db
  ├─ RuntimeHealth / failure policy / LLM / Embedding / ChromaDB / 知识库 / 文件存储
  └─ Repository / ORM / SQLite or Memory
```

## 4. API 闭环

```text
POST /api/learner/profile
→ POST /api/generate/
→ GET /api/resources/{learner_id}
→ POST /api/feedback/
→ 反馈决策 Agent 更新画像与下一轮建议
→ GET /api/feedback/history/{learner_id}
→ GET /api/report/{learner_id}
→ POST /api/generate/ 进入下一轮
```

## 5. Agent 运行数据

每次生成需要返回可视化 trace：

- `agent_name`
- `action`
- `input_summary`
- `output_summary`
- `decision_reason`
- `evidence_refs`
- `status`（success/degraded/failed；fallback 不得标记 success）
- `error_code`（稳定脱敏码，不保存原始上游异常）
- `timestamp`

后续如需回放历史过程，可继续增加 `agent_runs` 与 `agent_steps` 持久化。

反馈提交时由 `feedback` Agent 输出反馈决策数据：

- `decision`
- `decision_reason`
- `next_action`
- `recommended_topics`
- `updated_knowledge_states`
- `regenerate_suggestion`
- `profile_updates`

`feedback_service` 只负责调用该 Agent、应用画像更新、保存反馈记录和返回 API 响应。

## 6. 运行时路径标准

| 类型 | 标准路径 | 说明 |
|------|----------|------|
| 本地虚拟环境 | `.venv/` | 项目根目录下的 Python 虚拟环境，仅本地使用，不进入版本控制 |
| 后端运行根目录 | `backend/` | 配置、数据库、日志、生成资源基准目录 |
| 环境变量文件 | `backend/.env` | `app/config.py` 固定读取 |
| SQLite 数据库 | `backend/data/domain_knowledge.db` | `DB_TYPE=sqlite` 时使用 |
| 生成资源 | `backend/data/generated_resources/` | 文本、文件类资源统一落点 |
| 向量库索引 | `backend/chroma_db/` | ChromaDB 持久化目录 |
| 日志 | `backend/logs/` | 后端日志目录 |
| 原始知识库 | `knowledge_base/` | 可替换领域知识库源数据 |
| 示例数据 | `examples/` | 初始化和演示使用 |

禁止新增 `backend/app/data/` 或项目根目录 `data/` 作为正式运行目录。

## 7. 运行模式与健康边界

- `development`：默认 SQLite、禁止 degraded；not_ready 时应用保留 `/health`，生成入口在持久化前返回 503。
- `demo`：只有显式 `ALLOW_DEGRADED_GENERATION=true` 才允许 fallback；响应和 trace 必须显示 degraded。
- `production`：禁止 degraded 和 memory storage；配置或必需组件 not_ready 时启动 fail-fast。
- `backend/app/core/health.py` 只做本地、脱敏检查，不调用计费 LLM，不下载 Embedding 模型，不使用 `get_vector_store()` 隐式创建 collection。
- `backend/app/core/errors.py` 统一稳定错误码和 fallback allow/deny；P0-02 之前不承担 retry、结构化输出或模型路由职责。
- `/health` 返回 storage、LLM、Embedding、Vector Store、资源目录和 Python readiness，不返回 Key、完整 endpoint、绝对运行路径或 traceback。
- memory repository 是 ephemeral；即使可运行，也必须在启动日志和 health 中明确显示，不能作为 production ready。

## 8. 协作规则

| 规则 | 标准 |
|------|------|
| 接口优先 | 修改 API 请求/响应字段前，同步 `docs/api.md` 与 `backend/app/models/schemas.py` |
| 模型统一 | 前后端共享字段名以 Pydantic schema 为准 |
| 业务下沉 | 路由只做协议转换，业务规则放在 `services/` 或 `agents/` |
| 数据隔离 | 仓库实现放在 `db/`，服务层通过接口或工厂调用 |
| 路径统一 | 运行时文件只写入 `backend/data/`、`backend/chroma_db/`、`backend/logs/` |
| 可视化闭环 | Agent trace、审核证据、反馈变化和报告数据必须能被前端展示 |
