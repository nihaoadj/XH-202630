# 本地启动与部署说明

> 当前可验证的部署拓扑是 SQLite：一个 FastAPI Web 进程、一个独立互动课件 Durable Worker 和一个 Vite 前端。它适用于开发、演示和本地验收；不应描述为多 Worker 或多实例的生产集群。

## 1. 运行前提

- Python 3.11；推荐将项目虚拟环境放在仓库根目录 `.venv/`。
- Node.js 18+ 与 npm。
- 已准备的 Embedding 模型缓存和 Chroma collection。默认 `EMBEDDING_LOCAL_FILES_ONLY=true`，运行时不会下载模型。
- 真实生成需要 OpenAI-compatible Provider 的 `LLM_API_KEY`；离线测试不应设置 `RUN_LIVE_LLM=1` 或 `COURSEWARE_LIVE_EVAL=1`。

本地配置、SQLite、Chroma、日志和生成物都是运行时数据，不能提交。配置统一从 `backend/.env` 读取；相对数据库、向量库和资源路径均相对 `backend/` 解释。

## 2. 一键启动（推荐）

仓库提供跨 Windows、Linux 和 macOS 的标准库启动器：[scripts/start_local.py](../scripts/start_local.py)。它根据自身位置定位仓库，不依赖开发者的用户名或绝对路径，并分别启动：

1. FastAPI Web：`127.0.0.1:8000`；
2. 互动课件 Durable Worker：健康端点默认 `127.0.0.1:8081`；
3. Vite 前端：`127.0.0.1:5173`。

脚本从不替换已占用端口上的进程，也不会默认安装依赖、复制配置、下载模型或初始化数据。它把新启动进程的 PID 写入 `backend/logs/local-dev-processes.json`，日志写入 `backend/logs/local-*.log`。

### 2.1 首次准备

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe scripts\start_local.py --install --bootstrap
# 编辑 backend\.env，填写 LLM_API_KEY 等本机配置
.\.venv\Scripts\python.exe scripts\start_local.py --bootstrap --initialize
```

当前仓库若已使用便携式 `.venv\python.exe`，将上面两处 `.venv\Scripts\python.exe` 替换为 `.venv\python.exe`；启动器会自动识别这两种 Windows 布局和 Linux/macOS 的 `.venv/bin/python`。

Linux/macOS：

```bash
python3.11 -m venv .venv
.venv/bin/python scripts/start_local.py --install --bootstrap
# 编辑 backend/.env，填写 LLM_API_KEY 等本机配置
.venv/bin/python scripts/start_local.py --bootstrap --initialize
```

`--initialize` 会显式执行知识入库和示例数据库初始化，可能耗时；不要把它当作每次启动步骤。已有真实数据时，先备份 SQLite 文件，并只在确认需要时初始化。

### 2.2 日常一键启动

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

启动器依次等待 `GET /health` 和 Worker 的 `GET /health/ready`。成功后访问 `http://127.0.0.1:5173`。启动前可只校验本机环境：

```powershell
.\.venv\python.exe scripts\start_local.py --check
```

常用选项：

| 选项 | 用途 |
|---|---|
| `--no-worker` | 仅调试文本资源、反馈或报告时不启动课件 Worker；提交互动课件任务前必须去掉此选项。 |
| `--no-frontend` | 仅启动 API 和 Worker，便于 API/Worker 验收。 |
| `--no-reload` | 禁用 Uvicorn 热重载，适合稳定演示。 |
| `--host 0.0.0.0` | 允许局域网访问开发服务器；公开部署前仍须配置 HTTPS、鉴权和网络边界。 |
| `--worker-health-port 8082` | 将 Worker 健康端口改为未占用端口。 |

前端 Vite 代理当前固定指向 `localhost:8000`，因此同时启动前端时不要修改 `--backend-port`。脚本检测到不兼容的端口组合会直接退出。

## 3. 为什么课件必须单独启动 Worker

`POST /api/resources/courseware/jobs` 只创建持久任务和 outbox 记录；FastAPI lifespan **不会**执行课件工作流。独立 Worker 轮询 outbox、claim 一个任务、续租、执行规划/场景生成/审核/定向修订/渲染/发布，并在任务边界记录失败或死信。未启动 Worker 时，课件任务会停留在队列，Web 健康检查仍可能是 ready。

当前 SQLite 只支持一个顺序 Worker：`COURSEWARE_WORKER_BATCH_SIZE` 即使配置大于 `1` 也会被归一为 `1`。不要用第二个 Worker 作为扩容方案；租约和幂等保护只用于崩溃恢复和防止重复副作用，不构成多消费者吞吐保证。

Worker 的三个只读端点为：

| 端点 | 含义 |
|---|---|
| `GET /health/live` | 进程仍在运行。 |
| `GET /health/ready` | 至少完成一次持久 outbox 轮询，可安全消费任务。 |
| `GET /metrics` | 脱敏计数：claim、processed、failed、lease-lost、retry、fallback、quarantine、release。 |

## 4. 手动三进程启动与停机

需要分别观察日志或排障时，使用三个终端。以下是 Windows 当前便携式虚拟环境的命令；标准 venv 请把 `.venv\python.exe` 换成 `.venv\Scripts\python.exe`。

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

终端 C（前端）：

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
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

正常停机优先在各进程终端按 `Ctrl+C`，让 Worker 在当前租约边界有序退出。自动启动时，先根据 `backend/logs/local-dev-processes.json` 确认 PID 与命令行属于本项目，再停止对应进程；不要按端口或名称批量强杀其他人的服务。Worker 也接受 `SIGINT`/`SIGTERM`，本地编排可传 `--shutdown-file <sentinel>` 后创建该文件请求同一有序停止路径。

进程异常退出后，下一 Worker 会在租约到期后接管未完成 outbox 任务；已写入的 checkpoint、candidate 和 release 指针不会被回退。若任务为 `release_blocked`，保留旧 release，检查 job 的 `error_code`、Worker 日志和候选 manifest；不得手工改名候选文件来冒充发布。

## 5. 配置与健康检查

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
```

`/health=200` 不代表课件 Worker 已运行；必须额外看到 `/health/ready=200`，再提交互动课件生成任务。公共健康接口只检查默认知识库和核心依赖。完整多知识库详情需配置 `ADMIN_HEALTH_TOKEN` 并调用管理员接口，见 [API 文档](api.md)。

## 6. SQLite 数据保护与模式边界

- 当前开发、演示和本轮部署使用 SQLite。PostgreSQL 分支仅为兼容基础，尚无驱动、迁移和并发验收，不能作为已支持部署方案。
- SQLite 使用 WAL 与有界 busy timeout。Web 和唯一 Worker 必须指向同一个文件型 `DATABASE_URL`、同一资源根目录和同一 Chroma 配置。
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
git diff --check
```

SSE 路由须关闭代理缓冲，read timeout 必须大于 `WORKFLOW_SSE_HEARTBEAT_SECONDS`，并保留 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。反向代理、HTTPS、密钥管理、备份恢复演练和真实浏览器/CI 证据均属于目标部署环境的额外责任；本地测试通过不能替代它们。

课件本地故障矩阵、浏览器验证和发布候选证据以当前代码、测试目录和本部署文档为准；课件工作流的公开入口与启动方式由 `backend/scripts/courseware_worker.py` 和 [API 文档](api.md) 维护。
