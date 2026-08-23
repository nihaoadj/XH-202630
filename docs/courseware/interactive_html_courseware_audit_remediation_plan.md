# AI 互动课件下一次完整性修正任务书（Luna 执行版）

> 执行者：Luna。
>
> 任务目标：在现有 Q0-Q5 基础上完成批次继承、当前 release 隔离、组件实例恢复、质量统计和本地证据聚合。本文件是执行任务书，不是背景说明。
>
> 执行方式：严格按 R0 → R1 → R2 → R3 → R4 → R5 连续完成。每个阶段都遵循“先失败测试、再实现、再专项回归”。除非遇到权限、缺失依赖或无法从代码确认的破坏性选择，否则不要停下来等待确认。
>
> 禁止自动执行：真实计费模型、GitHub Actions、外部部署、多 Worker 扩容、提交、推送、合并。未获真实模型授权时统一记录 `LIVE_MODEL_AUTHORIZATION_PENDING`。

## 0. 开始执行前

从仓库根目录 `D:\CODE\XH-202630\version1` 开始。

先完成以下只读检查：

```powershell
Get-Content AGENTS.md
Get-Content README.md
Get-Content git-workflow.md
Get-Content docs/courseware/interactive_html_courseware_workflow_plan.md
git status --short
```

执行约束：

1. 当前工作区存在大量用户修改。不得 reset、checkout、删除、覆盖或整理无关文件。
2. 先查真实实现、公开入口、调用者和测试，再修改；不要建立重复实现或只做转发文件。
3. 本任务只修改 `courseware`、资源库映射、必要迁移、相关测试和指定文档。
4. 如果本文路径因用户正在进行的目录迁移而变化，先定位同一职责的真实文件，再修改真实实现；不要恢复旧路径。
5. 不打印或提交凭据、SQLite 数据库、临时报告、截图目录、构建产物或测试缓存。
6. 一次只推进一个阶段。当前阶段专项测试通过后再进入下一阶段，最终再跑完整门。

## 1. 不得误解的产品语义

以下三条必须同时成立：

| 概念 | 正确规则 | 明确禁止 |
|---|---|---|
| 参考源批次 | 一次课件生成的全部 `source_resource_ids` 必须来自同一非空 `batch_id` | 跨批次混选 |
| 生成资源归属 | 生成的 `interactive_courseware` 必须继承参考源唯一 `batch_id`，并在资源库显示为该批次的一份资源 | 按课件自身 `run_id` 建立独立批次 |
| 参考源资格 | 互动课件虽然属于该批次，但仍不能作为下一份课件的事实参考源 | 递归引用互动课件 |

字段职责：

- `source_batch_id`：本次生成冻结的唯一参考源批次，保存在 job 上，冻结后不可变。
- `batch_id`：生成课件资源的批次归属，保存在 `courseware_resources` 上；值必须等于 job 的 `source_batch_id`。
- `source_resource_ids`：事实引用关系，不等同于资源归属。
- `released_release_id`：资源当前可学习 release；普通学习 API 只能读写该 release。

不要再使用“强制所有课件资源属于同一反馈批次”作为需求描述。准确表述是：

> 单次生成的参考资源来自同一反馈批次，生成课件继承该批次，但不自动获得课件参考源资格。

## 2. 已有基础与已确认缺口

已有基础，不要重做：

- UI 已提交并持久化四个学习偏好字段；
- 后端来源准入已拒绝跨批次参考资源；
- AI-first、受控 fallback、11 类组件、三主题和 renderer/runtime 已存在；
- progress DTO、学习事件脱敏、iframe 初始化恢复和 HTTP-origin 浏览器测试已有基础；
- `flashcard`、`matching`、`ordering` 已有契约、渲染和交互；
- 12-case 冻结评测、Q5 测试、质量汇总和发布候选聚合已存在。

已确认缺口：

1. `CoursewareResourceORM` 没有 `batch_id`，生成课件没有继承来源批次。
2. 资源库课件映射没有填充 `batch_id`，前端会回退到 `run_id` 分组。
3. 普通学习事件和 progress API 没有强制调用方 release 等于当前 `released_release_id`。
4. `component_state` 仍按组件类型合并，多个同类组件会互相覆盖。
5. Viewer 只在初次挂载加载 progress，切换资源/release 可能复用旧状态和 nonce。
6. `courseware_next_journey.py` 未运行 `test_q5_local_user_journey.py`。
7. 发布候选未强制 journey 证据，浏览器门仍接受旧 schema 和至少 8 个组件。
8. `latency_p95_ms` 当前使用最大值，fallback 可能重复计数，整课 AI 成功可能漏查必需 scene。

## 3. 执行顺序和阶段门

| 阶段 | 目标 | 依赖 | 进入下一阶段的条件 |
|---|---|---|---|
| R0 | 固定所有失败反例 | 无 | 新测试在旧实现上按预期失败，断言没有歧义 |
| R1 | 批次继承与同组展示 | R0 | 后端、迁移和前端来源策略专项通过 |
| R2 | 当前 release 与 Viewer 生命周期 | R1 | API、事件和 Viewer 专项通过 |
| R3 | 组件实例级恢复 | R2 | 多实例契约、投影、runtime 和浏览器专项通过 |
| R4 | 质量统计与证据聚合 | R3 | Q5、浏览器和发布候选缺一不可 |
| R5 | 完整回归与文档收口 | R4 | 本文件第 11 节退出清单全部满足 |

每个阶段完成后记录：

```text
阶段：
修改文件：
新增/修改测试：
执行命令：
结果与准确计数：
仍未验证：
```

## 4. R0：先固定失败反例

### R0.1 后端和迁移反例

优先修改现有职责测试：

- `backend/tests/integration/courseware/test_api.py`
- `backend/tests/integration/courseware/test_durable_repository.py`
- `backend/tests/integration/courseware/test_br4_learning_events.py`
- `backend/tests/e2e/courseware/test_q5_local_user_journey.py`
- `backend/tests/migrations/`
- `backend/tests/unit/core/test_courseware_events.py`
- `backend/tests/unit/core/test_courseware_quality_summary.py`
- `backend/tests/unit/core/test_courseware_release_candidate.py`

必须先覆盖：

- [x] 同批次参考源生成后，job `source_batch_id` 和资源 `batch_id` 都等于来源批次。
- [x] 重试、修订、candidate 和新 release 不改变这两个批次字段。
- [x] 唯一来源批次可证明的旧课件能被迁移回填。
- [x] 来源批次缺失、多值或非法的旧课件保持 `NULL`，迁移不得猜测。
- [x] 旧、未知或其他课件 release 的事件写入返回明确失败。
- [x] 混合 release 的事件批次整批失败，数据库没有部分写入。
- [x] 旧或未知 release 不能通过当前 progress API 得到 `200 + 空状态`。
- [x] 两个同类组件得到不同实例恢复状态。
- [x] 缺少必需 AI scene 时 `ai_full_course_success=false`。
- [x] 同一 fallback 同时出现在 event 和 warning 时只计一次。
- [x] P95 按指定算法计算，而不是无条件取最大值。
- [x] release candidate 缺少 journey 或当前浏览器证据时不是 `LOCAL_READY`。

### R0.2 前端反例

优先修改：

- `frontend/tests/coursewareSourcePolicy.test.mjs`
- `frontend/tests/coursewareEvents.test.mjs`
- `frontend/tests/coursewareUserJourney.test.mjs`
- `frontend/tests/coursewareBrowser.test.mjs`

必须先覆盖：

- [x] 生成课件按 `batch_id` 加入来源批次，而不是按 `run_id` 单独分组。
- [x] 互动课件仍不出现在下一次生成的参考源选择器中。
- [x] Viewer 从资源 A 切换到资源 B 后清空 A 的恢复状态和 nonce。
- [x] 两个 flashcard、matching、ordering 实例分别恢复自己的状态。
- [x] 浏览器报告明确记录 11×3 矩阵、真实 forced-colors、200% zoom、HTTP-origin iframe、nonce 校验和 artifact restore。

R0 只负责建立精确反例。不要为了让 R0 变绿而放宽旧实现。

## 5. R1：实现批次继承与资源库同组展示

### R1.1 数据契约

修改真实职责文件：

- `backend/app/models/courseware/contracts.py`
- `backend/app/db/courseware/models.py`
- `backend/app/db/courseware/repository.py`
- `backend/app/services/courseware/source.py`
- `backend/app/agents/resource_workflows/interactive_courseware/workflow.py`
- `backend/app/models/shared/resource_library.py`

按以下契约实现：

1. `courseware_generation_jobs` 新增可空数据库列 `source_batch_id`。
   - 新任务完成来源准入后必须写入非空值。
   - 旧行允许为空。
   - 一旦冻结，不允许重试或恢复改变。
2. `courseware_resources` 新增可空数据库列 `batch_id`。
   - 新生成资源必须写入 job 的 `source_batch_id`。
   - 发布前若为空或与 job 不一致，按硬门失败，不发布。
3. `CoursewareJobResponse/CoursewareJobDetail` 公开返回 `source_batch_id: str | None`。
4. `CoursewareResourceDetail` 和 `ResourceLibraryItem` 公开返回 `batch_id: str | None`。
5. Memory repository 与 SQL repository 的 create/read/list/update 映射必须一致。
6. artifact manifest 增加只读 `source_batch_id`，仅用于追踪，不改变 artifact hash 规则前必须先更新对应测试。

### R1.2 迁移

新增：

- `backend/app/db/migrations/p0_18_courseware_batch_integrity.py`

同步注册：

- `backend/app/db/migrations/__init__.py`
- `backend/app/db/shared/database.py`
- 相关 migration 测试

迁移要求：

1. 只新增 `source_batch_id`、`batch_id` 和必要索引；不删除或重命名现有表/列。
2. 迁移必须幂等，并写入 `schema_migrations`。
3. 旧 job/资源的回填来源为 `courseware_source_links.source_snapshot` 中的 `batch_id`。
4. 仅当同一课件全部来源快照都包含同一个非空合法值时回填。
5. 缺失、多值、非法 JSON 或无法建立唯一资源关系时保留 `NULL`。
6. 不要把 `run_id`、`resource_family_id` 或创建时间推测为 `batch_id`。
7. 测试必须覆盖空库、旧库、重复执行、唯一批次、多批次、缺失批次和非法快照。

### R1.3 资源库和前端

修改：

- `backend/app/api/resource_library/library.py` 或当前真实资源库聚合入口
- `frontend/src/features/learning-documents/ResourcesView.vue`
- `frontend/src/features/courseware/sourcePolicy.js`

要求：

- `list_library_items()` 显式映射课件 `batch_id`。
- 资源库对存在 `batch_id` 的课件只按该值分组，不回退到自身 `run_id`。
- 旧课件 `batch_id=NULL` 可保留兼容分组，但必须与新课件路径区分。
- 参考源选择器继续只接受五类已发布文本学习资源；`interactive_courseware` 即使同批次也必须排除。
- 前端隐藏跨批次混选，后端来源准入继续二次拒绝。

### R1 完成门

- [x] 新任务冻结唯一 `source_batch_id`。
- [x] 新课件继承同一 `batch_id`。
- [x] 资源库在来源反馈批次中显示新课件。
- [x] 新 release 和重试不改变批次。
- [x] 旧数据只做可证明回填。
- [x] 互动课件仍不可作为参考源。

R1 专项通过后再进入 R2。

## 6. R2：强制当前 release 并修复 Viewer 切换

### R2.1 API 边界

修改：

- `backend/app/api/courseware/courseware.py`
- `backend/app/services/courseware/events.py`
- `backend/app/services/courseware/service.py`
- `backend/app/db/courseware/repository.py`
- `backend/app/models/courseware/events.py`

统一错误语义：

- 资源不存在或无权访问：保留现有 404/认证语义。
- 资源尚无当前 release：HTTP 409，错误码 `COURSEWARE_RELEASE_UNAVAILABLE`。
- 调用方 release 不等于 `released_release_id`：HTTP 409，错误码 `COURSEWARE_RELEASE_NOT_CURRENT`。
- 同一批事件含不同 release，或任一条不等于当前 release：整批 HTTP 409，不写入任何事件。

实现要求：

1. 事件路径中的 `resource_id`、每条事件的 `resource_id` 和实际资源必须一致。
2. 每条事件的 `release_id` 必须等于资源当前 `released_release_id`。
3. progress 默认读取当前 release。
4. 如果为兼容保留 `release_id` query 参数，它也必须等于当前 release。
5. 普通 API 不得用 `200 + 空 projection` 表示旧 release 被拒绝。
6. 仓储可以保留内部历史 release 投影能力，但不得通过普通当前 API 写入或混用。
7. 保留 event ID/occurrence ID 幂等语义。

### R2.2 Viewer 生命周期

修改：

- `frontend/src/features/courseware/CoursewareViewer.vue`
- `frontend/src/features/courseware/api.js`
- `frontend/src/features/learning-documents/ResourcesView.vue`

要求：

1. 以 `resource_id + released_release_id` 作为 Viewer 生命周期键。
2. 资源或 release 变化时：
   - 清空旧 progress；
   - 生成新 nonce；
   - 重新请求当前 progress；
   - 忽略上一请求的迟到响应；
   - iframe 完成当前初始化前不得注入旧状态。
3. 可以在 Viewer 内 watch，也可以由父层使用稳定 `:key` 强制重建；只保留一种清晰实现。
4. iframe 消息继续校验 `event.source`、origin、nonce、resource ID 和 release ID。
5. 资源 A 的消息在切换到资源 B 后必须被忽略。

### R2 完成门

- [x] 旧/未知 release 写入和查询均明确返回 409。
- [x] 混合 release 批次没有部分写入。
- [x] 当前 release 的重复事件仍幂等。
- [x] A→B 切换不复用 A 的 progress、nonce 或迟到响应。

## 7. R3：组件实例级状态和严格契约

修改：

- `backend/app/agents/resource_workflows/interactive_courseware/contracts.py`
- `backend/app/core/courseware/components/catalog.py`
- `backend/app/core/courseware/renderer.py`
- `backend/app/core/courseware/runtime.py`
- `backend/app/models/courseware/events.py`
- `backend/app/db/courseware/repository.py`
- `frontend/src/features/courseware/offlineEvents.js`

### R3.1 实例标识

要求：

1. 每个互动 block 必须有稳定 `component_id`；优先复用合法稳定的 `block_id`。
2. 不得在浏览器恢复时随机生成 component ID。
3. renderer 输出 `data-component-id` 和当前 `scene_id`。
4. 学习事件必须携带 `scene_id`、`component_id` 和 `component_version`。
5. 缺少实例标识的新事件不得进入组件恢复投影。

### R3.2 progress 形状

新 progress 中的 `component_state` 统一使用嵌套实例键：

```json
{
  "component_state": {
    "<scene_id>": {
      "<component_id>": {
        "component_version": "1.0",
        "value": {}
      }
    }
  }
}
```

规则：

- progress 响应增加 `component_state_schema_version: "2.0"`；前端只按该版本解释嵌套实例状态。
- `value` 只保存 `sanitize_component_state()` 允许的有界结构。
- 同一实例按事件顺序使用最后一个合法状态。
- 不同 scene 或 component ID 永不互相覆盖。
- 未知 component ID、跨 scene 状态和版本不兼容状态忽略并记录安全原因。
- 旧版没有 `component_id` 的事件可保留完成度统计，但不得恢复到全部新组件。
- DTO 变化要同步 `docs/api.md` 和前端适配。

### R3.3 三类组件

- flashcard：每个实例独立保存卡片状态；只允许 `front/back/known/review` 等有界值。
- matching：左右值分别唯一；保存稳定 item ID 的配对集合，不保存自由文本。
- ordering：item ID 非空且唯一；保存结构化 ID 顺序，不使用分隔符拼接答案。
- 三类组件都必须验证重复提交、非法 ID、跨实例注入、刷新恢复和离线重放。

### R3 完成门

- [x] 同一 scene 两个同类组件独立恢复。
- [x] 不同 scene 的同类组件独立恢复。
- [x] 恶意或未知实例状态不能注入其他组件。
- [x] flashcard、matching、ordering 契约和浏览器行为专项通过。

## 8. R4：质量统计与发布候选证据

### R4.1 质量汇总

修改：

- `backend/app/core/courseware/quality_summary.py`
- `backend/app/core/courseware/evaluation.py`
- 对应调用者与测试

固定算法：

1. 调用方从冻结 spec/storyboard 传入全部必需 AI scene ID。
2. `ai_full_course_success=true` 仅当：
   - planner/spec 成功；
   - 每个必需 AI scene 都成功；
   - review 成功；
   - 需要 revision 时 revision 成功；
   - 没有 deterministic content fallback。
3. fallback 去重优先使用 `occurrence_id`；缺失时使用稳定的 candidate/stage/scene/fallback-version 组合键。
4. 同一 fallback 同时出现在 event 和 warning 时只计一次。
5. P95 使用 nearest-rank：

```text
sorted_values = ascending(latencies)
index = ceil(0.95 * sample_count) - 1
p95 = sorted_values[index]
```

6. 报告增加 `latency_sample_count` 和 `latency_percentile_method="nearest_rank"`。
7. 没有样本时 P50/P95 为 `null`，样本数为 0。
8. 重放同一 event ID 不增加 token、成本、场景、retry 或 fallback。
9. `artifact_success` 只表示渲染、安全、打包和发布成功，不代替 AI 成功。

### R4.2 journey 聚合

修改：

- `backend/scripts/courseware_next_journey.py`
- 对应脚本测试

要求：

- 把 `backend/tests/e2e/courseware/test_q5_local_user_journey.py` 作为单独必需 case。
- report `schema_version` 从 `1.0` 升为 `1.1`。
- 每个 case 使用稳定 `case_id`，Q5 的 ID 固定为 `q5_local_user_journey`。
- `status=LOCAL_READY` 必须要求全部必需 case 通过。
- 报告继续声明没有调用外部服务。

### R4.3 浏览器证据

修改：

- `frontend/tests/coursewareBrowser.test.mjs`
- 对应报告消费者测试

要求：

- 浏览器 report `schema_version` 从 `1.2` 升为 `1.3`。
- 组件矩阵必须恰好覆盖平台注册的 11 个组件 × 3 个主题，共 33 个唯一组合。
- 报告增加机器可验证字段：
  - `http_origin_iframe: true`
  - `nonce_guard: true`
  - `artifact_restore: true`
  - `forced_colors_active: true`
  - `zoom_200_active: true`
- 不能只依赖 summary 文本或 viewport 标签。
- console errors 必须为空；keyboard、touch、focus、reduced-motion、contrast 和 a11y 保持必需。

### R4.4 发布候选

修改：

- `backend/app/core/courseware/release_candidate.py`
- `backend/scripts/courseware_release_candidate.py`
- `backend/tests/unit/core/test_courseware_release_candidate.py`
- `docs/courseware/release_candidate_runbook.md`

契约：

1. CLI 新增必需参数 `--journey`。
2. builder 新增必需 `journey_summary_path`。
3. 只接受 journey schema `1.1` 且包含通过的 `q5_local_user_journey`。
4. 只接受 browser schema `1.3`、33 个唯一组件主题组合和五个新增布尔证据。
5. evaluator 仍要求 12 个唯一 case；baseline 只有在确定性输出真实变化时才能更新。
6. `local_ready` 必须同时要求：

```text
evaluator_ok
and artifacts_ok
and fault_matrix_ok
and journey_ok
and browser_ok
```

7. release candidate report schema 从 `1.0` 升为 `1.1`。
8. CI、真实模型、目标部署和完整观察周期继续列为 `EXTERNAL_PENDING`。

### R4 完成门

- [x] full-course、fallback、artifact、P50/P95、token 和成本统计语义准确且幂等。
- [x] journey 聚合真实运行 Q5。
- [x] 缺少 journey、旧 browser schema、非 33 矩阵或 artifact restore 失败均不能 `LOCAL_READY`。
- [x] 12-case baseline 仅因 renderer 稳定组件标识这一确定性输出变化逐 case 更新并复验。

## 9. R5：完整回归、文档与交付

必须同步：

- `docs/api.md`：`batch_id/source_batch_id`、409 错误码、progress 实例状态。
- `docs/architecture.md`：批次归属与事实引用、current release、组件实例边界。
- `docs/courseware/interactive_html_courseware_workflow_plan.md`：完成状态与剩余外部边界。
- `docs/courseware/release_candidate_runbook.md`：`--journey` 和新 schema。
- migration 注册与部署前兼容说明。

最终 Q5/浏览器旅程必须证明：

```text
打开一个反馈批次
→ 只选择该批次的文本参考资源
→ 创建 AI-first 课件
→ Worker 生成并自动发布
→ job.source_batch_id 等于来源 batch_id
→ courseware_resource.batch_id 等于 job.source_batch_id
→ 资源库把课件显示在同一反馈批次
→ 打开当前 release
→ 分别恢复多个同类组件
→ 切换同批次另一课件不串状态
→ 旧 release 写入和查询被 409 拒绝
```

## 10. 验证命令

从仓库根目录执行。先专项，最后全量。

```powershell
python -m pytest backend/tests/unit/core/test_courseware_events.py backend/tests/unit/core/test_courseware_quality_summary.py backend/tests/unit/core/test_courseware_release_candidate.py -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-r-unit

python -m pytest backend/tests/integration/courseware backend/tests/e2e/courseware backend/tests/migrations -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-r-flow

python backend/scripts/courseware_next_journey.py --output backend/.pytest-tmp/courseware-r-journey.json --basetemp backend/.pytest-tmp/courseware-r-journey-tests

python backend/scripts/courseware_eval.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --baseline backend/tests/fixtures/courseware/evals/baseline.json --output backend/.pytest-tmp/courseware-r-eval.json

python backend/scripts/courseware_ci_artifacts.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --output backend/.pytest-tmp/courseware-r-artifacts

python -m pytest backend/tests/e2e/courseware/test_c1_process_fault_matrix.py -q -p no:cacheprovider --junitxml=backend/.pytest-tmp/courseware-r-faults.xml --basetemp=backend/.pytest-tmp/courseware-r-fault-tests

python backend/scripts/courseware_fault_matrix.py --junit backend/.pytest-tmp/courseware-r-faults.xml --output backend/.pytest-tmp/courseware-r-fault-matrix.json

npm --prefix frontend run test:courseware-source-policy
npm --prefix frontend run test:courseware-events
npm --prefix frontend run test:courseware-journey
$env:COURSEWARE_BROWSER_REQUIRED='1'
npm --prefix frontend run test:courseware-browser
Remove-Item Env:COURSEWARE_BROWSER_REQUIRED
npm --prefix frontend run test:workflow-events
npm --prefix frontend run test:tutor
npm --prefix frontend run build

python backend/scripts/courseware_release_candidate.py --evaluator backend/.pytest-tmp/courseware-r-eval.json --artifacts backend/.pytest-tmp/courseware-r-artifacts/artifact-summary.json --fault-matrix backend/.pytest-tmp/courseware-r-fault-matrix.json --journey backend/.pytest-tmp/courseware-r-journey.json --browser frontend/tests/test-results/courseware-browser/summary.json --output backend/.pytest-tmp/courseware-r-release-candidate.json

python -m pytest backend/tests -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-r-full

git diff --check
git status --short
```

上面的 release candidate 命令以 R4 完成后的新 `--journey` 契约为准；R4 未完成前该命令按预期失败。不要退回缺少 journey 的旧命令。

### R0-R5 本次执行记录（2026-08-23）

- 阶段：R0-R5；修改：批次字段与 `p0_18`、当前 release API/Viewer、组件实例状态、质量汇总、Q5/journey、浏览器证据和发布候选聚合。
- 失败反例：新增批次继承、混合 release 原子拒绝、旧 release 409、实例状态隔离、质量统计和候选证据缺失反例；均先在旧实现上失败，再由真实实现修复。
- 专项结果：核心单元 `128 passed`；课件集成/端到端/迁移 `92 passed`；进程故障矩阵 `14 passed`；后端全量 `550 passed, 5 skipped`；前端来源策略、事件、旅程、workflow、Tutor、强制浏览器和 build 均通过；冻结评测 `12/12` 通过；Q5 journey schema `1.1` 和 browser schema `1.3` 已进入候选链。
- 候选结果：`courseware-r-release-candidate.json` 为 `LOCAL_READY`，外部待验证项为 `LIVE_MODEL_REQUIRED`、`CI_REQUIRED`、`DEPLOYMENT_REQUIRED`、`RELEASE_CYCLE_REQUIRED`。
- 仍未验证：未触发 CI、未部署外部环境、未观察完整真实发布周期；这些不写成已通过。DeepSeek 真实调用只使用已有的有界报告，不在本次 R5 回归中追加无界调用。

如果某项无法运行：

- 记录准确命令；
- 记录未运行原因；
- 不得写成 passed；
- 继续完成不依赖该项的安全工作。

## 11. 最终退出清单

以下全部勾选后才结束：

- [x] 参考源具有唯一且冻结的 `source_batch_id`。
- [x] 新课件持久化并公开返回相同 `batch_id`。
- [x] 资源库把新课件展示在来源反馈批次中。
- [x] 互动课件仍被参考源选择器排除。
- [x] p0_18 迁移幂等，旧数据只做可证明回填。
- [x] 无法证明批次的旧课件保持 NULL，迁移测试记录了多值、缺失和非法原因。
- [x] 旧、未知和混合 release 被明确 409 拒绝。
- [x] 多个同类组件按 `scene_id + component_id` 独立恢复。
- [x] progress 明确返回 `component_state_schema_version="2.0"`，前后端解释一致。
- [x] Viewer 切换资源/release 不沿用旧 progress、nonce 或迟到响应。
- [x] full-course、fallback 和 P95 统计准确且幂等。
- [x] journey schema 1.1 真实包含 Q5。
- [x] browser schema 1.3 证明 11×3、HTTP-origin 和 artifact restore。
- [x] release candidate schema 1.1 强制 journey 和当前 browser 证据。
- [x] 12-case、课件专项、迁移、前端专项、强制浏览器、build 和后端全量通过。
- [x] 文档区分“参考源同批次”“生成资源批次归属”“参考源资格”。

达到这些条件只表示本地开发环境的完整性修正完成，不表示真实模型质量、CI、外部部署、完整发布周期或生产级多 Worker 已完成。

## 12. Luna 最终回复格式

最终只报告可验证事实：

```text
完成阶段：R0-R5

核心结果：
- 批次继承：
- current release：
- 组件实例恢复：
- 质量统计：
- journey/browser/release candidate：

迁移结果：
- migration ID：
- 安全回填数量：
- 保持 NULL 数量及原因：

验证：
- <命令>：<准确通过/失败/跳过计数>

未验证：
- <真实模型/CI/部署等外部事项>

修改文件：
- <按领域分组列出>
```

不要只回复“已完成”或“测试通过”，也不要把本地 fake provider、浏览器或单 Worker 结果描述成生产就绪。
