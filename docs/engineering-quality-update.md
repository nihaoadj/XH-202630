# T13 工程质量优化实施记录

日期：2026-10-10。基线提交：`577fc6ccb11bb13d4b5b396d05d308b459364334`。

## 总体结论与范围

本次按项目结构、代码规范、文件复杂度三个方向实施。沿用 FastAPI/Pydantic/SQLAlchemy/LangGraph 与 Vue 3/Pinia/Vite；调整实际代码归属、公开用例入口、关键类型与局部格式，提取稳定的领域计算和页面生命周期逻辑。

当前状态：01—05 全部完成，最终 acceptance 的六个套件均通过，退出码 0。结构、规范与职责归属已调整；通过契约、字节、工作流及浏览器检查验证本轮候选，验证边界和遗留项见下文。

本次保留 HTTP/DTO/认证、DI 构造与 provider、表名/字段、存储路径、事务顺序、Prompt/节点、事件与发布契约。没有新增业务功能、数据库迁移、运行配置、依赖升级或通用抽象框架。

## 分步索引

| 阶段 | 实施及验收记录 | 状态 |
|---|---|---|
| 01 项目结构 | [结构整理](update_plan/T13/01-project-structure.md) | 完成 |
| 02 代码规范 | [代码规范](update_plan/T13/02-code-conventions.md) | 完成 |
| 03 后端复杂度 | [后端职责提取](update_plan/T13/03-backend-complexity.md) | 完成 |
| 04 前端复杂度 | [生产页面逻辑](update_plan/T13/04-frontend-complexity.md) | 完成 |
| 05 运行时及收尾 | [运行资产及全范围验收](update_plan/T13/05-runtime-and-closeout.md) | 完成，无递延 |

[总计划](update_plan/T13.md) 及分步文档沿用同一个 T13。`docs/update_plan/` 为仓库既有忽略目录，未改变忽略规则；本文件保存可纳入版本控制的实施摘要。

## 问题、等级与实际优化

P1 表示已有入口失效；P2 表示职责、边界或表达影响长期维护；P3 为低紧迫度的组织改善。等级不由文件行数、个人引号或分号偏好决定。

| 问题 | 等级及原因 | 实际处理与兼容方式 |
|---|---|---|
| 根脚本引用已迁移路径 | P1：初始化、预检等入口无法正常导入 | 8 个脚本使用现有 `db.shared/learners/learning_documents`、`core.retrieval`、`models.learning_documents`、`services.reports` 等入口；仅改导入，不运行真实数据库初始化 |
| 课件 Agent/core 反向依赖业务 Service；仓储依赖 Agent 验证规则 | P2：基础能力与业务门面混杂，复用和测试受调用方向影响 | 来源准入、组装、追踪、候选发布实现在课件工作流领域；纯 review 在 core，资源不变量在 models；必要来源能力使用窄 `SourceResourcePort` |
| API 包含发布、续生成编排并调用报告私有方法 | P2：HTTP 适配与用例副作用交织 | 原 Service 增加公开用例；API 保留认证、HTTP 错误映射和最后的后台调度；延迟 factory 保持依赖解析及提交/事件顺序 |
| 关键依赖不明确、热点逻辑压缩成超长单行 | P2：接口要求与失败路径难审阅 | 描述当前仓储、LLM、learner context 与来源端口；补充关键 JSDoc/副作用说明，多行展开；不引入运行时校验或新工具 |
| Service 同时承载评分、推荐、图表与候选投影 | P2：确定性计算与读写编排混在大文件 | 提取同域 `feedback/assessment.py`、`recommendations.py`、`reports/projections.py`、`learners/generation_options.py`；门面和事务留在原 Service |
| 课件总编排及学习设计分支过长 | P2：生成、审核、持久化、发布等阶段难单独定位 | 提取 spec、单场景 compose、scene persistence、candidate artifact publication；core `storyboard.py` 管复习/实操及分页，总状态机和异常边界仍在 workflow |
| 页面同时管理监听、测评、发布和请求 | P2：职责集中，旧测试 hook 与生产逻辑分叉 | 实际页面使用 6 个同域 hook；页面 state/template/CSS 保留，旧 `useCoursewareJob` 保留公开兼容且说明差异；失效源码断言转为生产行为校验 |
| 运行时字符串包含连续替换和追加 | P3：静态源码与覆盖顺序难以维护 | 最终静态源码归入 `core/courseware/assets/`；原 CSS 覆盖顺序保留，STYLE/SCRIPT 字节相等，真实工作流等价案例通过 |

## 代码的真实归属

| 职责 | 实现位置 | 使用者 / 旧入口 |
|---|---|---|
| 不可变资源投影 | [models/learning_documents/invariants.py](../backend/app/models/learning_documents/invariants.py) | SQL/内存仓储；旧 validators 重导出 |
| 课件来源、组装、追踪、发布 | [interactive_courseware](../backend/app/agents/resource_workflows/interactive_courseware/) | workflow 直接使用；旧 services/courseware 同名模块仅兼容导出 |
| 纯来源及质量审核 | [core/courseware/review.py](../backend/app/core/courseware/review.py) | workflow 和确定性 evaluation；旧 Service 兼容 |
| recorded node | [agents/shared/recorded_node.py](../backend/app/agents/shared/recorded_node.py) | 文本工作流；旧 runs 模块兼容 |
| 业务评测执行 harness | [scripts/courseware_harness](../backend/scripts/courseware_harness/) | 两个 CLI 和直接测试；旧 core 入口按需转发，作为明确兼容例外 |
| 发布 / 续生成 / 报告列表用例 | [publication.py](../backend/app/services/learning_documents/publication.py)、[continuation.py](../backend/app/services/generation/continuation.py)、[reports.py](../backend/app/services/reports/reports.py) | 原 ResourceService、GenerationJobService、ReportService；构造函数及 provider 不变 |
| 生成监听、Claim、视口观察 | [useGenerationProgress](../frontend/src/features/generation/useGenerationProgress.js)、[useGenerationClaims](../frontend/src/features/generation/useGenerationClaims.js)、[useProductionLayout](../frontend/src/features/generation/useProductionLayout.js) | GenerateView 实际调用；生命周期注册保留原位置 |
| 测评 / 后续学习选择 | [useFeedbackEvaluation](../frontend/src/features/feedback/useFeedbackEvaluation.js)、[useFeedbackFollowup](../frontend/src/features/feedback/useFeedbackFollowup.js) | FeedbackView 实际调用；共享状态仍由页面持有 |
| 课件历史、恢复与追踪 | [useCoursewareTracking](../frontend/src/features/courseware/useCoursewareTracking.js) | CoursewareGenerationWorkspace 实际调用；未把行为不同的旧 hook 强接生产 |
| 课件运行资产 | [theme.css](../backend/app/core/courseware/assets/theme.css)、[runtime.js](../backend/app/core/courseware/assets/runtime.js) | runtime.py 按自身位置读取，Renderer 继续嵌入原资产；现有 Docker COPY 已覆盖 |

薄转发保留既有导入兼容，各职责的实现只有一份。它们不计入“物理迁移完成”的实现数量；后续只有在外部兼容入口可以撤销且完整回归通过后才能删除。

## 复杂度变化与取舍

下表为含注释/空行/字符串的物理行数，函数规模由 Python AST 范围计算，不等同于圈复杂度。数字基于同一 HEAD 与本次候选。

| 文件 / 热点 | 基线 → 整理后 | 实质变化 |
|---|---|---|
| FeedbackService 文件 | 2455 → 1879 | 题目/评分和推荐投影独立；`_build_question_specs` 119 → 17，原 helper 调用点仍可替换 |
| ReportService 文件 | 1624 → 997 | 四类展示投影独立；难度曲线门面 199 → 12，纯算法保留在同域模块 |
| MasteryService 文件 | 1355 → 1200 | `next_generation_options` 188 → 34；读取顺序和延迟完成度查询保持 |
| 课件 workflow | 1610 → 1542；`_run_workflow` 654 → 413 | 重点降低总编排的阶段交织，不机械追求整文件极短 |
| 学习设计 | 552 → 323；`build_learning_design` 399 → 253 | 另有 storyboard 分支模块；公共目标、配额与来源账本留在总设计 |
| GenerateView script | 1103 → 885 | 监听、Claim、视口职责提取，页面任务/画像状态仍共用 |
| FeedbackView script | 483 → 405 | 测评提交和后续选择提取，结果 watch 及状态所有权保留 |
| Courseware 工作区 script | 149 → 289 | 先展开压缩代码再提取 7 个生产函数，物理行数增加；以可读控制流和实际归属改善衡量，不以行数下降宣称收益 |
| runtime.py | 609 → 17 | 最终 CSS/JavaScript 移入同目录资产文件，删除构建字符串的替换与追加过程；没有减少原运行逻辑或清理 CSS 覆盖 |

Service 内的事务、模型调用与总流程仍可能较长：例如 `choose_followup`、`process_learning_attempt`、`_build_report_once`。继续切分必须证明存在稳定职责边界和副作用顺序收益，本轮没有把原子操作拆散或引入通用 Builder。

## 验证证据

| 阶段 | 实际命令 / 检查 | 结果及证据 |
|---|---|---|
| 01 | backend-full、competition、courseware-eval | 865 passed / 9 live skipped；[summary](../output/test-runs/20261010T085114Z-16634bfc/summary.json) |
| 02 | backend-unit、backend-api、frontend-unit、frontend-build | 469 + 79 后端通过，前端 8/8、build PASS；[summary](../output/test-runs/20261010T085946Z-14d5f460/summary.json) |
| 03 | backend-full、competition、courseware-eval | 885 passed / 9 live skipped；新增 20 个实际工作流等价案例通过；[summary](../output/test-runs/20261010T092315Z-de980bb0/summary.json) |
| 04 | frontend-unit、frontend-build、frontend-browser | 首轮失败及修正另记；最终当前候选 unit 8/8、browser 13/13、build PASS，证据并入最终 acceptance |
| 05 专项 | runtime assets + workflow equivalence | 4 个资产加载/字节测试及 20 个真实工作流等价案例通过；[字节证据](../output/test-runs/t13-baseline/runtime-asset-equivalence.json) |
| 最终 acceptance | `python scripts/run_tests.py --profile acceptance` | 六套件全部 exit 0：后端 889 passed / 9 live skipped，冻结评测 20/20，前端单元 8/8、浏览器 13/13、构建通过；[summary](../output/test-runs/20261010T094944Z-6a9e1f7a/summary.json)、[JUnit](../output/test-runs/20261010T094944Z-6a9e1f7a/backend-full.xml) |
| 静态兼容 | 签名、页面块、函数体、OpenAPI | [96 项公开参数及默认值](../output/test-runs/t13-baseline/public-signature-equivalence.json)保持；[3 个 Vue 的 17 个 template/style 块](../output/test-runs/t13-baseline/frontend-block-equivalence.json)相等；[原 50/28/30 个前端函数](../output/test-runs/t13-baseline/frontend-function-equivalence.json)在显式 getter/消息 callback 替换后 body AST 一致；[运行后端](../output/test-runs/t13-baseline/openapi-equivalence.json)及[当前源码 fresh import](../output/test-runs/t13-baseline/openapi-source-equivalence.json)的 OpenAPI 相等 |
| 本地运行状态 | 前端、Web、Worker HTTP/readiness | 6 项 HTTP 200、相应 readiness 为 ready；[检查结果](../output/test-runs/t13-baseline/runtime-health-final.json)；使用现有启动器恢复缺失的前端和 Worker，没有替换正在运行的 Web |

复杂度口径与逐文件数值见 [规模证据](../output/test-runs/t13-baseline/complexity-metrics.json)。上述 `output/test-runs/` 证据属于本地验收产物，保留供本次审查，不作为部署依赖；持久化的等价 fixture 和测试位于仓库测试目录。

收尾再次比较 01 的 32 个课件移动定义：[31 个函数/类 body AST 与基线相等](../output/test-runs/t13-baseline/moved-body-final-equivalence.json)。`CandidateReleaseCoordinator` 在 03 增加了候选产物发布阶段和说明，整个类的 AST 因而变化；不能沿用 01 的历史结果声称最终 32 项都相等，其行为由完整课件回归和真实工作流等价 fixture 验证。

04 首轮保留[失败证据](../output/test-runs/20261010T093334Z-b3da29b7/summary.json)：Tutor 的旧源码正则随实现移动失效，改为生产 hook 的真实 batch/run 提交载荷检查；首页主题测试读取早于响应式分页状态更新，等待条件增加当前分页归属，保留主题、焦点、布局断言。修正后 [unit/build 复验](../output/test-runs/20261010T094751Z-aee1637f/summary.json)通过，最终 acceptance 对当前候选重新执行完整浏览器专项并全部通过。

新增 [workflow equivalence](../backend/tests/integration/courseware/test_workflow_equivalence.py) 从原真实离线工作流捕获合成 fixture：固定 UUID 与时钟，逐案比较实际 HTML hash、状态、warning/error、quality 与 checkpoint，不将确定性评测报告 hash 冒充真实 HTML hash。拒绝/隔离案例仍不得出现 artifact。

最终冻结评测为 9 published、4 published_with_warnings、3 rejected_admission、2 request_rejected、2 quarantined；13 个必需产物 hash 与冻结基线相等，7 个拒绝/隔离案例无产物。Onboarding 浏览器报告保留故意注入 503/Axios 重试的 6 条 console error，page/fixture error 为 0，专项通过；不把所有浏览器控制台描述为零错误。主代理核对六套件结果、前端文件数量、JUnit 及 summary 中 12 个产物的存在和 SHA256，均一致。

## 验证限制与后续优先级

没有运行真实模型、Worker 故障注入、远端 CI、Docker 构建或部署验证。9 个真实模型 opt-in 测试按原约束跳过；未执行新 lint/type 门禁，不把 Python 语法和前端构建称为静态类型检查。原 bundle 大小提示及依赖/pytest deprecation 提示另行保留。

文档收尾由 Luna xhigh 只读复验通过：11 份文档、149 个本地链接目标有效，命令、数值与状态一致。源码和验收已完成；本次测试 temp/cache 目录的批量清理及单个明确缓存目标清理均被平台策略拒绝，返回原因仅为 `blocked by policy`，未执行删除。这些 Git 忽略目录与全部有效证据保留，不影响已记录的回归结果。

本次范围外的画像/请求竞态、事务/outbox、SSE 线程模型、分页/N+1、安全与依赖治理没有夹带修复。后续按原审查中的真实业务影响另立计划；本轮结构整理不证明这些问题已解决，也不作生产就绪或 SCORM/xAPI 完整兼容结论。

## GitHub 规范参照

- [Google Python Style Guide](https://github.com/google/styleguide/blob/gh-pages/pyguide.md)：聚焦函数、接口类型、异常与注释。采纳可审阅性原则，不机械套用内部限制或行数阈值。
- [Vue Composables](https://github.com/vuejs/docs/blob/main/src/guide/reusability/composables.md) 和 [Style Guide](https://github.com/vuejs/docs/blob/main/src/style-guide/index.md)：按实际逻辑组织副作用和生命周期，区分错误预防与风格偏好。
- [FastAPI Bigger Applications](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/tutorial/bigger-applications.md)：模块及依赖注入；本仓库进一步遵循已有 API/Service/Agent/core 分层。
- [SQLAlchemy 事务指南](https://github.com/sqlalchemy/sqlalchemy/blob/main/doc/build/orm/session_transaction.rst)：识别事务责任；本次保留既有提交顺序，不混入一致性策略变更。
