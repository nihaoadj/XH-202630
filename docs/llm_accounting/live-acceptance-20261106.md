# T41 真实链路专项验收（2026-11-06，含修复后重跑）

**结论：修复后重跑 PASS（限定范围）。** 第一次真实运行 FAIL，暴露 2 个阻塞缺陷（§3）；用户修复后，同规格重跑通过关键验收：26 次真实调用全部捕获、总量 143,601 与业务账本一致、资源分区可加总（§4）。首次失败证据保留，不因重跑成功而覆盖。

## 1. 第一次运行（修复前，FAIL）

| 项目 | 值 |
|---|---|
| run_id | `db60c0cd-f9b7-492d-be58-819f93ade7fd` |
| 学习者 | `user_8f5a1196abd2__rag_engineering_training__c28df92aa0f4` |
| 入口 | `GenerationJobService.create_job` + `backend/scripts/generation_worker.py --once`（真实 Worker 子进程） |
| 请求 | `resource_types=["讲义"]`，`include_review=true`，`include_claim_check=true`，`max_iterations=2`，`claim_max_iterations=1` |
| 终态 | job=`failed`，run=`failed`，`last_error_code=INTERNAL_ERROR`，`final_decision=null`，耗时约 76s |
| 资源 | `d7308266-62c5-4e94-bd32-4cba7ee443b3`，讲义，`review_status=approved`，`publication_status=unpublished`（2603 字符） |

冻结策略已确认生效：

- 讲义审核：`lecture_review_contract_version=2.0`，`strategy=lecture_issue_v2`，`context_tokens=129024`，`max_output_tokens=16384`，实际审核 schema 为 `LectureInitialReviewV2`。
- Claim：`strategy=neutral_estimate_v1`，`context_tokens=512`，`batch_claims=20`。

## 2. 模型调用与计量

实际发生 4 次逻辑调用 / 4 次底层 attempt / 0 次网关重试 / 0 次业务修订：

| 阶段 | 调用 | attempt | 输入 token | 输出 token | 合计 | 归属 |
|---|---:|---:|---:|---:|---:|---|
| diagnose | 1 | 1 | 572 | 189 | 761 | task |
| plan | 1 | 1 | 4,062 | 783 | 4,845 | task |
| generate | 1 | 1 | 7,263 | 1,524 | 8,787 | resource（`e69ec551…`、`讲义`） |
| review | 1 | 1 | 10,977 | 518 | 11,495 | resource（`25f51633…`） |
| 合计 | **4** | **4** | **22,874** | **3,014** | **25,888** | 4/4 usage 完整 |

计量查询结果（`LLMAccountingQueryService`，与 API 同口径）：

- `availability=available`，1 个 segment，`sealed=true`，无 `incomplete_reasons`，`as_of=2026-11-06T02:02:19Z`。
- `task_summary`：4 次调用，25,888 tokens，`usage_complete_calls=4`；与 `agent_steps.llm_attempts` 的 25,888 一致。
- 按 API 的 `expected_llm_stages={diagnose,plan,generate,review}` 查询时 `coverage_complete=true`，capture/attempt/usage/attribution 均为 true。
- 直接按任务终态查询、不传 expected stages 时 `coverage_complete=false`，原因为 `unproven_execution_coverage`（查询服务无法自行证明执行覆盖，符合现有设计）。
- 上游 4 次均返回 usage，无“未知用量”；Claim 阶段没有进入 Gateway，因此没有可标记的未知调用。

## 3. 阻塞缺陷

### B1（严重）：作用域标签在真实资源对象上调用 `.get`，直接打断业务

`backend/app/agents/resource_workflows/learning_documents/claim_extraction/executor.py:84`

```python
with stage_labeled_scope("claim_extract", labels=[str(resource.get("resource_id") or ""), batch.batch_id]):
```

`resource` 是 `LearningResource`（Pydantic 模型，文件内其他位置均用 `resource.resource_id` / `resource.content_text`），没有 `.get`。标签表达式在进入 `stage_labeled_scope` 之前求值，因此：

- 无论 `LLM_ACCOUNTING_ENABLED` 为 true 还是 false 都会抛出 `AttributeError`；
- Claim 抽取在进入 Gateway 前失败，`agent_steps` 第 7 步 `claim_extract` 状态 `failed`、`llm_attempts=[]`；
- 业务终态 `INTERNAL_ERROR`，错误文本为 `'LearningResource' object has no attribute 'get'`；
- 这不是质量门禁阻止发布，也不是模型/凭据错误。

`git diff` 显示该行及外层 `with` 是 T41 新增代码，属于本次计量接入引入的业务回归。现有 93 项计量专项没有直接调用 `execute_extraction` 的用例，因此未覆盖该路径。

### B2（严重）：资源分区视图重复累计 token

`backend/app/models/shared/llm_accounting.py:350-352`

```python
if observation.attribution == "resource" and observation.resource_labels:
    for label in observation.resource_labels:
        partitions.setdefault(("exclusive", label), []).append(observation)
```

同一 generate 调用带有 `["e69ec551…", "讲义"]` 两个标签，被同时计入两个 `exclusive` 分区。本次查询：

| 分区 | 调用 | token |
|---|---:|---:|
| exclusive `25f51633…` | 1 | 11,495 |
| exclusive `e69ec551…` | 1 | 8,787 |
| exclusive `讲义` | 1 | 8,787 |
| unallocated task | 2 | 5,606 |
| 分区合计 | 5 | **34,675** |

任务总计为 25,888，分区合计多出 8,787，恰好是 generate 调用被重复计入一次。T41 §4.3 要求“共享调用对全局只加一次”“独占资源与 shared/unallocated 作为可加总分区”；当前实现既重复累计，又把两个标签都标成 `exclusive`，查询方无法判断不可相加。

补充归属观察：generate 的主标签是 `resource_spec_id`（`e69ec551…`），review 的标签是 `review_id`（`25f51633…`），两者都不是最终 `generated_resources.resource_id`（`d7308266…`）。阶段汇总不受影响，但“按资源”视图无法直接与已发布资源对齐，需要业务 trace 才能映射；这也是资源分区需要一并修正的原因。

## 4. 第二次运行（修复后重跑，PASS）

用户修复 B1/B2 后，按同一规格重跑一次（新 run，未复用旧计量）：

| 项目 | 值 |
|---|---|
| run_id | `fe2663c9-a21c-427c-b9f5-b8ca8b878d52` |
| 入口/请求 | 同第一次；真实 `GenerationJobService` + `generation_worker --once`；单 `讲义`，`include_review=true`，`include_claim_check=true` |
| 终态 | job=`completed`，run=`human_review`，`final_decision="Claim 审核报告待用户决定是否发布"`，耗时约 271s |
| 资源 | v1 `c9e41c7b…`（approved，unpublished，2600 字符）；v2 `793ed6e3…`（human_review，unpublished，2540 字符，Claim 通过率 0.9074） |

冻结策略与第一次一致：讲义 `lecture_issue_v2` / contract `2.0` / context `129024`；Claim `neutral_estimate_v1` / context `512` / `batch_claims=20` / `max_calls=24`。

实际发生 26 次逻辑调用 / 26 次底层 attempt / 0 次网关重试；发生 1 轮 Claim 定向修订（v1→v2，`generation_attempt=2`，`prepare_claim_revision` 1 次），普通 `revision_count=0`：

| 阶段 | 调用 | attempt | 输入 token | 输出 token | 合计 |
|---|---:|---:|---:|---:|---:|
| diagnose | 1 | 1 | 572 | 233 | 805 |
| plan | 1 | 1 | 4,102 | 900 | 5,002 |
| generate | 2 | 2 | 21,790 | 3,038 | 24,828 |
| review | 2 | 2 | 23,460 | 1,157 | 24,617 |
| claim_extract | 18 | 18 | 34,268 | 22,646 | 56,914 |
| claim_judge | 2 | 2 | 21,067 | 10,368 | 31,435 |
| **合计** | **26** | **26** | **105,259** | **38,342** | **143,601** |

计量查询（`expected_llm_stages={diagnose,plan,generate,review,claim_extract,claim_judge}`）：

- `availability=available`，1 个 segment，`sealed=true`，无 `incomplete_reasons`，`coverage_complete=true`。
- 26 次调用 `usage_complete_calls=26`，`usage_source=both`；无未知用量。
- 26 个 `source_call_id` 全部唯一，`observation_id` 为 1—26，无重复投递；26 次 `outcome=success`，每次 1 个 attempt，`gateway_retry_count=0`。
- 资源分区：v1 `c9e41c7b…` 12 次 / 65,941；v2 `793ed6e3…` 12 次 / 71,853；task 2 次 / 5,807；**合计 143,601，与任务总计一致**（B2 修复生效）。
- 交叉核对：总计 143,601 与业务报告 `known_total_tokens` 一致；非抽取阶段 86,687 = diagnose+plan+generate+review+claim_judge；Claim 抽取 18 次 / 56,914 与抽取账本 `calls=18` / `known_tokens=56,914` 一致；无漏记或重复。

Claim 结果（按资源版本拆分）：v1 `c9e41c7b…` 73 条（factual 65、instructional 5、non_factual 3；supported 53、non_factual 8、not_in_evidence 12）；v2 `793ed6e3…` 62 条（factual 54、instructional 5、non_factual 3；supported 49、non_factual 8、not_in_evidence 5）。报告中的 135 = v1 73 + v2 62，是两版累计，不是最终资源条数；最终 v2 为 62 条，`claim_metric_status=complete`、`claim_factual_pass_rate=0.9074`（49/54）。v2 内按 `claim_text`、`claim_hash`、`source_start/source_end` 均无重复（62 条唯一），与 `claim-density-v1` 的 `chars_per_claim=35` 配置一致（2540 字符 / 62 ≈ 41 字符每 Claim）。业务未自动发布，进入 `human_review` 等待用户决定，这是现有 Claim 审核门禁的正常终态，不是失败，也未修改门禁或反复生成凑发布。

### 修复验证

- B1：`claim_extraction/executor.py:84` 已改为 `resource.resource_id`；本次 Claim 抽取 18 次调用全部成功，业务不再抛 `AttributeError`。
- B2：`models/shared/llm_accounting.py` 只把首个标签计入 `exclusive`；本次 v1/v2/task 三个分区合计严格等于任务总计。
- 资源对齐：本次 generate/review/claim 的主标签均为最终 `resource_id`（v1 `c9e41c7b…`、v2 `793ed6e3…`），未再出现 spec/review 标签导致的不可对齐。

## 5. 通过项与未覆盖项

重跑通过项：

- 26 次真实调用全部捕获；task/stage 与业务账本一致；资源分区严格可加总。
- Claim 抽取 18 次、判定 2 次实际执行；1 轮 Claim 定向修订与 4 个批次替换均保留，无漏记。
- 1 个 segment 已 seal，异步写入完成；26/26 usage 完整，无未知用量。
- 未发生网关重试；计量 `gateway_retry_count=0` 与业务 attempt 一致。
- 未自动发布，进入 `human_review` 等待用户决定；未修改门禁或反复生成凑发布。

未覆盖/未运行：

- 未运行全量测试、前端/浏览器、HTTP API 实际调用、部署；计量查询由与 API 相同的 `LLMAccountingQueryService` 执行，未另起 HTTP 服务。
- 单样本、单模型；不构成真实模型质量、精确账单核销或生产就绪结论。
- 第一次运行的 FAIL 保留为历史证据；其修复由用户完成，本次只做真实复验，未重跑 183 项离线测试。

## 6. 修复与复验（已完成）

1. B1：`executor.py:84` 已改为 `labels=[resource.resource_id, batch.batch_id]`；本次 18 次 Claim 抽取全部成功，业务不再抛 `AttributeError`。
2. B2：资源分区只把首个标签计入 `exclusive`；本次 v1/v2/task 三分区合计 143,601，与任务总计一致。
3. 资源对齐：review 以 `request.resource_id` 为主标签；生成侧在实际资源物化后绑定未解析的 spec 标签。本次 v1 `c9e41c7b…`、v2 `793ed6e3…` 的 generate/review/claim 主标签均与最终 resource_id 一致。
4. 既有离线修复证据（183 项）见[修复验收记录](live-fix-20261106.md)；本次未重复运行，只用一次真实单资源链路复验关键路径。

## 7. 证据路径

第一次运行（FAIL）：

- `output/t41-live-acceptance/run.log`
- `output/t41-live-acceptance/lecture-claim-report.json`
- `output/t41-live-acceptance/accounting-query.json`
- `output/t41-live-acceptance/accounting-query-expected-stages.json`
- `output/t41-live-acceptance/business-summary.json`
- `output/t41-live-acceptance/run-invalid-learner.log`（首次学习者层级前置拒绝，未创建 Run、未调用模型）

第二次运行（修复后 PASS）：

- `output/t41-live-acceptance/run-r2.log`
- `output/t41-live-acceptance/lecture-claim-report-r2.json`
- `output/t41-live-acceptance/accounting-query-r2.json`
- `output/t41-live-acceptance/accounting-query-r2-expected-stages.json`
- `output/t41-live-acceptance/business-summary-r2.json`

计量库：`backend/data/llm_accounting.db`（按 run_id 查询）。修复离线证据：`docs/llm_accounting/live-fix-20261106.md`。

## 8. 后续修复状态

B1/B2 与资源归属已修复，并经本次真实单资源重跑复验：Claim 抽取/判定实际执行，26 次调用全部捕获，资源分区合计等于任务总计。原真实 FAIL 保留为本报告 §1—§3 的历史记录；修复后真实复验已完成，详见 §4。
