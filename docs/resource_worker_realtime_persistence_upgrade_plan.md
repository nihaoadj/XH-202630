# 资源级 Worker 与即时持久化升级方案

> 状态：待评审，尚未实施。  
> 更新日期：2026-08-20。  
> 本文是对 [资源导向工作流改造方案](resource_oriented_workflow_refactor_plan.md) 的第二阶段升级设计：保留既有专用 Agent、资源版本、HTML 两阶段派生和前端展示，升级执行模型为“每个资源独立 Worker、状态即时持久化、SSE 实时投影”。

## 1. 决策与目标

### 1.1 已确认的决策

- 新 Run 使用资源级 Worker 工作流；不提供用户可操作的旧/新流程切换按钮。
- `讲义 → TextResourceAgent`、`实操指南 → HtmlPracticeGuideAgent`、`分阶测试题 → AssessmentAgent` 的确定性路由保持不变。
- Worker 是资源级执行与持久化边界，不是把所有资源重新塞入一个大模型响应。
- 每个资源可独立生成、审核、Claim 审核、返工、发布或转人工；一个资源失败不得阻塞已通过资源。
- 已批准且已发布的文本资源应在该资源 Worker 完成时立即可读；实操指南 HTML 仅在其 canonical Markdown 文本已批准并发布后派生。
- 草稿、`revision_requested`、`human_review` 和失败资源均不得预览正文或 HTML。

### 1.2 解决的问题

当前统一汇总模式虽然已按资源类型调用专用 Agent，但资源执行记录、资源版本和 SSE 事件只在 Generator/Reviewer/Claim 节点整体返回后持久化。于是前端只能看到节点边界的状态跳变，无法在一个较长批次中准确显示“讲义已完成、测试题仍在生成”。

升级后需要达到：

1. 调度器先为每个 `(resource_spec_id, representation)` 创建 `queued` 执行记录并立即发事件。
2. 单个 Worker 获取任务后立即以原子事务写入 `generating`，模型成功后立即写入资源版本与 `generated`。
3. 同一 Worker 按该资源的策略继续审核、Claim 和 HTML 派生；每个阶段完成都持久化并生成可回放事件。
4. 批次汇总节点只读取已经持久化的资源当前态并决定 Run 终态，不能覆盖任何资源终态。
5. SSE 在事务提交后最多一个轮询周期内向前端可见；前端按事件序列和资源版本单调合并。

## 2. 当前基线与目标边界

| 维度 | 当前统一汇总 | 升级后的资源级 Worker |
| --- | --- | --- |
| LangGraph | 一个 Generator/Reviewer/Claim 节点处理全量 Spec | Dispatcher 动态派发一个或多个 `ResourceWorker`，再进入 Batch Join |
| 资源落库 | 节点返回后由 `WorkflowArtifactRecorder` 批量持久化 | 每个 Worker 在每个外部副作用完成后直接、原子地持久化 |
| SSE | 节点完成时资源状态跳变 | `queued`、`generating`、`generated`、`reviewing`、`claim_checking`、终态逐资源推送 |
| 返工 | 当前每类型唯一 Spec 时按类型选择 | 由 `resource_spec_id` 精确选择，允许未来同类型多 Spec |
| 失败隔离 | 产物层面隔离，但等待同节点返回 | 执行、发布、事件和恢复均完全按资源隔离 |
| Run 终结 | 节点输出内计算 | Join 从持久化投影计算；不写回或降级已发布资源 |

本期不引入消息队列、分布式任务平台或跨进程调度器。Worker 仍由当前一次 Run 的 LangGraph 执行动态派发；但所有 Worker 状态都必须可由数据库恢复。若将来需要跨实例长期运行，可在不改变资源状态机与事件协议的情况下，把 Dispatcher 替换为队列投递器。

## 3. 目标拓扑

```text
Run 创建
  → Diagnosis → Retrieval → Evidence Gate → Planner → ResourceSpec Builder
  → ResourceWorkerDispatcher
       ├─ persist Spec + queued execution × N
       └─ Send("resource_worker", ResourceWorkItem) × N

ResourceWorker（每个 Spec 的文本表示独立运行）
  → acquire lease / generating
  → Specialized Generate
  → persist resource version / generated
  → review one resource / persist reviewing → approved | revision_requested | human_review | failed
  → [claim one resource / persist claim_checking → approved | revision_requested | human_review]
  → [for 实操指南 text 已发布：derive HTML worker task]
  → emit ResourceWorkerResult（只含小型结果，不含正文）

  → ResourceWorkerJoin（等待本轮目标 Worker；从数据库重建聚合投影）
       ├─ 有 revision_requested：仅派发目标 resource_spec_id 的下一次 Worker
       └─ 无待返工目标：BatchFinalize
  → BatchFinalize（计算 Run 终态、发 Run 事件，不覆写资源终态）
  → END
```

### 3.1 使用 LangGraph 的方式

当前项目安装的 LangGraph 已提供 `Send(node, arg)`，可用于受控动态派发。因此实施使用 `add_conditional_edges` 从 Dispatcher 返回 `list[Send]`，并将所有 `resource_worker` 边收敛到 Join。不要依赖当前环境中不存在的 `Command` API。`DurableWorkflowRunner` 调用 `workflow.stream()` 时必须传入 `config={"max_concurrency": settings.resource_worker_max_concurrency}`；不能只在环境变量中声明并发上限而不传给 LangGraph，也不能继续以 `ThreadPoolExecutor` 作为 Worker 主并发控制。

`resource_worker` 每次只接收一个不可变的 `ResourceWorkItem`，不能直接写 `generated_resources`、`resource_executions`、`errors` 等共享列表。它只返回以执行键为键的小型 `ResourceWorkerResult`，由显式 reducer 合并；正文、审核全文和模型原始输出不通过 LangGraph state 传播。

```text
dispatch generation
  -- Send(work_item A) --> resource_worker A --┐
  -- Send(work_item B) --> resource_worker B --┼--> resource_worker_join
  -- Send(work_item C) --> resource_worker C --┘
```

Join 运行后再决定是否派发下一轮精确返工，避免同一 Spec 在同一轮被重复派发。

### 3.2 每个 Worker 的私有流水线

Worker 不是“只有生成”的函数，而是一个资源的最小闭环。其处理顺序如下：

1. 获取执行 lease，写入 `generating`。
2. 从冻结 `ResourceSpec` 和限定证据构建 `ResourceGenerationContext`，按注册表调用专用 Agent。
3. 验证产物，原子保存新资源版本、更新执行为 `generated`，并发出 `resource_generated`。
4. 若开启审核，写入 `reviewing`，只将当前资源与其允许证据交给 `review_one_resource()`。
5. 审核通过且未开启 Claim 时，原子发布该文本资源；审核要求返工时，仅将该执行置为 `revision_requested`。
6. 若开启 Claim，写入 `claim_checking`，只执行当前资源的抽取、判定和指标计算。Claim 通过才发布；不通过按当前资源进入返工或人工复核。
7. 对已发布的 `实操指南/text` 创建独立 `html` 表示任务。HTML Worker 仅接收已批准文本、manifest、hash 和源版本；HTML 失败只能使 HTML 执行失败，不能撤回文本发布。
8. 释放 lease，并返回不含正文的结果摘要。

Worker 内部的每次模型调用都使用独立、可审计的 `worker_step_id` 和 `stage`；但 `worker_step_id` 不得被当成资源身份或版本身份。资源身份始终为 `(run_id, resource_spec_id, representation)`，资源版本身份为 `resource_id + version`。

## 4. 数据模型、状态机与一致性

### 4.1 新增的 Worker 契约

在 `backend/app/agents/resource_workers/contracts.py` 定义以下 Pydantic 契约：

```python
class ResourceWorkItem(BaseModel):
    run_id: str
    batch_id: str
    resource_spec_id: str
    representation: Literal["text", "html"]
    resource_attempt: int
    worker_id: str                 # 每次派发唯一 UUID
    source_resource_id: str | None # HTML 或返工时的来源
    source_resource_version: int | None
    expected_state: str            # 用于 CAS/状态转换校验

class ResourceWorkerResult(BaseModel):
    execution_key: str             # run_id/spec_id/representation
    worker_id: str
    resource_spec_id: str
    representation: Literal["text", "html"]
    resource_attempt: int
    final_state: str
    resource_id: str | None
    published_resource_id: str | None
    review_id: str | None
    needs_revision: bool = False
    error_code: str | None = None

class ResourceWorkerJoinState(TypedDict, total=False):
    worker_results: Annotated[dict[str, ResourceWorkerResult], merge_worker_results]
```

`merge_worker_results` 必须按 `execution_key` 与 `resource_attempt` 单调合并：高 attempt 覆盖低 attempt；同 attempt 的不同 `worker_id` 或不同终态视为持久化冲突，禁止“后到覆盖先到”。

### 4.2 `ResourceExecutionRecord` 扩展

保持现有 `(run_id, resource_spec_id, representation)` 唯一行作为“当前态投影”，并新增以下字段：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `stage` | 枚举 | `dispatch`、`generate`、`review`、`claim_extract`、`claim_judge`、`derive_html`、`finalize` |
| `worker_id` | UUID/string | 本次 Worker 领取者；替代把 `worker_step_id` 同时当作任务与步骤的混用 |
| `stage_attempt` | int | 当前阶段的重试次数 |
| `row_version` | int | 乐观并发控制版本 |
| `lease_owner` | string/null | 当前执行实例标识 |
| `lease_expires_at` | UTC datetime/null | 防止崩溃后永久占用 |
| `heartbeat_at` | UTC datetime/null | 用于可观测性与失效回收 |
| `last_event_sequence` | int/null | 该执行已提交的最新工作流事件序列 |
| `terminal_at` | UTC datetime/null | 资源达到 `approved`、`human_review` 或 `failed` 的时间 |

保留 `attempt`，但将其明确命名为“资源级生成/返工轮次”；它不再借用全局 `generation_attempt` 的含义。当前模型中的 `worker_step_id` 保留为兼容字段，迁移后表示当前阶段的审计步骤 ID。

### 4.3 状态转换

```text
queued
  → generating → generated → reviewing
                             ├─ revision_requested → generating（attempt + 1，仅当前 Spec）
                             ├─ claim_checking → approved
                             │                   ├─ revision_requested
                             │                   └─ human_review
                             ├─ approved
                             ├─ human_review
                             └─ failed

实操指南 html：queued → generating → approved | failed
```

规则：

- `approved`、`human_review` 和 `failed` 是该表示的终态；终态只能由一个新的、明确授权的 retry/revision 创建下一 `attempt`，不能被旧 Worker 直接覆盖。
- `revision_requested` 不是发布状态；原资源版本保留为未发布历史，下一版本必须通过 `parent_resource_id` 连接。
- `html` 只能从同一 Spec 已发布文本的 `(resource_id, version, canonical_text_hash)` 创建，且其 `derived_from_resource_id`、`source_resource_version` 与 hash 必须一致。
- Join 和 BatchFinalize 无权把 `approved` 改回草稿或把 `failed` 改成成功；它们只计算聚合状态。

### 4.4 原子持久化与幂等

现有 `ResourceRepository` 与 `AuditRepository` 分别自行提交事务，不能直接用于 Worker 的“资源 + 当前态 + 事件”一致性要求。新增一个跨表事务边界：

`ResourceWorkflowPersistenceService`（接口）及其 SQL/内存实现必须提供：

```text
dispatch_execution(...)          # 保存 Spec、创建 queued、写 resource_execution_queued
acquire_execution_lease(...)     # CAS 获取 lease，写 resource_generation_started
persist_generated(...)           # 保存资源版本 + execution=generated + event，同一事务
persist_review_outcome(...)      # 保存审核 + 更新资源/执行 + resource_approved/revision/human，同一事务
persist_claim_outcome(...)       # 保存 Claim/判定/指标 + 发布或返工事件，同一事务
persist_html_outcome(...)        # 保存 HTML 资源 + execution + event，同一事务
mark_execution_failed(...)       # 脱敏错误码 + failed/human_review + event，同一事务
release_or_expire_lease(...)     # 仅由 owner 或超时恢复流程执行
```

每个方法必须：

1. 以 `(execution_id, resource_attempt, stage, stage_attempt)` 生成稳定 `operation_id`。
2. 使用 `row_version` 或等效的 SQL `WHERE row_version = :expected` compare-and-swap。
3. 在同一数据库事务中写资源/审核/Claim、当前执行态和 `WorkflowEvent`。
4. 使用由 `run_id + execution_id + operation_id` 派生的稳定 `event_id`，使重复执行返回既有成功结果而不是重复事件。
5. 事务提交后才允许 SSE 查询到事件；事务回滚时不得留下“资源已发布但没有事件”或“事件指向不存在版本”。

SQL 实现应使用同一 `Session` 与 `session.begin()`；内存实现必须在一个锁内同时更新资源、执行投影和事件账本。不能由 Worker 依次调用 `save()`、`upsert_execution()`、`append_event()` 来模拟原子性。

## 5. 后端实施设计

### 5.1 新目录与职责

```text
backend/app/agents/
├── resource_agents/                 # 已存在：只负责资源内容生成
└── resource_workers/                # 新增：只负责编排一个资源的执行闭环
    ├── __init__.py
    ├── contracts.py                  # ResourceWorkItem/Result 与 reducer
    ├── dispatcher.py                 # 选择可运行 Spec、创建 queued、返回 Send[]
    ├── worker.py                     # 资源生成→审核→Claim→发布/HTML 的私有流水线
    ├── join.py                       # 聚合小型 worker result，不读取正文
    └── recovery.py                   # 领取超时 lease、构造恢复 WorkItem

backend/app/services/
└── resource_workflow_persistence_service.py  # 原子资源工作流持久化门面
```

`resource_agents/` 继续只处理 `TextResourceAgent`、`HtmlPracticeGuideAgent`、`AssessmentAgent` 的 Prompt、Schema 与内容校验；不得将事务、SSE、状态机或重试逻辑塞入专用内容 Agent。

### 5.2 现有文件的具体改动

| 文件 | 必须改动 |
| --- | --- |
| `backend/app/agents/workflow.py` | 导入 `Send`；以 `resource_worker_dispatch`、`resource_worker`、`resource_worker_join` 替换统一 `generate/review/claim` 主链；保留高层节点名映射供前端展示。`batch_finalize` 从持久化投影计算 Run 状态。 |
| `backend/app/models/workflow.py` | 增加 `worker_results` 的自定义 reducer、`active_resource_spec_ids`、`resource_worker_round` 等轻量 state；禁止 Worker 写共享资源正文列表。 |
| `backend/app/agents/generator.py` | 保留文件名与公共导入兼容，但收缩为 Spec 构建、资源物化帮助函数和 Dispatcher 共用逻辑；移除 ThreadPoolExecutor 作为主执行机制。 |
| `backend/app/agents/reviewer.py` | 提取无共享 state 的 `review_one_resource(resource, evidence, context)`；统一 `review_node()` 仅保留历史 Run 兼容或作为 Worker 调用的薄包装。Reviewer 的“返工目标”由服务端绑定当前 `resource_spec_id`，不相信模型自由返回的类型。 |
| `backend/app/agents/claim_review.py` | 提取 `review_claims_for_resource()`；每次只处理一个资源版本，返回该资源的 Claim 结果与发布建议。 |
| `backend/app/services/recorded_node.py` | Dispatcher、Join、Finalize 仍用 RecordedNode；`resource_worker` 以 Worker 步骤记录启动/结束，但业务资源状态与事件必须由即时持久化服务写入，不等待 `RecordedNode.complete_step()`。 |
| `backend/app/services/durable_workflow_runner.py` | 调用 `workflow.stream(..., config={"max_concurrency": settings.resource_worker_max_concurrency})` 以实际限制动态 `Send` 的并发；继续在 Join/Finalize 等 merge 边界保存 checkpoint；不得再把 Worker 产物持久化职责交给 `WorkflowArtifactRecorder`。增加恢复入口在失效 Worker 后重新调度非终态 execution。 |
| `backend/app/services/workflow_artifact_recorder.py` | 不再处理 Worker 资源、审核和 Claim 的主写入；保留 Spec/最终兼容投影或逐步删除重复写入路径，防止和 Worker 事务双写。 |
| `backend/app/db/resource/base.py`、`memory.py`、`sql_repository.py` | 增加执行领取、CAS 更新、按状态/超时 lease 查询、按 `resource_spec_id` 查询当前资源版本的仓储方法。 |
| `backend/app/db/models.py` | 扩展 `ResourceExecutionORM` 的 stage、lease、行版本、事件序列与终态字段；为 `(run_id, state, lease_expires_at)`、`(run_id, resource_spec_id, representation, row_version)` 建索引。 |
| `backend/app/db/migrations/` | 新增可重复的 `p0_14_resource_worker_execution.py`；旧 execution 行填充默认 stage/row_version，空 lease。迁移不得重写资源正文或历史事件。 |
| `backend/app/models/persistence.py` | 将实际需要的 `RESOURCE_EXECUTION_QUEUED`、`RESOURCE_GENERATION_STARTED`、`RESOURCE_GENERATED`、`RESOURCE_REVIEW_STARTED`、`RESOURCE_REVISION_REQUESTED`、`RESOURCE_CLAIM_CHECK_STARTED`、`RESOURCE_APPROVED`、`RESOURCE_EXECUTION_FAILED`、`HTML_DERIVATION_*` 加入 `WorkflowEventType`。 |
| `backend/app/services/run_event_stream_service.py` | 允许投影 `worker_id`、`worker_step_id`、`stage`、`resource_attempt`、`last_event_sequence` 等安全标量；绝不投影正文、Prompt 或原始模型响应。新连接 snapshot 应包含 `resource_progress_summary` 与有界 `items`。 |
| `backend/app/services/generation_job_service.py` | Job 摘要直接读取最新 execution 投影；Job 在资源部分完成时保持 `running`，所有目标 execution 到终态后才转 completed/degraded/human_review/failed。 |
| `backend/app/containers.py`、`generation_service.py` | 注入 Worker Dispatcher、ResourceWorkerPipeline、即时持久化服务与恢复器；避免在 Worker 内自行构建全局单例。 |
| `backend/app/config.py`、`.env.example` | 增加 `RESOURCE_WORKER_MAX_CONCURRENCY`、`RESOURCE_WORKER_LEASE_SECONDS`、`RESOURCE_WORKER_HEARTBEAT_SECONDS`、`RESOURCE_WORKER_RECOVERY_INTERVAL_SECONDS`、`RESOURCE_EVENT_SSE_MAX_LATENCY_SECONDS`，全部实施上下界校验。 |

### 5.3 精确返工策略

返工目标必须升级为 `target_resource_spec_id`，并附带 `target_representation="text"`。当前资源类型唯一的限制仍可保留，但不再作为返工定位的依据。

1. Worker 的 Reviewer/Claim 结论为 `revise` 时，服务端生成 `RevisionRequest(resource_spec_id=current_spec_id, parent_resource_id=current_resource_id, required_actions=...)`。
2. Join 只收集 `revision_requested` 的 `resource_spec_id`，并在该资源 `attempt < max_iterations` 时发送下一轮 WorkItem。
3. 返工 WorkItem 使用相同 Spec、Agent 和 Prompt family；新文本版本 `version + 1`，`parent_resource_id` 指向上一版本。
4. 旧 HTML 派生物不得复用；只有新文本批准并发布后，才重新派发相应 HTML WorkItem。
5. 额度耗尽时只将目标资源置为 `human_review`，其他已发布资源保持可用。

### 5.4 崩溃、重试与恢复

- Worker 获取 lease 后每个模型调用前后更新 heartbeat；长 HTML 调用期间至少按配置更新一次。
- 进程崩溃或 lease 过期时，恢复器查询非终态 execution，使用 CAS 领取并按其已持久化 `stage` 构造恢复 WorkItem。
- 生成产物已保存但 Worker 在发下一阶段前崩溃时，恢复器从 `generated` 开始审核，不得重新生成相同版本。
- 已发布资源的重复投递必须因 operation/event 幂等键成为 no-op。
- 正常 LLM 瞬态错误只能在当前 stage 的受控重试额度内重试；超过额度后写 `human_review` 或 `failed`，并带脱敏错误码。
- 一次 Run 的全局 deadline 仍有效，但不能取消或回滚已提交的资源事务；超时时将尚未终态的 execution 安全转入 `human_review`/`failed` 并生成事件。

## 6. SSE 与前端实时进度

### 6.1 事件协议

所有 Worker 事件采用 `WorkflowEvent.event_sequence` 全局单调序列，且事件 payload 至少包含：

```json
{
  "resource_spec_id": "...",
  "representation": "text",
  "resource_type": "讲义",
  "resource_execution_state": "generating",
  "resource_attempt": 1,
  "stage": "generate",
  "worker_step_id": "...",
  "agent_name": "TextResourceAgent",
  "prompt_version": "...",
  "validation_status": "pending"
}
```

`resource_id`、`review_id`、`publication_status` 仅在已实际生成、审核或发布后出现。事件载荷保持标量/短数组边界，不包含学习者画像、证据正文、资源正文、HTML 或 Prompt。

推荐事件顺序：

```text
resource_execution_queued
resource_generation_started
resource_generated
resource_review_started
[resource_claim_check_started]
resource_approved
resource_published
[html_derivation_started → html_derivation_completed | html_derivation_failed]
```

### 6.2 SSE 服务要求

- SSE 使用现有 `Last-Event-ID` 优先于 `after_sequence` 的游标规则，持续重放 durable event ledger。
- `get_snapshot()` 注入 Resource Repository，返回当前 `resource_progress_summary` 及最多 100 个有界 `items`，使新连接无需等待下一事件就能恢复资源卡片。
- 事件提交后由现有短轮询读取；`WORKFLOW_SSE_POLL_INTERVAL_SECONDS` 必须满足产品定义的最大可见延迟。若目标为 1 秒内可见，默认值建议不高于 0.25 秒，并以压测结果确认数据库负载。
- 不以“EventSource 收到事件”作为资源已落库证明；前端只相信已提交事件和随后可读取的详情接口。

### 6.3 前端改动

| 文件 | 改动 |
| --- | --- |
| `frontend/src/api/runEvents.js` | 将所有资源 Worker 事件加入监听列表；保留 sequence 去重与 Last-Event-ID 重连。 |
| `frontend/src/utils/workflowEventReducer.js` | 用 `(resource_spec_id, representation)` 作为卡片键，用 `resource_attempt + last_sequence` 单调合并；拒绝旧 attempt 或旧序列覆盖新状态。 |
| `frontend/src/components/AgentVisualization.vue` | 连接标签恢复为“资源级同步”；高层流程不展开为多条复杂主线，只在“资源生成”“审核与发布”下展示资源卡片。 |
| `frontend/src/components/ResourceExecutionProgressList.vue` | 展示排队、生成、审核、Claim、返工、已发布、人工复核和失败；不要把 `generated` 误展示为可阅读。 |
| `frontend/src/views/GenerateView.vue` | 收到 `resource_published` 时使用 100–250ms 去抖刷新资源列表；收到非发布事件只更新 reducer，不额外请求资源正文。Run 终态后保留短轮询，覆盖 Job 状态与最后事件的提交竞争。 |
| `frontend/src/views/ResourcesView.vue` | 仅显示服务端已发布资源；实操指南同一 family 的文本/HTML 切换保持，HTML 未完成时文本不受影响。 |

前端进度语义：`实时`指“数据库事务提交后的资源状态实时投影”，不表示 LLM token 流式输出。模型调用中只能显示“生成中”；不得伪造百分比。

## 7. 实施步骤与验收

### 阶段 A：契约、迁移和原子事务

1. 增加 P0-14 migration、执行记录字段、状态转换校验和 CAS/lease 仓储接口。
2. 实现 `ResourceWorkflowPersistenceService` 的 SQL 与内存版本，并为每个转换定义稳定 operation/event ID。
3. 扩展 SSE DTO/allow-list 和 Job snapshot，但暂不改变图拓扑。

验收：并发重复提交、旧 Worker 回写、事件重复投递、事务中断均不会生成重复资源版本或错误发布状态。

### 阶段 B：生成 Worker 与即时展示

1. 引入 Dispatcher 和 `resource_worker` 动态 `Send` 派发；先仅迁移文本生成及 `queued → generating → generated`。
2. Worker 直接持久化每个资源版本和事件；Join 从数据库聚合。
3. 前端实时展示生成状态，但不展示草稿正文。

验收：人为让一个文本 Agent 延迟，其他资源已 `generated` 的状态先出现在 SSE/前端；断线后可由 snapshot + replay 精确恢复。

### 阶段 C：资源级审核、发布与返工

1. 抽取单资源 Reviewer 与 Claim 服务，迁移进 Worker 私有流水线。
2. 审核通过即原子发布；`revision_requested` 仅调度对应 `resource_spec_id` 的下一轮。
3. Batch Join/Finalize 只汇总资源当前态，停止对已发布资源做全局覆写。

验收：三资源中一项返工时，其余已批准资源立即可读，返工项产生正确版本谱系，SSE 事件和资源列表均不出现回退。

### 阶段 D：HTML Worker、恢复与上线

1. 将 HTML 派生改为独立表示 WorkItem，严格使用已发布 canonical 文本的来源版本/hash。
2. 加入 lease heartbeat、超时恢复、Run resume 与失效 Worker 扫描。
3. 完成端到端压测、真实模型受控冒烟和直接切换部署。

验收：HTML 失败不影响文本；模拟进程在生成后/审核前崩溃可从正确 stage 恢复；新 Run 无需开关全部使用 Worker 流程，历史 Run 仍可读取和回放。

## 8. 测试与质量门禁

必须新增或更新：

- Worker reducer：重复 `Send`、乱序返回、高 attempt 覆盖、同 attempt 冲突拒绝。
- 状态机：所有合法/非法转换、终态不可被旧 worker 覆盖、精确按 `resource_spec_id` 返工。
- 原子事务：资源版本、execution、审核/Claim 和 event 要么一起提交要么一起回滚。
- CAS/lease：双 worker 抢同一任务、心跳续租、过期回收、旧 lease owner 提交失败。
- 生成即时性：慢资源与快资源同时执行时，快资源的 `generated` 和 `resource_published` 必须先可查询、先到 SSE、先出现在前端。
- 断线恢复：snapshot、Last-Event-ID、重复事件、事件乱序回填均不能回退资源状态。
- 重启恢复：在 `generating`、`generated`、`reviewing`、`claim_checking`、HTML 派生中分别中断，验证恢复从正确 stage 继续且不重复版本。
- HTML：只从已发布 canonical 文本派生；源版本/hash 变化后旧 HTML 不得冒充新版本；HTML 失败不撤回文本。
- 授权与安全：草稿正文、未发布 HTML、Prompt、原始模型响应均不可通过 Worker 事件、详情或预览接口泄露。
- 压力测试：3、6、12 个 Spec 下验证并发上限、SSE 延迟、数据库事务耗时、事件量和 Run 收尾时延。

质量门禁：后端单元/集成/迁移/恢复测试全绿，前端 reducer 与组件测试全绿，前端生产构建通过，一次离线端到端演练和一次受控真实模型冒烟通过。不得用吞异常或把失败直接标为 `approved` 的方式让测试通过。

## 9. 风险与控制

| 风险 | 控制措施 |
| --- | --- |
| 并发 Worker 覆盖共享 state | Worker 只返回小型结果；资源事实以数据库为准；Join 使用显式 reducer。 |
| 资源已存但 SSE 丢失 | 将资源、execution、事件放进同一事务；SSE 可从 ledger 回放。 |
| SSE 事件先到但资源尚不可读 | 仅在事务提交后写事件；发布事件后前端再请求只读资源接口。 |
| 重试产生重复版本 | operation ID + execution CAS + 唯一 `(run_id, spec, representation, version)` 约束。 |
| 崩溃后任务永久卡住 | lease、heartbeat、恢复器、幂等再派发。 |
| 同类型多 Spec 返工错路由 | 强制 `target_resource_spec_id`；不按资源类型猜测。 |
| HTML 影响已发布文本 | HTML 为独立 representation；失败只影响 HTML execution。 |
| 事件数量增加 | payload 严格有界、前端按资源合并、发布刷新去抖、SSE 分页回放。 |

## 10. 最终效果

用户仍然只看到“诊断、检索、规划、资源生成、审核/Claim、完成”这条高层流程，但在资源子树中能看到真实的资源级状态：讲义正在审核、测试题已发布、实操指南正在派生互动 HTML。已发布资源可立即阅读；任一资源返工、人工复核或失败不会让其他资源消失或回退。

系统获得可恢复的资源级执行单元、可回放的即时事件、精确的版本谱系和可扩展的并发模型；未来即使换为队列或多实例 Worker，也不需要改变资源 API、SSE 语义或前端状态合并规则。
