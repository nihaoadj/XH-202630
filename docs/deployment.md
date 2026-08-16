# 部署说明

> 当前项目仍处于 P0 开发阶段；production 模式采用 fail-fast，不应把 degraded 演示产物当作正式生成结果。

## 1. 环境要求

- Python 3.11（使用项目根目录唯一 `.venv/`）
- Node.js 18+
- OpenAI-compatible LLM API Key
- 预先准备的 Embedding 模型缓存和 Chroma collection

`.venv/`、`backend/.env`、SQLite、Chroma 索引、日志和生成资源不得提交。

## 2. Windows PowerShell

从仓库根目录执行，不依赖机器上的绝对项目路径：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

编辑 `backend/.env`。推荐开发配置：

```env
APP_MODE=development
ALLOW_DEGRADED_GENERATION=false
DB_TYPE=sqlite
DATABASE_URL=sqlite:///./data/domain_knowledge.db
DEBUG=false
SQL_ECHO=false
CHROMA_COLLECTION_PREFIX=kb
LLM_REQUEST_TIMEOUT_SECONDS=30
LLM_WORKFLOW_TIMEOUT_SECONDS=105
LLM_MAX_ATTEMPTS=2
LLM_RETRY_BASE_DELAY_SECONDS=0.5
LLM_RETRY_MAX_DELAY_SECONDS=3.0
LLM_MAX_OUTPUT_TOKENS=4096
LLM_GENERATOR_MAX_OUTPUT_TOKENS=8192
LLM_STRUCTURED_OUTPUT_MODE=auto
```

LLM 预算约束：workflow timeout 必须大于单次 request timeout，并建议小于前端当前 120 秒 Axios timeout；attempts 允许 `1..3`，delay 不得为负且 max delay 不得小于 base delay。`auto` 优先使用结构化调用，Provider 不支持时受控切到 text + 严格 parser。对于已知不支持 function calling 的 OpenAI-compatible 服务，应显式设置 `LLM_STRUCTURED_OUTPUT_MODE=text`，这样每个 Agent 不会先付出一次固定的 BAD_REQUEST 探测开销。SDK retry 固定关闭，所有重试都计入 Gateway 总预算。

填入真实 `LLM_API_KEY` 后执行只读环境检查：

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
$LASTEXITCODE
```

退出码：0=ready、2=degraded、1=not-ready/配置非法。脚本不调用计费 LLM、不下载模型、不创建 collection。

初始化默认知识库和示例数据：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py
.\.venv\Scripts\python.exe scripts\init_db.py
```

启动后端：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 3. Linux/macOS

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
.venv/bin/python scripts/check_environment.py
.venv/bin/python scripts/ingest_knowledge.py
.venv/bin/python scripts/init_db.py
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 4. 多 KB collection 与兼容期

- 每个 KB 的 Chroma collection 由统一 `_collection_name(kb_id)` 生成：`<prefix>_<kb_id_hash>`。
- 创建、写入、查询、删除和 health 使用同一个 resolver，不再共享唯一固定集合名。
- 首选 `CHROMA_COLLECTION_PREFIX=kb`。
- 兼容期保留旧 `CHROMA_COLLECTION_NAME`；若未显式设置新变量，它按“前缀”解释，不再表示固定 collection。
- 更换前缀会改变目标 collection 名，应重新对每个 KB 执行入库；不要直接复制/重命名 Chroma 内部文件。

公共 `GET /health` 和 `GET /health/ready` 只检查默认 KB 和核心依赖：默认 KB 异常可按模式产生 degraded/503，非默认 KB 异常不会影响公共 readiness。

全 KB 详情接口默认关闭。需要时设置随机高强度 `ADMIN_HEALTH_TOKEN`，再使用：

```powershell
$headers = @{ "X-Admin-Token" = "<ADMIN_HEALTH_TOKEN>" }
Invoke-RestMethod http://127.0.0.1:8000/api/admin/knowledge-bases/health -Headers $headers
```

知识索引崩溃恢复：服务启动时会将超过
`KNOWLEDGE_INDEX_STALE_SECONDS=900` 仍处于 `indexing` 的记录标为
`not_ready/KNOWLEDGE_INDEXING_INTERRUPTED`，不会在启动阶段自动下载模型或阻塞重建。
确认源文件无误后，由管理员显式执行：

```powershell
$headers = @{ "X-Admin-Token" = "<ADMIN_HEALTH_TOKEN>" }
Invoke-RestMethod -Method Post `
  http://127.0.0.1:8000/api/admin/knowledge-bases/rag_engineering_training/reconcile `
  -Headers $headers
```

也可以在服务器本地执行：

```powershell
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py `
  --knowledge-base-id rag_engineering_training
```

未配置 token 返回 404，错误 token 返回 401；部分非默认 KB 异常返回 HTTP 200 + `status=degraded`。响应不包含 token、绝对路径、Embedding 内容或完整异常。

## 5. 运行模式

| 模式 | degraded | memory | not-ready 行为 |
|---|---|---|---|
| development | 默认 false，可显式 true | 允许但标 ephemeral | 应用可启动，生成 503 |
| demo | 仅显式 true | 允许但标 ephemeral | 有保底产物时 HTTP 200 + degraded |
| production | 禁止 | 禁止 | 核心依赖/默认 KB 不可用时启动失败 |

`DEBUG=false` 和 `SQL_ECHO=false` 是安全默认；即使临时开启 SQL echo，SQLAlchemy 仍使用 `hide_parameters=True`。

## 6. 前端

```powershell
Set-Location frontend
npm install
npm run dev
```

生产构建：

```powershell
npm run build
```

## 7. 验收

```powershell
Set-Location <仓库根目录>
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest backend\tests -m "not live_llm" -q
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
git diff --check
git status --short --branch
```

验收不能只检查 HTTP 200：还要确认 `status/error_codes`、默认 KB collection/count、degraded 标记、管理员接口鉴权，以及日志中没有 Key、完整画像、prompt、模型原文、SQL 参数和原始上游异常。可选 live smoke 必须显式设置 `RUN_LIVE_LLM_TESTS=1`，默认测试不得访问 Provider。

## 8. P0-04 Run 持久化与迁移

可配置项：

```dotenv
WORKFLOW_RUN_LEASE_SECONDS=180
WORKFLOW_CHECKPOINT_MAX_BYTES=65536
WORKFLOW_TIMELINE_DEFAULT_LIMIT=100
WORKFLOW_TIMELINE_MAX_LIMIT=500
```

应用启动时先执行版本化 additive migration，再仅将 lease 已过期的
`running/finalizing` Run 标记为 `interrupted`。该扫描不会自动 resume，也不会调用
LLM。SQLite migration 已包含幂等回归；PostgreSQL 上线前仍需数据库负责人对 DDL、
索引和锁行为执行受控验证。

SQLite 单进程重启时还会将上一进程遗留的 `queued/running` GenerationJob 标记为
`failed`，错误码为 `GENERATION_JOB_INTERRUPTED`；对应的 `feedback_followup_runs`
同步转为 `failed`。如果 Feedback 已提交、但进程在创建 Follow-up 关系前退出，启动
扫描会补一条 `failed` 关系，不会伪造 child Run。相同幂等请求再次提交时复用稳定
run_id，将失败 Job 安全重排队，不会再次增加 mastery、profile version 或 PathMutation。
该自动扫描当前只对 SQLite 单进程模式启用；PostgreSQL 多 worker 部署必须先增加租约
或 worker ownership 验证，不能直接套用单进程判定。

迁移或生命周期 Repository 不可用属于核心持久化故障；即使 demo 模式允许生成降级，
也不得绕过 Run/Step/Event 写入继续调用模型。查询验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/<run_id>/timeline?after_sequence=0&limit=100"
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>/evidence
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>/claims
```

## 9. P0-07 反馈闭环迁移与验收

应用初始化会幂等执行 `20260811_p0_07_feedback_profile_path_closed_loop`。该迁移只做 additive 列/表创建，不删除或重写 legacy feedback。生产 PostgreSQL 上线前需审核唯一约束、FK、索引、`SELECT FOR UPDATE` 和 profile CAS 的并发行为。

最小验收：

```powershell
$body = @{
  learner_id = "<learner_id>"
  source_resource_id = "<published_resource_id>"
  source_resource_version = 1
  source_run_id = "<source_run_id>"
  idempotency_key = "feedback-e2e-0001"
  expected_profile_version = 1
  submitted_at = (Get-Date).ToString("o")
  knowledge_point_results = @(@{
    knowledge_point_id = "<stable_skill_node_id>"
    question_ids = @("q-1", "q-2")
    correct_count = 1
    total_count = 2
  })
} | ConvertTo-Json -Depth 8
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/feedback/attempts -ContentType "application/json" -Body $body
$result
Invoke-RestMethod http://127.0.0.1:8000/api/feedback/path/<learner_id>
Invoke-RestMethod http://127.0.0.1:8000/api/report/<learner_id>
```

用同一 body 再提交一次，应返回同一 `attempt_id`、`idempotent_replay=true`，且画像版本、路径版本和 child run 数量不再增加。服务重启后再次查询 Attempt、Path 和 Report，结果必须保持。

真实 Uvicorn 进程重启演练使用隔离临时数据库且不调用 LLM：

```powershell
python scripts/rehearse_feedback_process_restart.py
```

## 10. P0-08 SSE 配置与反向代理

```dotenv
WORKFLOW_SSE_POLL_INTERVAL_SECONDS=0.5
WORKFLOW_SSE_HEARTBEAT_SECONDS=15
WORKFLOW_SSE_EVENT_PAGE_SIZE=100
```

约束：poll 至少 50ms，heartbeat 必须大于 poll，page size 最大 500。SSE 不属于生成 hard dependency；传输失败时前端回退到 Job/timeline 查询，但底层 Workflow persistence 失败仍按既有策略 fail closed。

接口响应包含 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。Nginx/网关还需关闭该路由的响应缓冲，并将 read timeout 配置为大于 heartbeat；不得由 CDN 聚合或缓存事件流。手工查看：

```powershell
curl.exe -N -H "Accept: text/event-stream" "http://127.0.0.1:8000/api/runs/<run_id>/events?after_sequence=0"
curl.exe -N -H "Last-Event-ID: 18" "http://127.0.0.1:8000/api/runs/<run_id>/events"
```

浏览器 EventSource 使用同源 cookie/session（当前仓库尚未引入应用登录鉴权），不把 bearer token 放到 URL。未来增加 Run ownership 后，SSE 必须与 `/runs/{id}` 使用同一授权依赖。

## 11. P0-09 Demo Gate

正式 demo 前从仓库根目录执行：

```powershell
python scripts/p0_09_preflight.py --output wzx/out/p0-09-preflight.json
python scripts/run_p0_09_acceptance.py --offline --output wzx/out/p0-09-offline-manifest.json
python scripts/run_p0_09_acceptance.py --runtime --output wzx/out/p0-09-runtime-manifest.json
```

preflight 为只读检查：数据库可达与 migration、默认 KB/Chroma、一次本地 retrieval smoke、LLM/structured-output 配置和前端构建产物。它不打印 secret、不调用收费 LLM、不重建数据库。退出码为 `0 READY`、`1 NOT_READY`、`2 DEGRADED`；acceptance runner 对应 `0 PASS`、`1 FAIL`、`2 PARTIAL`。

正式放行要求 preflight `READY`、offline Scenario A～J 全 PASS、runtime PASS 和浏览器 checklist 通过。`/health/ready=200` 不能覆盖数据库或前端比赛 Gate。当前代码已强制 SQLite 每连接 FK，并通过 P0-09 migration 建立 `generated_resources(run_id, resource_type, version)` 唯一约束；正式数据仍必须完成只读完整性检查和受控 migration rehearsal。完整操作见 `docs/demo-runbook.md`。
