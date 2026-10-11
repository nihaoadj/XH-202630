# 工程质量优化实施记录：T14

日期：2026-10-10。依据：[复审报告](engineering-quality-review-2026-10-10.md)；本地详细计划：[T14](update_plan/T14.md)（该目录按仓库规则不随 Git 分发）。基于 T13 当前工作树实施，保留此前修改。

## 结果

报告的 10 项问题已按范围实施，完整验收 12/12 套件通过。兼容检查与回归支持正常 API、DTO、DI、文本文档生成/Claim/发布及课件硬门保持；新增故障恢复和迟到响应保护。production 的不安全认证配置改为启动拒绝，这是本次明确的配置收紧。

| 报告项 | 本次调整 |
|---|---|
| 1 生产配置 | 校验 JWT 密钥和 Secure Cookie；凭据 CORS 使用 HTTPS 白名单，开发本机动态端口保持。 |
| 2 镜像上下文 | `.dockerignore` 排除本地配置、数据库、日志和生成物；Docker 创建空运行目录，使用哈希锁安装依赖。 |
| 3 请求竞态 | 反馈/课件请求绑定 learner、batch/run 与版本，覆盖成功、失败、卸载、SSE/poll 和通知；已发送 POST 的 payload 保持。 |
| 4 续生成事务 | 标准 SQL 仓储共享本次调用的外层事务；Memory 仓储协调锁与快照回滚。关联失败不遗留 queued 任务，调度失败保留 failed 任务；成功重复调用仍创建新 Run。 |
| 5 审计一致性 | 相同业务请求重试补缺失事件，稳定 ID 去重并保持顺序；保留既有时间、payload 和旧 Claim 随机 ID 事件。 |
| 6 SSE 查询 | 同步查询移入线程池，Session 在线程内使用；事件、heartbeat、cursor 和错误响应保持。 |
| 7 共享边界 | 模型内容契约物理归入 `models/courseware/content.py`；旧导出与新导入保持对象身份。shared retrieval 直接引用 WorkflowState。 |
| 8 职责与复杂度 | 提取雷达纯投影和候选页面修复/渲染校验。报告主方法 365 → 331 行，课件主流程 413 → 366 行；总状态机、异常边界和硬门顺序保持。 |
| 9 静态门禁 | Ruff、全 src ESLint、共享请求 guard 的严格 JSDoc 类型检查进入统一验收和 CI；修正两个未定义名称，不做整仓格式重写。 |
| 10 依赖复现 | 运行与开发工具分别锁定版本/SHA256，增加声明/锁/安装版本检查；安装入口使用锁文件和 npm ci，前端运行依赖未升级。 |

旧 P0-09 runtime 的源码检查已按现行路径更新；只核对连线，不能替代浏览器验收。README、部署、架构、API 与测试说明已同步。

## 验证

- 独立 Python 3.11 环境实际安装哈希锁的 143 个运行/工具依赖，websockets=13.1；声明/锁/环境及 pip check 通过。
- [兼容检查](../output/test-runs/t14-targeted/compatibility.json)：72 个 OpenAPI 路径和完整 schema 相同，34 个内容导出保持身份，81 个 npm 运行依赖版本/integrity 不变，共享层未发现反向业务导入。
- [冻结比对](../output/test-runs/t14-targeted/frozen-equivalence.json)：20 个用例的稳定字段相同；固定 UUID/时钟的工作流产物 hash 检查全部通过。普通运行的 run/release ID 与时间不同，完整 JSON 和 HTML hash 不作直接相等保证。
- [最终验收](../output/test-runs/t14-acceptance/summary.json)：12/12 套件 PASS、退出码均为 0；后端 928 passed / 9 live skipped，迁移 28 passed，冻结评测 20/20，前端单元 9/9 文件、浏览器 13/13 文件，构建通过。静态检查、局部类型检查和依赖一致性检查均通过。9 项跳过均为未授权启用的真实模型测试。
- 专项及全量回归覆盖配置/API/事件/SSE、SQL/Memory continuation 回滚、迟到响应、SQL 重启补事件和旧 Claim 事件。验收命令：`output/test-runs/t14-clean-env/Scripts/python.exe -X utf8 scripts/run_tests.py --profile acceptance --suite backend-migration --output output/test-runs/t14-acceptance`（仓库根执行）。
- [文档复核](../output/test-runs/t14-targeted/document-review.json)通过：链接、命令、状态及验证范围与当前实现相符；历史复审报告明确保留为 T14 实施前的记录。

## 保留边界

本轮不提供提交后进程中断到 BackgroundTasks 的精确重放，也不新增自动 outbox；事件恢复依赖相同业务请求重试。Memory 中绕过仓储锁直接改已返回对象，仍不受事务协调。

旧 `useCoursewareJob` 的等待语义保持；构建仍有大于 500 kB 的 chunk 提示，是否分包需另有加载性能依据。

当前服务仍使用原 `.venv` 与 websockets=16.1.1；其二进制被运行进程占用，本轮恢复原环境后改用独立锁环境验收，未停止/重启服务。正常停机后需按锁文件安装；不能称旧环境已一致。

Docker daemon 不可用，[上下文过滤模拟](../output/test-runs/t14-targeted/t14-final-checks.json) 符合预期，未构建镜像；远端 CI、Linux 安装、真实模型、实际部署及生产压测不属于已验证证据。

[npm 审计](../output/test-runs/t14-targeted/npm-audit-current.json) 仍有 9 个依赖包告警（6 high / 3 moderate），与优化前一致，exit 1。涉及 Vue、axios、ECharts、Vite 等，不能把功能回归通过当成安全告警消除；应单独评估补丁/跨主版本升级及使用场景，不直接执行 `audit fix --force`。

本轮无用的依赖恢复副本位于 `output/test-runs/t14-environment-repair/`；工具策略以 `blocked by policy` 拒绝删除，已保留。源码、测试证据和运行环境不受该清理失败影响。
