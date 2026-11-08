# 领域知识个性化生成与多智能体协同决策系统

T42 修复续作：新中立任务冻结 locator-v2，实际执行编辑比例、信息量和计算上限；旧任务继续按 locator-v1 回放。匹配成功以正确定位并回写真实原文为准，保留受限错字容错，不新增 Judge/来源核对调用。冻结 Prompt/schema 在新请求前验证，失败诊断有界持久化且不可改删。当前 E11 评测使用 source_locating_v2 的分离来源组；原数据保留为历史回归，不再用作独立验收证据。

> 提交代码前，请先仔细阅读 [`git-workflow.md`](./git-workflow.md)，并按其中的分支、提交信息和协作规范操作。

题目编号：XH-202630  
文档版本：2.1\
文档核对日期：2026-10-27（资源审核规范化与私有审计更新）

本项目面向多领域技能学习者，构建“学习者画像输入 → 能力诊断 → 多 Agent 协同决策 → 个性化资源生成 → 审核纠偏与知识溯源 → 学情报告 → 学习反馈 → 动态调整学习路径”的领域知识个性化生成系统。RAG 工程训练是当前示例知识库和比赛分工中的一个方向，实际生成方向由用户输入的学习主题、学习者画像和所接入的知识库共同决定。

## 项目亮点

- 多智能体协同：基于 LangGraph 实现学情诊断、知识库检索、学习路径规划、个性化资源生成、审核纠偏、反馈决策等 Agent 的协同闭环。
- 证据约束 Tutor：已发布资源与测评题支持多轮启发式导学；按Frozen Evidence、SourceRef、缺失时受控检索的原顺序取证，仅保留生成契约优化：正文与内部引用分离、证据不足可拒答。
- 反馈真实闭环：服务端判分的正式 Attempt 会原子更新知识点掌握度、画像版本和持久化学习路径；学习者确认下一步方案后创建异步生成任务，并保留父子 Run 来源关系。
- 实时 Agent 轨迹：生成页通过 SSE 只读持久化 WorkflowEvent，支持 queued snapshot、断线续传、事件去重、terminal close 与轮询降级。
- 幻觉防控：引入冻结 Evidence、独立 Claim 抽取/判定、审核纠偏与可复核指标。
- 节点优先检索：带能力目标的请求先在模块级 Chunk—节点映射范围内执行向量、BM25 与精排；无映射或证据不足时自动回退全库检索，底层故障保持原有错误语义。
- 跨语言候选保护：知识库可配置有界英文术语提示，精排始终对照原问题；全局候选池为纯向量结果保留语言无关名额，避免被RRF在精排前全部挤出。默认精排预算仍为20，不强制英文比例，不调用LLM翻译或重新入库。
- 英文选材偏好（T17）：原相关性>=0.35的可信英文片段可获0.08选材加分，原始分数及门槛不变。T29新学习路径让完整20候选先参与校验/去重/来源选材，单查询默认最多6、多个查询全局最多8，不提前按owner截6；旧Tutor/E1仍用原配额。不保证每题出现英文，`RETRIEVAL_ENGLISH_SCORE_BONUS=0`关闭偏好。
- 学习检索细化（T29）：节点任务细化为原理/区别、操作验证/边界问题，最多6查询；选材先保护节点，再软保留合格原文、限制教材和单文档集中度。仅legacy学习文本文档生效，`LEARNING_RETRIEVAL_REFINEMENT_ENABLED=false`恢复旧逻辑；不换模型、不重建索引。
- 内容去冗余（T19）：最终可信SQL候选在节点/资源分配前识别长文本完全重复和同源高度近似片段，按原选材顺序保留强者、以其余合格候选补位。独有节点/资源用途受保护，不重写来源、不删除原文、不额外调用模型；可用`RETRIEVAL_REDUNDANCY_ENABLED=false`关闭。
- 个性化适配：基于学习者画像动态匹配资源难度、生成学习路径与分阶测试。
- 可视化决策：提供 Agent 调度过程、学情报告、资源难度匹配曲线等可视化能力。
- 可回放运行记录：Run 在模型调用前建档，节点 Step/Event/Evidence/Checkpoint 持续落库，可跨进程只读查询并识别中断。
- 文本持久投递：冻结请求与画像随任务落库，独立单实例 Worker 领取；执行前退出可恢复，执行中断后以关联的新尝试重试。
- 单份失败资源重生成：复用原画像、诊断、计划与冻结证据，从资源生成处创建同批次的新尝试；保留旧版本及审核记录，不再自动从学情诊断重跑。缺少可信历史上下文会明确拒绝，批量重生仍走完整流程。
- 互动课件：将单份已发布文本资源转换为结构化、可追溯的互动 HTML；由独立 Durable Worker 执行自动审核、修订和发布。
- 学习工作区：提供五步新建方向、资源生产、专注阅读、测评反馈、学习旅程和动态学情报告；共享响应式外壳与减少动态效果支持。

知识库资料按教材、中文/英文官方原文及许可分层，见[资料入口](knowledge_base/rag_engineering_training/README.md)。六章教材修订为 `teaching-2026-10-v2`；多语言索引使用 `BAAI/bge-m3` dense（生成与精排模型不变），旧SQL/Chroma保留。换模与新资料入库流程、实际状态及回滚边界见[数据库说明7.7](docs/knowledge_base_database.md#77-多语言embedding与受控重建t112026-10-27)。

全库分类型清洗提供文件候选构建入口`scripts/knowledge_corpus_cleaning.py`；T28已激活T27教学单元v2资料并完成本机入库，62篇/1121片（六教材44片），900字符目标/1200软限/100重叠，纯辅助URL移入独立元数据。SQL/Chroma均ready且ID/正文/完整metadata一致；bge-m3模型、端口与配置路径未变。原始资料、旧SQL版本及冻结Evidence保留；旧3177片输入可由`provenance/evidence-base`重放，再经`cleaning-base`追溯更早采集基线。父级回填未启用，Evidence摘录仍最多1200字符。构建与入库仍是两个明确步骤，见[部署说明3.2–3.5](docs/deployment.md)。

本地数据同步边界：Git 拉取只更新代码和知识源文件，不更新实际 SQLite 或 Chroma。旧 BGE-zh 运行库首次换模可使用 `scripts/rebuild_multilingual_index.py` 的 `prepare-model`、`build`、`audit`，当前支持冻结的 62 篇 / 1121 片 evidence-v2 快照并核对完整 hash；先在新库验证，再成组切换本机 `.env`，保留旧库和索引。已有目标时禁止重复 `build` 或删除数据重来；具体流程见[多语言换模与入库](docs/deployment.md#多语言embedding换模与资料入库)。便携式项目环境使用 `.venv/python.exe`，不要用全局 Python 的依赖状态替代项目环境验收。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Vue Router + Pinia + Element Plus + ECharts |
| 后端 API | FastAPI (Python 3.11+) |
| Agent 编排 | LangChain + LangGraph |
| 大模型 | 国产大模型 API（通义千问 / 文心一言 / DeepSeek 等，可配置） |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite（当前开发、演示和部署） |
| 部署 | 本地 Web + 文本 Worker + 课件 Worker + Vite；Dockerfile 仅提供后端 Web 镜像 |

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

# 3. 启动 Web、文本 Worker、互动课件 Worker 与前端
.\.venv\Scripts\python.exe scripts\start_local.py
```

便携式 Windows 环境将 `.venv\Scripts\python.exe` 换为 `.venv\python.exe`；Linux/macOS 使用 `.venv/bin/python`，完整首次准备命令见 [部署说明](docs/deployment.md)。`--check` 只检查本地启动前置条件；运行时依赖 readiness 使用 `python scripts/check_environment.py` 检查。后续文档中的 `python` 命令均应在项目虚拟环境内执行。

SQLite 启动器会等待后端 `/health`、课件 Worker（`127.0.0.1:8081`）与文本 Worker（`127.0.0.1:8082`）的 `/health/ready`，日志写入 `backend/logs/`。Web 不执行这两类长任务；两个 Worker 各自并发 1。文本 Worker 按数据库文件加单实例进程锁，`GENERATION_DISPATCH_MODE=worker` 为 SQLite 必需配置。memory 模式保留非持久 `BackgroundTasks`，启动器自动跳过文本 Worker。

完整的一键启动、首次安装、手动四进程启动、Worker 健康检查、升级与 SQLite 数据保护方案见 [部署说明](docs/deployment.md)。

知识索引异常后，可按知识库 ID 显式重新入库并对账 SQL/Chroma：

```bash
python scripts/ingest_knowledge.py --knowledge-base-id rag_engineering_training
```

运行模式和退出语义：

| 模式 | degraded fallback | 存储建议 | 启动/生成语义 |
|---|---|---|---|
| `development` | 默认禁止，可显式开启 | SQLite | not-ready 时保留 `/health`，生成返回 503 |
| `demo` | 仅显式 `ALLOW_DEGRADED_GENERATION=true` | SQLite | fallback 必须标记 degraded |
| `production` | 永远禁止 | SQLite | 核心依赖或默认 KB not-ready 时 fail-fast；同一数据库每类只运行一个 Worker |

`scripts/check_environment.py` 不调用计费 LLM、不下载 Embedding，退出码为 0=ready、2=degraded、1=not-ready。公共 `/health` 与 `/health/ready` 只检查默认 KB 和核心依赖；其他 KB 的异常不会轻易把整个服务变成 503。全 KB 详情位于 token 保护的管理员接口，见 `docs/api.md`。

当前项目不依赖 PostgreSQL。代码中保留的 PostgreSQL 方言分支仅是可选兼容基础，仓库未捆绑 PostgreSQL 驱动，也没有完成真实迁移和并发验收；以后若更换数据库，必须先单独立项并更新部署文档，不能直接把兼容分支视为已支持的生产方案。

数据库迁移或比赛联调前，可在项目根目录执行只读完整性预检：

```powershell
python scripts/check_database_integrity.py
```

该脚本检查 SQLite 外键开关、现有 FK 违规、资源版本重复/NULL、数据库唯一约束和 Resource 到 Run、Step、父版本的真实外键。退出码为 0=ready、2=约束缺失警告、1=存在阻塞迁移的数据问题；脚本不会修改或删除数据。

`LLM_STRUCTURED_OUTPUT_MODE=auto` 会先尝试 function calling。若所用 OpenAI-compatible 服务明确不支持该能力，请在本地 `.env` 显式设为 `text`，避免每个 Agent 固定产生一次 BAD_REQUEST 后再回退；不要提交真实 `.env` 或 API Key。

配置模板使用百炼兼容模式（`LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`）与 `LLM_MODEL=deepseek-v4.1-flash`，实际运行以本机 `.env` 为准；Embedding仍是BGE-M3，精排配置不变。修改模型后重启Web/Worker即可，不需要重新入库；日常启动不要加`--initialize`。健康检查不调用计费LLM，不代表模型权限或实际生成质量已经验证。

生成 Agent 与独立交互式 Tutor 统一通过可注入的 `LLMGateway` 调用模型。Tutor 不进入资源生成 LangGraph，也不直接修改画像、掌握度、路径或资源。默认Tutor单阶段生成预算25秒/4096输出tokens、最近6轮/Evidence4条/最高提示3，保留原网关重试与错误语义，不再独立审核或拆分预算。保留生成契约：正文不报内部证据清单，引用ID仅用于结构字段，允许证据不足时空引用安全拒答。auto在Tutor内直接使用JSON文本+严格schema解析，显式协议及其他Agent不变；不保证事实支持性已被验证。

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
├── scripts/                      # 独立文本/课件 Worker、冻结评测与比赛评测工具
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
│   │   ├── api/                 # 共享 Axios 客户端与旧入口兼容导出
│   │   ├── components/          # PreparationPanel、PreparationWorkspace 等共享展示
│   │   ├── features/<domain>/   # 按领域组织的页面与交互逻辑
│   │   ├── router/              # Vue Router 路由配置
│   │   ├── stores/              # Pinia 全局状态
│   │   ├── styles/             # 认证与学习工作区主题
│   │   ├── ui/                 # 页面与模块公共动效
│   │   ├── utils/              # 事件归并、资源排序等工具
│   │   ├── App.vue             # 公共页、学习外壳与专注模式分支
│   │   └── main.js
│   ├── tests/                  # Node 单元与浏览器专项，成员以 tests/suites.json 为准
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

Windows中文项目路径：当前锁定的`chroma-hnswlib 0.7.6`由检索入口适配原生文件路径编码，无需搬项目或更换Embedding。若旧索引报`Cannot open header file`，先停服并备份SQLite/Chroma，再从保留知识库资料重建；不要仅凭`count`判断索引健康。详见[知识库中文扩容与持久化说明](docs/knowledge_base_database.md#74-官方中文完整资料扩容)。系统ANSI代码页不能表示的路径字符仍需避免。

T9知识库资料现按 `teaching/zh`、`references/{zh,en}`、`licenses/`、`provenance/` 直接存放，没有旧目录别名。离线源文件核验统一运行 `\.venv\Scripts\python.exe scripts\prepare_knowledge_sources.py --check`；路径与旧SQL/Chroma索引边界见[当前资料布局](docs/knowledge_base_database.md#75-t9当前物理目录与准备入口)。

| 目录/文件 | 用途 | 是否进入版本控制 |
|-----------|------|------------------|
| `.venv/` | 项目根目录下的本地 Python 虚拟环境 | 否 |
| `backend/data/domain_knowledge.db` | SQLite 数据库文件 | 否 |
| `backend/data/generated_resources/` | 运行时生成的资源文件 | 否（保留目录结构） |
| `backend/chroma_db/` | ChromaDB 向量索引 | 否（保留目录结构） |
| `backend/logs/` | 应用日志文件 | 否（保留目录结构） |
| `examples/` | 示例学习者画像等静态示例数据 | 是 |
| `knowledge_base/` | 领域知识库原文档 | 是 |

### 可选资源证据分配（E1）

`RESOURCE_AWARE_RETRIEVAL_ENABLED=false` 默认沿用原检索。启用后，新普通文本 Run 冻结 `resource-aware-v1`：公共查询优先，五类资源按用途补充查询，分配同一批 Evidence 中的公共／专属 ID；Planner 一次读取完整最终证据，生成、来源投影、审核、Claim 与修订均使用各资源原 spec 的证据范围。缺类型及内部纠错包继续旧策略；不改变工作流节点和公开请求限制。

普通资源审核采用静态版本化 profile 和独立规则构建器。实操通过 V3 结构检查后，每份增加一次模型语义审核，代码与非代码均适用；不可用或无效结果保持未发布，`include_review=false` 仍只生成草稿。结构通过不表示代码或操作已执行。

`ASSESSMENT_REVIEW_STRATEGY=two_stage_v1` 默认保留测评逐题范围及整卷两阶段；`combined_v2` 已交付为候选，真实模型质量对照尚未执行，当前未启用。候选必须配置已核实的 `ASSESSMENT_REVIEW_CONTEXT_TOKENS`，完整输入和输出预留超窗口时零调用、保持未发布。策略在 Run 创建时冻结，公开请求不能覆盖。配置、评测前置门及回滚见 [部署说明](docs/deployment.md)。

从仓库根执行 `python scripts/run_tests.py --suite resource-review-focused --suite resource-review-eval --output output/test-runs/resource-review-check` 可运行专项和 60 份合成资源的离线回放。输出目录须为空；默认不读取模型凭据或联网，报告只证明 fixture 契约与策略，不能证明真实模型质量。私有调用、完整 findings 和可空用量通过步骤 JSON 持久化，公开 trace 的单调用字段含义保持。

独立查询预算 `RESOURCE_AWARE_RETRIEVAL_MAX_QUERIES=10`，精排最多20个唯一chunk且每owner最多top_k，最终证据数及摘录上限仍由原配置控制（默认8条×1200字符）。启用前必须明确填写 `RESOURCE_AWARE_PLANNER_CONTEXT_TOKENS` 为部署模型窗口；完整 messages、schema 和1024预留的UTF-8字节数作为保守 token 估计，与 `RESOURCE_AWARE_PLANNER_INPUT_BUDGET_TOKENS=32768` 和实际输出预留核对。未配置窗口／超预算沿原严格失败或显式规则降级，不删证据。策略在实际执行建立 Run 时冻结，尚在队列中的 job 仍按执行时配置选择；关闭开关不改历史 Evidence/spec。已实施功能和验证结果见 [项目更新说明](docs/project-update-2026-10-26.md)；详细计划与证据保留在本地，真实模型质量、时延及净成本尚待另行授权对照，保持默认关闭。

### 可选 Claim 缺证补检（T50）

`include_claim_evidence_retrieval=false` 为默认值；只有显式开启并同时满足 `include_claim_check=true`、`include_review=true` 才会在首次 Claim 判定后，对**首次 `not_in_evidence` 的事实 Claim** 追加一次知识库补检与重判。原 `supported`/`contradicted`/非事实判定、正文、spec、allocation 与证据快照均不变；全部预期批次成功后才原子激活，指标以全部事实 Claim 为分母。新反证/来源冲突会永久阻断该资源版本发布（用户确认不能清除），进行中或中断的版本同样保持未发布；所有自动收尾、用户确认、事件重放与仓储写入共用同一持久 guard。新增摘录只通过受控 child evidence scope 进入返工版本的生成、引用校验、普通审核与 Claim 抽取/判定；单资源重试遇到补证上下文时显式拒绝而不是静默降级。

只读摘要：`GET /api/runs/{run_id}/claim-evidence-retrieval`。专项命令：`python scripts/run_tests.py --suite claim-evidence-retrieval-unit --suite claim-evidence-retrieval-persistence --suite claim-evidence-retrieval-workflow --suite claim-evidence-retrieval-recovery --suite claim-evidence-retrieval-api --suite claim-evidence-retrieval-compat --output output/test-runs/t50-check`（前端另跑 `claim-evidence-retrieval-ui`/`-browser`）。全部模型为 mock/scripted；真实召回、误放率、费用与最坏时延未验证，不能把离线通过当作质量或生产就绪结论。设计与证据见 [T50 计划](docs/update_plan/T50.md)。

## 测试运行

Claim 中立抽取默认 `CLAIM_EXTRACTION_STRATEGY=neutral_estimate_v1`，使用无外部资产的字符估算：ASCII/CJK/其他Unicode系数0.3/0.6/1，完整实际请求统一增加15%余量，每消息8和请求128的包装余量只计一次。无需tokenizer下载、PROFILE路径/ID或校准PASS。短文单批、长文按需分批、程序汇总，同资源一次原Judge；无额外Evidence和模型整合调用。每个真实attempt发送前CAS预留本次输入估算及实际输出cap，返回按可靠usage核销，未知用量保留预留并阻止自动补调；实际超估不丢有效结果，超支入账后阻断下一请求。正常批次及同图返工共享run预算，中断按原失败/新run重试。配置与迁移见[部署说明](docs/deployment.md#claim-中立抽取候选)。估算不是精确token或计费硬上限；真实冒烟和质量对照分别验证，本轮按用户要求只做代码与离线验证。T37 为 `neutral_estimate_v1` 增加冻结的密度装箱子契约（`density_batching`，version `claim-density-v1`）：按 paragraph/list/table/code 的原文字符数预估候选数，与既有 token 上界**同时**约束装箱；标题与空行不占风险权重，但仍完整送模型并逐 unit 回执；仅当候选批只含 1 个 unit 时豁免密度。`CLAIM_EXTRACTION_DENSITY_ENABLED` / `_PRIOR` / `RISK_SHARE` 只影响此后冻结的新 Run——旧 2.0 快照不含该键、hash 与原 token 装箱保持不变。触顶判废、细分、预算、CAS 与 Judge 均不变；密度是调度启发式，不构成事实召回或成本改善证明。

专项命令：`python scripts/run_tests.py --suite claim-extraction-focused --suite claim-extraction-eval --output output/test-runs/claim-extraction-check`。输出目录必须为空；评测固定合成正文并调用实际抽取/判定代码，输出 `fixture_policy_gate`、`quality_gate=NOT_RUN_OFFLINE` 与 `judge_capacity_gate=NOT_RUN_OFFLINE`。范围处理清单不能充当事实召回分母，工程上限不能充当实测容量。

T42 程序化来源定位与受限文字容错（`neutral_estimate_v1`）：新版中立模型不再输出 `source_start/source_end`，程序在所属 target unit 内按 A 唯一精确 → B 受控格式（CRLF→LF、叙述内连续横向空白折叠）→ C 受限文字编辑分层定位，只允许漏抄虚词、意外重复相邻字符、受控错字对等有正反例支撑的编辑，保护数字/否定/量词/条件/关系顺序/单位版本，歧义与最佳/次佳差距不足即拒绝；定位成功从冻结正文截取真实 `source_text` 并计算偏移与 hash。`CLAIM_EXTRACTION_SOURCE_LOCATING_MODE=tolerant_v1`（默认）只影响新建 Run；`exact_v1` 关闭 B/C；显式空值保持历史 v1 Prompt。定位诊断私有化，不进公开 DTO/trace/SSE；Judge 输入/Prompt/schema/options/判定与发布逻辑不变，本版不增加来源核对模型调用、不声称完成来源语义核验。专项命令：`python scripts/run_tests.py --suite claim-e11-unit --suite claim-e11-integration --suite claim-e11-recovery --suite claim-e11-eval --output output/test-runs/t42-e11-r1`。所有样本合成，真实模型质量 `NOT_RUN`。启用/回滚见[部署说明](docs/deployment.md#claim-中立抽取候选)。


2026-10-30 本地 Claim 升级离线验收完成：最终完整 acceptance 的13套全部通过，后端1931项通过、9项显式 live 跳过，前端19个浏览器文件通过；25个合成案例的策略门禁通过。证据分别位于 `output/test-runs/t31-acceptance-verified/`、`t31-eval-verified/` 与 `t31-implementation/`。真实抽取质量、成本和一次 Judge 容量尚未验证，默认 `legacy_v3`；未执行远程 CI 或部署。

完整的层级、功能覆盖矩阵、数据/证据规范见 [项目测试方案](docs/testing/README.md)，比赛54用例、来源快照与三指标口径见 [比赛评测方案](docs/testing/competition.md)。统一入口按套件运行，默认关闭真实模型调用，每次输出独立日志、JUnit 和 JSON/Markdown 摘要：

LLM 调用旁路计量专项：`python scripts/run_tests.py --suite llm-accounting-focused --output output/test-runs/llm-accounting-check`。它覆盖文本与互动课件全链路模型调用的旁路观察/作用域/独立库/故障矩阵/迁移/API/e2e，不启用真实模型。两个可选配置 `LLM_ACCOUNTING_ENABLED`（默认 true）与 `LLM_ACCOUNTING_DB_PATH`（默认 `backend/data/llm_accounting.db`，独立于业务库）见 [部署说明](docs/deployment.md)。

资源质量指标与报告专项（T48）：先执行 `npm --prefix frontend run build`，再运行 `python scripts/run_tests.py --suite resource-quality-unit --suite resource-quality-query --suite resource-quality-report --suite resource-quality-evaluation --suite resource-quality-ui --output output/test-runs/t48-metrics` 与 `python scripts/run_tests.py --suite resource-quality-browser --output output/test-runs/t48-browser`（输出目录必须新建；运行器使用当前 Python 解释器，依赖须已安装在该解释器中）。核心知识点覆盖率只取普通审核逐目标结果（已覆盖冻结目标数 ÷ 冻结目标总数），不再由 Claim 知识点关联派生；幻觉率在 Claim 完整时使用核验统计，未开启 Claim 且同版普通审核符合通过证据时显示 5% 未校准参考（不写入 `claim_hallucination_rate`、不判达标、不参与均值）；难度适配准确率只来自带明确参考标签的标注样本。离线 v2 金标 PASS 与 `official_gates=NOT_MEASURABLE` 分开报告，不能当作正式模型质量成绩。


学习轮次专项（T49）：先执行 `npm --prefix frontend run build`，再运行 `python scripts/run_tests.py --suite learning-round-contracts --suite learning-round-policies --suite learning-round-persistence --suite learning-round-budget --suite learning-round-transactions --suite learning-round-generation --suite learning-round-recovery --suite learning-round-api --suite learning-round-projections --suite learning-round-compat --output output/test-runs/t49-backend-r4`、`python scripts/run_tests.py --suite learning-round-frontend --output output/test-runs/t49-frontend-r2` 与 `python scripts/run_tests.py --suite learning-round-browser --output output/test-runs/t49-browser-r2`（输出目录必须新建）。覆盖单主节点/附带复习契约、联合冻结题组、一次提交分别判分、本轮纠错与仅复习复测、追加与失败恢复边界、SQLite 文件重开/租约回收/失败重试绑定、预算作用域跨线程/重试、历史与报告投影、容器事务接线及旧入口兼容；不运行全量后端或全部浏览器，也不启用真实模型。`LEARNING_ROUND_CREATION_ENABLED` 默认 false，配置与回滚见[部署说明](docs/deployment.md#t49-学习轮次存储与创建开关)。

部分发布汇总专项（T47）：先执行 `npm --prefix frontend run build`，再运行 `python scripts/run_tests.py --suite publication-policy-focused --suite publication-summary-focused --suite publication-compat-focused --suite publication-ui-focused --output output/test-runs/t47-focused-r1` 与 `python scripts/run_tests.py --suite publication-browser --output output/test-runs/t47-browser-r1`（输出目录必须新建且为空）。它只覆盖自动发布判定等价、发布汇总读取与 Job/Run/前端表达，不运行全量后端、全前端或全部浏览器，也不启用真实模型。范围与未运行项见[测试说明](docs/testing/README.md)。

```powershell
python scripts/run_tests.py --list
python scripts/run_tests.py --profile quick
python scripts/run_tests.py --profile regression
python scripts/run_tests.py --profile acceptance
python scripts/run_tests.py --suite backend-api --suite backend-migration
```

`quick` 包含架构导入、生成契约漂移、核心回归、比赛金标与前端单元；`regression` 另含 Ruff、全前端 ESLint、关键 API/SSE/请求上下文 JSDoc 类型检查、Python 声明/锁/环境检查、后端全量、课件冻结评测与生产构建。`acceptance` 追加实际浏览器专项，单元与浏览器成员以 `tests/suites.json` 为准。产物位于 `output/test-runs/`，原浏览器截图路径保留。临时目录/cache 隔离到本次报告；离线金标和冻结回放的 PASS 不能当作正式模型质量成绩。

报告读取提供独立的合成基准（临时SQLite、固定时钟/种子、100/1000/10000条正式历史，不调用模型或读取业务库）：

```powershell
python backend/scripts/report_benchmark.py --output output/test-runs/report-benchmark --sizes 100 1000 10000 --repeats 3
```

它记录 GET/304/分页/单与三订阅 poll 的 SQL次数、ORM装载对象、build次数、小样本P95和内存；不等于数据库物理扫描行数或线上容量。报告迁移、快照失效和完整历史的专项入口见 [测试方案](docs/testing/README.md)。

关键前端契约由后端 DTO/枚举导出：修改后执行 `python scripts/export_frontend_contracts.py`，再以 `python scripts/export_frontend_contracts.py --check` 核对产物。`python scripts/check_architecture.py` 检查共享层、API、models 与 db 的导入边界；业务 HTTP wrapper 归各 `features/<domain>/api.js`，旧集中入口只兼容转出，内部静态导入由 ESLint 约束。范围、兼容例外与负例验证见 [统一测试方案](docs/testing/README.md)。后端必需 CI 使用 Python 3.11/3.12 矩阵，各自安装哈希锁并运行回归；本地结果与远端 CI 结果分别判定。

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

Tutor 界面专项使用本地 HTTP fixture，覆盖普通/专注阅读和测评提示中的消息、引用、输入、等待与失败恢复，以及五页顶部辅助导航的颜色一致性；不调用真实 Tutor 模型：

```powershell
npm --prefix frontend run build
npm --prefix frontend run test:tutor-ui-browser
```

截图和 `summary.json` 位于 `frontend/tests/test-results/tutor-ui/`；Windows 默认使用 Edge，可通过 `TUTOR_BROWSER_CHANNEL` 或 `TEST_BROWSER_CHANNEL` 选择通道。

学习历史、学习报告、用户资料、四页画像请求归属及页面动效专项都使用本地 HTTP fixture。先构建后可单项运行；聚合浏览器入口会执行全部十五项专项：

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
- [2026-10-25 结构优化](docs/architecture-optimization-2026-10-25.md)：系统性结构审查、成熟实践依据、本轮职责重构与验证范围。
- [API 契约](docs/api.md)：认证、HTTP/DTO、反馈证据入口和事件。
- [知识库与数据库](docs/knowledge_base_database.md)：源文件、问卷、诊断与持久化。
- [部署说明](docs/deployment.md)：首次安装、四进程启动、Worker 健康检查与停机。
- [测试方案](docs/testing/README.md)：套件、浏览器专项与证据边界。
- [Git 规范](git-workflow.md)：分支、提交信息、禁止提交内容和文档同步规则。
- [Demo Runbook](docs/demo-runbook.md)：比赛 fixture、主 Demo、故障恢复与人工 checklist。

`docs/update_plan/` 保存本地计划、实施与验收记录以及 `archive.md` 历史摘要，历史计划按编号保留，不覆盖其他更新。该目录及 `output/test-runs/` 验收产物均为本地忽略资料，不随仓库分发；当前功能状态以源码及专题文档为准。

## P0-09 比赛验收

P0-09 固定离线 fixture 不调用收费 Provider；只读 preflight 检查配置中的数据库、默认知识库与构建产物：

初始化、完整性检查、检索与 P0-09 脚本已使用当前领域包路径（`db/shared`、`core/retrieval`、`services/reports`）；CLI 参数不变。互动课件评测的业务执行器位于 `backend/scripts/courseware_harness/`，继续通过原 `backend/scripts/courseware_eval.py` 入口运行。导入检查不等于数据库检查；初始化和 preflight 应针对预期数据目录执行。

```powershell
python scripts/p0_09_preflight.py --output wzx/out/p0-09-preflight.json
python scripts/run_p0_09_acceptance.py --offline --output wzx/out/p0-09-offline-manifest.json
```

`scripts/run_p0_09_acceptance.py --runtime` 已按 `features/<domain>/` 更新源码检查，仍不替代实际浏览器交互验收。该模式通过 TestClient 启动 FastAPI lifespan，会触发正常数据库初始化与启动对账，并非全程只读。工程验证使用 `python scripts/run_tests.py --profile acceptance`，目标环境 readiness 与真实业务闭环按 Runbook 单独核对。

状态只使用 `PASS`、`FAIL`、`SKIP`、`NOT_MEASURABLE`；小型 fixture 的实际值不等于正式统计达标。Live Provider 测试必须显式设置 `RUN_LIVE_LLM=1`，并与 deterministic offline 结果分开报告。

## 统一课件内容审核（默认关闭）

`content_v1` 私有策略覆盖复习 V2 与实操 V3（代码/非代码）的字段依据审核、定向修订、固定投影、预算账本、恢复和发布核对。`COURSEWARE_CONTENT_REVIEW_ENABLED=false` 为默认；现有任务继续使用其冻结策略。首版只有离线 fixture token estimator，真实模型缺少已验证 tokenizer/chat 包装 profile 时拒绝启用，不能只设置窗口和开关投入生产。

专项入口：`python scripts/run_tests.py --suite courseware-content-review-focused --suite courseware-content-review-eval --output output/test-runs/content-review-check`。离线执行实际引擎和三组真实工作流，`fixture_policy_gate` 与 `quality_gate=NOT_RUN_OFFLINE` 分开；browser 组使用真实冻结 HTML 验证 iframe/runtime。`python backend/scripts/courseware_content_review_fixtures.py` 可重生合成 fixtures，manifest 记录来源、源码及产物 hash；重生有新运行/release 标识，不覆盖 legacy baseline。真实质量与生产启用另有条件门，本次不修改实际 `.env`、运行库或服务进程。

2026-10-30 本地专项、完整 acceptance（含前端构建/浏览器）与文本离线评测均通过；真实模型质量未运行，未执行远程CI或部署。生产计数profile与真实质量/授权依赖尚未满足，默认开关保持false。


T31第12节取代历史tokenizer/profile运行前置；[Claim估算配置](docs/testing/claim-counting-profile.md)说明启用项、离线预检及旧任务处理。默认legacy，真实DeepSeek冒烟未执行，不能写“真实可用已验证”；完整质量对照不作为接通API的前置条件。


T37 修复（2026-11-05）：estimate 抽取结果载体支持最多128条，持久读取和CAS同时受任务冻结的resource_claims约束；历史1.0上限64保留，默认仍legacy。真实验收按完整任务计次数，内部正常重试/返工不另计；repair使用独立cap1预算及隔离目录，不重置历史账本。成功须核对最终叶资源的抽取与Judge完整结果，不能只看节点出现或job完成。报告用私有抽取账本替换不完整trace用量，未知用量单列。新增真实结果以T37本次记录为准，不提前声明效果通过。

### 讲义普通审核策略（T38）

默认 `LECTURE_REVIEW_STRATEGY=legacy_content_v2`。可选 `lecture_issue_v1`（T38）与 `lecture_issue_v2`（T39）仅用于讲义普通审核，需显式设置已确认的 `LECTURE_REVIEW_CONTEXT_TOKENS`；输出预算沿用 reviewer 配置并随任务冻结。配置变化只影响后续新任务。新策略以逐问题账本核销返工，不改变 Claim 与发布门禁。真实质量验收未运行，默认策略不切换。`lecture_issue_v2` 删除模型自填的总体 coverage 结论，只保留逐目标 covered/missing，覆盖比例、阻断判定与 approve/revise/human_review 全部由程序从冻结目标派生；覆盖问题必须写明受影响目标。三维语义判断（事实、难度、自包含）仍为独立判断。对白名单内的自相矛盾（目标集不全、缺失目标未关联问题、维度与问题冲突、风险分冲突、核销漏项、临时 ID 重复）允许一次有界纠正，与首次请求共享冻结的物理尝试上限 M，不增加全局重试。V2 首次请求前必须有持久 step 记录，旧 running/failed 审核步骤会让新调用被拒绝。真实模型质量仍未验收。专项命令见 docs/testing/README.md。

Claim定向返工默认最多1次（`claim_max_iterations=1`），显式0可禁用；Claim要求修订但专用额度不可用时进入人工复核且未发布，不借普通`max_iterations`。普通审核返工默认仍为2。已冻结任务按保存值执行。

### 文本文档普通审核通用化（T44）

新增内部策略 `RESOURCE_REVIEW_STRATEGY=resource_issue_v1`（默认启用；显式 `compat` 可回退历史各类型审核），让六类文本资源（讲义、实操指南、分阶测试题、案例分析、复习清单、内部纠错训练包）共用同一版本化闭环：证据约束问题登记、稳定 `issue_id`（`ri_`/`rip_` 前缀）、精确定向返工、逐问题核销、全文回归、无变化控制、程序硬门（结构失败零语义调用）与一次有界纠正；结构化资源的完整私有包也进入审核。启动须显式填写已核实的 `RESOURCE_REVIEW_CONTEXT_TOKENS`，缺失将拒绝初始化；示例及本地配置使用当前 reviewer 已声明的 129024，其他模型应按实际窗口配置。Claim 中立策略要求 `LLM_THINKING_MODE=disabled`。环境显式值优先；默认变更只影响此后新建且未被旧环境值覆盖的任务，已冻结任务不转换。当前策略已默认切换，真实模型质量仍未验收，未在本次执行真实调用或重启服务。策略在 Run 创建时冻结，回滚只影响后续新 Run；私有审计使用 `review_audit_v4` 命名空间，不做物理迁移。专项命令见 docs/testing/README.md。

新版通用审核与讲义专用 issue 策略互斥：启用 `resource_issue_v1` 时设 `LECTURE_REVIEW_STRATEGY=legacy_content_v2`，关闭旧专用循环，由通用新审核接管讲义；本地已同步。其他部署显式设置的 `lecture_issue_v1/v2` 也须调整。若回退此前讲义 V2 行为，须同时设 `RESOURCE_REVIEW_STRATEGY=compat` 与 `LECTURE_REVIEW_STRATEGY=lecture_issue_v2`，并保留原讲义窗口。
