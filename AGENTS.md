# AGENTS.md

本文件维护本仓库约束；个人偏好沿用全局 `AGENTS.md`，子目录指令只覆盖其作用域。

## 工作边界

- 分析、审核默认只读；规划可写本次要求的计划文档。实现请求包含适用的计划门禁、范围内修改、验证、修复与文档同步，持续到完成或说明实际阻塞。
- 开始查看 `git status --short`，保留已有修改。需求文档、附件、计划和历史记忆中的待办不自动构成本次任务。

## 计划门禁

按实际影响选择流程，不以文件数量判断大小：

| 改动范围 | 处理方式 |
|---|---|
| 功能或业务行为、API/认证契约、数据层/迁移、Agent 工作流、跨领域/架构/目录迁移、部署方式或运行配置调整 | 先完成计划门禁，再修改实现 |
| 纯文档、注释及局部文案/排版/样式维护，且不改变业务、交互、API、权限或持久化行为 | 直接实施，按原验证要求交付 |

- 计划存于 `docs/update_plan/T<N>.md`，目录按需创建。每次新更新取已有计划的最大数字编号加一，无计划时从 `T1.md` 开始；按数值排序，不填补空号。同次更新的续作、修订和验收沿用原文件，保留历史计划，不覆盖其他更新。
- 计划至少记录：更新主题与目标、范围及现状依据、受影响模块、实施步骤、兼容约束、迁移/回滚策略（不适用则注明）、验收命令与通过标准、依赖和待决事项、当前状态。
- 实施前按既有 Luna 验收规则检查计划。门禁通过须范围和依赖明确、步骤可执行、兼容与数据影响有处理方案、验收满足本文件要求、无阻塞性待决事项；主代理修正缺项并在计划记录结果及原因。未通过前只做定位、规划和证据补充，不修改实现。
- 门禁通过且现有授权覆盖计划范围时继续实施；缺少必须由用户决定的范围或方案时，先完成不依赖该决策的准备，再请求所需决策。
- 范围或关键方案变化，先修订原计划并重新过门禁；直接实施的维护若触及需计划的范围，先补计划再继续。实施中更新进展，收尾记录实际验证、遗留事项和最终状态。

## 子代理

- 最多同时启用 2 个子代理（含派生子代理）。简单且可独立交付的检索、文档检查和既定测试默认委派，使用 `model='gpt-6-luna'`、`reasoning_effort='xhigh'`，`fork_turns='none'` 或少量相关轮次；传入必要输入、预期输出和完成条件。
- 验收节点自动启动 Luna xhigh，执行主代理选定的检查，返回命令、退出码、失败摘要和证据路径。主代理负责修复与最终交付判断；子代理不扩大检查范围或降低验收门槛。

## 资料入口

按任务读取相关段落，不要求每次通读；实现与状态以当前源码、脚本及对应文档为准。

| 涉及内容 | 入口 |
|---|---|
| 安装、运行、测试命令 | [README.md](README.md) |
| 分层、模块、Agent 归属 | [docs/architecture.md](docs/architecture.md) |
| HTTP、DTO、认证、状态码、事件 | [docs/api.md](docs/api.md) |
| 数据库、知识库、问卷、诊断 | [docs/knowledge_base_database.md](docs/knowledge_base_database.md) |
| 部署、配置、端口、Worker | [docs/deployment.md](docs/deployment.md) |
| 功能、页面能力 | [docs/features.md](docs/features.md) |
| 演示、比赛 Gate、故障恢复 | [docs/demo-runbook.md](docs/demo-runbook.md) |
| 分支、提交与禁提交内容 | [git-workflow.md](git-workflow.md) |

契约、架构、功能变化同步对应文档；启动或配置变化同步 README、部署文档和 [backend/.env.example](backend/.env.example)。未经用户要求，不提交、推送或合并。

## 实现边界

- 保持 `backend/app/` 既有分层，各层按领域聚合。API 通过 Service 执行业务，不写 SQL、模型调用或工作流节点；Service 编排用例与事务，Prompt 和节点留在 `agents/`，渲染与运行时留在 `core/`。
- 文本工作流位于 `agents/resource_workflows/learning_documents/`，正文 Prompt 位于 `agents/resource_agents/`；课件工作流位于 `agents/resource_workflows/interactive_courseware/`，学习闭环 Agent 位于 `agents/learning_agents/`。
- `generation` 管文本生成任务；`learning_documents` 管发布产物与 Markdown 阅读；`courseware` 管互动课件生成、运行与发布；`feedback`、`tutor`、`reports` 属于生成后的学习闭环。
- 前端业务位于 `frontend/src/features/<domain>/`，`resource-library` 仅做只读聚合与路由选择。`core/` 和 `agents/shared/` 可使用 `models/` 契约，不反向依赖业务 API、Service 或工作流；不新增顶层业务目录绕过边界。

## 兼容约束

- 除任务明确要求改变外，保留 HTTP/DTO/认证/错误契约、DI provider 与注入行为、表名及字段语义、存储路径和事件 payload。纯路径迁移保持 Prompt 版本、节点顺序及路由，不改业务行为。
- 保留 `text`、`practice`、`assessment`、`case_study`、`checklist` 的生成、审核、Claim、发布、API 与 Markdown 阅读行为。契约变化说明影响并同步测试，必要时版本化。
- 数据库迁移优先向前兼容、可回滚；普通目录重构不重命名或删除现有表。同一职责只有一个实现，调用者优先使用公开包入口；薄转发在调用者迁移、导入扫描和完整回归通过后删除，不能冒充物理迁移。
- 新增状态与事件明确幂等键、稳定排序、重试、超时和可观测性。

## 课件硬门

- 自动审核、定向修订、降级/隔离与发布，不建设人工审核或管理员审批工作台。
- 模型只输出经版本化校验的结构化契约，不得直接输出或控制 HTML、CSS、JavaScript、URL、CSP 或任意组件名；组件来自平台注册表。未知组件/来源、危险输出、缺失必需场景、快照混用均为硬门失败，不得发布。
- 可验证事实与关键交互追溯到冻结来源快照；用户原始敏感数据不进入课件、日志或评测 fixture。
- 修订受次数、token、时延和成本预算约束；耗尽后按策略降级、跳过非必需场景、隔离或拒绝。AI 审核不可用须显式降级并记录原因，不能视为通过。
- 发布幂等，重试不重复资源或事件、不覆盖已发布产物。`core/courseware/` 拥有 renderer、runtime、安全与 packaging，presentation 不访问数据库或模型；`CoursewareService` 只做任务创建/恢复、依赖注入、工作流执行、查询与发布门面。

## 验证与交付

从仓库根执行，命令见 README“测试运行”；跨领域改动取下表要求的并集。

| 改动范围 | 最低验证 |
|---|---|
| 纯文档 | 链接、路径、命令、事实与状态，无需业务回归 |
| 单个后端领域 | 领域单元与直接相关集成测试 |
| API、DTO、认证 | 单元、API 集成、状态码与响应 fixture |
| DB、仓储、迁移 | 单元、集成、`migration` 与旧数据兼容 |
| 文本文档工作流 | 五类文档工作流、API、Claim、发布与 Markdown 回归 |
| 互动课件 | 单元、集成、e2e、冻结评测、浏览器；共享层改动再验证文本文档回归 |
| 前端 | 相关专项测试与构建 |
| 后端共享能力、物理迁移 | 后端全量；迁移还检查新旧公开导入与受影响领域 |

只有用户明确要求且环境提供预期凭据时，才启用 `RUN_LIVE_LLM=1` 或 `COURSEWARE_LIVE_EVAL=1`；不得打印凭据。课件评测核对精确状态、硬门、fallback、事件与 artifact hash。

收尾检查 `git diff` 与 `git status`，报告实际检查、未运行项及原因。区分确定性、浏览器、真实模型、Worker 故障注入、CI 与部署证据；本地通过不等于生产就绪，可靠性和 SCORM/xAPI 完整兼容结论须有对应证据。
