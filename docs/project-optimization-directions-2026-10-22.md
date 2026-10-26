# 项目优化未完成事项与建议

更新日期：2026-10-24（第一、二项实施状态）。依据：2026-10-23 独立审阅、当前工作树源码、T24 本地复验与原运行环境修复记录。文件名沿用首次审查日期。

第一项已按 [T24](update_plan/T24.md) 完成修复与本地验收；原问题及验收要求保留供核对。第二项已恢复锁定版本、正在回归验收，第三项交付证据仍待补齐；本地结果不替代远端或部署证据。后续行为或运行配置修改按 [AGENTS.md](../AGENTS.md) 及本次用户明确要求执行。

## 一、生成命令的迟到响应缺少上下文隔离（P2，已修复并本地验收）

### 修复前的问题与证据

修复前，在任务 A 发起追加资源，请求尚未返回时切换到同一画像的任务 B，A 的响应到达后仍会切换选中任务、写入本地选择、清空 B 的资源并启动 A 新任务的订阅。

[GenerateView.vue](../frontend/src/features/generation/GenerateView.vue) 的 `confirmAppendResources()` 在 `await executeGenerationPlan(...)` 后没有检查原 learner/run、命令版本或挂载状态，直接应用结果。`retryGeneration()`、`regeneratePendingResources()`、`retryResource()` 存在相同的无条件回写结构；成功、失败通知和 `finally` 中的按钮状态也需一起审查。

`handleTaskChange()` 的版本保护只约束自身流程，`loadJobs()` 的保护只核对列表请求版本、learner 和挂载状态，不能阻止此前的命令回写。同画像切任务尤其不会触发 learner 不匹配。命令期间任务选择器仍可切换。

已抽取真实页面命令函数和 `loadJobs()`，结合实际 [generationCommands.js](../frontend/src/features/generation/generationCommands.js) 与合成延迟 API 响应复现：切至 `run-B` 后，晚到响应使选中项变为 `run-A-child`，当前资源清空并订阅该旧命令的新任务。证据见[上下文竞态探针](../output/test-runs/optimization-audit-probes-20261023/command-context-race.json)。这是函数级复现，尚未做此场景的浏览器复现；未证明后端跨画像写入或数据损坏。该问题是既存遗漏，不能归因于本次职责拆分。

### T24 实施与证据

[useGenerationCommands.js](../frontend/src/features/generation/useGenerationCommands.js) 已集中保护四个命令，复用请求 guard 并同步失效 learner/run 切换和卸载的旧命令；三类 busy 通道明确所有者，自身合法选中新 Run 后继续执行，其他旧命令不能回写。真实页面的 `loadJobs` 接受可选命令谓词，过期列表不写入 UI，false 不触发订阅或成功通知。请求计划、Claim 拆分/合并及已受理任务保持。

原实现真实浏览器失败反例已补充：同画像切至 run-other 后，迟到响应仍将持久选择改为 continue-1。见 [红灯 summary](../output/test-runs/t24-red-r2-20261024/generation-ui/summary.json) 和 [截图](../output/test-runs/t24-red-r2-20261024/generation-ui/command-late-post-switch.png)；该证据补齐上面的历史函数探针，仍不证明真实后端跨画像写入或数据损坏。

生产协调器/Axios 命令矩阵、原请求竞态专项和 [工程六套件](../output/test-runs/t24-final-20261024/summary.json) 全部通过，十二个前端单元文件均执行。新构建的 [生成页浏览器完整报告](../output/test-runs/t24-browser-r5-20261024/generation-ui/summary.json) PASS：七个命令竞态场景、13 个状态场景、84 项布局、75 项交互检查完成；0 未登记 API、外网请求和页面错误。列表并发用例同时 hold 两个响应正文，旧列表结束仍保留新命令和列表 loading，新任务随后正常完成选择和订阅。[画像请求浏览器](../output/test-runs/t24-browser-20261024/ui-repair/profile-requests/summary.json) 11 项检查通过，0 写请求。上述均为本地确定性/浏览器 fixture 证据，未启用真实模型、远端 CI 或部署；无提交/推送/合并。

### 原优化要求（保留验收依据）

1. **为命令建立可失效的上下文。** 发起时捕获 learner、来源 run、命令身份和页面上下文版本；用户切换画像、任务或卸载时使旧上下文失效。只比较 learner/run 字符串不足以覆盖 A→B→A，需要版本或等效 token。
2. **约束每个异步回调的副作用。** 请求返回后，先检查上下文，再更新选中项、资源、localStorage、弹窗和订阅。等待 `loadJobs()` 或其他异步步骤后再次检查，并处理其 `false` 返回值。命令自身合法选中新 run 的行为应明确更新预期上下文，避免把自己的状态切换误判为用户切换。
3. **让通知和按钮状态遵循同一归属。** 过期请求的成功或失败不向新上下文弹提示；旧命令的 `finally` 不得清除新命令的 loading/retrying 状态。不同操作需要独立并发时保持独立命令身份；共用按钮状态时明确当前所有者。
4. **保留已经受理的后端任务。** 忽略过期页面回写不等于撤销任务。用户返回原画像或批次后，通过任务列表发现其结果；不要因页面切换自动重发生成请求，也不要把前端取消等待当成服务端取消。
5. **保持现有职责边界。** `generationCommands.js` 继续负责请求计划和发送，页面或同领域的窄命令协调模块拥有上下文及 UI 副作用。复用现有 [requestContext.js](../frontend/src/utils/requestContext.js) 中适用的机制，不合并资源、节点、列表和订阅的独立版本，不传入整个页面或容器。

### 必须补充的验收

| 场景 | 通过标准 |
|---|---|
| A 发起命令，切至 B，A 成功返回 | 保持 B 的选中项、资源、持久选择和订阅，不显示 A 的成功通知 |
| 切画像或 A→B→A 后收到旧响应 | 旧命令失效，不覆盖当前同名上下文或新命令 |
| 页面卸载后收到成功或失败 | 不更新持久选择、不重启订阅、不弹页面通知 |
| 旧命令结束时新命令仍在执行 | 旧 `finally` 不清除新命令状态 |
| POST 返回后、列表刷新期间再次切换 | 不在刷新结束后应用旧选择、订阅或通知；刷新失败不当作成功 |
| 上下文不变的四种命令 | 请求形状、Claim 拆分/合并、响应顺序和正常跳转保持；后端任务不重复创建 |

测试应经过真实页面命令或其生产协调模块，覆盖成功、失败、收尾三个路径；仅测试纯请求计划或资源加载 hook 无法证明命令回写安全。先保留失败反例，再修复并验证。浏览器至少补“延迟 continuation 响应期间切任务”的真实组件场景。

从仓库根运行相关验证：

```powershell
node frontend/tests/generationPreparation.test.mjs
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:generation-browser
npm --prefix frontend run test:profile-request-browser
```

新增命令竞态用例纳入统一套件，浏览器使用新构建，缺少浏览器环境时不得把跳过记为通过。现有测试入口见 [README](../README.md#测试运行) 和 [测试说明](testing/README.md)。

## 二、本地运行环境与依赖锁不一致（依赖已对齐，回归验收中）

2026-10-23 只读查询确认原 `.venv` 安装 `websockets=16.1.1`，而 [requirements.lock.txt](../backend/requirements.lock.txt) 锁定 `13.1`。本地复验使用独立锁定 Python 3.11 环境，不能证明原运行环境已与锁一致。T24 未变更或重建该环境；暂未取得该版本差异导致实际业务故障的证据。

2026-10-24 已对原 `.venv/python.exe` 直接修复：确认没有项目 Python 进程使用该环境后，备份原包，按现有两个哈希锁安装。dry-run 与安装报告都仅变更 `websockets 16.1.1 → 13.1`，其余 144 个已安装包未变，wheel SHA256 已核对存在于原锁文件；没有调整依赖声明、锁文件、启动入口或业务配置。证据见 [修复后版本与哈希](../output/test-runs/environment-repair-20261024/after-install.json)、[安装报告](../output/test-runs/environment-repair-20261024/install-result.json)。完整回归正在使用修复后的原解释器执行。

以后若再次出现环境漂移，按 [README](../README.md) 和 [部署说明](deployment.md) 在维护窗口用哈希锁恢复实际运行环境；不要只修改锁文件来迁就已安装版本。本次使用同一解释器验收：

```powershell
.\.venv\python.exe scripts/check_dependencies.py
.\.venv\python.exe -m pip check
.\.venv\python.exe scripts/run_tests.py --profile regression
```

通过标准：声明、锁和安装版本一致，依赖兼容检查及规定回归通过；启动器仍选择原 `.venv/python.exe`，不将之前的独立验收环境替换为日常入口。Web 和两个 Worker 的真实部署、模型就绪及长期运行结果继续按第三项分别取证，不由依赖对齐或前置检查替代。

## 三、交付前尚缺的验证证据（待验证）

以下为验证边界，不据此断言现有实现失败，也不自动增加新的开发范围：

| 未验证项 | 后续建议与通过标准 |
|---|---|
| 远端 CI 与 Python 3.12 | 在用户授权的提交/推送或 CI 流程中执行现有版本矩阵，核对哈希锁安装、必需套件和 required gates；保留实际运行链接及产物。本地 Python 3.11 结果不替代这一证据。 |
| Docker 或目标部署、业务库升级及 Worker 运行 | 在实际选定的交付方式下，先用隔离旧库副本演练迁移和回滚，再按部署流程验证 Web、课件 Worker、文本 Worker 的 readiness、提交后执行、重启收敛及旧执行者拒写；记录配置和日志，不能只检查启动命令存在。 |
| 真实模型质量与线上容量 | 仅在明确需要相应交付结论时安排。真实模型测试需用户明确授权及预期凭据；容量验证需明确数据规模和并发预算，涵盖冷构建、多学习者写入与多订阅。冻结回放和既有暖缓存合成基准不替代这些结果。 |

审阅证据入口：[本地复验汇总](../output/test-runs/optimization-audit-20261023-sol/summary.md)、[历史证据核对](../output/test-runs/optimization-audit-20261023-sol-history.json)。这些 `output/` 文件是本地忽略产物，远端仓库不一定包含；交付验收需要另行保留可访问证据。
