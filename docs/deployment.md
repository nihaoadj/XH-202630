# 部署指南

当前部署基线为 Python 3.11、Node.js 24、SQLite 和 Chroma。同一套环境运行一个 Web、一个文本 Worker 和一个互动课件 Worker。开发前端使用 Vite，静态部署使用构建后的 `frontend/dist`。

## 1. 首次安装

从仓库根执行。首次准备先安装依赖并生成本地配置，再编辑配置文件。

**Windows PowerShell**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python scripts/start_local.py --install --bootstrap --check
```

便携式 Windows 环境可直接用 `.\.venv\python.exe` 执行下文的 Python 命令。

**Linux / macOS**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python scripts/start_local.py --install --bootstrap --check
```

启动器从后端锁文件安装 Python 依赖并运行 `npm ci`。单独运行 `--check` 仅检查本地启动前置条件。

## 2. 配置和初始化

根据 [环境变量模板](../backend/.env.example) 编辑 `backend/.env`。相对数据路径基于 `backend/` 解析，Web 与两个 Worker 使用相同配置和数据目录。

| 配置 | 部署时确认 |
|---|---|
| `APP_MODE` | 本地用 `development`。生产模式要求核心依赖就绪 |
| `AUTH_JWT_SECRET` | 使用环境专用随机密钥，HTTPS 部署设置 `AUTH_COOKIE_SECURE=true` |
| `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | 使用同一供应商的凭据和模型，审核上下文按实际窗口配置 `RESOURCE_REVIEW_CONTEXT_TOKENS` |
| `DATABASE_URL`、`VECTOR_STORE_DIR`、`RESOURCES_DIR` | 分别指向 SQLite 文件、Chroma 索引和生成产物目录。启用计量时也持久化独立的 `LLM_ACCOUNTING_DB_PATH` |
| `KNOWLEDGE_BASE_DIR`、`EMBEDDING_MODEL` | 确认默认知识库和索引模型匹配。模板使用 BGE-M3，本地模式要求模型文件提前就绪 |
| `LEARNING_ROUND_CREATION_ENABLED` | 需要创建新学习轮次时设置为 `true`，模板默认关闭 |

如果缺少 BGE-M3 模型，联网准备时运行 `python scripts/rebuild_multilingual_index.py prepare-model`，它会下载并核对仓库固定的模型版本。将 `EMBEDDING_MODEL` 设为 `backend/data/models/bge-m3/<模型版本>` 的绝对路径，保留 `EMBEDDING_LOCAL_FILES_ONLY=true`。离线部署同时提供配置中使用的精排模型文件或缓存。

对**新环境**执行一次初始化：

```powershell
python scripts/start_local.py --initialize --check
```

该命令执行知识入库和数据库初始化，包括示例数据。已有环境按下文升级流程处理，单库维护见 [知识库与数据库](knowledge_base_database.md#入库与索引维护)。

## 3. 启动与检查

从仓库根运行：

```powershell
python scripts/start_local.py --no-reload
```

| 进程 | 默认地址 | 检查 |
|---|---|---|
| FastAPI Web | `127.0.0.1:8000` | [Web readiness](http://127.0.0.1:8000/health/ready) |
| 互动课件 Worker | `127.0.0.1:8081` | [课件 Worker readiness](http://127.0.0.1:8081/health/ready) |
| 文本生成 Worker | `127.0.0.1:8082` | [文本 Worker readiness](http://127.0.0.1:8082/health/ready) |
| Vite 前端 | `127.0.0.1:5173` | [打开前端](http://127.0.0.1:5173) |

启动器保留已占用端口上的进程。日志在 `backend/logs/local-*.log`，本次启动的 PID 记在 `backend/logs/local-dev-processes.json`。分别排障时，从仓库根在独立终端执行以下命令，Web 终端先切到 `backend/`：

```powershell
# Web，工作目录 backend/
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 两类 Worker，分别从仓库根运行
python backend/scripts/courseware_worker.py --health-host 127.0.0.1 --health-port 8081
python backend/scripts/generation_worker.py --health-host 127.0.0.1 --health-port 8082

# 前端，从仓库根运行
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

文本或课件任务持续排队时，先检查对应 Worker 的 readiness 和日志，再核对它与 Web 的数据路径。环境预检使用 `python scripts/check_environment.py`。就绪检查验证配置与服务依赖，供应商额度和真实生成质量须通过独立验证确认。

## 4. 静态前端与容器

在仓库根运行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`，通过静态服务器发布 `frontend/dist`。同源反向代理将 `/api` 和 `/health`、`/health/ready` 转给 Web，Vue 页面路径回退到 `index.html`。文本、课件、报告的 SSE 均需关闭代理缓冲，读取超时应留出大于心跳周期的余量。

根 [Dockerfile](../Dockerfile) 可用 `docker build -t xh-learning-web .` 构建，默认启动 Web。容器部署另配置两个 Worker，使用同一镜像版本，分别运行 `python scripts/generation_worker.py` 和 `python scripts/courseware_worker.py`（容器工作目录 `/app/backend`）。Web 与 Worker 共享挂载的 SQLite、Chroma、资源目录和所需模型文件。配置从部署环境注入，前端仍独立发布。

## 5. 升级与恢复

1. 停止接收新任务，等待进行中的任务收口，正常停止 Web 与 Worker。
2. 在停写后备份 SQLite、Chroma、资源目录和配置，保持同一备份点。
3. 用同一版本更新 Web 与两个 Worker。启动时执行数据库迁移，随后用 `python scripts/check_database_integrity.py` 检查完整性。
4. 启动两个 Worker，核对三项 readiness、目标知识库可检索、已有发布资源可读，再恢复流量。每项业务验收按 [测试指南](testing/README.md) 选取专项。
5. 需要恢复时在停写状态下成组恢复对应版本的代码、配置及数据。涉及新写入的数据先保留副本，核对迁移及在途任务的兼容性。

前台进程通过终端 `Ctrl+C` 停止。使用启动器或服务管理器时，确认本次 PID 和命令后停止相应进程，两个 Worker 也支持 `--shutdown-file` 请求有序停止。
