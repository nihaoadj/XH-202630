# 本地启动与部署说明

> 文档核对日期：2026-10-23。

> 当前 SQLite 拓扑：一个 FastAPI Web、一个文本 Worker、一个互动课件 Worker 和一个 Vite 前端。每类 Worker 均为单实例、并发 1；这不是同类多消费者或生产集群的扩容方案。

## 1. 运行前提

- Python 3.11；推荐将项目虚拟环境放在仓库根目录 `.venv/`。
- Node.js 24（工程工具兼容 20.19+ / 22.13+）与 npm。
- 已准备的 Embedding 模型缓存和 Chroma collection。默认 `EMBEDDING_LOCAL_FILES_ONLY=true`，运行时不会下载模型。
- 真实生成需要 OpenAI-compatible Provider 的 `LLM_API_KEY`；离线测试不应设置 `RUN_LIVE_LLM=1` 或 `COURSEWARE_LIVE_EVAL=1`。

本地配置、SQLite、Chroma、日志和生成物都是运行时数据，不能提交。配置统一从 `backend/.env` 读取；相对数据库、向量库和资源路径均相对 `backend/` 解释。

初始化、完整性及 preflight 脚本使用当前 `db/shared` 和 `core/retrieval` 入口。课件验收 CLI 保持在 `backend/scripts/`，业务执行器归于其 `courseware_harness/` 子包；按下文原命令运行即可，端口、环境变量与数据路径不变。

Claim 审核完成但存在无证据事实时，`CLAIM_USER_REVIEW_ENABLED=true` 且事实通过率达到 `CLAIM_USER_REVIEW_MIN_FACTUAL_PASS_RATE`（默认 `0.60`）会等待用户在审核报告中决定是否发布；旧 `CLAIM_WARNING_PUBLISH_*` 配置不再触发自动发布。

## 2. 一键启动（推荐）

仓库提供跨 Windows、Linux 和 macOS 的标准库启动器：[scripts/start_local.py](../scripts/start_local.py)。它根据自身位置定位仓库，不依赖开发者的用户名或绝对路径，并分别启动：

1. FastAPI Web：`127.0.0.1:8000`；
2. 互动课件 Durable Worker：健康端点默认 `127.0.0.1:8081`；
3. 文本生成 Worker（SQLite）：健康端点默认 `127.0.0.1:8082`；
4. Vite 前端：`127.0.0.1:5173`。

脚本从不替换已占用端口上的进程，也不会默认安装依赖、复制配置、下载模型或初始化数据。它把新启动进程的 PID 写入 `backend/logs/local-dev-processes.json`，日志写入 `backend/logs/local-*.log`。

### 2.1 首次准备

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe scripts\start_local.py --install --bootstrap --check
# 编辑 backend\.env，填写 LLM_API_KEY 等本机配置
.\.venv\Scripts\python.exe scripts\start_local.py --initialize --check
```

当前仓库若已使用便携式 `.venv\python.exe`，将上面两处 `.venv\Scripts\python.exe` 替换为 `.venv\python.exe`；启动器会自动识别这两种 Windows 布局和 Linux/macOS 的 `.venv/bin/python`。

Linux/macOS：

```bash
python3.11 -m venv .venv
.venv/bin/python scripts/start_local.py --install --bootstrap --check
# 编辑 backend/.env，填写 LLM_API_KEY 等本机配置
.venv/bin/python scripts/start_local.py --initialize --check
```

`--initialize` 会显式执行知识入库和示例数据库初始化，可能耗时；不要把它当作每次启动步骤。已有真实数据时，先备份 SQLite 文件，并只在确认需要时初始化。

上述准备命令通过 `--check` 在完成指定操作后退出，不启动 Web / Worker / 前端；准备完成后再执行下一节的日常启动命令。`--check` 本身只校验虚拟环境、本地配置、Uvicorn 和前端依赖存在，不执行 readiness、模型连接或数据库完整性检查；与 `--install` / `--initialize` 组合时，这些显式操作仍会执行。模型文件须在入库前准备，默认不会在线下载。

### 2.2 日常一键启动

本机主模型已切为`deepseek-flash`（`LLM_MODEL`，官方最新Flash别名当前指向V4.1-Flash-1017），沿用原`LLM_BASE_URL`/API Key、思考模式与预算；此键由共享网关读取，会影响生成及共用该网关的Agent。Embedding/精排/SQL/向量配置不随此切换变化。改模型后重启Web及Worker，勿重新初始化或入库；启动健康检查不发计费LLM请求，因此模型账号权限与生成质量仍须后续由用户实际请求验证。真实.env和含密钥的备份不提交。Flash别名具体版本以[官方模型页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)为准。

在仓库根目录使用虚拟环境解释器执行：

```powershell
.\.venv\Scripts\python.exe scripts\start_local.py
```

或在当前便携式 Windows 虚拟环境中：

```powershell
.\.venv\python.exe scripts\start_local.py
```

Linux/macOS：

```bash
.venv/bin/python scripts/start_local.py
```

启动器依次等待 `GET /health` 和两个 Worker 的 `GET /health/ready`。memory 不启动文本 Worker。成功后访问 `http://127.0.0.1:5173`。启动前可只校验本机环境：

```powershell
.\.venv\python.exe scripts\start_local.py --check
```

常用选项：

| 选项 | 用途 |
|---|---|
| `--no-worker` | 仅调试文本资源、反馈或报告时不启动课件 Worker；提交互动课件任务前必须去掉此选项。 |
| `--no-generation-worker` | 不启动文本 Worker；SQLite 文本任务仍会被接受，但保持 queued，直到兼容的消费者启动。 |
| `--no-frontend` | 仅启动 API 和 Worker，便于 API/Worker 验收。 |
| `--no-reload` | 禁用 Uvicorn 热重载，适合稳定演示。 |
| `--host 0.0.0.0` | 允许局域网访问开发服务器；公开部署前仍须配置 HTTPS、鉴权和网络边界。 |
| `--worker-health-port 8083` | 更改课件 Worker 健康端口。 |
| `--generation-worker-health-port 8084` | 更改文本 Worker 健康端口，避免与课件端口相同。 |

前端 Vite 代理当前固定指向 `localhost:8000`，因此同时启动前端时不要修改 `--backend-port`。脚本检测到不兼容的端口组合会直接退出。

## 3. 为什么课件必须单独启动 Worker

`POST /api/resources/courseware/jobs` 只创建持久任务和 outbox 记录；FastAPI lifespan **不会**执行课件工作流。独立 Worker 轮询 outbox、claim 一个任务、续租、执行规划/场景生成/审核/定向修订/渲染/发布，并在任务边界记录失败或死信。未启动 Worker 时，课件任务会停留在队列，Web 健康检查仍可能是 ready。

当前 SQLite 课件链路只支持一个顺序 Worker：`COURSEWARE_WORKER_BATCH_SIZE` 即使配置大于 `1` 也会被归一为 `1`。不要用第二个课件 Worker 作为扩容方案；租约和幂等保护只用于崩溃恢复和防止重复副作用，不构成多消费者吞吐保证。

Worker 的三个只读端点为：

| 端点 | 含义 |
|---|---|
| `GET /health/live` | 进程仍在运行。 |
| `GET /health/ready` | 至少完成一次持久 outbox 轮询，可安全消费任务。 |
| `GET /metrics` | 脱敏计数：claim、processed、failed、lease-lost、retry、fallback、quarantine、release。 |

### 3.1 文本持久 Worker

`GENERATION_DISPATCH_MODE=worker` 为 SQLite 必需设置；显式 `background` 会在配置校验时拒绝。普通生成、批次 continuation 和反馈后续选择先提交冻结请求与画像，再由 `backend/scripts/generation_worker.py` 领取，每轮最多 1 条。进程锁绑定实际数据库文件，第二个实例以 `GENERATION_WORKER_ALREADY_RUNNING`、退出码 2 拒绝启动。memory 使用非持久 BackgroundTasks，不能运行此 CLI。

文本 Worker 默认每 2 秒对账，每轮最多 100 个候选；执行期间主线程继续续租和对账。`WORKFLOW_RUN_LEASE_SECONDS` 为执行租约；`GENERATION_WORKER_POLL_SECONDS`（默认 2）、`GENERATION_WORKER_SHUTDOWN_SECONDS`（默认 30）及 `GENERATION_QUEUE_TIMEOUT_SECONDS`（默认 1260，仅旧 legacy 无 Run 任务）见 `.env.example`。新 worker queued 不按年龄失败。未开始任务最多领取 3 次，重新排队使用有界退避；已经开始的任务过期后只中断，不自动重复模型工作，用户需通过既有入口创建关联的新尝试。

执行期间续租或对账异常不会放弃当前线程去领取下一项；Worker 保留当前 claim，继续监护，并以 `GENERATION_WORKER_POLL_FAILED` 标记未就绪。一次完整续租和对账成功后恢复；明确失去租约时停止领取并保留 `GENERATION_WORKER_LEASE_LOST` 原因。持续异常仍执行既有停机预算检查，执行线程结束或按退出预算退出前不启动另一个任务。

文本 Worker 提供 `/health/live`、`/health/ready` 和 JSON `/metrics`。ready 要求依赖可执行、轮询近期正常且未停止；指标只含安全计数、active/concurrency 和错误码。`--once` 仅对账并尝试领取一条；`--shutdown-file <sentinel>` 可请求停止新领取，等待当前执行最多配置的退出时间；超时退出保留租约，后续按中断规则收敛。

升级前停止旧 Web 的写入并等旧后台任务结束或租约到期，再启动新 Web 和唯一文本 Worker；新旧二进制不可混跑同一库。增量迁移保留旧行归属 legacy，不自动把旧请求当作新冻结任务执行。回滚前停止新领取并排空 worker queued 或保留兼容消费者，保留新增字段、尝试记录和发布资源；不能直接退回仅认识 BackgroundTasks 的旧代码而遗留无人消费的任务。

T23 单份资源重生成不新增环境变量或数据库迁移，但 Web 与文本 Worker 必须同时更新并重启后才可使用新按钮。任务采用 `learning_documents.resource_retry.v1` 分发版本和内部冻结上下文；旧 Worker 不认识该版本会拒绝/失败，不应混跑或把它改写成普通生成版本。回滚前停止新任务提交与领取，排空此类 queued 任务或保留兼容消费者，再回滚 Web/Worker；保留历史 Run/Evidence/版本，不清理业务库。T23交付当轮没有自动重启；后续T24清洗维护已同步恢复本机Web/文本Worker，未用真实模型执行新任务。

### 3.1 官方资料清洗维护（T24）

清洗不换Embedding/精排/生成模型，也不改`.env`。先确认本项目没有排队、运行或finalizing任务，暂停已核验的Web及两个Worker（保留前端）；不要强杀活跃任务。使用同一虚拟环境运行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_chinese_sources.py --refresh-derived --receipt output/test-runs/kb-cleaning/sources-before
.\.venv\Scripts\python.exe scripts/refresh_cleaned_knowledge.py --apply --receipt output/test-runs/kb-cleaning/index-before
.\.venv\Scripts\python.exe scripts/prepare_knowledge_sources.py --check
```

receipt目录必须不存在，每次维护用新目录；这里名称只是示例，不要覆盖现有备份。第一个命令只从已固定本地快照重建派生资产，保留原文/许可。第二个命令先校验当前本地模型文件receipt与SQL embedding profile、备份SQLite和Chroma，再核验旧索引ready/全集身份/正文与历史profile，最后经既有入库staging、少量smoke、activation对账。完全同文/同分块/profile的向量复用到新ID，其余只用原模型重编码；向量目录中的`knowledge-embedding-profile.json`随备份恢复，不能单独移植到其他模型库。

只有receipt显示ready、历史hash核验通过后，才恢复原本运行的Web/Worker。失败保持服务停止，使用receipt的before资产恢复metadata/content/registry、SQLite备份和完整向量目录；先把失败向量目录移至同data目录下独立归档，再恢复备份，不能把两个目录直接混合或删除历史库。备份含用户数据，留在本机受忽略output目录，不进入Git。T11重建工具与fixture描述的是当时3222片历史快照；T24当前正文为3214片，日常清洗使用本节维护入口而非拿旧快照数量冒充当前状态。

### 3.2 全库文件候选构建，不入库（T25）

该流程不使用上一节的入库工具，不暂停服务、不换模型、不修改canonical/SQL/Chroma/.env。先预览，再输出一个新候选目录：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/knowledge_corpus_cleaning.py --output output/knowledge-cleaning/T25
.\.venv\Scripts\python.exe scripts/knowledge_corpus_cleaning.py --apply --output output/knowledge-cleaning/T25
.\.venv\Scripts\python.exe scripts/knowledge_corpus_cleaning.py --check --output output/knowledge-cleaning/T25
```

`--apply`只生成文件；默认dry-run不写，`--check`只读且缺少快照时失败，不补造文件。输出目录必须位于仓库`output/knowledge-cleaning/`下且不存在；本机T25目录已存在，重建必须换新目录名，禁止覆盖既有候选。失败的部分产物保留诊断，不能据此认为候选已完成。

T25交付时是62篇/3177片候选、42篇修改/20篇原样，未入库。后续用户已授权T26激活，当前canonical/SQL/Chroma为3177片（见3.3）。冻结audit与candidate-snapshot仍保留构建时`ingested=false`，实际部署状态以T26维护receipt和health为准；不能直接覆盖旧SQL metadata。

### 3.3 清洗候选激活、入库与运行（T26）

操作前核验候选/source hash与项目端口/PID，确认没有queued/running/finalizing任务，停止已确认归属本项目的Web和Workers；不能终止无关或活跃任务。备份目录必须新建；以下本机T26目录已用，重做必须换新目录名。

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/knowledge_corpus_promotion.py --apply --output output/knowledge-cleaning/T25 --receipt backend/data/knowledge_backups/T26/source
.\.venv\Scripts\python.exe scripts/prepare_knowledge_sources.py --check
.\.venv\Scripts\python.exe scripts/refresh_cleaned_knowledge.py --apply --receipt backend/data/knowledge_backups/T26/index
.\.venv\Scripts\python.exe scripts/start_local.py --no-reload
```

第一步只切换源文件并留完整before副本、公开可重放基线，不写索引；第三步沿既有SQL staging/vector/smoke/activate，在相同模型profile下复用同文向量，成功ready及历史hash核验后才运行最后一步。配置/端口/模型均未换，CPython UTF8是本机命令编码保障，不是新的业务`.env`字段。

激活后`prepare_knowledge_sources.py --check`在受忽略的临时目录重建旧输入，原固定采集器离线检查后再重放当前清洗结果。`knowledge_corpus_cleaning.py --check`及新候选重建也使用保存基线；当前metadata、原文/许可、页跨度、来源节点和3177片身份必须一致。新baseline blob不进入manifest，不参与检索。

私有业务备份必须放`backend/data/knowledge_backups/`，该目录及source receipt自带Git忽略；公开`provenance/cleaning-base`仅含知识源旧字节。资料切换中若检测并发编辑，拒绝覆盖，必要时标记`recovery_blocked`，保留服务停机和备份请求人工处理。无并发编辑时文件级失败会恢复before；可用`knowledge_corpus_promotion.py --rollback --receipt <source备份>`恢复文件。若索引已经改变，先停服务，再同时恢复SQLite与向量完整备份（失败目录移至已验证data下独立归档，不混合复制）；不得仅回滚文件却继续用新索引。

### 3.4 教学单元分片候选（T27，构建时未入库，后由T28激活）

`prepare_evidence_chunks.py --build --output <新目录>`只读T26资料，生成独立文件候选并内存分片；输出须为新的`output/knowledge-cleaning/`子目录，不覆盖已有候选。最终T27含62篇及原六教材，opt-in `markdown_evidence_v2`共1121片；T27交付时仍运行3177片，T28激活后自动重建保存的T26输入进行候选复核：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH='backend'; $env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/prepare_evidence_chunks.py --check --output output/knowledge-cleaning/T27
```

构建/check不调用Embedding/LLM、DB、向量库或服务生命周期。辅助链接不进正文，parent-context仅离线预览、运行时未回填。候选有独立身份epoch；后续T28使用专门的v2激活器及维护边界，不能直接拿T26 promotion假定新profile已受支持或覆盖旧不可变metadata。

### 3.5 教学单元v2激活与入库（T28）

先确认没有queued/running/finalizing任务，暂停已核实归属本项目的Web与Workers，保留前端。完整源备份与SQLite/Chroma备份存入受忽略的新目录（以下T28已用，不可重复覆盖）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe scripts/evidence_corpus_promotion.py --apply --output output/knowledge-cleaning/T27 --receipt backend/data/knowledge_backups/T28/source
.\.venv\Scripts\python.exe scripts/prepare_knowledge_sources.py --check
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe scripts/refresh_cleaned_knowledge.py --apply --receipt backend/data/knowledge_backups/T28/index
# 仅在receipt ready且history_verified为true后恢复
.\.venv\Scripts\python.exe scripts/start_local.py --no-reload --startup-timeout 60
```

预期62篇1121片（官方1077、六教材44），所有新片使用原本地bge-m3重编码；完整结果以index/receipt.json为准。新epoch不覆盖旧SQL版本，旧Run冻结Evidence不更新。活动源的`provenance/evidence-base`仅含知识资料重放差异，业务数据备份不得提交。文件回滚入口`evidence_corpus_promotion.py --rollback --receipt <source备份>`拒绝未知并发修改；索引若已变动，必须在服务停止下成组恢复database-before.db与vectors-before，不能只回滚源文件后重启。

当前Evidence摘录上限仍1200字符，82个长原子可在SQL保留全文，但不保证完整进入模型；父context未启用。不新增环境配置、HTTP契约或表迁移；健康/本地查询通过不等于真实生成质量测试通过。

若维护进程中断且receipt仍`backed_up`（本机T28曾完成864片后中断），先确认没有同一维护进程或Web/Worker，再使用同目录`refresh_cleaned_knowledge.py --apply --resume --receipt backend/data/knowledge_backups/T28/index`。仅支持当前evidence-v2资料；不会重新备份或覆盖原备份。它验证相同模型/profile/路径、原SQL历史hash、原向量备份完整副本的全部ID/正文/metadata/有限向量、活动源重放与现存部分向量，未知内容/损坏/变更均拒绝；原有864条稳定ID可直接保留，后续仍须原2smoke和SQL激活。原向量备份未直接打开修改，此次功能校验的文件hash清单绑定到receipt；不声称拥有中断前未记录的全文件hash。运行可用独立隐藏进程并保留PID/日志，最终以ready receipt为准，不能仅凭进度日志启动服务。

本机T28最终已ready：1121/1121/1121，2smoke通过，history_verified=true，旧13条Evidence及旧SQL不可变行均保留。最终核对报告为`output/test-runs/kb-activate-t28/final-index-audit.json`；源重放指纹与入库snapshot是不同算法，不可混为一项。`start_local.py --no-reload --startup-timeout 60`恢复8000/8081/8082均ready及5173 HTTP200；本机通过不表示他人部署已更新。既有Windows中文HNSW路径适配必须随项目使用，单独外部脚本直接打开Chroma应先安装项目`install_windows_hnsw_paths()`进程内兼容层；不需因此重建或下载模型。

## 4. 手动四进程启动与停机

需要分别观察日志或排障时，使用四个终端。以下是 Windows 当前便携式虚拟环境的命令；标准 venv 请把 `.venv\python.exe` 换成 `.venv\Scripts\python.exe`。

终端 A（Web）：

```powershell
Set-Location backend
..\.venv\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

终端 B（**必需，互动课件生成链路**）：

```powershell
Set-Location <仓库根目录>
.\.venv\python.exe backend\scripts\courseware_worker.py `
  --health-host 127.0.0.1 --health-port 8081
```

终端 C（**必需，SQLite 文本生成链路**，仓库根目录）：

```powershell
.\.venv\python.exe backend\scripts\generation_worker.py --health-host 127.0.0.1 --health-port 8082
```

终端 D（前端）：

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Linux/macOS 的对应命令：

```bash
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# 新终端，从仓库根目录执行
.venv/bin/python backend/scripts/courseware_worker.py --health-host 127.0.0.1 --health-port 8081
# 新终端
.venv/bin/python backend/scripts/generation_worker.py --health-host 127.0.0.1 --health-port 8082
# 新终端
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

正常停机优先在各进程终端按 `Ctrl+C`，让 Worker 在当前租约边界有序退出。自动启动时，先根据 `backend/logs/local-dev-processes.json` 确认 PID 与命令行属于本项目，再停止对应进程；不要按端口或名称批量强杀其他人的服务。Worker 也接受 `SIGINT`/`SIGTERM`，本地编排可传 `--shutdown-file <sentinel>` 后创建该文件请求同一有序停止路径。

进程异常退出后，下一 Worker 会在租约到期后接管未完成 outbox 任务；已写入的 checkpoint、candidate 和 release 指针不会被回退。若任务为 `release_blocked`，保留旧 release，检查 job 的 `error_code`、Worker 日志和候选 manifest；不得手工改名候选文件来冒充发布。

## 5. 配置与健康检查

E1 资源证据分配为默认关闭的文本生成增强：`RESOURCE_AWARE_RETRIEVAL_ENABLED=false`、独立查询上限 `RESOURCE_AWARE_RETRIEVAL_MAX_QUERIES=10`（1—10）。启用前核实部署模型的实际上下文窗口并设置 `RESOURCE_AWARE_PLANNER_CONTEXT_TOKENS`，输入预算默认 `RESOURCE_AWARE_PLANNER_INPUT_BUDGET_TOKENS=32768`。Planner 对完整系统／用户消息、输出 schema 包装的 UTF-8 字节数加1024作保守 token 估计，核对输入预算及实际输出 token 预留；这是程序预检，不是精确分词或模型质量验收。窗口缺失或超预算沿现有 `require_agent_fallback` 失败／降级，禁止静默截断。默认关闭无需修改现有部署配置。

实际执行建立 Run 时，输入快照保存策略选择，检索 trace 保存实际版本、config hash 和 ID 分配；尚在队列中的 job 按执行时配置选择，不承诺排队时冻结。公共查询数超过增强查询预算时整体使用旧策略并记原因；专属空集不重查、不增加发布门禁。精排候选上限20，owner 每查询最多top_k，最终 Evidence 仍受原数量／分数／摘录限制。关闭增强不回写已保存 Evidence/spec/资源，不新增数据库迁移；已经建立的在途 Run 保留已冻结策略。上线仍需独立真实资料、模型质量与成本对照，当前默认保持关闭，见 [已实施功能与验证结果](project-update-2026-10-26.md)。

最小开发配置应保留：

```dotenv
APP_MODE=development
ALLOW_DEGRADED_GENERATION=false
DB_TYPE=sqlite
DATABASE_URL=sqlite:///./data/domain_knowledge.db
SQLITE_BUSY_TIMEOUT_SECONDS=60
COURSEWARE_AI_ENABLED=true
COURSEWARE_GENERATION_MODE=ai_first
COURSEWARE_WORKER_POLL_SECONDS=2
COURSEWARE_WORKER_BATCH_SIZE=1
COURSEWARE_WORKER_HEALTH_HOST=127.0.0.1
COURSEWARE_WORKER_HEALTH_PORT=8081
```

课件 AI-first 链路的预算、总时限和审核策略由 `COURSEWARE_*` 环境变量控制，完整受约束模板见 [backend/.env.example](../backend/.env.example)。AI 审核不可用、预算耗尽或硬门失败会按策略降级、隔离或拒绝，不能把失败当作发布成功。

`APP_MODE=production` 要求 `AUTH_JWT_SECRET` 至少 32 个 UTF-8 字节且不是开发/占位密钥，`AUTH_COOKIE_SECURE=true`，服务通过 HTTPS 对外提供。`CORS_ALLOW_ORIGINS` 使用 JSON 数组，例如 `["https://learn.example.org"]`；production 中只能配置 HTTPS origin，不能包含通配符、路径或凭据。同源部署可保留 `[]`。development/demo 仍允许 localhost / 127.0.0.1 的动态端口；其他前端 origin 必须显式配置。CORS 允许凭据并向前端暴露 ETag，认证和错误响应契约保持。

代码内建默认值与分发模板有以下差异，最终值以进程环境和 `backend/.env` 为准：

| 配置项 | `Settings` 内建默认 | `.env.example` | 影响 |
|---|---|---|---|
| `LLM_STRUCTURED_OUTPUT_MODE` | `auto` | `json_mode` | 新建本地配置使用模板值；`auto` 才先尝试 function calling |
| `CLAIM_PARTIAL_PUBLISH` | `false` | `true` | 模板显式允许符合策略的 partial Claim 发布，保留 `incomplete` 指标；不能计作完整事实审核 |
| `LLM_BASE_URL` / `LLM_MODEL` | DashScope / Qwen | DeepSeek 示例 | 示例 Provider 选择可覆盖；真实运行必须填写对应凭据 |

讲义默认输出上限 65536 token / 240 秒，实操指南默认 65536 token / 300 秒；通用资源输出预算由 `LLM_RESOURCE_GENERATOR_MAX_OUTPUT_TOKENS` 控制，普通审核和 Claim 使用独立的重试 / 超时配置。以上是调用预算，实际内容受 DTO、Evidence 和整 Run 时限约束。完整字段以 [配置源码](../backend/app/config.py) 和模板为准。

启动前的只读检查不会调用计费 LLM、下载 Embedding 或创建 collection：

```powershell
.\.venv\python.exe scripts\check_environment.py
$LASTEXITCODE  # 0=ready，2=degraded，1=not-ready 或配置非法
```

服务启动后：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8081/health/live
Invoke-RestMethod http://127.0.0.1:8081/health/ready
Invoke-RestMethod http://127.0.0.1:8081/metrics
Invoke-RestMethod http://127.0.0.1:8082/health/live
Invoke-RestMethod http://127.0.0.1:8082/health/ready
Invoke-RestMethod http://127.0.0.1:8082/metrics
```

Web `/health=200` 不代表任何 Worker 已运行；还应分别核对 8081 和 8082 的 `/health/ready=200`。公共健康接口只检查默认知识库和核心依赖。完整多知识库详情需配置 `ADMIN_HEALTH_TOKEN` 并调用管理员接口，见 [API 文档](api.md)。

## 6. SQLite 数据保护与模式边界

Windows索引路径注意：当前`chroma-hnswlib 0.7.6`原生文件接口由`core/retrieval/hnsw_windows.py`按系统ANSI代码页适配，Python侧SQLite/Chroma配置路径仍不变，不需搬目录或更换模型。仅该版本/Windows/非ASCII str路径生效；系统代码页无法表示的字符仍显式报错，应选可表示路径。若已有`Cannot open header file`，兼容适配不会自动补出损坏索引，必须先停服、备份，再按知识库对账流程从保留原文重建目标集合；不能对所有集合做reset。重启验收应包含真实向量query和HNSW四文件，而不是只有SQL count/HTTP health。

T9 知识库源资料已直接移动到 `teaching/zh`、`references/{zh,en}`、`licenses/`、`provenance/`，统一离线核验命令为 `\.venv\Scripts\python.exe scripts\prepare_knowledge_sources.py --check`。此命令核验源文件与registry，不迁移数据库。T9 更新了 manifest 中的来源物理路径，但既有 SQL/Chroma 仍保留旧 `source_path`/完整 metadata；部署或换模型前须创建新的知识库版本、完成数据库与向量索引备份，并受控重建和对账，禁止在同一知识库版本直接 reconcile 覆盖旧 metadata。直接移动使用的本地备份是 `output/test-runs/kb-layout-direct/backup-20261026-215648`；迁移时三端服务均停止，本次未自动启动服务。

- 当前开发、演示和本轮部署使用 SQLite。PostgreSQL 分支仅为兼容基础，尚无驱动、迁移和并发验收，不能作为已支持部署方案。
- SQLite 使用 WAL 与有界 busy timeout。Web、唯一文本 Worker 和唯一课件 Worker 必须指向同一个文件型 `DATABASE_URL`、同一资源根目录和同一 Chroma 配置。
- 备份前必须停止 Web/Worker 写入；禁止复制正在写入的 `.db`、`-wal` 或 `-shm` 文件。
- `development` 可启动但核心依赖 not-ready 时生成返回 503；`demo` 仅在显式 `ALLOW_DEGRADED_GENERATION=true` 时允许标记为 degraded 的保底结果；`production` 禁止降级且核心依赖 not-ready 时 fail-fast。

数据库迁移或演示联调前运行只读完整性预检：

```powershell
.\.venv\python.exe scripts\check_database_integrity.py
```

## 7. 验收与反向代理

最小本地验收：

```powershell
.\.venv\python.exe -m pip check
.\.venv\python.exe -m pytest backend\tests -m "not live_llm" -q
npm --prefix frontend run build
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8081/health/ready -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8082/health/ready -UseBasicParsing
git diff --check
```

SSE 路由须关闭代理缓冲，read timeout 必须大于 `WORKFLOW_SSE_HEARTBEAT_SECONDS` 与 `REPORT_SSE_HEARTBEAT_SECONDS` 中的较大值，并保留 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。反向代理、HTTPS、密钥管理、备份恢复演练和真实浏览器/CI 证据均属于目标部署环境的额外责任；本地测试通过不能替代它们。

报告当前快照流 `/api/report/{learner_id}/events` 使用独立的 `REPORT_SSE_*` 间隔，也需要关闭缓冲；它是 revision 失效通知，客户端重新拉取带 ETag 的报告。事实变更与滚动时间边界都可触发失效；每个 Web 进程独立共享快照，不需要 Redis，也不宣称跨进程只构建一次。课件事件流和文本 Run SSE 是各自的持久任务流，不能混用游标。

课件本地故障矩阵、浏览器验证和发布候选证据以当前代码、测试目录和本部署文档为准；课件工作流的公开入口与启动方式由 `backend/scripts/courseware_worker.py` 和 [API 文档](api.md) 维护。

## 多语言Embedding换模与资料入库

检索候选保护默认`RETRIEVAL_BALANCED_CANDIDATES_ENABLED=true`、`RETRIEVAL_DENSE_RESERVE=10`：全局最多保留10条原查询dense结果，再按RRF填满`RERANK_CANDIDATE_K`（当前20），不是每query/每语言10条。reserve不得大于该全局预算，自定义较小预算时需相应下调reserve；设enabled=false并重启Web/Worker可恢复旧选择策略，不改DB/索引。每原query内部最多增加1条来自KB `query_aliases.json`的英文术语probe（最多6条术语规则合成、400字符），不是完整翻译；原query、节点与allowed范围不变，精排仍用原query，禁用/失败时不使用alias-only结果。缺失/非法配置显式降级原查询，配置/策略hash用于审计；不下载模型、不调用生成LLM，模型与阈值不变。单query候选可能从10增到20，另有probe召回成本，但精排总数仍受原有20预算约束；不保证时延完全不变。

RAG示例库使用`BAAI/bge-m3`的dense向量（1024维、归一化），固定模型commit为`5617a9f61b028005a4858fdac845db406aefb181`；模型卡见[官方说明](https://huggingface.co/BAAI/bge-m3)。生成LLM和CrossEncoder保持原配置；不启用M3 sparse/ColBERT。默认`EMBEDDING_LOCAL_FILES_ONLY=true`，运行请求不承担联网下载。

仓库根先执行`.venv/Scripts/python.exe scripts/rebuild_multilingual_index.py prepare-model`，下载约2.3GB的固定权重与所需配置/tokenizer到`backend/data/models/bge-m3/<commit>/`，核对上游权重SHA并做本地encode。已有库必须保留旧配置直至下述audit通过，再将`.env`的`EMBEDDING_MODEL`设为该快照**绝对路径**；不能假定项目目录中的模型自动出现在用户全局HuggingFace缓存。CPU `EMBEDDING_BATCH_SIZE=4`；长资料入库前检查token长度，模型8192上限不代表精排输入也扩大。运维脚本的进程预检使用已有开发依赖psutil，执行环境应安装仓库开发锁文件。

已有SQLite演示库换模须先停止项目Web/Worker，在旧配置仍有效时执行`python scripts/rebuild_multilingual_index.py build`，再以新进程执行同脚本`audit`。默认生成新SQL`backend/data/domain_knowledge_m3.db`与独立向量目录`backend/data/chroma_bge_m3/`，只迁移影子库的P0-34；拒绝覆盖目标，失败保留现场且不改.env。审核通过后将本机配置同组切为：`DATABASE_URL=sqlite:///./data/domain_knowledge_m3.db`、`VECTOR_STORE_DIR=./data/chroma_bge_m3`、前述绝对模型路径及`EMBEDDING_LOCAL_FILES_ONLY=true`。源码中的默认数据库路径仍用于全新安装，不自动探测或迁移他人的本地库。

P0-34为历史文档版本增加identity_revision区分来源元数据epoch，不伪造正文hash、不改变逻辑文档/知识库ID；历史SQL正文和冻结证据保留。迁移当前仅验收SQLite，其它方言明确拒绝。manifest的revision、模型快照、SQL和向量目录是成组部署资产；不能只切一个模型名，尤其两个模型同1024维也不能混用。其他已有知识库也必须重建，不能指向尚未迁移的旧空间。

运行报告及敏感的旧.env备份位于`output/test-runs/kb-m3/`（Git忽略，不上传/打印密钥）。回滚前停机，恢复旧配置与旧manifest epoch，旧SQL和旧Chroma未删除；需匹配旧schema应用版本，或再复制旧SQL并仅在副本上执行P0-34，避免新代码启动链升级旧原件。上线后产生新学习记录则先迁移增量再回滚。小范围检索smoke不等于质量benchmark，检索阈值仍须后续正式标注集校准。新模型不意味着生成/审核能力已进行真实LLM验收。

## 8. Docker 与前端静态部署边界

当前 `Dockerfile` 安装 Python 依赖并启动端口 8000 的 Uvicorn Web；不构建前端、不启动文本或课件 Worker，也没有配套 Compose 编排。容器方式仍须分别运行两个 Worker，并共享数据库、资源根目录和模型 / 索引配置；前端生产构建为 `frontend/dist`，由目标环境的静态服务器提供。

根 `.dockerignore` 排除本地环境文件、数据库、日志、缓存和生成物，保留 `.env.example`。镜像创建空运行目录，持久数据需挂载或初始化；不能依赖构建上下文携带开发数据。

依赖安装使用 `pip install --require-hashes -r backend/requirements.lock.txt`；开发/验收另外安装 `backend/requirements-dev.lock.txt`。前端使用 `npm ci`，Node 24 为本地验收和 CI 的推荐版本。变更依赖后在仓库根执行：

```bash
python -m uv pip compile backend/requirements.txt --universal --python-version 3.11 --generate-hashes --no-annotate --output-file backend/requirements.lock.txt
python -m uv pip compile backend/requirements-dev.txt --universal --python-version 3.11 --generate-hashes --output-file backend/requirements-dev.lock.txt
python scripts/check_dependencies.py
python -m pip check
```

现有锁文件会作为版本偏好；有意升级才显式使用 `--upgrade` 并执行完整验收。已运行进程可能锁住 Windows 二进制依赖，正常停机后再安装；验收可在独立虚拟环境安装上述锁文件，避免影响当前服务。

后端必需 CI 以 Python 3.11/3.12 矩阵分别安装两个哈希锁，运行依赖一致性、架构/生成契约、Ruff（含 `backend/scripts/`）和后端全量/比赛金标/课件冻结检查；保留课件 artifact 与进程故障矩阵，各版本产物分开上传。frontend 使用 Python 3.11 / Node 24。部署基线仍为 Python 3.11，不改变 Web/Worker 拓扑或运行配置。

验证干净安装时用 Python 3.11 创建独立虚拟环境，以其解释器执行安装和测试：

```powershell
python -m venv output/clean-py311
output/clean-py311/Scripts/python.exe -m pip install --require-hashes -r backend/requirements.lock.txt -r backend/requirements-dev.lock.txt
output/clean-py311/Scripts/python.exe scripts/run_tests.py --suite backend-lint --suite architecture --suite frontend-contracts --suite dependency-check --suite pip-check --suite backend-full --suite competition --suite courseware-eval
```

建环境前核对 `python --version` 为 3.11；Linux 使用 `output/clean-py311/bin/python`。本地现有环境、隔离环境、远端矩阵和实际镜像构建分别判定，当前机器没有 Python 3.12 或可用 Docker daemon 时不能推断其通过。

课件运行时从 `backend/app/core/courseware/assets/` 读取平台静态 CSS/JavaScript，部署 backend 源码时需包含该目录。现有 `COPY backend ./backend` 已包含这些文件，无需新增配置；读取不依赖工作目录，资产仍嵌入生成 HTML，不新增静态服务或 URL。字节兼容及加载约束见 [资产说明](../backend/app/core/courseware/assets/README.md)。

本轮已添加根 `.dockerignore`，验证了合成敏感路径的上下文过滤；Docker daemon 不可用，未实际构建镜像。运行配置和持久数据仍由部署环境注入，Git 忽略规则不会自动排除 Docker 构建上下文。

`vite.config.js` 中的 `/api`、`/health` 代理只在开发服务器生效。静态部署需在同源反向代理中配置这些后端路径，并对 `/dashboard`、`/learning/new`、`/learning/history`、`/user/profile` 等 Vue Router history URL 回退到 `index.html`，确保刷新和直达可用。课件预览路径及认证 Cookie / SSE 契约保持 [API 文档](api.md) 的约束。


## 报告读模型维护

初始化链在既有迁移后执行 SQLite `p0_35_report_read_model`，增加报告水位/trigger/索引；没有新增环境变量或外部服务。缓存仅在原生依赖同库、SQLite JSON/window能力和来源覆盖检查通过时启用；其他配置仍走权威完整读取。缓存上限64项、JSON估算总量32MiB、闲置300秒，下一滚动内容边界会提前失效；超大报告不缓存。全局 epoch 可能因其他 learner 写入使本报告冷重建，目标环境应结合实际并发测量。合成基准不是线上延迟/容量保证。

回滚先停用/回退本次代码与读路径、停止相关写进程并备份目标 SQLite 文件，再在维护窗口执行。以下命令中的文件必须为明确选择的已有数据库；应用启动会重新安装迁移，所以保持旧代码或服务停止直到维护完成：

```powershell
$env:PYTHONPATH = 'backend'
python -m app.db.migrations.p0_35_report_read_model --database D:/path/to/backed-up-app.db --rollback
```

该回滚仅删除本迁移拥有的水位/触发器/索引，不删除学习事实。临时副本的重复迁移、回滚、重装与身份更换由 migration 测试覆盖；是否已升级/已回滚实际部署库，必须以目标环境核验为准。本任务未操作部署库。

## 英文选材配置

### 学习检索细化与来源软平衡（T29）

`LEARNING_RETRIEVAL_REFINEMENT_ENABLED=true`默认只作用于legacy学习文本文档：最多6查询、20精排候选，SQL验证/去重后一次全局选材，预算`min(max_evidence, top_k_per_query×query_count)`；默认单query最多6、多query最多8。`.constraints.retrieval_top_k`影响最终预算，不在该多query路径按owner提前截断。教材合计2、单文档2和合格原文预留2为软规则，节点覆盖及原0.35门槛优先；原文预留还要求原分不低于平衡前预算末位原分-0.15。先放宽软配额保质量，再必要回填，原因进入profile；没有英文硬配额。

确认无queued/running/finalizing任务后空闲重启Web/两个Workers读取新逻辑，前端可保留。设`LEARNING_RETRIEVAL_REFINEMENT_ENABLED=false`并空闲重启恢复旧查询/截断/hash，不需迁移或入库。Tutor/E1、旧Run及单份retry冻结证据不受影响；显式E1即使预算回退legacy也不混入新调度。不新增模型调用、不改摘录上限或模型配置。

新profile包含`learning_query_strategy=learning-tasks-v2`、`learning_candidate_window=full_pool`与`learning_source_balance`（来源数、节点保护、相对基准及回填原因）；`legacy_adapter`表示注入后端只支持旧窗口。分类以可信SQL路径与manifest匹配为准，不把unknown当原文；配置hash绑定来源清单和规则。健康与本地检索通过不等于真实生成质量已验证。

### Tutor生成契约（T21部分回退后）

当前按用户要求撤销独立支持审核、每轮补检索与双阶段预算，仅保留生成契约/正文与引用分离及无证据空引用拒答。`TUTOR_LLM_TIMEOUT_SECONDS=25`、`TUTOR_MAX_OUTPUT_TOKENS=4096`恢复单阶段生成，网关原重试/修复语义保持；auto在Tutor内预先使用TEXT，由网关注入JSON schema并严格解析，显式协议/其他Agent不改。不新增配置键、模型、入库或表迁移，Web需重启加载；旧turn不回填/覆盖。引用ID合法不代表回答事实已审核，无独立事实支持校验。

内容去冗余T19默认`RETRIEVAL_REDUNDANCY_ENABLED=true`、`RETRIEVAL_REDUNDANCY_THRESHOLD=0.90`（有限0.85..1，1为只去完全重复）；仅影响生成前的新Evidence选材，无额外模型调用、入库或迁移。`false`关闭并恢复旧选材/hash逻辑；变更需Web与两个Worker空闲重启，不打断正在执行的任务。内容级规则和保护边界见[数据库说明16](knowledge_base_database.md#16-内容级去冗余t19)，本轮实现不自动重启现有进程。

与E1兼容：`RESOURCE_AWARE_RETRIEVAL_ENABLED=false`仍是默认。启用时公共节点/资源用途候选保留优先，dense保护仅占剩余20条预算及每query配额，缺口见`dense_reserve_shortfall`。两项p34迁移（知识身份revision、生成调度）均保留，初始化链随后安装p35报告读模型。本次远程同步仅做副本演练，真实库未迁移，Web/Worker未自动恢复；实际启动会触发初始化，运行前须确认备份与迁移前置条件。

T17选材配置：`RETRIEVAL_TOP_K_DEFAULT=6`（旧环境显式设3会覆盖新默认），`RETRIEVAL_ENGLISH_SCORE_BONUS=0.08`（有限0..0.25，0关闭）；总证据8、候选20、原始相关性门槛0.35不变。仅SQL可信`references/en/...`路径且成功精排/原分达门槛才加选材分；完整候选池在TopK前校验，普通无可信回调的原始向量检索不加分。不需要模型下载/入库/DB迁移，原分与历史Evidence不改；可设置bonus=0、TopK=3并空闲重启回滚。Web/Worker需空闲重启读取新源码与Settings，启动不加`--initialize`，不打断queued/running任务；健康检查不等于LLM生成质量已验证。
