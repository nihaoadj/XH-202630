# 领域知识个性化生成与多智能体协同决策系统

> 提交代码前，请先仔细阅读 [`git-workflow.md`](./git-workflow.md)，并按其中的分支、提交信息和协作规范操作。

题目编号：XH-202630  
文档版本：2.1\
文档核对日期：2026-10-10（T14 整改、依赖门禁与验收记录同步）

本项目面向多领域技能学习者，构建“学习者画像输入 → 能力诊断 → 多 Agent 协同决策 → 个性化资源生成 → 审核纠偏与知识溯源 → 学情报告 → 学习反馈 → 动态调整学习路径”的领域知识个性化生成系统。RAG 工程训练是当前示例知识库和比赛分工中的一个方向，实际生成方向由用户输入的学习主题、学习者画像和所接入的知识库共同决定。

## 项目亮点

- 多智能体协同：基于 LangGraph 实现学情诊断、知识库检索、学习路径规划、个性化资源生成、审核纠偏、反馈决策等 Agent 的协同闭环。
- 证据约束 Tutor：已发布资源与测评题支持多轮启发式导学；提示等级由服务端递进，回答按 Frozen Evidence、SourceRef、受控检索顺序取证，证据不足时安全拒答。
- 反馈真实闭环：服务端判分的正式 Attempt 会原子更新知识点掌握度、画像版本和持久化学习路径；学习者确认下一步方案后创建异步生成任务，并保留父子 Run 来源关系。
- 实时 Agent 轨迹：生成页通过 SSE 只读持久化 WorkflowEvent，支持 queued snapshot、断线续传、事件去重、terminal close 与轮询降级。
- 幻觉防控：引入冻结 Evidence、独立 Claim 抽取/判定、审核纠偏与可复核指标。
- 节点优先检索：带能力目标的请求先在模块级 Chunk—节点映射范围内执行向量、BM25 与精排；无映射或证据不足时自动回退全库检索，底层故障保持原有错误语义。
- 个性化适配：基于学习者画像动态匹配资源难度、生成学习路径与分阶测试。
- 可视化决策：提供 Agent 调度过程、学情报告、资源难度匹配曲线等可视化能力。
- 可回放运行记录：Run 在模型调用前建档，节点 Step/Event/Evidence/Checkpoint 持续落库，可跨进程只读查询并识别中断。
- 互动课件：将单份已发布文本资源转换为结构化、可追溯的互动 HTML；由独立 Durable Worker 执行自动审核、修订和发布。
- 学习工作区：提供五步新建方向、资源生产、专注阅读、测评反馈、学习旅程和动态学情报告；共享响应式外壳与减少动态效果支持。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Vue Router + Pinia + Element Plus + ECharts |
| 后端 API | FastAPI (Python 3.11+) |
| Agent 编排 | LangChain + LangGraph |
| 大模型 | 国产大模型 API（通义千问 / 文心一言 / DeepSeek 等，可配置） |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite（当前开发、演示和部署） |
| 部署 | 本地 Web + 独立课件 Worker + Vite；Dockerfile 仅提供后端 Web 镜像 |

## 快速开始

> 当前代码包含文本生成、互动课件和学习反馈闭环。工程验收以 [统一测试方案](docs/testing/README.md) 为入口；比赛与部署证据见 [Demo Runbook](docs/demo-runbook.md)。P0-09 runtime 的前端检查仅核对源码连线，不能替代统一 acceptance，详见本页“P0-09 比赛验收”。

配置文件默认读取 `backend/.env`，运行时数据统一落在 `backend/data/` 和 `backend/chroma_db/`。  
默认 `KNOWLEDGE_BASE_DIR` 指向 RAG 工程训练示例知识库；接入其他领域时，将该配置改为对应知识库目录即可，后端 Agent 不会把生成方向固定为 RAG。

首次使用需准备 Python 3.11、Node.js 24（工程工具也支持 20.19+ / 22.13+）、npm 和本地 Embedding 模型缓存。从仓库根目录执行（Windows PowerShell）：

```powershell
# 1. 创建虚拟环境，安装前后端依赖并创建 backend/.env；此时不启动服务
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe scripts\start_local.py --install --bootstrap --check

# 2. 编辑 backend/.env，填写 Provider 配置，并准备本地模型缓存
# 首次初始化知识库、目录、问卷、诊断题与示例画像；已有数据时按部署说明处理
.\.venv\Scripts\python.exe scripts\start_local.py --initialize --check

# 3. 启动 Web、互动课件 Durable Worker 与前端
.\.venv\Scripts\python.exe scripts\start_local.py
```

便携式 Windows 环境将 `.venv\Scripts\python.exe` 换为 `.venv\python.exe`；Linux/macOS 使用 `.venv/bin/python`，完整首次准备命令见 [部署说明](docs/deployment.md)。`--check` 只检查本地启动前置条件；运行时依赖 readiness 使用 `python scripts/check_environment.py` 检查。后续文档中的 `python` 命令均应在项目虚拟环境内执行。

启动器会等待后端 `/health` 与课件 Worker `/health/ready`，并把日志写入 `backend/logs/`。互动课件 Worker 默认在 `127.0.0.1:8081` 提供 `/health/live`、`/health/ready` 和安全的 `/metrics`；Web 进程不会自动启动它。当前 SQLite Worker 每轮只 claim 一个任务，`COURSEWARE_WORKER_BATCH_SIZE` 大于 `1` 会被安全归一为 `1`，不能作为并发或横向扩容手段。

完整的一键启动、首次安装、手动三进程启动、Worker 健康检查、停机和 SQLite 数据保护方案见 [部署说明](docs/deployment.md)。

知识索引异常后，可按知识库 ID 显式重新入库并对账 SQL/Chroma：

```bash
python scripts/ingest_knowledge.py --knowledge-base-id rag_engineering_training
```

运行模式和退出语义：

| 模式 | degraded fallback | 存储建议 | 启动/生成语义 |
|---|---|---|---|
| `development` | 默认禁止，可显式开启 | SQLite | not-ready 时保留 `/health`，生成返回 503 |
| `demo` | 仅显式 `ALLOW_DEGRADED_GENERATION=true` | SQLite | fallback 必须标记 degraded |
| `production` | 永远禁止 | SQLite | 核心依赖或默认 KB not-ready 时 fail-fast；同一数据库只运行一个 Durable Worker |

`scripts/check_environment.py` 不调用计费 LLM、不下载 Embedding，退出码为 0=ready、2=degraded、1=not-ready。公共 `/health` 与 `/health/ready` 只检查默认 KB 和核心依赖；其他 KB 的异常不会轻易把整个服务变成 503。全 KB 详情位于 token 保护的管理员接口，见 `docs/api.md`。

当前项目不依赖 PostgreSQL。代码中保留的 PostgreSQL 方言分支仅是可选兼容基础，仓库未捆绑 PostgreSQL 驱动，也没有完成真实迁移和并发验收；以后若更换数据库，必须先单独立项并更新部署文档，不能直接把兼容分支视为已支持的生产方案。

数据库迁移或比赛联调前，可在项目根目录执行只读完整性预检：

```powershell
python scripts/check_database_integrity.py
```

该脚本检查 SQLite 外键开关、现有 FK 违规、资源版本重复/NULL、数据库唯一约束和 Resource 到 Run、Step、父版本的真实外键。退出码为 0=ready、2=约束缺失警告、1=存在阻塞迁移的数据问题；脚本不会修改或删除数据。

`LLM_STRUCTURED_OUTPUT_MODE=auto` 会先尝试 function calling。若所用 OpenAI-compatible 服务明确不支持该能力，请在本地 `.env` 显式设为 `text`，避免每个 Agent 固定产生一次 BAD_REQUEST 后再回退；不要提交真实 `.env` 或 API Key。

生成 Agent 与独立交互式 Tutor 统一通过可注入的 `LLMGateway` 调用模型。Tutor 不进入资源生成 LangGraph，也不直接修改画像、掌握度、路径或资源。默认 Tutor 请求预算为 25 秒、最近上下文 6 轮、Evidence 4 条、最高提示等级 3。结构化输出和 Evidence ID 子集均会严格校验。配置项及模式说明见 `backend/.env.example` 和 `docs/deployment.md`。

## 后端目录说明

```text
backend/
├── app/
│   ├── api/<domain>/              # HTTP 路由、认证依赖、请求解析与响应映射
│   ├── services/<domain>/         # 用例编排、事务边界和领域门面
│   ├── agents/                    # 学习 Agent、资源工作流和共享 Agent 能力
│   ├── core/                      # 课件运行时、LLM、事件、检索、安全和存储等基础能力
│   ├── db/<domain>/               # SQL/内存仓储、迁移和共享数据库能力
│   ├── models/<domain>/           # DTO、领域契约和共享枚举
│   ├── utils/                     # 通用内部工具
│   ├── config.py                  # 应用配置
│   ├── containers.py              # 依赖注入组合根
│   └── main.py                    # FastAPI 入口
├── scripts/                      # 独立课件 Worker、冻结评测与比赛评测工具
├── tests/                        # 分层测试套件
│   ├── unit/                    # Agent、核心组件、模型契约与纯策略
│   ├── integration/             # API、持久化、服务与工作流集成
│   ├── migrations/              # 数据库迁移与历史兼容性
│   ├── e2e/                     # 生命周期、重启、恢复与回放
│   ├── live/                    # 显式启用的真实 Provider 冒烟测试
│   ├── fakes/                   # 共享测试替身
│   └── fixtures/                # 固定验收数据
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
│   ├── public/                  # 品牌图片、字体等静态资产
│   ├── src/
│   │   ├── api/                 # axios 接口封装
│   │   ├── components/          # PreparationPanel、PreparationWorkspace 等共享展示
│   │   ├── features/<domain>/   # 按领域组织的页面与交互逻辑
│   │   ├── router/              # Vue Router 路由配置
│   │   ├── stores/              # Pinia 全局状态
│   │   ├── styles/             # 认证与学习工作区主题
│   │   ├── ui/                 # 页面与模块公共动效
│   │   ├── utils/              # 事件归并、资源排序等工具
│   │   ├── App.vue             # 公共页、学习外壳与专注模式分支
│   │   └── main.js
│   ├── tests/                  # 9 项 Node 单元专项与 13 项浏览器专项
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
│   ├── features.md
│   ├── deployment.md
│   ├── testing/                 # 工程、浏览器与比赛评测说明
│   └── ...
├── scripts/                     # 初始化与辅助脚本
│   ├── ingest_knowledge.py
│   ├── init_db.py
│   ├── start_local.py
│   ├── run_tests.py
│   └── check_environment.py      # 只读、脱敏的运行环境检查
├── tests/suites.json            # 测试套件与前端分组的唯一清单
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

## 测试运行

完整的层级、功能覆盖矩阵、数据/证据规范见 [项目测试方案](docs/testing/README.md)，比赛54用例、来源快照与三指标口径见 [比赛评测方案](docs/testing/competition.md)。统一入口按套件运行，默认关闭真实模型调用，每次输出独立日志、JUnit 和 JSON/Markdown 摘要：

```powershell
python scripts/run_tests.py --list
python scripts/run_tests.py --profile quick
python scripts/run_tests.py --profile regression
python scripts/run_tests.py --profile acceptance
python scripts/run_tests.py --suite backend-api --suite backend-migration
```

`quick` 用于快速定位；`regression` 包括 Ruff、全前端 ESLint、请求上下文 JSDoc 类型检查、Python 声明/锁/环境检查、后端全量、比赛金标、课件冻结评测、前端九项单元与构建；`acceptance` 追加十三项实际浏览器专项。产物位于 `output/test-runs/`，原浏览器截图路径保留。临时目录/cache 隔离到本次报告；离线金标和冻结回放的 PASS 不能当作正式模型质量成绩。

安装入口、CI 和 Docker 消费 `backend/requirements.lock.txt`（精确版本与 SHA256），工程工具单独锁在 `backend/requirements-dev.lock.txt`；前端使用 `npm ci`。更新依赖后重新生成锁文件，再运行 `python scripts/check_dependencies.py` 与 `python -m pip check`。锁文件再生成命令见 [部署说明](docs/deployment.md)，不会自动升级正在运行的服务。

后端测试按执行层级分类，并由 `backend/tests/conftest.py` 自动添加 pytest marker：

```powershell
python -m pytest
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m migration
python -m pytest -m e2e
```

真实 LLM 测试默认跳过，必须显式启用：

```powershell
$env:RUN_LIVE_LLM = "1"
python -m pytest -m live_llm
```

互动课件改动还应执行冻结评测、浏览器质量门和前端构建：

```powershell
python backend/scripts/courseware_eval.py `
  --manifest backend/tests/fixtures/courseware/evals/manifest.json `
  --baseline backend/tests/fixtures/courseware/evals/baseline.json `
  --output backend/courseware-eval-report.json
npm --prefix frontend run test:courseware-browser
npm --prefix frontend run test:workflow-events
npm --prefix frontend run test:tutor
npm --prefix frontend run build
```

初始首页与账号弹窗的浏览器专项使用隔离的 fixture HTTP 服务，不向实际后端登录或注册用户。先构建，再运行：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:landing-browser
```

Windows 默认使用本机 Microsoft Edge，其他平台默认使用 Playwright Chromium；可通过 `LANDING_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 选择通道，空字符串使用 Chromium。浏览器无法启动时检查失败，不会作为跳过通过。截图和 `summary.json` 位于 `frontend/tests/test-results/landing-ui/`（本地验收产物，不进入版本控制）。六屏桌面主截图为 `1886×1290`；检查各屏完整占满视口、上下滚轮与键盘/页码平滑切换、hash/历史导航，以及宽屏、窄屏、低高度及相当于 200% 桌面缩放的 CSS 布局视口，后者不代表原生浏览器缩放操作验收。

首页前两屏后依次展示协作星图、证据档案、成长航线与反馈进阶，上下滑动切换；第二屏卡片可直接定位章节，顶栏随章节配色。`/#multi-agent`、`/#evidence`、`/#learning-path`、`/#feedback-loop` 支持直达，旧 `/features/*` URL 重定向至相应章节。四屏以本地机制示意介绍真实 Agent 分工、Claim 审计来源链、默认 RAG 知识图谱和正式反馈规则，不展示实际文档、个人结果或实时任务，不创建账号或生成任务。专项同样读取构建产物并使用隔离 fixture 服务：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:feature-showcase-browser
```

特色专项沿用上述平台默认通道，可通过 `FEATURE_SHOWCASE_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 覆盖；覆盖章节 hash 和旧 URL 兼容、刷新与历史导航、四个场景各七种视口、顶栏主题与对比度、Agent 分工/可选 Claim（五步各约1.8秒、单角色/对应连线选中态及等角对称分布）、三种 Claim 判定与溯源字段、三种诊断定阶起点和反馈补救/强化/推进规则。证据章节检验两轮自然12秒循环、光点路径与说明无遮挡、来源到左侧第四步的完整行程、终末到达才亮起结果，以及无依据时从证据直达判定且来源未绑定。路线的13个节点及15条先修关系直接对照仓库默认知识库metadata校验。反馈章节使用抽象学习节点A、B，自动慢速循环当前规则；专项覆盖无点击启动、完整重复、鼠标切换后自动播放、路线标识与阶段进度同步及完整到达、暂停/继续不重启进度、键盘焦点暂歇、离屏/遮罩/隐藏、运行时减少动态效果和卸载清理，保留零业务写请求及关键文字对比度检查。报告与截图位于 `frontend/tests/test-results/feature-showcase/`，桌面主截图为 `1886×1290`，自然等到结果再明确暂停演示或静态展示，等待字体和入场动画停稳截取；动态行为单独验证。

`backend/courseware-eval-report.json` 等评测报告和浏览器证据为本地产物，不应提交。`pytest-asyncio` 已列入 `backend/requirements.txt`，以确保全新环境能收集异步报告流测试。

学习工作台专项使用构建产物与隔离 API fixture，浏览器通道沿用平台默认，可通过 `DASHBOARD_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 覆盖；覆盖桌面一屏完整显示与禁止滚动、响应式及长内容阅读、画像切换/分页/持久化/请求竞态、摘要及左右分区对齐、三个推荐分支、入口路由、八个学习页侧栏一致性、五导航均匀分布、收起/展开中间帧及快速反向/路由/窗口/减少动态效果取消、键盘焦点和文字对比度，不向实际后端写入业务数据：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:dashboard-browser
```

截图和 `summary.json` 位于 `frontend/tests/test-results/dashboard-ui/`（本地验收产物，不进入版本控制）。

新建方向页的浏览器专项通过隔离 HTTP fixture 驱动领域、方向、问卷、诊断与资源确认五步，不连接实际后端或创建真实业务记录：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:onboarding-browser
```

专项覆盖桌面、平板、手机、横屏与短窗口，检查领域/方向在内容完整容纳时桌面固定一屏且禁止滚动、窗口与侧栏变化重测、问卷区域内部滚动且标题/步骤固定、切步重置题区，以及长目录/极低窗口可达，保留选项与条件题、诊断复测/跳过、推荐节点、资源选择、Claim 请求拆分、提交加载/错误反馈、步骤切换焦点与答案、文字对比度检查。截图和 `summary.json` 位于 `frontend/tests/test-results/onboarding-ui/`；Windows 默认使用 Edge，可通过 `ONBOARDING_BROWSER_CHANNEL` 或统一 `TEST_BROWSER_CHANNEL` 选择通道，浏览器不可启动时失败。

资源生产页的专项使用隔离 HTTP/SSE fixture，保留现有任务与接口语义，不向真实后端提交生成或发布请求：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:generation-browser
```

验证任务状态、画像/批次与资源切换、刷新、重试、追加资源和 Claim 发布决策、学习路由及课件嵌入；检查桌面内容完整容纳时固定框架且过程/预览各自滚动，窄屏和短窗口自然回退、键盘焦点与按钮可达性。同一专项还覆盖 `/resources` 文本阅读页的资源架切换、下载目标、刷新、Tutor 入口、专注模式进出与文档切换，以及桌面/手机按钮可见性、对比度和焦点。证据位于 `frontend/tests/test-results/generation-ui/`；Windows 默认使用 Edge，可通过 `GENERATION_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 选择通道。

学习反馈页浏览器专项使用独立本地 API fixture，不提交真实反馈或资源生成请求；只允许 fixture 接收测评提交与下一步选择：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:feedback-browser
```

专项覆盖桌面展开/收起与手机布局、无可用批次、测评前状态、单选/多选/问答、未完成时禁用提交、反思字段 payload、反馈小结与逐题结果、纠错及新节点选择、下一步确认和原 `/generate` 路由，并检查 44px 操作目标、横向溢出、选中对比度、键盘焦点与减少动态效果。截图和 `summary.json` 位于 `frontend/tests/test-results/feedback-ui/`；Windows 默认使用 Edge，可通过 `FEEDBACK_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 选择通道。

学习历史、学习报告、用户资料、四页画像请求归属及页面动效专项都使用本地 HTTP fixture。先构建后可单项运行；聚合浏览器入口会执行全部十三项专项：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:history-ui-browser
npm --prefix frontend run test:report-ui-browser
npm --prefix frontend run test:user-profile-ui-browser
npm --prefix frontend run test:profile-request-browser
npm --prefix frontend run test:motion-browser
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

学习历史专项覆盖画像筛选、分页、状态/时间筛选、未关联事件和删除后自动加载替代画像；学习报告专项核对四图的数据/颜色/字号与 ECharts 节点框和标签在桌面及 375px 屏幕内完整可见，并保留图表交互与 SSE/ETag；用户资料专项核对字段与保存行为、布局和主题路由行为。画像请求专项覆盖四页画像切换的慢响应竞态和失败归属。各专项不访问真实后端或真实模型；报告不依赖 ignored reference 文件，页面证据保存在 `frontend/tests/test-results/{history-ui,report-ui,user-profile-ui}/`，画像请求证据在 `frontend/tests/test-results/ui-repair/profile-requests/`。

## 核心指标

以下是比赛目标；离线金标回归、页面展示或工程检查通过均不代表真实模型已达标。统计口径与证据要求见 [比赛评测方案](docs/testing/competition.md)。

- 专业知识幻觉率 < 5%
- 学习者画像-资源难度适配准确率 ≥ 85%
- 核心知识点覆盖率 ≥ 90%

## 协作开发入口

当前代码与文档入口：

- [功能与页面](docs/features.md)：当前功能边界、真实路由和前端交互。
- [总体架构](docs/architecture.md)：系统分层、模块职责、运行路径和主流程。
- [工程质量优化记录](docs/engineering-quality-update.md)：T13 结构、规范及复杂度调整的实际范围、兼容证据与分步验收。
- [API 契约](docs/api.md)：认证、HTTP/DTO、反馈证据入口和事件。
- [知识库与数据库](docs/knowledge_base_database.md)：源文件、问卷、诊断与持久化。
- [部署说明](docs/deployment.md)：首次安装、三进程启动、Worker 健康检查与停机。
- [测试方案](docs/testing/README.md)：套件、浏览器专项与证据边界。
- [Git 规范](git-workflow.md)：分支、提交信息、禁止提交内容和文档同步规则。
- [Demo Runbook](docs/demo-runbook.md)：比赛 fixture、主 Demo、故障恢复与人工 checklist。
- [本次文档同步核对](docs/documentation-sync.md)：同步依据、修正内容与代码侧遗留问题。

`docs/update_plan/` 保存本地计划与 `archive.md` 历史摘要，详细计划保留最近两次（T13、T14，含 T13 分步记录）。该目录为本地资料，已由 Git 忽略；可分发的更新结果见 [T13 实施记录](docs/engineering-quality-update.md) 和 [T14 实施记录](docs/engineering-quality-optimization.md)，当前功能状态以源码及专题文档为准。

## P0-09 比赛验收

P0-09 固定离线 fixture 不调用收费 Provider；只读 preflight 检查配置中的数据库、默认知识库与构建产物：

初始化、完整性检查、检索与 P0-09 脚本已使用当前领域包路径（`db/shared`、`core/retrieval`、`services/reports`）；CLI 参数不变。互动课件评测的业务执行器位于 `backend/scripts/courseware_harness/`，继续通过原 `backend/scripts/courseware_eval.py` 入口运行。导入检查不等于数据库检查；初始化和 preflight 应针对预期数据目录执行。

```powershell
python scripts/p0_09_preflight.py --output wzx/out/p0-09-preflight.json
python scripts/run_p0_09_acceptance.py --offline --output wzx/out/p0-09-offline-manifest.json
```

`scripts/run_p0_09_acceptance.py --runtime` 已按 `features/<domain>/` 更新源码检查，仍不替代实际浏览器交互验收。该模式通过 TestClient 启动 FastAPI lifespan，会触发正常数据库初始化与启动对账，并非全程只读。工程验证使用 `python scripts/run_tests.py --profile acceptance`，目标环境 readiness 与真实业务闭环按 Runbook 单独核对。

状态只使用 `PASS`、`FAIL`、`SKIP`、`NOT_MEASURABLE`；小型 fixture 的实际值不等于正式统计达标。Live Provider 测试必须显式设置 `RUN_LIVE_LLM=1`，并与 deterministic offline 结果分开报告。
