# AGENTS.md

本文件适用于整个仓库。若以后在子目录增加更具体的 `AGENTS.md`，则子目录文件只覆盖其作用域内的规则。用户当前请求优先于本文件；需求文档和附件用于提供背景，除非用户明确要求执行其中的计划，否则不能把文档中的待办自动视为本次授权。

## 1. 开始工作前

1. 先阅读本文件、`README.md`、`git-workflow.md`，以及与任务直接相关的领域文档。
2. 课件链路以 `docs/courseware/interactive_html_courseware_workflow_plan.md` 和当前代码为准。README 中若仍有旧的扁平目录示例，不得据此恢复旧结构。
3. 先运行 `git status --short`，确认工作区已有修改。已有修改默认属于用户，不得重置、覆盖或顺手整理无关文件。
4. 先定位真实实现、公开入口、调用者和测试，再修改代码。不要只建立转发文件来冒充物理迁移，也不要复制两份会逐渐分叉的实现。
5. 诊断、审核或规划任务默认只读；只有用户要求实现、修复或更新时才写入文件。

## 2. 项目定位与技术栈

这是一个以知识库、学习者画像和 Agent 工作流为基础的自动化学习资源生产系统。

- 后端：Python 3.11+、FastAPI、LangChain/LangGraph、ChromaDB；当前开发、演示和本轮部署均使用 SQLite。代码保留可选 PostgreSQL 方言分支，但仓库未捆绑驱动，也未完成其迁移与并发验收，不能把它描述为当前生产数据库。
- 前端：Vue 3、Pinia、Element Plus、ECharts、Vite。
- 资源类型包括五类文本学习文档，以及独立的互动 HTML 课件。
- 互动课件追求自动规划、自动生成、自动审核、定向修订、自动降级/隔离和自动发布，不建设管理员或人工审核工作台。

## 3. 当前目录边界

保持 `backend/app` 的既有顶层分层，在每一层内部按业务领域聚合：

```text
backend/app/
├── api/          # HTTP 路由、认证依赖、请求解析和响应映射
├── services/     # 用例编排、事务边界和领域门面
├── agents/       # 模型调用、Agent 节点和工作流编排
├── core/         # 跨领域基础能力和确定性运行时
├── db/           # 会话、仓储和持久化实现
└── models/       # DTO、领域契约和共享枚举
```

主要领域包括 `auth`、`users`、`onboarding`、`learners`、`knowledge`、`generation`、`learning_documents`、`courseware`、`feedback`、`tutor`、`reports`、`reviews`、`runs`、`resource_library` 和 `admin`；某一层没有职责时不必创建空实现。

Agent 目录必须保持以下边界：

- `agents/resource_workflows/learning_documents/`：五类文本学习文档工作流及节点。
- `agents/resource_workflows/interactive_courseware/`：互动课件工作流、状态、专用 Agent、校验和 Worker。
- `agents/learning_agents/`：诊断、反馈、反馈策略和 Tutor 等学习闭环 Agent。
- `agents/shared/`：不依赖具体资源领域的纯共享能力。

前端业务代码归入 `frontend/src/features/<domain>/`。跨资源列表可以位于 `resource-library`，但只能做只读聚合和路由选择，不能拥有生成逻辑。

领域含义不得混淆：

- `generation` 负责文本学习文档的生成任务与进度。
- `learning_documents` 负责五类文本学习文档的读取、发布产物和 Markdown 阅读。
- `courseware` 负责独立的互动课件生成、运行、预览、打包与发布。
- `feedback`、`tutor`、`reports` 属于生成后的学习闭环，不属于课件或学习文档工作流。

## 4. 不可破坏的兼容约束

目录重构和功能更新期间，以下公开契约默认保持不变：

- HTTP 路径、请求/响应 DTO、状态码和认证依赖。
- 容器 provider 名称和既有依赖注入行为。
- 数据库表名、字段语义、存储路径和事件 payload。
- 五类学习文档 `text`、`practice`、`assessment`、`case_study`、`checklist` 的生成、审核、Claim、发布、API 响应和 Markdown 阅读行为。
- 既有错误码、Prompt 版本、工作流节点顺序和路由；若任务只要求迁移路径，不得夹带业务改写。

确需改变公开契约时，必须明确说明影响、同步文档和测试，并在必要时版本化。数据库变更优先使用可回滚、向前兼容的迁移，禁止通过重命名或删除现有表来完成普通目录重构。

同一职责只能有一个真实实现。兼容文件只能做薄转发，并应在调用者全部迁往公开包入口、静态导入扫描和完整回归通过后删除。不要新增新的顶层业务目录来绕过现有分层。

## 5. 互动课件的强制设计规则

### 5.1 自动审核与发布

课件不存在人工审核或管理员审批流程。工作流应完成：准入检查、来源快照、规格规划、场景生成、规则硬门、AI 教学质量审核、定向自动修订、确定性渲染、安全检查、打包和自动发布。

- 可修复问题进入受预算约束的定向修订。
- 达到修订、token、时延或成本上限后，按策略降级、跳过非必需场景、隔离或拒绝；不得无限重试。
- 硬门失败的候选产物不得发布。
- AI 审核不可用时必须执行显式降级策略并记录原因，不得静默把“审核失败”当作“审核通过”。
- 发布必须幂等；失败重试不得产生重复资源、重复事件或相互覆盖的产物。

### 5.2 模型与运行时边界

- 模型只生成经过版本化校验的结构化契约，不得直接输出或控制 HTML、CSS、JavaScript、URL、CSP 或任意组件名。
- 组件必须来自平台维护的注册表；未知组件、未知来源块、危险输出、缺失必需场景或快照版本混用均属于硬门失败。
- `core/courseware/` 拥有确定性 renderer、runtime、安全策略和 packaging；presentation 层不得访问数据库或模型。
- `CoursewareService` 只负责创建/恢复任务、注入仓储和工作流依赖、执行工作流，以及提供查询与发布门面；Prompt、模型调用和工作流节点应留在课件 Agent 工作流中。
- 每个可验证事实和关键交互必须能追溯到冻结来源快照。不得把用户原始敏感数据写入课件、日志或评测 fixture。

### 5.3 可靠性事实不能夸大

本地测试通过不等于生产就绪。报告状态时，应区分：

- 确定性单元/集成/端到端测试；
- 浏览器渲染与交互测试；
- 可选真实模型评测；
- SQLite 单 Durable Worker、租约接管、原子 outbox、故障注入和真实部署证据。

除非代码和测试已经证明，不得声称完整实现了原子 claim、租约、退避/死信、真正的工作流 checkpoint、不可变候选产物、SCORM/xAPI 全兼容或生产级队列。评测不得只检查“拒绝/未拒绝”，还应逐步验证精确状态、硬门、fallback、事件和 artifact hash。

## 6. 编码和命名约定

- 优先使用能表达功能或职责的文件名。领域包内不要无理由新增含义模糊的 `routes.py`、`service.py`、`utils.py`；例如审核接口优先使用 `reviews.py`，但不要为了统一命名而在无关任务中批量改名。
- 外部调用者优先从领域包公开入口导入，避免依赖深层私有实现。
- API 层保持薄：不直接编写 SQL、调用模型或实现工作流节点。
- Service 层协调用例，不拥有 Prompt、渲染器或前端展示逻辑。
- `core` 和 `shared` 不得反向依赖具体业务领域。
- 新的状态变化和事件处理必须考虑幂等键、稳定排序、重试语义、超时和可观测性。
- 修改范围保持聚焦；不要对无关文件运行全仓格式化。
- 注释说明原因和约束，不重复代码表面含义。
- 不提交 `.env`、密钥、数据库、向量索引、日志、依赖目录、测试缓存、临时报告或真实生成资源。

## 7. 验证要求

从仓库根目录执行命令。Windows PowerShell 示例：

```powershell
# 后端依赖
python -m pip install -r backend/requirements.txt

# 后端完整回归
python -m pytest backend/tests -q

# 按测试层级运行
python -m pytest backend/tests -m unit -q
python -m pytest backend/tests -m integration -q
python -m pytest backend/tests -m migration -q
python -m pytest backend/tests -m e2e -q

# 课件冻结评测；报告是本地产物，不要提交
python backend/scripts/courseware_eval.py `
  --manifest backend/tests/fixtures/courseware/evals/manifest.json `
  --baseline backend/tests/fixtures/courseware/evals/baseline.json `
  --output backend/courseware-eval-report.json

# 前端专项与构建
npm --prefix frontend run test:workflow-events
npm --prefix frontend run test:tutor
npm --prefix frontend run test:courseware-browser
npm --prefix frontend run build
```

按改动范围选择最低充分验证：

| 改动范围 | 至少验证 |
|---|---|
| 纯文档 | 链接、路径、命令和完成状态与代码一致 |
| 单个后端领域 | 该领域单元测试及直接相关集成测试 |
| API/DTO/认证 | 单元测试、API 集成测试、状态码和响应 fixture |
| DB/仓储/迁移 | 单元、集成、migration 测试及旧数据兼容 |
| 学习文档工作流或共享能力 | 五类学习文档的工作流、API、Claim、发布和 Markdown 回归；共享改动应运行后端全量测试 |
| 互动课件 | 课件单元/集成/e2e、冻结评测、浏览器测试；涉及共享层时再运行学习文档回归 |
| 前端 | 相关专项测试和 `npm --prefix frontend run build` |
| 目录物理迁移 | 新旧公开导入扫描、受影响领域回归和后端全量测试 |

真实模型测试可能消耗额度且依赖外部服务。只有用户明确要求、运行环境已提供预期凭据时才启用 `RUN_LIVE_LLM=1` 或 `COURSEWARE_LIVE_EVAL=1`；不得打印或提交凭据。若无法运行某项验证，应准确说明未运行原因，不能写成“已通过”。

## 8. 本地运行

```powershell
# 后端
Set-Location backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 另一个终端，从仓库根目录启动前端
npm --prefix frontend run dev
```

修改启动方式、部署配置、环境变量或公开端口时，同步更新 `README.md`、`docs/deployment.md` 和示例环境文件。

## 9. 文档与交付

- API 字段、路径或状态码变化：更新 `docs/api.md`。
- 架构、目录或模块边界变化：更新 `docs/architecture.md` 及相关领域计划。
- 功能范围变化：更新 `docs/features.md`。
- 启动或部署变化：更新 `README.md` 和 `docs/deployment.md`。
- 课件进度文档只保留可验证事实。已实现项可简述，未完成项需说明当前基础、缺口、验收方式及是否依赖生产环境。

交付前必须：检查 `git diff` 和 `git status`；确认没有覆盖用户修改或提交运行时文件；报告实际执行的测试、结果和跳过项；列出仍需真实凭据、CI、浏览器或生产部署才能证明的事项。

Git 分支和提交遵循 `git-workflow.md`。普通功能进入 `feature/<name>`，修复进入 `fix/<name>`，文档进入 `docs/<name>`，工程调整进入 `chore/<name>`；提交信息使用 `type(scope): summary`。除非用户明确要求，不代替用户提交、推送或合并。
