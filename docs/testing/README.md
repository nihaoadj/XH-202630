# 项目测试方案

> 文档核对日期：2026-10-25；登记数量以 `tests/suites.json` 为准，当前结果以本次 `output/test-runs/` 报告为准。

本方案把工程回归、冻结评测、浏览器体验、真实模型质量和部署验收分别组织成可执行套件。套件成员以 [`tests/suites.json`](../../tests/suites.json) 为准，运行工具为 [`scripts/run_tests.py`](../../scripts/run_tests.py)。比赛数据与三项质量指标见 [比赛评测方案](competition.md)。更新计划与本地 skills 不随仓库分发。

知识资料完整性按RAG目录的精确字节校验；Git换行策略见根`.gitattributes`，更新该策略时须将RAG已跟踪资产重新暂存以消除旧Git转换，不得只提交属性文件。术语溯源更新先逐条核对原始快照hash与正文锚点，再同步当前hash及registry；历史重放通过内容寻址`.source`保留旧记录，不能用当前记录替代旧hash。冻结比赛快照仅在核对教学模块与所有金标证据仍完全相同后同步清洗辅助资料hash，篡改拒绝与质量阈值不放宽。

## 一、执行层级与职责

| 层级 | 所在位置 | 验证什么 | 数据与外部依赖 |
|---|---|---|---|
| 后端单元 | `backend/tests/unit/<domain>/` | DTO、策略、Agent 输出契约、指标、渲染与测试工具边界 | 内存、固定数据、测试替身 |
| 后端集成 | `backend/tests/integration/{api,persistence,services,workflow,courseware}/` | 跨层调用、事务、认证、事件、审核纠偏、发布 | 隔离数据库与冻结响应 |
| 数据迁移 | `backend/tests/migrations/` | 表结构升级、旧数据、外键与回滚兼容 | 测试数据库 |
| 生命周期 | `backend/tests/e2e/` | 重启恢复、SSE 回放、耐久执行、进程故障 | 临时进程和数据库；按具体测试判断故障范围 |
| 前端单元 | `frontend/tests/`，catalog 的 unit 组 | 状态、难度/掌握度、报告数据、事件、资源排序 | Node，无浏览器 |
| 前端浏览器 | catalog 的 browser 组 | 首页/账号、能力展示、工作台、新建方向、资源生产、学习报告、课件、学习反馈、学习历史、用户资料、画像请求归属及页面/模块动效 | Playwright、隔离 HTTP fixture；不写真实账号或反馈 |
| 冻结评测 | `backend/tests/fixtures/{competition,courseware}/` | 固定输入下的数据/策略/指标与课件硬门 | 版本化本地来源，禁止动态拉取替代快照 |
| 真实模型 | `backend/tests/live/` 与显式评测 CLI | 生产生成与模型自审的实际输出、耗时、失败 | 单独授权、有效凭据、隔离测试环境与预算 |
| CI / 部署 | `.github/workflows/courseware-quality.yml`、demo-runbook | 干净 runner 与实际运行环境验收 | CI 必需 job；部署证据单独记录 |

后端继续按目录自动添加 `unit`、`integration`、`migration`、`e2e`、`live_llm` marker，不搬动现有测试。前端 unit/browser 文件成员以 `tests/suites.json` 为准，聚合入口检查是否遗漏或重复注册；新增文件必须登记一次。`coursewareUserJourney.test.mjs` 是 Node 的用户流程状态验证，不能因名称而算作真实浏览器 e2e。

后端课件浏览器冒烟使用独立临时 Edge profile，通过仅绑定 `127.0.0.1` 的 CDP
读取实际 DOM，检查页码、场景激活与 JavaScript 错误，并包含脚本异常及启动超时清理负例。
它不依赖 Edge `--dump-dom` 的标准输出，也不要求 Node 或 Playwright；启动、连接、
命令与关闭都有超时，结束后关闭本次浏览器；启动失败时仅按本次临时 profile
精确识别并清理已分离的测试进程（进程管理使用开发锁中的 `psutil`，需安装开发依赖）。
未安装 Edge 时沿用该项的可选跳过策略；
浏览器已安装但启动失败、页面异常或关闭失败时会失败，不能跳过代替。

报告 SSE 的真实 HTTP 测试显式使用 `trust_env=False` 直连临时本地服务，并在测试
作用域设置无效代理来验证隔离。快照/变更事件及正常停机断言仍保留；不改动系统代理。
前端清单校验以实际测试文件集合、唯一性与关键专项为依据，不再用固定数量断言，
新增专项仍须在 `tests/suites.json` 登记。

## 二、统一命令

从仓库根运行，依赖安装沿用 [README](../../README.md)。

```powershell
python scripts/run_tests.py --list
python scripts/run_tests.py --profile acceptance --dry-run
python scripts/run_tests.py --profile quick
python scripts/run_tests.py --profile regression
python scripts/run_tests.py --profile acceptance
python scripts/run_tests.py --suite backend-api --suite backend-migration
```

| 组合 | 成员 | 适用场景 |
|---|---|---|
| quick | 架构导入、生成契约漂移、核心契约/策略/报告/工具、比赛金标、前端单元 | 迭代中快速定位；不替代领域最低验收 |
| regression | quick 中两个静态门禁、Ruff / ESLint / 关键 API/SSE/请求类型、Python 依赖一致性、后端全量、比赛金标、课件冻结、全部前端单元、生产构建 | 共享测试设施或多领域回归 |
| acceptance | regression 加十五个浏览器专项 | 本地完整工程验收 |

`--suite` 可重复，和 profile 组合时去重。`--fail-fast` 停止后续执行，但摘要将余下套件记为 `NOT_RUN`；默认尽量执行全部已选套件以便一次定位问题。只运行 `frontend-browser` 时，须先执行 `frontend-build`；acceptance 已按依赖顺序安排。直接 pytest 与原 npm 专项命令继续可用：

```powershell
python -m pytest -m unit
npm --prefix frontend test
npm --prefix frontend run test:browser
npm --prefix frontend run test:resource-shelf
npm --prefix frontend run test:onboarding-browser
npm --prefix frontend run test:generation-browser
npm --prefix frontend run test:feedback-browser
npm --prefix frontend run test:history-ui-browser
npm --prefix frontend run test:report-ui-browser
npm --prefix frontend run test:user-profile-ui-browser
npm --prefix frontend run test:profile-request-browser
npm --prefix frontend run test:motion-browser
npm --prefix frontend run test:tutor-ui-browser
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

### 关键契约与架构门禁

```powershell
python scripts/export_frontend_contracts.py
python scripts/export_frontend_contracts.py --check
python scripts/check_architecture.py
python scripts/run_tests.py --suite architecture --suite frontend-contracts --suite frontend-typecheck --suite frontend-unit
```

导出脚本从 22 个后端 Pydantic 根模型及状态/事件枚举生成 [`contracts.d.ts`](../../frontend/src/contracts/generated/contracts.d.ts)、[`constants.js`](../../frontend/src/contracts/generated/constants.js) 和 [`schema.json`](../../frontend/src/contracts/generated/schema.json)。`--check` 只比较，不改文件；新增未支持的结构 schema 会失败。扩展字段使用 `unknown`，不把类型声明当作运行时完整校验。合成边界 fixture 位于 [`tests/contracts/v1.json`](../../tests/contracts/v1.json)，生成确定性和漂移负例见 [`test_frontend_contracts.py`](../../backend/tests/unit/tooling/test_frontend_contracts.py)。

[`tsconfig.quality.json`](../../frontend/tsconfig.quality.json) 的严格 `checkJs` 根文件包括真实 HTTP 客户端、领域 API、课件发送器、Run/报告 SSE 客户端、报告 200/304 adapter、请求上下文和生成命令协调器。API 保持完整 `AxiosResponse<DTO>`；Vue 组件及大型 reducer 尚未全量纳入类型检查。运行时只校验 ACK、身份、状态、序号、报告窗口/revision 等关键字段。非法 ACK 不删除队列；非法 SSE 不更新当前状态；304 不伪造正文。真实 Axios adapter 与生产 wrapper 的边界测试、合法正例及错误 ACK 层级/状态/窗口/revision/可空值的编译负例在 [`contracts.test.mjs`](../../frontend/tests/contracts.test.mjs) 中执行，另有对生产发送器错误层级的临时变异检查。

AST 门禁覆盖 `core/`、`agents/shared/`、`api/` 的绝对/相对、函数内、`TYPE_CHECKING` 和可静态解析的动态导入。共享层不能反向依赖业务 API/Service/Agent，API 不能直接导入 Agent；不限制合法 Service 编排和组合根。受限目录无法解析的动态目标会失败。两处既有课件 harness 转发保留精确 source→target 例外，原因及删除条件见 [`architecture-import-exceptions.json`](../../tests/architecture-import-exceptions.json)；多余或过期例外失败。该门禁只验证可识别的导入边，不能证明任意 Python 执行、SQL 位置或事务归属。违规注入及 CLI 非零退出测试见 [`test_architecture.py`](../../backend/tests/unit/tooling/test_architecture.py)。

### 用例内部准备与组合验证

[`test_feedback_preparation.py`](../../backend/tests/unit/services/test_feedback_preparation.py) 使用明确的已确认选项和评分替身，验证 Claim 请求拆分/纠错包批次、Tutor 不可用回退、短答复评阈值及分歧、加权分数/题序与提交参数。正式事务、重放和审计/关系失败回滚继续由现有 [反馈服务集成](../../backend/tests/integration/services/test_feedback_loop_service.py)、[反馈 API](../../backend/tests/integration/api/test_feedback_api.py) 和 [重启恢复](../../backend/tests/e2e/test_feedback_restart_recovery.py) 验证，不把纯准备函数通过当作已提交事实的证据。

[`test_courseware_stages.py`](../../backend/tests/unit/agents/test_courseware_stages.py) 验证设计/场景阶段显式失败、未知组件/来源硬门、warning 稳定顺序、冻结绑定及恢复不重复 compose。工作流仍需通过 [冻结等价](../../backend/tests/integration/courseware/test_workflow_equivalence.py)、[检查点恢复](../../backend/tests/integration/courseware/test_executor_recovery.py) 和 [候选发布](../../backend/tests/integration/courseware/test_candidate_release.py)，以及全量课件 e2e/冻结评测/浏览器；等价测试固定身份与时钟核对历史产物 hash，不能通过更新 baseline 掩盖结构提取造成的变化。

[`generationPreparation.test.mjs`](../../frontend/tests/generationPreparation.test.mjs) 经真实 Axios wrapper 验证 continuation 请求形状和 Claim 并行完成后的响应顺序；对生产资源 hook 验证 A→B→A、旧成功/失败、卸载、节点等待后上下文已失效及两个独立版本号。生产 `useGenerationCommands.js` 的四命令矩阵覆盖正常自选新 Run、重复点击、同画像切任务/切画像/ABA/卸载后的成功与失败、旧 finally 与新 busy/key、独立通道、共享资源 key、列表刷新 false/切换和订阅等待后失效。

[`generationBrowser.test.mjs`](../../frontend/tests/generationBrowser.test.mjs) 的 command 竞态用例通过实际 GenerateView/DOM/Axios，分别 hold 已受理 continuation 响应或其后列表刷新；检查同画像切任务、ABA、旧失败、弹窗归属、列表失败、旧列表收尾时新命令/列表的忙碌状态，以及已受理任务的列表重新发现。它们与原页面完整矩阵一起运行，复用现有 browser 登记；画像请求专项仍拒绝全部非 GET。T24 保留原实现的行为失败反例，再用新构建验证修复，证据见 [T24](../update_plan/T24.md)。页面的其他切换、重试、追加和订阅清理仍由 generation/profile-request/onboarding 浏览器组合验证，Node 或本地 HTTP fixture 均不替代真实后端、真实模型或部署证据。

### 浏览器专项与证据位置

先执行 `npm --prefix frontend run build`；既有专项读取 `frontend/dist`，新增同步专项为真实 Vue 组件启动隔离 Vite fixture。下面列出全部 15 个 browser 成员。更细的页面合同保留在源码与已链接的专项说明中。

| npm 专项 | 主要覆盖 | 本地证据目录 / 文件 |
|---|---|---|
| `test:landing-browser` | 六屏入口、账号弹窗、翻页与登录 / 注册 fixture | `frontend/tests/test-results/landing-ui/` |
| `test:feature-showcase-browser` | 四个机制示意、章节 / 旧 URL、真实知识图谱对照和演示生命周期 | `frontend/tests/test-results/feature-showcase/` |
| `test:dashboard-browser` | 推荐分支、画像切换、工作台一屏 / 回退、共享侧栏 | `frontend/tests/test-results/dashboard-ui/` |
| `test:onboarding-browser` | 五步引导、条件题、复测、资源确认和请求 payload | `frontend/tests/test-results/onboarding-ui/` |
| `test:generation-browser` | 文本 / 课件任务、追加 / 重试、Claim 决策、阅读与专注模式 | `frontend/tests/test-results/generation-ui/` |
| `test:feedback-browser` | 正式测评、反思、逐题结果、纠错与下一步选择 | `frontend/tests/test-results/feedback-ui/` |
| `test:learning-report-browser` | 报告自动更新、SSE / ETag、图表交互 | `frontend/tests/test-results/learning-report/` |
| `test:courseware-browser` | 课件实际 HTML、发布来源、组件状态、恢复与安全 | `frontend/tests/test-results/courseware-browser/` |
| `test:courseware-sync-browser` | 真实 Viewer/Pinia/Axios 与 IndexedDB：250 条分批、部分 ACK、账号/版本迟到响应、401 登录恢复、隔离导出、存储失败及双标签 | `frontend/tests/test-results/courseware-sync/` |
| `test:history-ui-browser` | 画像、轮次、未关联事件、分页和删除后恢复 | `frontend/tests/test-results/history-ui/`；[合同](history-ui.md) |
| `test:report-ui-browser` | 四图字段 / 颜色 / 字号和实际节点框、标签可见性 | `frontend/tests/test-results/report-ui/`；[合同](report-ui.md) |
| `test:user-profile-ui-browser` | 本人资料字段、保存 / 失败 / 重试、响应式与路由样式 | `frontend/tests/test-results/user-profile-ui/`；[合同](user-profile-ui.md) |
| `test:profile-request-browser` | 历史 / 报告 / 生成 / 资源四页画像竞态和失败归属 | `frontend/tests/test-results/ui-repair/profile-requests/` |
| `test:motion-browser` | 页面 / 模块过渡、减少动态效果、快速导航和清理 | `frontend/tests/test-results/motion-ui/`；[合同](motion-ui.md) |
| `test:tutor-ui-browser` | Tutor 消息、引用、输入、等待与失败恢复，普通/专注/测评及五页顶部辅助导航 | `frontend/tests/test-results/tutor-ui/` |

本地 HTTP fixture 中允许的登录、注册、资料 PATCH、画像 DELETE、测评和方案确认只写入各脚本的隔离服务。业务写入、外网和页面异常按各专项审计，不能以这些 fixture 结果推断真实后端事务、模型质量或目标部署已通过。

默认统一入口将 `RUN_LIVE_LLM`、`COURSEWARE_LIVE_EVAL` 设为 `0`，即使调用者环境原来为 `1`。它不会为正式质量评测自动启用模型。原始 `python -m pytest` 不经过该保护，使用时仍须遵守仓库 live 授权规则。

Windows 默认使用已安装的 Edge；其他平台默认使用 Playwright Chromium。CI 安装 Chromium。`TEST_BROWSER_CHANNEL` 可统一选择通道，设置为空字符串选择 Playwright Chromium，各专项自己的 `*_BROWSER_CHANNEL` 优先。聚合浏览器入口强制必需模式，浏览器不可启动会失败；单独旧课件专项的可选 skip 不能用作验收证据。

`scripts/run_p0_09_acceptance.py --runtime` 的前端探针已适配现行目录，仅核对源码连线，不替代浏览器行为验证；该模式启动 TestClient lifespan，会初始化数据库和启动对账。统一 acceptance 是隔离工程验收；runtime 须在隔离 demo 环境执行，步骤见 [Demo Runbook](../demo-runbook.md)。

## 三、需求与功能覆盖矩阵

| ID / 功能 | 主要可执行证据 | 套件与验收要点 |
|---|---|---|
| F-AUTH 认证与 HTTP/DTO | [API 测试](../../backend/tests/integration/api/)、[契约单元](../../backend/tests/unit/models/) | backend-api；状态码、非法输入与身份隔离 |
| F-PROFILE 画像、诊断、学情定阶 | [策略](../../backend/tests/unit/policies/)、[生成映射](../../backend/tests/integration/services/test_generation_mapping.py) | unit/integration；前置知识、目标节点与难度策略 |
| F-ONBOARDING 新建方向、问卷与诊断界面 | [浏览器专项](../../frontend/tests/onboardingBrowser.test.mjs) | frontend-browser；领域/方向桌面一屏、问卷区域内部滚动、条件题、复测、资源选择与 fixture payload |
| F-GENERATION 资源生产工作台与文本阅读 | [浏览器专项](../../frontend/tests/generationBrowser.test.mjs) | frontend-browser；任务状态、桌面内部滚动与响应式、重试、追加/Claim、阅读与课件嵌入；学习页资源切换/下载/Tutor/专注模式及按钮对比度；所有写入只到 fixture |
| F-KB 入库/检索/来源 | [检索集成](../../backend/tests/integration/services/test_evidence_retriever.py)、[来源快照单元](../../backend/tests/unit/reports/test_competition_evidence.py) | integration/competition；证据不足、跨 KB、正文漂移拒绝 |
| F-E1 公共／专属证据分配 | [查询调度](../../backend/tests/unit/agents/test_resource_query_schedule.py)、[真实候选与记录路径](../../backend/tests/integration/services/test_resource_aware_retrieval.py)、[下游范围](../../backend/tests/integration/workflow/test_resource_aware_workflow.py) | backend-full；五类／混合、owner配额/评分/归属、C/S/A、完整Planner及预算、引用隔离、旧spec、修订与checkpoint。真实模型收益另验，见 [T26](../update_plan/T26.md) |
| F-AGENT 分工与协同 | [证据工作流](../../backend/tests/integration/workflow/test_evidence_workflow.py)、[54 例回放](../../backend/tests/integration/workflow/test_competition_replay.py) | backend-workflow；实际 graph 控制和可追溯中间输出 |
| F-RESOURCE 五类文档 | [资源 Agent](../../backend/tests/unit/agents/test_resource_type_agents.py)、[资源 API](../../backend/tests/integration/api/test_resource_api.py)、[生成任务 API](../../backend/tests/integration/api/test_generate_jobs_api.py) | backend-full；讲义/实操/分阶题/案例/清单原行为 |
| F-REVIEW 审核/纠偏/Claim/发布 | [Claim 工作流](../../backend/tests/integration/workflow/test_claim_workflow.py)、[发布定稿](../../backend/tests/integration/services/test_generation_finalization.py)、[资源 API](../../backend/tests/integration/api/test_resource_api.py) | backend-workflow/full；保留历史版本、仅统计最终发布叶子 |
| F-READ Markdown 与资源库 | [资源库 API](../../backend/tests/integration/api/test_resource_library_api.py)、[资源详情](../../backend/tests/integration/api/test_resource_api.py)、`resourceShelfOrder.test.mjs` | backend-api/frontend-unit；公开产物与排序 |
| F-FEEDBACK 学习反馈与动态路径 | [浏览器专项](../../frontend/tests/feedbackBrowser.test.mjs)、[反馈闭环](../../backend/tests/integration/services/test_feedback_loop_service.py)、[掌握度策略](../../backend/tests/unit/policies/test_learner_mastery_policy.py)、`learnerMastery.test.mjs` | integration/unit/browser；低正确率补救、强化/推进与版本变化；测评题、反思 payload、反馈结果、纠错与下一步选择；浏览器提交只写本地 fixture |
| F-TUTOR 导学 | [Tutor 服务](../../backend/tests/unit/services/test_tutor_service.py)、`tutorState.test.mjs`、[Tutor 界面专项](../../frontend/tests/tutorUiBrowser.test.mjs) | backend-unit/frontend-unit/browser；上下文与追问状态、消息/引用/输入、等待防重复、失败恢复及响应式可达性 |
| F-REPORT 学情、难度与路径报告 | [真实SQL读取专项](../../backend/tests/integration/services/test_report_read_model.py)、[P0-35迁移](../../backend/tests/migrations/test_p0_35_report_read_model.py)、[报告API](../../backend/tests/integration/api/test_report_api.py)、[报告可视化](../../backend/tests/unit/reports/test_report_visualizations.py)、`learningReport.test.mjs`、[报告 UI 专项](../../frontend/tests/reportUiBrowser.test.mjs)、`learningReportBrowser.test.mjs` | unit/integration/migration/browser；完整revision/滚动时间失效、304 metadata、10001历史、批量/分页/并发与权限；图表交互、SSE/ETag 与实际节点边界可见性 |
| F-HISTORY 学习历史与旅程 | [历史 UI 专项](../../frontend/tests/historyUiBrowser.test.mjs) | browser；画像归属、分页、轮次与未关联事件时间过滤、删除后选择并加载替代画像 |
| F-PROFILE-UI 用户资料 | [资料 UI 专项](../../frontend/tests/userProfileUiBrowser.test.mjs) | browser；字段、PATCH payload、保存/失败/重试、布局与页面路由行为合同 |
| F-PROFILE-RACE 四页画像请求归属 | [请求竞态专项](../../frontend/tests/profileRequestBrowser.test.mjs) | browser；history/report/generation/resources 慢响应乱序、失败与重试不串画像数据 |
| F-MOTION 页面与模块动效 | [动效专项](../../frontend/tests/motionBrowser.test.mjs) | browser_fixture；真实导航、原生/回退、资源焦点模式、模块状态、减少动态效果与异常清理 |
| F-RECOVERY 事件、重启、数据库 | [e2e](../../backend/tests/e2e/)、[迁移](../../backend/tests/migrations/) | backend-e2e/migration；重复执行、回放、旧数据兼容 |
| F-COURSEWARE 互动课件硬门 | [课件单元](../../backend/tests/unit/core/)、[课件集成](../../backend/tests/integration/courseware/)、[课件 e2e](../../backend/tests/e2e/courseware/) | backend-full/courseware-eval/browser；安全、fallback、hash、发布幂等 |
| Q-COMP 比赛三指标与数据完整性 | [比赛金标单元](../../backend/tests/unit/reports/test_competition_suite.py)、[指标集成](../../backend/tests/integration/workflow/test_competition_metrics.py) | competition；≥50 用例/三背景/三资源形态，详见比赛方案 |

矩阵映射功能与现有可执行文件，不把测试文件数、参数化数量或覆盖率工具的行覆盖率当作比赛用例数。以根 AGENTS.md 的影响矩阵选最低验收；跨领域取并集。没有修改的低影响文案无需全量。

## 四、数据与证据治理

- fixture 按领域存于 `backend/tests/fixtures/`，版本、来源、画像、期望与负例须可审查；使用虚构/脱敏画像。真实敏感数据不得复制到 fixture、日志或报告。
- 修改输入契约、来源或期望先说明依据并更新相应 fixture/version；知识库正文变化会使 competition 加载失败，复核标注后显式更新快照，禁止用自动重写快照掩盖漂移。
- 同一行为只保留一份权威实现。CLI 组织原测试入口，指标复用既有 Claim/难度计算；不要在 runner 内实现业务或重新写一套判分逻辑。
- 新测试必须说明所防止的错误和可观察结果。优先验证边界、非法输入、事务、重试和缺证据；避免只镜像实现的断言。

## 五、报告与通过标准

每次默认产生独立的 `output/test-runs/<UTC时间>-<ID>/`；可用 `--output` 指定空目录，已有非空目录会拒绝复用。目录包含 `summary.json`、`summary.md`、每套日志、pytest JUnit、评测 JSON、前端分组 JSON。后端全量另输出 `competition-replay.json`，包含54例完整固定输入/协同轨迹/Claim/资源示例。浏览器截图继续在 `frontend/tests/test-results/`，前端分组报告与日志指向对应专项；这些是本地产物，已忽略，不提交。

摘要记录 Git SHA、dirty 状态、套件目录 hash、命令、工作目录、退出码、耗时、JUnit 跳过/失败/错误数量和报告文件 hash。Git dirty 只是记录身份信息，不证明所有改动已经提交。pytest 临时目录/cache 和子进程 TEMP 均隔离到本次产物，避开旧目录权限与不同运行混用。

| 状态 | 含义 | 总体退出码 |
|---|---|---|
| PASS | 该工程套件实际命令退出 0 | 全部已选套件 PASS 才为 0 |
| FAIL | 命令返回非 0 | 1 |
| ERROR | 命令无法启动 | 1 |
| TIMEOUT | 超过套件预算，结束本次启动的进程树 | 1 |
| NOT_RUN | fail-fast 后未执行 | 1 |

pytest 中按规则 skip 的真实模型测试须从 JUnit 单独读取；它们不因工程套件 PASS 而成为模型验证证据。比赛的 `NOT_MEASURABLE` 与上述执行状态分别记录；offline_gold 的数值 PASS 只说明金标回归通过，正式质量门仍缺证据。

CI 的 backend job 使用 Python 3.11/3.12 必需矩阵（`fail-fast=false`），各版本真实安装哈希锁，运行 Ruff（含 `backend/scripts/`）、架构/生成契约门禁、依赖检查及 backend-full/competition/courseware-eval。课件 CI artifacts 和故障矩阵均保留，每个版本分别上传产物；required-gates 检查整个 backend 矩阵与 frontend。frontend 使用 Python 3.11 / Node 24，执行 ESLint、类型检查及 frontend-unit/build/browser；既有手动 live job 保留，须另行授权使用。

故障矩阵只接受专属 `test_c1_process_fault_matrix` 模块的进程证据，缺失/失败/跳过均阻断；全量测试中的其他失败仍由 backend-full 独立阻断。前端源码、测试工具、知识库与 PR 均在触发范围。本地现有环境、隔离锁定环境和远端 CI 证据分别记录；环境版本漂移必须保留失败摘要，不能以 `pip check` 通过替代精确锁一致性。远端 CI 或部署未经实际执行不得标为通过。

## 六、交付清单

交付检查包含：需求矩阵与计划、版本化 suite/fixture/来源、已执行命令、失败修复与未执行原因、JUnit/逐例 JSON/浏览器证据以及 Git diff/status。比赛提交另按比赛方案补真实模型与独立质量证据。生产 readiness、Worker 故障覆盖、SCORM/xAPI 完整兼容分别需要相应验收，不能由此处汇总推导。


## 报告读取专项与性能基准

确定性用例：`backend/tests/unit/reports/test_report_snapshots.py`、`backend/tests/integration/services/test_report_read_model.py`、`backend/tests/migrations/test_p0_35_report_read_model.py`。它们覆盖完整语义/新增字段兜底、事实时间保留、未来Attempt进入/本期到上期/退出、mastery趋势跨窗、无缓存构建跨边界重试、原生SQLite同事务失效、全部27来源增改删/回滚、lease-only不失效、旧结构/缺trigger/未知protocol、安全降级、key隔离与权限、singleflight、缓存大小/闲置/容量、正文拷贝，以及SQL/Memory可见性与旧游标400对照。API/真实HTTP SSE和异步事件循环回归仍保留。

```powershell
python scripts/run_tests.py --suite backend-full --suite frontend-contracts --output output/test-runs/report-regression
python backend/scripts/report_benchmark.py --output output/test-runs/report-benchmark --sizes 100 1000 10000 --repeats 3
```

基准独立于常规suite：临时SQLite开外键，固定30资源（同Run多类型、发布修订、审核/Claim精确绑定）、6 Run，100/1000/10000条完整正式记录，冻结UTC计算时点；能力图谱规模不是本基准变量。初始mastery/tier初始化后测量暖 GET、条件GET/304、5条可信度页、单订阅和三订阅实际poll函数，各至少3样本。`report.json` 与 `size-N.json` 记录种子/input hash、Python/源码身份、SQL语句数、ORM对象装载数、构建次数、每次耗时/峰值和样本P95。它不计物理扫描行、不模拟网络SSE长连接/跨Web进程/线上模型流量，也没有人为设定的速度提升百分比门槛。冷构建的完整历史与批量查询由10001专项单独核验；暖路径低成本不能外推冷构建容量。

前后比较必须使用相同种子和input hash，并保留改前源码/日志；不能修改before快照或用变小数据证明提速。通过标准：暖304/SSE不build或装载历史、SQL分页仅装载limit+1完整资源且无漏重/排序漂移、同Run证据复用、10001+聚合完整；失效正确性先于缓存收益。产物位于忽略的 `output/test-runs/`；相关浏览器专项为 learning-report/report-ui/profile-request/motion。首次失败、修复和隔离复跑分别记录，不把复跑PASS覆盖首次失败证据。

2026-10-23同输入前后测量见 [报告读取基准](report-read-performance.md)，包含原始本地证据链接与限制。

## 文本 Worker 与课件同步异常回归

`backend/tests/unit/services/test_generation_worker.py` 使用受控执行线程与锁错误/普通异常验证：续租和对账失败后不领取第二项，恢复后继续串行处理且 readiness 恢复，持续错误仍按停机预算退出，lease-lost 原因保留。真实 SQLite、失效执行者 fencing 与进程退出/重启由既有 `test_generation_dispatch.py` 和 `test_generation_worker_recovery.py` 继续验证；受控异常不等于真实线上故障演练。

`frontend/tests/coursewareEvents.test.mjs` 覆盖队列读取期间切换账号/resource/release、卸载、等待 Web Lock 及迟到状态更新，保留原批 ACK、部分确认和退避回归。`coursewareSyncBrowser.test.mjs` 通过真实 Viewer/Pinia/Axios/IndexedDB 链路延迟队列读取结果，验证切换账号/release 或卸载后旧事件仍保留且不上传，新上下文正常发送。

```powershell
python -m pytest backend/tests/unit/services/test_generation_worker.py backend/tests/integration/services/test_generation_dispatch.py backend/tests/e2e/test_generation_worker_recovery.py -q
node frontend/tests/coursewareEvents.test.mjs
npm --prefix frontend run test:courseware-sync-browser
```

以上直接专项不能替代根 AGENTS.md 要求的相关回归与前端生产构建；测试使用隔离的虚构事件和任务，不调用真实模型或业务数据库。
