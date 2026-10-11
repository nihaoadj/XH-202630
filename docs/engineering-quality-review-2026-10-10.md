# 工程质量复审：T13 优化后

日期：2026-10-10。对象：`577fc6c` 基线及当前未提交工作树；技术栈：FastAPI / Pydantic / SQLAlchemy / LangGraph、Vue 3 / Pinia / Vite。本轮只审查和生成报告，保留已有修改。

> 本报告记录 T14 实施前的 T13 候选状态；当前整改与验收结果见 [T14 实施记录](engineering-quality-optimization.md)，不将下表继续视为整改后的现状。

## 总体评价

**T13 的结构和职责整理有效，但项目仍有正确性、故障一致性与部署配置方面的缺口，尚不能仅凭回归通过认定达到成熟生产工程标准。** 当前领域划分基本清晰，API 已通过公开 Service 用例编排；课件实现、纯审核、共享契约及评测脚本的归属更合理。6 个前端 hook 均被实际页面调用，职责提取已进入生产路径。

复杂度有所下降：FeedbackService 文件 2455 → 1879 行、ReportService 1624 → 997 行，课件 `_run_workflow` 654 → 413 行。以上物理行数仅反映规模；提取改善了定位和阅读，但没有自动消除原有分支与副作用。课件工作区展开压缩代码后行数增加，也不应因此判定质量退步。详细过程见 [T13 实施记录](engineering-quality-update.md)。

| 审查方面 | 当前评价 |
|---|---|
| 项目结构 | 领域目录、前端 feature 组织基本合理；共享层仍有两处依赖具体工作流的残留。 |
| 代码规范 | 关键类型、注释和控制流表达有所改善；缺少持续执行的 lint / 类型检查门禁。引号、分号等个人偏好不列为缺陷。 |
| 模块解耦 | Service 用例及页面 hook 提取有效；反馈与课件请求仍未完整绑定上下文，状态回写有竞态。 |
| 文件复杂度 | 热点规模下降；反馈、报告、课件总编排仍集中较多职责，需要有边界的后续整理。 |
| 架构设计 | 分层与 DI、契约、课件硬门有明确设计；部分跨仓储提交与事件缺少可恢复的一致性策略。 |
| 工程化质量 | 已有前后端 CI、冻结评测、浏览器测试及前端锁文件；生产配置校验、镜像上下文隔离和 Python 环境复现仍不足。 |

## 具体问题与优化方案

P1：可能影响结果正确性、任务恢复或部署安全，应优先处理；P2：影响并发能力、维护成本或工程可复现性。等级依据影响与触发条件，不依据文件数量或个人风格。

| 等级 / 位置 | 问题、原因与影响 | 最小优化方案 |
|---|---|---|
| **P1 · 1 生产配置**：[config.py:216、477](../backend/app/config.py)、[main.py:153](../backend/app/main.py) | `production` 校验未拒绝开发用 JWT 默认密钥及非 Secure Cookie；合成配置已复现可通过。CORS 同时允许 `*` 和 credentials。若部署未覆盖这些配置，会留下认证和跨域配置风险；未证明线上正在使用默认值。 | 生产模式拒绝默认/弱密钥；HTTPS 部署启用 Secure Cookie；凭据请求使用明确的 CORS 白名单。 |
| **P1 · 2 镜像上下文**：[Dockerfile:10](../Dockerfile) | 全量 `COPY backend`，仓库根没有 `.dockerignore`。从含本地 `.env`、数据库或日志的开发目录构建时，这些文件可能进入镜像；`.gitignore` 不能隔离 Docker 上下文。 | 增加 `.dockerignore`；区分必要源码/fixture 与本地数据，运行数据按需挂载或注入。 |
| **P1 · 3 请求竞态**：[useFeedbackEvaluation.js:47](../frontend/src/features/feedback/useFeedbackEvaluation.js)、[useCoursewareTracking.js:31](../frontend/src/features/courseware/useCoursewareTracking.js) | 反馈资源、测评/后续请求及课件列表/详情返回时，未统一核对发起时的 learner、batch/run。快速切换后旧响应可能覆盖新上下文；实际测评 hook 的迟到响应已通过零网络探针复现。生成页已有版本校验，不属于同一缺口。 | 捕获上下文和请求版本，回写状态、路由、通知前校验；必要时取消请求。补迟到成功/失败及切换场景测试。 |
| **P1 · 4 续生成恢复**：[continuation.py:107](../backend/app/services/generation/continuation.py)、[documents.py:79](../backend/app/api/learning_documents/documents.py) | 新任务先独立提交，随后关联 follow-up、标记 superseded；这些步骤失败时，API 尚未注册后台执行，可能留下 queued 任务。再次请求可能新建另一个 run。此结论来自提交与调度顺序，未进行实际故障注入。 | 使用用例级事务或可恢复的持久化意图，保留幂等重试键；验证提交后异常与恢复，不只测试成功路径。 |
| **P1 · 5 事件一致性**：[feedback.py:153、274、1160](../backend/app/services/feedback/feedback.py)、[publication.py:34、46](../backend/app/services/learning_documents/publication.py) | 反馈/Claim 事实先提交，再写审计事件；事件失败可能只记录日志或使请求报错。相同请求重试又提前返回，缺失事件无法由该路径补写，影响追踪和恢复。 | 为这两类用例建立可重放事件意图或明确补偿；业务重试同时检查事件完整性，并验证幂等与故障恢复。 |
| **P2 · 6 SSE 同步调用**：[report.py:77](../backend/app/api/reports/report.py)、[courseware.py:89](../backend/app/api/courseware/courseware.py) | async generator 内同步查仓储、构建报告；慢查询或多订阅可能阻塞事件循环。源码机制明确，实际延迟和吞吐未压测。 | 在线程池中执行同步工作并管理 Session 生命周期；报告优先按 revision 轻量轮询，验证多订阅场景。 |
| **P2 · 7 共享层边界**：[live_model.py:26](../backend/app/core/courseware/live_model.py)、[retrieval.py:7](../backend/app/agents/shared/retrieval.py) | core 引用课件工作流契约，shared retrieval 引用文本文档状态；共享能力与具体工作流绑定。静态扫描发现这两处残留，未证明已有循环依赖。 | 真正共享的 DTO 下沉到 models；仅单工作流使用的能力归回该领域。按真实使用范围选择，不新增通用框架。 |
| **P2 · 8 职责集中**：[feedback.py](../backend/app/services/feedback/feedback.py)、[reports.py:168](../backend/app/services/reports/reports.py)、[workflow.py:275](../backend/app/agents/resource_workflows/interactive_courseware/workflow.py) | `_build_report_once` 365 行，集中多个领域查询和投影；`_run_workflow` 413 行，集中状态转换、失败分支与持久化。反馈主流程也较长，理解变更影响和验证失败路径成本高。 | 优先提取稳定的纯计算和阶段边界，保留总状态机、事务与异常边界；不按固定行数拆文件。 |
| **P2 · 9 静态门禁**：[package.json](../frontend/package.json)、[courseware-quality.yml](../.github/workflows/courseware-quality.yml) | CI 已执行测试、评测和构建，但未找到 lint / 类型检查配置或对应步骤。Vite 已解析构建图内导入；测试未触及路径中的未定义名称、未使用导入及接口误用仍缺少持续静态诊断。 | 渐进加入 Ruff、ESLint 的错误预防规则；关键 DTO / hook 接口补类型检查或 JSDoc 校验，避免一次性全量格式重写。 |
| **P2 · 10 依赖复现**：[requirements.txt:5](../backend/requirements.txt) | Python 直接依赖多已固定，但未发现传递依赖锁定。当前声明 `websockets>=10.4,<14`，安装版本却为 `16.1.1`；`pip check` 通过也不验证与项目声明一致，可能掩盖环境漂移。 | 锁定可复现的依赖集合，并校验安装环境与声明；用干净环境验收，不将本地可运行视为依赖一致。 |

低优先级保留项：旧 `useCoursewareJob` 有不同等待语义，暂不强行合并；[旧验收脚本:135](../scripts/run_p0_09_acceptance.py) 的 `--runtime` 仍读取已迁移页面路径，应明确废弃或更新，当前统一 acceptance 不依赖它。前端已有 bundle 大小提示，是否分包应结合实际加载表现决定。

## 整改顺序与验证依据

1. **先处理 P1**：部署前完成配置与镜像隔离；并行修复请求竞态、续生成恢复与事件一致性。后三项涉及行为和事务，应另立实施计划及故障场景验收。
2. **再补工程门禁与边界**：依赖复现、静态检查、两处共享依赖；SSE 改动以并发验证确认收益。
3. **最后按维护需求整理复杂度**：围绕稳定职责逐步提取，清理兼容入口；不为行数下降扩大改动。

本轮依据：检查目录、`backend/app` 的 343 个 Python 文件及 `frontend/src` 的 65 个 JS/Vue 文件，核对关键导入和热点 AST 范围；零网络探针复现默认生产认证配置可被接受、测评迟到响应错误回写；`pip check` 通过但声明/安装版本比对发现上述漂移。已核对 T13 候选清单 **86 个文件 hash 全部一致**。

本轮 [诊断结果](../output/test-runs/engineering-review-20261010/results.json) 及 [诊断脚本](../output/test-runs/engineering-review-20261010/verify_review.py) 保留为 T13 状态的审查证据。脚本以缺陷可复现及当时的候选 hash 为前提，T14 修复后不能作为现行通过门禁；当前回归与兼容检查见 T14 实施记录。脚本仅使用合成配置和延迟 API stub，不启动服务或真实模型。

既有 [T13 acceptance 证据](../output/test-runs/20261010T094944Z-6a9e1f7a/summary.json) 为六套件通过：后端 889 passed / 9 live skipped，冻结课件评测 20/20，前端单元 8/8 文件、浏览器 13/13 文件、构建通过。**本轮未重跑全量回归，也未运行真实模型、故障注入、并发压测、远端 CI 或 Docker 部署**；既有回归不覆盖本报告全部风险，静态判断不等于已发生线上故障。

## 规范参照

结合项目既有分层与以下成熟实践评估，不机械套用文件行数或所有风格规则：[Google Python Style Guide](https://github.com/google/styleguide/blob/gh-pages/pyguide.md)、[Vue Composables](https://github.com/vuejs/docs/blob/main/src/guide/reusability/composables.md)、[FastAPI 模块组织](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/tutorial/bigger-applications.md)及[异步执行说明](https://fastapi.tiangolo.com/async/)、[SQLAlchemy 事务](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)、[Starlette CORS/Session 配置](https://github.com/encode/starlette/blob/master/docs/middleware.md)、[Docker 构建上下文](https://docs.docker.com/build/concepts/context/)。
