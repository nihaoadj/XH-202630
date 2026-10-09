# 项目测试方案

> 文档核对日期：2026-10-09；登记数量以 `tests/suites.json` 为准，本次文档核对不代表重新执行业务验收。

本方案把工程回归、冻结评测、浏览器体验、真实模型质量和部署验收分别组织成可执行套件。套件成员以 [`tests/suites.json`](../../tests/suites.json) 为准，运行工具为 [`scripts/run_tests.py`](../../scripts/run_tests.py)。比赛数据与三项质量指标见 [比赛评测方案](competition.md)。更新计划与本地 skills 不随仓库分发。

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

后端继续按目录自动添加 `unit`、`integration`、`migration`、`e2e`、`live_llm` marker，不搬动现有测试。前端目前八个 unit 文件、十三个 browser 文件，聚合入口检查是否遗漏或重复注册；新增文件必须登记一次。`coursewareUserJourney.test.mjs` 是 Node 的用户流程状态验证，不能因名称而算作真实浏览器 e2e。

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
| quick | 核心契约/策略/报告/工具、比赛金标、前端单元 | 迭代中快速定位；不替代领域最低验收 |
| regression | 后端全量、比赛金标、课件冻结、全部前端单元、生产构建 | 共享测试设施或多领域回归 |
| acceptance | regression 加十三个浏览器专项 | 本地完整工程验收 |

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
node frontend/tests/run.mjs browser --output frontend/tests/test-results/ui-repair/frontend-browser.json
```

### 浏览器专项与证据位置

每个专项读取已构建的 `frontend/dist`，先执行 `npm --prefix frontend run build`；下面列出全部 13 个 browser 成员。更细的页面合同保留在源码与已链接的专项说明中。

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
| `test:history-ui-browser` | 画像、轮次、未关联事件、分页和删除后恢复 | `frontend/tests/test-results/history-ui/`；[合同](history-ui.md) |
| `test:report-ui-browser` | 四图字段 / 颜色 / 字号和实际节点框、标签可见性 | `frontend/tests/test-results/report-ui/`；[合同](report-ui.md) |
| `test:user-profile-ui-browser` | 本人资料字段、保存 / 失败 / 重试、响应式与路由样式 | `frontend/tests/test-results/user-profile-ui/`；[合同](user-profile-ui.md) |
| `test:profile-request-browser` | 历史 / 报告 / 生成 / 资源四页画像竞态和失败归属 | `frontend/tests/test-results/ui-repair/profile-requests/` |
| `test:motion-browser` | 页面 / 模块过渡、减少动态效果、快速导航和清理 | `frontend/tests/test-results/motion-ui/`；[合同](motion-ui.md) |

本地 HTTP fixture 中允许的登录、注册、资料 PATCH、画像 DELETE、测评和方案确认只写入各脚本的隔离服务。业务写入、外网和页面异常按各专项审计，不能以这些 fixture 结果推断真实后端事务、模型质量或目标部署已通过。

默认统一入口将 `RUN_LIVE_LLM`、`COURSEWARE_LIVE_EVAL` 设为 `0`，即使调用者环境原来为 `1`。它不会为正式质量评测自动启用模型。原始 `python -m pytest` 不经过该保护，使用时仍须遵守仓库 live 授权规则。

Windows 默认使用已安装的 Edge；其他平台默认使用 Playwright Chromium。CI 安装 Chromium。`TEST_BROWSER_CHANNEL` 可统一选择通道，设置为空字符串选择 Playwright Chromium，各专项自己的 `*_BROWSER_CHANNEL` 优先。聚合浏览器入口强制必需模式，浏览器不可启动会失败；单独旧课件专项的可选 skip 不能用作验收证据。

旧 `scripts/run_p0_09_acceptance.py --runtime` 当前引用已迁移的前端文件，并按旧契约静态检查，修复前不可作为工程入口或前端能力结论。统一 acceptance 是隔离工程验收；真实环境步骤和此遗留问题见 [Demo Runbook](../demo-runbook.md)。

## 三、需求与功能覆盖矩阵

| ID / 功能 | 主要可执行证据 | 套件与验收要点 |
|---|---|---|
| F-AUTH 认证与 HTTP/DTO | [API 测试](../../backend/tests/integration/api/)、[契约单元](../../backend/tests/unit/models/) | backend-api；状态码、非法输入与身份隔离 |
| F-PROFILE 画像、诊断、学情定阶 | [策略](../../backend/tests/unit/policies/)、[生成映射](../../backend/tests/integration/services/test_generation_mapping.py) | unit/integration；前置知识、目标节点与难度策略 |
| F-ONBOARDING 新建方向、问卷与诊断界面 | [浏览器专项](../../frontend/tests/onboardingBrowser.test.mjs) | frontend-browser；领域/方向桌面一屏、问卷区域内部滚动、条件题、复测、资源选择与 fixture payload |
| F-GENERATION 资源生产工作台与文本阅读 | [浏览器专项](../../frontend/tests/generationBrowser.test.mjs) | frontend-browser；任务状态、桌面内部滚动与响应式、重试、追加/Claim、阅读与课件嵌入；学习页资源切换/下载/Tutor/专注模式及按钮对比度；所有写入只到 fixture |
| F-KB 入库/检索/来源 | [检索集成](../../backend/tests/integration/services/test_evidence_retriever.py)、[来源快照单元](../../backend/tests/unit/reports/test_competition_evidence.py) | integration/competition；证据不足、跨 KB、正文漂移拒绝 |
| F-AGENT 分工与协同 | [证据工作流](../../backend/tests/integration/workflow/test_evidence_workflow.py)、[54 例回放](../../backend/tests/integration/workflow/test_competition_replay.py) | backend-workflow；实际 graph 控制和可追溯中间输出 |
| F-RESOURCE 五类文档 | [资源 Agent](../../backend/tests/unit/agents/test_resource_type_agents.py)、[资源 API](../../backend/tests/integration/api/test_resource_api.py)、[生成任务 API](../../backend/tests/integration/api/test_generate_jobs_api.py) | backend-full；讲义/实操/分阶题/案例/清单原行为 |
| F-REVIEW 审核/纠偏/Claim/发布 | [Claim 工作流](../../backend/tests/integration/workflow/test_claim_workflow.py)、[发布定稿](../../backend/tests/integration/services/test_generation_finalization.py)、[资源 API](../../backend/tests/integration/api/test_resource_api.py) | backend-workflow/full；保留历史版本、仅统计最终发布叶子 |
| F-READ Markdown 与资源库 | [资源库 API](../../backend/tests/integration/api/test_resource_library_api.py)、[资源详情](../../backend/tests/integration/api/test_resource_api.py)、`resourceShelfOrder.test.mjs` | backend-api/frontend-unit；公开产物与排序 |
| F-FEEDBACK 学习反馈与动态路径 | [浏览器专项](../../frontend/tests/feedbackBrowser.test.mjs)、[反馈闭环](../../backend/tests/integration/services/test_feedback_loop_service.py)、[掌握度策略](../../backend/tests/unit/policies/test_learner_mastery_policy.py)、`learnerMastery.test.mjs` | integration/unit/browser；低正确率补救、强化/推进与版本变化；测评题、反思 payload、反馈结果、纠错与下一步选择；浏览器提交只写本地 fixture |
| F-TUTOR 导学 | [Tutor 服务](../../backend/tests/unit/services/test_tutor_service.py)、`tutorState.test.mjs` | backend-unit/frontend-unit；上下文与追问状态 |
| F-REPORT 学情、难度与路径报告 | [报告可视化](../../backend/tests/unit/reports/test_report_visualizations.py)、`learningReport.test.mjs`、[报告 UI 专项](../../frontend/tests/reportUiBrowser.test.mjs)、`learningReportBrowser.test.mjs` | unit/browser；数据/颜色/字号契约、图表交互、SSE/ETag 与实际节点边界可见性 |
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

CI 的 backend job 使用 backend-full/competition/courseware-eval，frontend job 使用 frontend-unit/build/browser，并上传本次报告与浏览器证据。保留课件 CI artifacts、故障矩阵、required-gates 和既有手动 live job。故障矩阵只接受专属 `test_c1_process_fault_matrix` 模块的进程证据，缺失/失败/跳过均阻断；全量测试中的其他失败仍由 backend-full 独立阻断。新增前端源码、测试工具、知识库与 PR 触发；本地同命令通过不能声称 GitHub Actions 或部署已通过。

## 六、交付清单

交付检查包含：需求矩阵与计划、版本化 suite/fixture/来源、已执行命令、失败修复与未执行原因、JUnit/逐例 JSON/浏览器证据以及 Git diff/status。比赛提交另按比赛方案补真实模型与独立质量证据。生产 readiness、Worker 故障覆盖、SCORM/xAPI 完整兼容分别需要相应验收，不能由此处汇总推导。
