# 文档同步核对记录

核对日期：2026-10-09。范围为当前工作区的 README、docs 正文、测试说明和相关 SVG；历史更新计划保留原记录。此次由主代理完成全部分析与文档编辑，保留已有修改，不变更业务实现。

## 1. 项目现状与核对依据

当前前端业务已按 `features/<domain>/` 组织，路由包含 3 个公开账号入口、8 个需登录的学习页面，以及 4 个旧特色页重定向。五步方向引导、资源生产与专注阅读、正式测评反馈、学习旅程、四图报告、本人资料和公共动效均有对应实现；首页四个机制场景使用本地示意数据，生成页的任务轨迹读取持久化事件。

后端继续按 API、Service、Agent / 工作流、core、db 和 models 分层。五类通用文本资源、反馈纠错包、证据约束 Tutor 和单来源互动课件已有独立边界；文本任务使用 Web `BackgroundTasks`，课件使用独立 Durable Worker。前端优化沿用这些 API 和数据契约。

事实依据是 [前端路由](../frontend/src/router/index.js)、当前 `frontend/src/features/`、[后端路由装配](../backend/app/main.py)、领域 DTO / Service / 工作流、[配置模板](../backend/.env.example)、[启动器](../scripts/start_local.py)、[测试清单](../tests/suites.json) 和受版本控制的知识库 / fixture。此次未读取个人 `.env`、查询真实运行数据库或据历史计划推断完成状态。

## 2. 已修正的不同步内容

| 核对项 | 原有差异 | 文档修正 |
|---|---|---|
| 前端结构与路由 | README 保留旧目录；资料 / 历史路由写成旧值 | 同步 `features/`、`components/`、`ui/`，使用 `/user/profile`、`/learning/history`；补充公开入口、旧 URL 重定向和登录守卫 |
| 页面能力 | 五步引导被列为待完成，部分前端能力被描述为缺失 | 按当前实现同步五步确认、批次工作区、专注模式、四图报告、画像请求归属、响应式及动效边界 |
| 账号契约 | 以用户资料创建接口作为注册入口 | 注册使用 `/api/auth/register`；补充 Cookie、本人权限和状态码，注明主应用的 `POST /api/users/` 返回 403 |
| 正式反馈 | 聚合分数被当作掌握度写入口，后续生成被描述为自动触发 | 使用 run / batch 服务端判分入口；旧聚合入口返回 422；学习者确认下一步方案后才创建后续任务 |
| 审核与发布 | 流程图将关闭普通审核画成通过；Claim 分支遗漏独立审计与发布例外 | 关闭普通审核仅保存草稿；普通返工优先，eligible 资源独立接受 Claim 审计；区分阻断、待用户决定与配置允许的不完整降级 |
| 配置与数据 | 数据库路径写成临时探测库，预算与默认配置说明滞后 | 同步模板的 `backend/data/domain_knowledge.db`、调用预算、Settings / 模板差异、现有迁移和部分唯一索引；历史索引数量明确标注快照日期 |
| 启动与部署 | 首次启动步骤未明确先完成配置 / 模型准备，Docker 范围不清 | 将安装、初始化与实际启动分开，解释 `--check`；说明单 Worker、前端静态代理、Docker 仅含后端 Web 的边界 |
| 测试与证据 | 专项数量、浏览器通道与部分产物路径过期 | 同步 8 项 Node 单元与 13 项浏览器、统一 profile、证据目录及当前课件评测 / 浏览器报告契约 |
| 状态结论 | 历史验证、离线成绩和当前功能状态容易混用 | 保留历史日期和证据类型，指标写为目标；隔离 fixture、真实模型、CI 和目标部署分别记录 |

已更新 [README](../README.md)、[架构](architecture.md)、[功能](features.md)、[API](api.md)、[知识库与数据库](knowledge_base_database.md)、[需求](requirements.md)、[部署](deployment.md)、[Demo Runbook](demo-runbook.md)、[测试入口](testing/README.md)。同步修改资源生产工作流、代码架构和三类学习者对比三份 SVG；四份页面专项合同及比赛方案保留其当前有效说明。

## 3. 代码侧遗留问题

| 位置 | 已确认的问题 | 对文档 / 验收的影响 |
|---|---|---|
| [旧 P0-09 验收脚本](../scripts/run_p0_09_acceptance.py) 的 `--runtime` | 读取不存在的旧 `views/FeedbackView.vue`、`views/ReportView.vue`、`components/ResourceViewer.vue`，检查旧 `api/runEvents.js`，并使用旧反馈 / 报告静态字段 | 可能在输出完整 manifest 前抛出 `FileNotFoundError`；修复路径和静态契约前不能用它判定当前前端能力。该模式还会启动 FastAPI lifespan 并执行正常初始化 / 对账，不能称为全程只读 |
| 前端 API 封装 | 仍保留文本 `getPreview` 和资源表示级 `retryResourceRepresentation`，当前后端没有对应挂载路径，业务页面也未调用 | 不列为可用接口；文本阅读使用发布详情 / 文件，追加与重试使用批次 continuation，互动预览使用课件 API |
| [Dockerfile](../Dockerfile) 的构建范围 | 仅启动后端 Web，未构建前端或启动课件 Worker；仓库没有 `.dockerignore` | 不能描述为完整三进程部署；发布镜像前应使用干净构建上下文，避免 `COPY backend` 带入本地配置和运行数据 |

上述问题仅记录，未在此次文档任务中修改代码。当前隔离工程入口为 `python scripts/run_tests.py --profile acceptance`；目标环境 readiness 与真实业务演示仍按 Runbook 单独验收。

## 4. 本次验证与证据边界

| 检查 | 实际结果 |
|---|---|
| Markdown 链接、文件路径、代码块与 SVG XML | 扫描 16 份 Markdown，104 个本地链接有效，代码块闭合，7 份 JSON 示例有效，6 份 SVG 可解析；本次修改路径逐一对照源码 |
| API 静态清单 | 通过 AST 核对 19 个挂载 Router、76 条 `/api` 路由，API 文档全部覆盖；已移除路径只作为兼容边界说明 |
| 前端测试登记与 npm 命令 | 8 个 unit、13 个 browser 文件各登记一次，无遗漏；文档中的 npm script 均存在 |
| 知识库与冻结来源 | 源文件为 6 模块、13 节点、15 条先修关系、39 道诊断题、130 道测评题、4 道通用 / 5 道方向问卷题；比赛 fixture 为 18 画像、54 案例、78 Claim，10 文件 / 51 章节，10 份源文件哈希一致 |
| `python scripts/run_tests.py --list` | 退出码 0，套件与 quick / regression / acceptance 组成和文档一致 |
| `python scripts/run_tests.py --profile acceptance --dry-run` | 退出码 0，列出 6 个套件的计划命令，未实际运行这些套件 |
| `python scripts/start_local.py --help` | 退出码 0，文档引用选项存在，未启动服务或执行初始化 |
| SVG 浏览器检查 | 修改图以 Edge 离线渲染，核对文字边界与排版；无图内文字超出画布 |
| `git diff --check` 与收尾 diff / status | 空白检查退出码 0；检查本次文档改动及工作区，保留已有修改，未提交或推送 |

本次为纯文档维护，未执行前后端完整回归、业务页面浏览器验收、冻结工作流评测、真实模型、Worker 故障注入、CI 或目标部署。SVG 排版检查只证明图示可读；源码、命令清单与 fixture 哈希核对不构成上述运行证据。未初始化、迁移或重建真实数据库 / Chroma；临时核对文件和截图在收尾清理。
