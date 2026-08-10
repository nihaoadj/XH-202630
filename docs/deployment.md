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

迁移或生命周期 Repository 不可用属于核心持久化故障；即使 demo 模式允许生成降级，
也不得绕过 Run/Step/Event 写入继续调用模型。查询验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/<run_id>/timeline?after_sequence=0&limit=100"
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>/evidence
Invoke-RestMethod http://127.0.0.1:8000/api/runs/<run_id>/claims
```
