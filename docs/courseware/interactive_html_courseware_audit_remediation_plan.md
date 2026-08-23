# AI 互动课件下一步质量收口执行计划

> 文档用途：承接已完成的审计整改，指导后续执行者连续完成本地产品链路的质量收口。
>
> 执行方式：按 Q0 → Q5 连续实施；每阶段先建立失败反例，再修改真实实现，再运行专项与上层回归，不等待用户逐项发送“继续”。
>
> 核心产品约束：课件材料只允许来自同一反馈批次。跨反馈批次资源在前端不可选，后端准入必须再次拒绝。
>
> 本轮不自动执行：真实计费模型、GitHub Actions、外部部署、完整发布观察期、多 Worker 横向扩容。真实模型 smoke 只有用户另行明确授权且环境提供预期凭据时才运行。

## 1. 当前结论

上一轮 N0-N6 的主要实现已经进入当前工作区，下一步不得重复搭建同类骨架。当前可确认的基础包括：

- `COURSEWARE_AI_ENABLED=true`、`COURSEWARE_GENERATION_MODE=ai_first` 已成为默认配置；
- 正常 fake AI 任务已经覆盖 planner、scene composer 和 quality reviewer，紧急确定性 fallback 保留独立语义；
- 前后端均已实现同一反馈批次来源约束，后端还要求同一知识库且至少包含一份已发布讲义；
- 请求契约已支持 `learning_goal`、`expected_duration_minutes`、`interaction_intensity` 和 `visual_style_id`；
- 注册组件已从 8 类扩展到 11 类，包含 `flashcard`、`matching` 和 `ordering`；
- 已有三套主题、确定性 renderer/runtime、安全门、HTML/ZIP、学习事件、来源摘要、Viewer 工具栏、任务恢复入口和单 Durable Worker；
- 当前课件专项后端测试基线为 `214 passed, 16 warnings`，但这只证明所运行的确定性测试，不等于完整真实用户旅程、真实模型质量或生产就绪。

下一步重点不是继续增加表面功能，而是把已存在的能力连接成真实、可恢复、可度量的本地用户链路，并收紧互动组件和浏览器质量门。

## 2. 审计后的剩余缺口

### 2.1 P0：前端尚未使用完整请求契约

后端已经持久化四个学习偏好字段并传给 planner，但当前资源选择界面创建任务时仍只提交：

- `learner_id`；
- `source_resource_ids`；
- `publish_mode=automatic`。

因此用户还不能在真实界面设置学习目标、预计时长、互动强度和视觉风格，也无法证明这些偏好从 UI 到冻结请求再到 AI planner 的完整链路。

### 2.2 P0：学习进度“能记录”但尚未真正恢复到播放器

当前已有学习事件写入、离线队列和 `learning-progress` API，但 Viewer 没有在打开时读取服务端进度并把恢复状态注入 iframe。后端投影主要返回已查看/已完成场景和答题数，也不足以恢复当前场景及受控组件状态。

下一步必须形成：

    打开课件
    → 拉取当前 release 的安全进度投影
    → iframe ready
    → 注入恢复状态
    → runtime 恢复场景和允许的组件状态
    → 后续事件继续幂等写入

不得持久化自由文本答案、Prompt、模型响应或其他敏感输入。

### 2.3 P0：互动组件契约和行为仍偏浅

当前组件注册表已有 11 类，但仍存在以下收口项：

- 冻结 fixture 仍只列出旧 8 类组件，和真实注册表不一致；
- 通用 payload 校验只检查 `text` 与 `source_refs`，没有逐组件严格验证 `front/back`、`pairs`、`ordering_items/correct_order` 等字段；
- `matching` 当前主要记录点击尝试，尚未形成完整的配对状态、正确性判定、逐项反馈和恢复；
- `ordering`、`flashcard` 的状态恢复还没有接入服务端进度；
- 浏览器测试证明了组件可渲染，但不能替代每种互动完整教学行为和来源约束测试。

### 2.4 P0：所谓“用户旅程”仍是测试聚合，不是完整旅程

当前 `frontend/tests/coursewareUserJourney.test.mjs` 主要验证长轮询可以超过旧的 10 秒边界；`courseware_next_journey.py` 聚合 API、浏览器 smoke 和进程测试。它们有价值，但还没有在一条自动化旅程中证明：

    选择同一反馈批次资源
    → 填写学习偏好
    → 创建 AI-first 任务
    → 长任务进度与断线恢复
    → 自动选中新课件并打开
    → 完成互动
    → 刷新页面
    → 恢复到上次学习状态

下一步必须补真实状态驱动的前端旅程，不能只做字符串扫描或把多个独立测试汇总后命名为端到端。

### 2.5 P1：AI 成功指标未形成稳定汇总契约

当前 LLM trace 已记录 token、latency 和估算成本，工作流也记录 fallback 等事件，但尚未形成可直接查询和评测的稳定汇总，至少缺少：

- `ai_path_attempted`；
- `ai_spec_success`；
- `ai_scene_success_count/total`；
- `ai_review_success`；
- `ai_revision_attempted/success`；
- `schema_repair_count/success`；
- `primary/secondary route`；
- `ai_full_course_success`；
- `deterministic_fallback_count`；
- `artifact_success`；
- 总 token、latency 和 estimated cost。

`artifact_success` 与 `ai_full_course_success` 必须分开，不能因为最终生成了 HTML 就把紧急降级记成 AI 成功。

### 2.6 P1：浏览器质量门仍需从“有证据”升级为“证据可信”

当前浏览器脚本已经使用真实 renderer、三主题和 11 类组件，并检查控制台、键盘、reduced-motion、forced-colors 与截图。但下一步仍需：

- 真实断言 `forced-colors` 已生效；
- 使用浏览器缩放或等价 CSS 像素验证 200%，不能只把 viewport 改成 640×1280；
- 对关键布局建立可维护的基线或结构化断言，不能只生成 hash 而不比较；
- 在完成门中设置 `COURSEWARE_BROWSER_REQUIRED=1`，浏览器缺失不能静默当作通过；
- 覆盖 Viewer 与真实生成页面的组合，而不只覆盖孤立组件 artifact。

## 3. 不可改变的产品和架构边界

### 3.1 来源批次硬约束

- 一份课件的全部源资源必须属于同一反馈批次；
- 选择器只读取当前反馈批次内该学习者可用的已发布文本学习资源；
- 互动课件不能作为新课件的事实来源；
- 跨批次资源不可见、不可选、不可提交；伪造请求由后端以稳定错误码拒绝；
- 同一批次内仍需检查同一学习者、同一知识库、发布状态、版本和至少一份讲义；
- 批次约束必须进入前端纯函数测试、API 集成测试和本地用户旅程，不能只依赖 UI 隐藏。

### 3.2 模型与确定性平台边界

- AI 负责课程主线、场景、互动设计、反馈文本和教学修订；
- 模型只输出版本化结构化契约，不得输出 HTML、CSS、JavaScript、URL、CSP 或任意组件名；
- 确定性平台负责来源、schema、组件注册、渲染、安全、打包、状态、幂等和最终紧急兜底；
- 所有 learner-visible 事实、判分答案和解释都必须追溯到冻结来源块；
- AI 审核不可用时执行显式降级或隔离，不得静默当作通过；
- 新任务保持 automatic，不建设管理员审核或人工发布工作台。

### 3.3 兼容和范围边界

- 保持现有 HTTP 路径、认证依赖、表名、事件语义和五类学习文档行为兼容；
- 新增 API 字段优先向后兼容；确需增加 readiness 或 progress 字段时同步 `docs/api.md`；
- Web 不执行长任务；本地仍使用一个 Web 加一个 Durable Worker；
- 当前数据库仍是 SQLite，不引入 PostgreSQL、Redis、Celery 或多 Worker 扩容；
- 不重置、覆盖或顺手整理当前 dirty worktree 的无关修改。

## 4. Q0：冻结质量缺口反例

优先级：P0

先新增或扩展测试，固定以下失败反例：

1. UI 未提交四个学习偏好字段时，完整用户偏好链路测试失败；
2. 跨反馈批次资源即使伪造请求也被后端稳定拒绝；
3. Viewer 打开已有进度的课件时不能恢复当前场景，测试失败；
4. 旧 release 的进度不能污染新 release；
5. `flashcard`、`matching`、`ordering` 缺少必需字段时被严格拒绝；
6. `matching` 未全部正确配对时不能记为完成；
7. runtime 恢复状态不能包含原始答案文本或任意未知字段；
8. 完整用户旅程不能只通过长轮询单测冒充；
9. 200% 和 forced-colors 未真正生效时浏览器质量门失败；
10. AI 成功和 artifact 成功没有分离时评测失败。

优先扩展已有职责文件；只有职责明显不同才新增：

- `backend/tests/integration/courseware/test_ai_first_generation.py`；
- `backend/tests/integration/courseware/test_component_contract.py`；
- `backend/tests/integration/courseware/test_br4_learning_events.py`；
- `backend/tests/integration/courseware/test_api.py`；
- `backend/tests/e2e/courseware/`；
- `frontend/tests/coursewareSourcePolicy.test.mjs`；
- `frontend/tests/coursewareEvents.test.mjs`；
- `frontend/tests/coursewareUserJourney.test.mjs`；
- `frontend/tests/coursewareBrowser.test.mjs`。

Q0 完成门：测试准确表达产品要求，不能通过删除场景、放宽断言或把真实浏览器门改成可选来变绿。

## 5. Q1：完成用户生成输入与 AI readiness

优先级：P0

主要文件：

- `frontend/src/features/learning-documents/ResourcesView.vue`；
- `frontend/src/features/courseware/useCoursewareJob.js`；
- `frontend/src/features/courseware/api.js`；
- `backend/app/models/courseware/contracts.py`；
- `backend/app/api/courseware/courseware.py`；
- `backend/app/services/courseware/service.py`。

要求：

- 资源选择器继续只展示当前反馈批次资源，并显示批次标签、类型、主题、版本和知识点；
- 增加学习目标、预计时长、互动强度和视觉风格控件，提供可直接生成的默认值；
- 创建请求真实提交四个字段，并在任务详情中只读回显冻结值；
- 生成前提供轻量、无敏感信息的 AI/Worker readiness；不可用时给用户可操作提示，不静默生成普通模板课件；
- 若新增 readiness 路径或 DTO，同步 `docs/api.md`，不得改变现有创建任务响应；
- 关闭弹窗不取消任务，刷新资源页后继续恢复 active run；
- 所有新任务保持 `publish_mode=automatic`。

完成门：浏览器外的前端测试与 API 集成测试共同证明 UI 值、请求 payload、持久化 request options 和 planner 输入一致；跨批次混选继续被前后端双重拒绝。

## 6. Q2：打通可恢复学习进度

优先级：P0

主要文件：

- `backend/app/models/courseware/events.py`；
- `backend/app/services/courseware/events.py`；
- `backend/app/db/courseware/repository.py`；
- `backend/app/api/courseware/courseware.py`；
- `backend/app/core/courseware/runtime.py`；
- `frontend/src/features/courseware/CoursewareViewer.vue`；
- `frontend/src/features/courseware/offlineEvents.js`。

要求：

- 定义版本化的安全 progress DTO，至少包含 release ID、当前/已查看/已完成场景、课件完成状态、答题计数和允许恢复的组件状态；
- 服务端只接受 allow-list 字段和有界标量/枚举，不保存自由文本答案；
- progress 严格按 `resource_id + release_id` 投影，旧 release 不能推进新 release；
- Viewer 打开后先拉取进度，等待 iframe ready，再通过 nonce 校验的消息注入恢复状态；
- runtime 恢复当前场景、flashcard 复习状态、matching 配对状态和 ordering 顺序；
- 重新开始生成新的受控 reset 事件，不删除历史事件；
- 离线事件重放保持 occurrence/event 幂等，重复提交不重复计数。

完成门：关闭 Viewer、刷新页面、离线后重开三种路径均能恢复；新 release 从自己的进度开始；恶意或未知状态字段无法进入数据库或 runtime。

## 7. Q3：收紧三类新增互动组件

优先级：P0

主要文件：

- `backend/app/agents/resource_workflows/interactive_courseware/contracts.py`；
- `backend/app/core/courseware/components/catalog.py`；
- `backend/app/core/courseware/renderer.py`；
- `backend/app/core/courseware/runtime.py`；
- `backend/tests/fixtures/courseware/components/catalog_v1.json`；
- `backend/tests/integration/courseware/test_component_contract.py`；
- `frontend/tests/coursewareBrowser.test.mjs`。

要求：

- 冻结 fixture 与真实注册表统一为 11 类组件；组件总数不再写死成“八类”；
- 为每种组件建立版本化必需字段、长度、唯一性和来源规则；未知组件或 schema 版本硬拒绝；
- `flashcard` 的 front/back、记住/再复习状态均可操作、可追踪、可恢复；
- `matching` 具备完整左右项选择、配对、撤销、正确性判定、逐项反馈、提示和完成状态；
- `ordering` 支持键盘和触控上移/下移，正确顺序来自冻结来源，提交后显示逐项反馈；
- 每个判分答案和解释具备 source refs；没有可靠答案时改用不判分互动；
- 三类组件都覆盖 keyboard、touch、a11y、reduced-motion、三主题和 320px；
- 组件事件只记录受控状态，不记录原始自由文本。

完成门：三类组件从 AI 契约、catalog、renderer、runtime、事件、恢复到浏览器的资产完整；负例不能绕过 source/component hard gate。

## 8. Q4：建立稳定的 AI/Artifact 质量汇总

优先级：P1

主要文件：

- `backend/app/agents/resource_workflows/interactive_courseware/workflow.py`；
- `backend/app/db/courseware/repository.py`；
- `backend/app/models/courseware/contracts.py`；
- `backend/app/core/courseware/evaluation.py`；
- `backend/scripts/courseware_eval.py`；
- `backend/tests/fixtures/courseware/evals/`。

要求：

- 从稳定事件和持久化 trace 生成版本化 summary，不依赖日志文本解析；
- summary 至少覆盖第 2.5 节列出的 AI、fallback、artifact、token、latency 和成本字段；
- `ai_full_course_success=true` 只允许 planner、所有必需 AI scenes、AI review 和必要 revision 成功且没有确定性内容 fallback；
- `artifact_success=true` 只表示确定性渲染、安全、打包和发布成功；
- emergency fallback 或 published_with_warnings 必须在汇总中明确可见；
- 同一 run 重放不能重复累计 token、成本、fallback 或 scene 数；
- 评测按同一反馈批次准备 lecture-only、lecture+practice、lecture+assessment、五类齐全、重复、冲突和缺失 assessment fixture；另有跨反馈批次拒绝 fixture；
- 报告不得包含 Prompt、模型原始响应、API Key、Authorization 或真实敏感资源。

完成门：API/评测能直接回答“这份 HTML 是否由完整 AI 主链生成”，而不是从若干 warning 猜测。

## 9. Q5：完成真实本地用户旅程与浏览器质量门

优先级：P0

### 9.1 用户旅程

至少覆盖：

1. 打开当前反馈批次资源页；
2. 证明其他反馈批次资源不可选；
3. 选择同批次讲义及互补资源；
4. 填写学习目标、时长、互动强度和主题；
5. 创建 AI-first 任务；
6. 观察长于 10 秒的进度并模拟 SSE 中断后轮询恢复；
7. 完成后自动刷新、选中新课件并打开 Viewer；
8. 完成至少一项判分互动和一项探索互动；
9. 查看来源和降级状态；
10. 刷新页面并恢复当前场景与组件状态；
11. 在 320px 下完成同一核心旅程；
12. 跨批次伪造请求在 API 层被拒绝。

可使用 fake LLM transport 和临时 SQLite，但必须驱动真实公开 workflow、真实 API DTO 和真实前端状态逻辑。若前端完整 API 浏览器 E2E 先使用稳定 mock server，必须同时保留后端独立 API+Worker 旅程；最终报告要明确两者边界。

### 9.2 浏览器门

- 使用真实 renderer 生成三主题 × 11 组件矩阵；
- 验证 320×640、768×1024、1280×720 和真实 200% 缩放；
- 真实断言 forced-colors、reduced-motion、keyboard focus、touch target 和无横向内容丢失；
- 检查 console/page errors、CSP、iframe 消息 nonce 和未知消息拒绝；
- 覆盖 Viewer + artifact 的组合旅程；
- 完成验收时设置 `COURSEWARE_BROWSER_REQUIRED=1`，浏览器缺失视为未运行而非通过。

### 9.3 完成门

- 用户不需要人工发布、手动刷新或理解内部状态名；
- 生成任务和学习进度都能跨刷新恢复；
- 同一反馈批次来源边界在 UI、API 和 artifact 中一致；
- 正常 fixture AI full-course success 为 100%，deterministic fallback 为 0；
- emergency fallback fixture 明确标记 degraded/published_with_warnings 且不计入 AI 成功；
- 浏览器、前端 build、课件专项和后端全量无非预期回归。

## 10. 验证命令

从仓库根目录执行。先跑专项，再跑完整门：

```powershell
python -m pytest backend/tests/unit/agents/test_courseware_worker.py backend/tests/unit/core -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-q-unit

python -m pytest backend/tests/integration/courseware backend/tests/e2e/courseware backend/tests/migrations -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-q-flow

python backend/scripts/courseware_next_journey.py --output backend/.pytest-tmp/courseware-q-journey.json --basetemp backend/.pytest-tmp/courseware-q-journey-tests

python backend/scripts/courseware_eval.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --baseline backend/tests/fixtures/courseware/evals/baseline.json --output backend/.pytest-tmp/courseware-q-eval.json

npm --prefix frontend run test:courseware-source-policy
npm --prefix frontend run test:courseware-events
npm --prefix frontend run test:courseware-journey
$env:COURSEWARE_BROWSER_REQUIRED='1'
npm --prefix frontend run test:courseware-browser
Remove-Item Env:COURSEWARE_BROWSER_REQUIRED
npm --prefix frontend run test:workflow-events
npm --prefix frontend run test:tutor
npm --prefix frontend run build

python -m pytest backend/tests -q -p no:cacheprovider --basetemp=backend/.pytest-tmp/courseware-q-full

git diff --check
git status --short
```

临时报告、数据库、截图运行目录、构建产物和测试缓存不得提交。

真实模型 smoke 不属于上述自动命令。未获用户明确授权时记录 `LIVE_MODEL_AUTHORIZATION_PENDING`，不能写成 passed、failed 或 DONE。

## 11. 执行和交付规则

1. Q0-Q5 连续执行，不在每阶段结束后等待“继续”。
2. 每阶段先写反例，再改真实实现，再跑专项与上层回归。
3. 不删除、跳过或放宽测试来制造成功。
4. 不把跨反馈批次开放列为优化项；同一反馈批次是固定产品约束。
5. 不用 deterministic 内容替代正常 AI 主链来提高 artifact 成功率。
6. 新增组件字段必须一次完成契约、校验、渲染、runtime、事件、恢复和浏览器资产。
7. UI 必须覆盖 loading、empty、success、degraded、quarantined、failure 和恢复状态。
8. 任何公共 API/DTO 变化同步 `docs/api.md`；实现状态变化同步本计划和整体工作流文档。
9. 不修改五类学习文档工作流来迁就课件，不顺手重构无关目录。
10. 不提交、推送、合并、部署或触发外部系统。

## 12. 退出条件

以下全部满足后，才可以结束本轮：

- [ ] 四个学习偏好字段从 UI 到 planner 全链可证；
- [ ] 来源始终限定同一反馈批次，跨批次前后端均拒绝；
- [ ] Viewer 能从服务端恢复当前 release 的场景和受控组件状态；
- [ ] 11 类组件 fixture 与注册表一致；
- [ ] flashcard、matching、ordering 的严格契约和完整行为通过；
- [ ] AI full-course、fallback 和 artifact 成功拥有稳定汇总；
- [ ] 完整本地用户旅程不是长轮询单测或测试聚合；
- [ ] 真实 200%、forced-colors、三主题 × 11 组件和 Viewer 组合浏览器门通过；
- [ ] 课件专项、迁移、前端专项、浏览器、build 和后端全量通过；
- [ ] 实际命令、准确计数、跳过项和外部待验证事项已报告。

达到以上条件只代表互动课件链路在本地开发环境中可供真实用户验证，不代表真实模型质量、CI、外部部署、完整发布周期或生产级多 Worker 已完成。
