# T41 本次更新验收记录（2026-11-06）

**结论：本次相关范围验收 PASS，T41 已收尾。**

本轮以当前源码的计量关闭/开启受控对照作为行为验收依据。历史实施前完整工作树无法恢复，旧基线没有重录；历史全链路追溯仍为 NOT_PROVEN。这与本轮受控对照是两种证据，不互相冒充。

## 验收方法与范围

新增 [受控对照测试](../../backend/tests/integration/workflow/test_llm_accounting_equivalence.py)，注册 `llm-accounting-equivalence`。固定合成输入、业务时钟与随机 ID，保留完整请求及业务结果进行比较；打开计量必须有观察，关闭计量必须无观察。使用真实 Gateway 与进程内脚本 transport，不访问真实模型。对照器的两个负例故意改变请求参数或结果，要求检测失败。

| 覆盖项 | 用例数 | 核对内容 |
|---|---:|---|
| 六类生成器 × 正常/抛错计量 publisher | 12 | 完整产物、请求、options/context；计量故障不改变生成结果 |
| assessment/checklist 本地校验重调与最终失败 | 4 | 两次实际请求，完整结果或异常类型/code/cause |
| 诊断、规划、普通审核、legacy Claim 抽取及判定 | 4 | 请求、完整业务投影与调用配置 |
| 课件三类来源 × 正常/修订 | 6 | 内容审核/质量审核/修订 schema，发布状态、job、事件、请求 |
| 并发资源 | 1 | 四个真实请求，按资源对齐比较结果和请求 |
| 文本生产图到发布 | 1 | 隔离非 LLM 检索边界，其余生产节点执行；四次调用及发布产物 |
| observer 重试及 observer 抛错 | 2 | before/error/before/after 或 before/after，原异常对象保持 |
| 课件规划失败后确定性编排与审核失败阻止发布 | 1 | AI_PLAN_FALLBACK，release_blocked，无 artifact，完整事件/请求相等 |
| 比较器负例 | 2 | 请求变化、结果变化均被拒绝 |

课件内容审核保留既有 offline TokenEstimatorProfile 硬门，通过合法离线适配器把调用转交真实 Gateway；这不构成生产 TokenEstimatorProfile 配置验收。schema 驱动脚本不使用填充响应队列，未知 schema 会记录并导致失败。失败路径使用主动抛错 transport，不依靠脚本耗尽触发降级。

上述矩阵验证指定分支的计量开关等价，不声称穷尽所有工作流组合。Claim 新预算/CAS 全流程、全部课件批次/复查次数、Service 全部持久化副作用没有逐项新增配对证明。既有计量专项提供查询/独立存储/迁移/恢复/进程故障等相关验证，不能外推为所有业务预算分支的配对证明。

## 命令与证据

仓库根执行，设置 `PYTHONPATH` 为 `backend` 绝对路径，`RUN_LIVE_LLM=0`、`COURSEWARE_LIVE_EVAL=0`。脚本自动隔离 pytest temp/cache 并输出 JUnit。

```powershell
./.venv/python.exe scripts/run_tests.py --suite llm-accounting-equivalence --suite llm-accounting-focused --suite architecture --suite frontend-contracts --suite backend-lint --output output/test-runs/t41-closeout-related
./.venv/python.exe scripts/run_tests.py --suite llm-accounting-equivalence --output output/test-runs/t41-closeout-final
./.venv/python.exe -m ruff check backend/tests/integration/workflow/test_llm_accounting_equivalence.py
```

首轮 [related summary](../../output/test-runs/t41-closeout-related/summary.json)：原计量专项 93 passed / 0 skipped；architecture、frontend-contracts、backend-lint exit 0；当时受控对照 30 passed。之后仅补测试，未修改生产实现，因此只复跑最终对照与新增测试静态检查。

补充测试调试中发现预期 schema 名猜测错误、实际终态为 release_blocked，以及预算模块直接导入的 uuid4 未冻结；修正测试前置条件及精确断言，保留完整事件字段，没有删除差异字段或修改业务实现。早期失败日志保留诊断，不计为最终验收结果。

最终独立复验 [final summary](../../output/test-runs/t41-closeout-final/summary.json)：**33 passed / 0 failed / 0 skipped**（31项正向配对、2项比较器负例），runner exit 0；[Ruff 日志](../../output/test-runs/t41-closeout-final/ruff.log) exit 0。与前述93项计量专项合计126项测试通过。独立代理只读复核了新增断言，主代理核对报告/JUnit后作出本次范围验收通过判断。

## 交付边界

本轮仅新增对照测试、套件注册与验收文档。前序 R1—R9 及读取完整性修复由 93 项计量专项复验。相关测试规则已写入 [AGENTS.md](../../AGENTS.md)，默认只运行本次更新相关内容。

未运行后端/前端全量、全部浏览器或真实模型，不改变实际 .env，不提交、推送、部署。计量 Worker 相关进程证据来自专项中的受控测试，不代表生产故障注入、CI 或部署验收；不新增生产就绪、真实账单一致性、SCORM/xAPI 完整兼容结论。

回滚本轮验收补充时，仅移除新增对照测试、suite 注册及本轮文档；本轮没有业务数据迁移。工作区其他既有修改保留，测试报告作为本地证据保存。T41 计划目录受既有忽略规则约束，未修改忽略规则或强制暂存。

## 后续真实验证与修复

本文件是此前离线验收快照。后续[真实测试](live-acceptance-20261106.md)发现B1/B2，已完成[对应修复和183项相关验证](live-fix-20261106.md)，修复后真实复验待执行；不得将此前离线PASS当作真实链路通过。
