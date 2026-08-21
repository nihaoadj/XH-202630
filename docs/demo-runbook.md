# P0-09 比赛 Demo Runbook

> 适用基线：`feature/multi-AGENTS`，fixture `p0-09-demo-suite/v1`。本 Runbook 区分“确定性离线验收”和“真实运行时演示”；fixture/replay 不冒充实时大模型结果。

## 1. 放行原则

正式演示前必须同时满足：

- `python scripts/p0_09_preflight.py` 返回 `READY`（退出码 0）。
- offline acceptance 的 Scenario A～J 全部 `PASS`。
- runtime acceptance 为 `PASS`，而不只是 `/health` HTTP 200。
- 浏览器人工 E2E checklist 全部确认。
- live provider smoke 如被列入本次演示范围，必须显式启用并单独记录结果。

`DEGRADED` 只能用于排障或受控预演；`NOT_READY` 与任一 required Gate 的 `FAIL` 都是 No-Go。当前代码已包含 SQLite 外键 hook 和资源版本唯一约束 migration，但正式 demo 数据仍须完成迁移演练；前端 Claim/Evidence、SourceRef V2 和画像/路径报告缺口仍会使 runtime Gate 失败。

## 2. 启动前准备

### 2.1 环境与数据保护

1. 从 `backend/.env.example` 创建个人 `backend/.env`，不要将真实 Key 写入 Git。
2. 确认 `APP_MODE`、`DB_TYPE`、默认 KB、Embedding、LLM Provider 和 structured output 配置；检查命令不得输出 secret。
3. 正式演示使用独立 demo 数据库和 Chroma 目录。若复用已有开发数据，先在仓库外做可恢复备份。
4. 不执行删除数据库、清空 Chroma、`git clean` 或覆盖团队数据的命令。

### 2.2 安装、初始化与构建

在仓库根目录执行：

```powershell
python -m pip install -r backend/requirements.txt
python scripts/init_db.py
python scripts/ingest_knowledge.py
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

`init_db.py` 和 `ingest_knowledge.py` 会改变配置指向的数据；只允许对明确的 demo 路径执行。固定离线 fixture 位于 `backend/tests/fixtures/p0_09/`，其测试不需要公网，也不写正式 demo 数据库。

### 2.3 Preflight 与验收

```powershell
python scripts/p0_09_preflight.py --output wzx/out/p0-09-preflight.json
python scripts/run_p0_09_acceptance.py --offline --output wzx/out/p0-09-offline-manifest.json
python scripts/run_p0_09_acceptance.py --runtime --output wzx/out/p0-09-runtime-manifest.json
```

退出码：`0=PASS/READY`、`1=FAIL/NOT_READY`、`2=PARTIAL/DEGRADED`。不得只看最后一行或 HTTP 200；必须打开 manifest 核对 Scenario、Metric、DB、Frontend 和 known limitations。

如需收费 Provider 冒烟，另开一次并保存单独证据：

```powershell
$env:RUN_LIVE_LLM='1'
python scripts/run_p0_09_acceptance.py --live --output wzx/out/p0-09-live-manifest.json
Remove-Item Env:RUN_LIVE_LLM
```

### 2.4 启动服务

终端 A：

```powershell
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端 B：

```powershell
Set-Location frontend
npm run dev
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

管理员全 KB health 需要有效管理员 Token；不得在投屏、日志或截图中显示 Token。

## 3. 十步主 Demo

1. 打开固定 learner/profile，说明 beginner/intermediate/advanced 中本次使用的层级、目标知识点和画像版本。
2. 创建异步 Generation Job，记录 `run_id`；解释 Job 与 AgentRun 共用稳定 ID，但职责不同。
3. 展示 SSE Agent timeline：queued、Diagnosis、Retriever/Evidence Gate、Planner、Generator、Reviewer、Claim Audit、terminal。
4. 打开 Evidence 详情，展示安全 locator、DocumentVersion、Chunk ID 与冻结 snapshot；不展示 prompt 或模型原始响应。
5. 展示 Reviewer 决策、结构化 issue/revision instruction 与 Claim verdict，强调 Reviewer 自评分不是正式幻觉指标。
6. 打开最终 published leaf，展示资源版本链、SourceRef 和 publication gate；旧版与不安全状态不进入默认资源库。
7. 提交 Formal LearningAttempt，展示后端重算的逐知识点得分与幂等键。
8. 展示 mastery、ProfileVersion N→N+1 和 LearningPath mutation；说明低/中/高分及 critical blocker 规则。
9. 若决策为 remediate/advance，跳转 child Run 并订阅 child SSE；practice 默认不创建无意义 child generation。
10. 打开 Report，核对 Attempt、掌握度、画像版本、路径和 child relation 都来自持久化事实。

## 4. 可信性分支

### Evidence 不足

使用固定 `no_hit/evidence_insufficient` 场景。应看到 Evidence Gate fail closed、Generator 不执行、资源为空、无 published 资源，timeline 明确记录安全阻断。

### Reviewer 定向返工

展示 tutorial v1 + exercise v1，Reviewer 只返工 tutorial，随后出现 tutorial v2；exercise 继续沿用 v1。最终只有批准的叶子版本发布，v1 与指令保留用于回放。

### Claim 驱动返工

展示 Reviewer approve 后 Claim Judge 判为 `contradicted/not_in_evidence`，系统生成带 `target_claim_ids` 的返工指令；v2 重新抽取、重新判定，旧 judgement 不覆盖，最终指标只取 published leaf。

## 5. 故障与恢复

| 情况 | 演示动作 | 期望结果 |
|---|---|---|
| SSE 断线 | 记录最后 sequence，断开后重连 | `Last-Event-ID` 后续传，无重复 Step，Job 不受影响 |
| 页面刷新 | 保留 run_id 后刷新 | REST timeline 恢复持久化事实，再续订 SSE |
| KB not ready | 查看 `/health/ready` 与管理员 KB health | 默认 KB 故障阻断生成；非默认 KB 故障只在管理员明细中 degraded |
| LLM auth/bad request | 使用受控 failure fixture | 不做不安全重试，不发布伪成功结果 |
| Reviewer/Claim Judge 失败 | 使用 failure fixture | 进入 `human_review`，无默认发布 |
| Retriever 基础设施失败 | 使用 failure fixture | fail closed，不生成虚构资源 |
| Persistence conflict | 使用 failure fixture | 返回稳定冲突语义，无 false success/重复 mutation |

P0-04 的 Replay 是“重建后查询历史事实”，不是服务重启后自动从中断点 Resume。

## 6. 浏览器人工 E2E Checklist

- [ ] health ready
- [ ] learner fixture visible
- [ ] generation job created
- [ ] SSE queued
- [ ] Diagnosis visible
- [ ] Retriever/Evidence visible
- [ ] Planner visible
- [ ] Generator visible
- [ ] Reviewer visible
- [ ] Claim visible
- [ ] Publication visible
- [ ] Resource visible
- [ ] SourceRef visible
- [ ] Claim metric visible
- [ ] Attempt submit
- [ ] Profile version update
- [ ] Mastery update
- [ ] Path mutation
- [ ] child Run
- [ ] child SSE
- [ ] Report reflects state
- [ ] Refresh replay
- [ ] SSE reconnect

## 7. 演示证据与收尾

保留 acceptance manifest、preflight JSON、浏览器 checklist 和必要截图。真实 Golden Run 可调用 `build_safe_evidence_bundle()` 导出 allowlist 摘要，只包含稳定 ID、计数、状态和安全 locator；不得导出 prompt、raw provider response、Chain-of-Thought、API Key、绝对路径或完整学习者画像。

## 8. Tutor 1~2 分钟演示脚本

1. 在资源书架打开一个已发布资源，点击“向 Tutor 提问”。
2. 第一次询问具体卡点，展示服务端给出的“提示 1/3”和 Evidence 来源。
3. 明确表示仍未理解，展示“提示 2/3”的结构化拆解。
4. 第三次继续追问，展示“提示 3/3”的 grounded explanation 与理解检查问题。
5. 刷新页面并重新打开抽屉，确认会话与三轮内容恢复。
6. 进入反馈页，在某道题旁点击“需要提示”，说明题目上下文由后端按 `question_id` 解析，答案未暴露给客户端或 Tutor context。
7. 完成批次测评并提交，展示 Attempt 的 `hint_count` 由服务端按 `batch_id` 汇总持久化 Tutor 轮次，同时 Feedback Decision、Mastery 与路径仍沿用原确定性策略。
8. 可选安全分支：使用无 Frozen Evidence、无 SourceRef 且检索不可用的 fixture，展示 HTTP 200 `evidence_insufficient`，并说明该轮不会调用模型自由知识回答。

演示结束后记录 Git SHA、suite/fixture 版本、APP_MODE、DB_TYPE、默认 KB、offline/runtime/live 结果以及所有 FAIL/NOT_MEASURABLE。不要因为现场演示成功而把未执行的统计评测标成 PASS。
