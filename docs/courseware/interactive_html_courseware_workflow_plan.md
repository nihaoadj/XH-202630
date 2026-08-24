# AI 互动课件整体更新计划

> 文档用途：交付给后续执行者连续实施。本文只保留已实现基础的简要说明和后续更新路线，不再重复历史任务卡与执行流水。
>
> 当前阶段：开发更新与本地真实可用。不要求生产级完整部署、GitHub Actions 证据、真实发布周期或多 Worker 扩容。
>
> 执行原则：用户当前请求优先于本文。执行者必须先阅读仓库根目录 AGENTS.md、README.md、git-workflow.md 和当前代码，保护已有 dirty worktree。

## 0. 已实现基础简述

当前仓库已经具备独立互动课件领域、来源快照与 ProvenanceGraph、AI-first planner/scene/reviewer 主链、版本化结构化契约、受控组件注册表、确定性 renderer/runtime、安全检查、HTML/ZIP 产物、SQLite Durable Worker、任务进度、课件播放器、学习事件、3 套主题和 11 类组件。Q0-Q5 与 R0-R5 已打通四个学习偏好字段、批次继承、当前 release 隔离、组件实例级恢复、AI/artifact 质量汇总、真实状态驱动 Q5 旅程、HTTP-origin 浏览器验证、12-case 冻结评测和本地发布候选聚合。R0-R5 本地门已完成；真实模型、CI、外部部署和完整发布周期不在本地完成声明内。

这些基础不再重复搭建。R0-R5 已解决以下完整性缺口；当前后续路线转为 S0-S6 的成功率与教学质量提升：

- 生成的 `interactive_courseware` 已继承唯一 `batch_id`，资源库按来源反馈批次分组，互动课件仍排除在下一次参考源选择器之外；
- 公开学习事件与进度 API 已强制只接受资源的当前 release，并对混合 release 批次整批拒绝；
- flashcard、matching、ordering 的恢复状态按 `scene_id + component_id` 实例隔离；
- Viewer 切换资源或 release 时清理旧 progress、更新 nonce 并丢弃迟到响应；
- Q5、11×3 浏览器矩阵、HTTP-origin artifact 恢复和发布候选已形成缺一不可的本地证据链；
- `ai_full_course_success`、fallback 去重和 `latency_p95_ms` 已按固定算法汇总并报告样本量。

## 1. 产品目标

> 2026-08-24 产品边界更新：互动课件不再把多份资源整合为一门课程。每个已发布文本资源独立生成一个 HTML 互动版本；用户的多选操作只创建多个相互隔离的任务。下文所有“资源组合”“至少讲义加实操指南”“同批次合成”的表述均由此规则取代，待后续文档收口时删除旧路线细节。

后续课件能力只围绕三个核心价值方向展开。

### 1.1 现有资源的整合学习

用户从自己已有的讲义、实操指南、测试题、案例分析和复习清单中选择一到多份资源，AI 不是简单拼接，而是：

- 单次生成引用的全部参考源资源必须属于同一反馈批次；跨反馈批次资源在前端不可选，后端准入再次拒绝；
- 生成的互动课件继承参考源的唯一 `batch_id`，作为该反馈批次的一份资源展示和分组；
- 批次归属不等于参考资格：互动课件属于该批次，但仍不作为下一份课件的事实参考源，避免递归引用；
- 理解每份资源的角色、版本、知识点和来源块；
- 结合学习者水平和学习目标形成统一课程主线；
- 把概念、案例、步骤、练习、测验和复习组织成前后连贯的学习过程；
- 对重复内容合并，对互补内容建立关联，对冲突内容显式标记而不是擅自裁决；
- 每个可见事实、题目、反馈和关键互动都能追溯到冻结来源；
- 向用户说明本课件整合了哪些资源、覆盖了哪些目标、哪些资源未被使用以及原因。

资源整合的完成标准不是“传入了多个 resource ID”，而是用户能明显感受到这些资源被组织成了一门连贯课程。

### 1.2 可互动学习模式

课件不是把 Markdown 换成网页，而是让用户通过操作完成学习。互动必须服务于具体学习目标：

- 概念理解：翻卡、重点揭示、对比、示例判断；
- 程序性知识：步骤排序、流程演练、分阶段展开；
- 记忆巩固：快速回忆、配对、复习检查；
- 应用练习：单选、多选、情境决策和即时反馈；
- 反思总结：知识回顾、错题提示、完成度与下一步建议。

互动必须具备键盘、触控、移动端、无障碍、状态恢复和学习事件。没有可靠答案来源时不得凭空生成可判分题。

### 1.3 美观和趣味性

课件应当具有统一视觉叙事，而不是组件堆叠：

- 清晰的封面、章节节奏、视觉层级、进度感和完成反馈；
- 与主题和学习内容匹配的受控配色、版式、图标、装饰和动效；
- 互动状态有明确、友好且不过度的反馈；
- 桌面、平板和手机均可读可操作；
- 动效尊重 reduced-motion，颜色尊重对比度和 forced-colors；
- 趣味性来自节奏、探索、反馈和成就感，不依赖夸张动画或无关装饰。

AI 只能选择平台注册的主题、布局、动效和组件 ID，不得自由生成 HTML、CSS、JavaScript、URL 或任意组件。

## 2. AI-first 与平台边界

### 2.1 正常生成链

正常用户任务必须执行：

    冻结所选资源与学习者上下文
    → AI 规划课程目标和资源融合策略
    → AI 生成 storyboard
    → AI 生成各场景和互动
    → 来源与组件硬门
    → AI 教学质量审核
    → AI 定向修订
    → 平台确定性渲染与安全检查
    → 本地自动生成可学习课件
    → 用户直接打开学习

AI 负责教学内容、组织、互动设计、反馈文本和修订。平台确定性代码负责 schema、来源、组件、渲染、安全、打包、状态和幂等。

### 2.2 fallback 语义

确定性内容生成不是正常选项，也不能由普通用户选择。只有以下 AI 恢复链全部失败后才允许兜底：

    primary model
    → structured-output repair
    → 同阶段受控 retry
    → AI 定向修订
    → 已配置 secondary model
    → 最终 deterministic emergency fallback 或 quarantine

fallback 课件必须：

- 标记 degraded 或 published_with_warnings；
- 展示简明用户提示；
- 记录触发阶段和失败链；
- 通过全部来源、安全和组件硬门；
- 不计入 AI 生成成功率。

当前配置已将 `COURSEWARE_AI_ENABLED=true` 和 `COURSEWARE_GENERATION_MODE=ai_first` 设为默认值。后续仍必须通过测试和汇总指标保证 deterministic-v1 只出现在显式紧急降级或离线评测语义中，不能重新成为普通用户的正常生成路径。

### 2.3 成功率指标

本地 fake provider 套件中：

- 所有正常 fixture 的 AI 主路径尝试率必须为 100%；
- 所有正常 fixture 的 AI full-course success 必须为 100%；
- 正常 fixture 的 deterministic content fallback 必须为 0；
- 可恢复错误必须由 repair、retry、revision 或 secondary route 恢复；
- 最终 HTML 成功和 AI 生成成功必须分开统计。

以后获准运行真实模型验收时，初始目标为：

- 至少 30 个多样化脱敏资源组合；
- 整课 AI 完成率不低于 90%；
- 场景经受控恢复后的 AI 成功率不低于 95%；
- 最终确定性内容 fallback 率不高于 5%；
- 来源硬门错误发布率为 0。

真实模型验收不自动执行，但为了最终证明用户使用的确实是 AI 课件，所有无计费开发完成后应保留小规模本地 live smoke。只有用户明确授权并提供预期凭据时才能运行；未获授权时标记 LIVE_MODEL_AUTHORIZATION_PENDING，不能把 fake provider 结果描述为真实模型质量。

## 3. 当前阶段范围

### 3.1 本轮需要完成

- 完成“参考源同批次 → 生成课件继承批次 → 资源库同组展示”的数据与用户链路闭环。
- 新增向前兼容迁移；旧课件只有在来源快照能证明唯一批次时才回填，不能猜测。
- 在公开学习事件与 progress API 强制当前 release 边界，并修复 Viewer 切换资源/release 的恢复生命周期。
- 将互动状态从组件类型提升为稳定的 `scene_id + component_id` 实例作用域。
- 修正 AI full-course、fallback 去重、artifact 和 P95 汇总语义。
- 把 Q5、11×3 浏览器矩阵、HTTP-origin artifact 恢复和发布候选组成强制证据链。
- 完成本地后端、迁移、前端、浏览器、用户旅程和构建回归。

### 3.2 暂不处理

- GitHub Actions 实跑和 CI artifact 证明；
- 生产环境部署、扩缩容、生产监控和完整发布周期；
- 多 Durable Worker 横向扩容；
- PostgreSQL、Redis、Celery 或新队列基础设施；
- 管理员审核台、人工发布流程；
- SCORM/xAPI 完整标准兼容认证；
- 任意模型生成 HTML/CSS/JavaScript；
- 与三个核心价值无关的大规模架构迁移。

内部 candidate、release pointer 和 artifact 仍可作为本地原子可用机制保留，但用户界面不强调“发布”，而应呈现“生成完成，可以学习”。

## 4. 目标用户链路

1. 用户进入学习资源页，选择学习画像。
2. 用户点击“生成 AI 互动课件”。
3. 选择器只展示当前反馈批次内该用户可用的已发布文本参考资源；支持按主题和资源类型筛选，不允许跨反馈批次混选，也不把互动课件作为事实参考源。
4. 系统推荐一个资源组合，并说明讲义、实操、案例、测验和复习清单各自作用。
5. 用户可填写可选学习目标、期望时长和互动偏好；不要求理解模型或技术参数。
6. 创建任务前检查 AI 服务是否可用；不可用时给出明确说明，不静默生成模板课件。
7. 生成窗口持续展示“整合资源、设计课程、生成互动、教学审核、优化页面、完成”等用户可理解阶段。
8. 任务完成后，新课件继承参考源的 `batch_id`，资源库在同一反馈批次中显示、选中并打开它。
9. 用户在当前 release 中导航、答题、获得反馈、查看来源和完成进度。
10. 关闭后再次打开能够按组件实例恢复上次位置和互动状态；切换同批次另一课件时不串状态。
11. 旧、未知或其他课件 release 不能写入或冒充当前进度。
12. 某场景失败时提供“优化这个场景”或“重新生成课件”，不要求用户理解 checkpoint、revision 或 release。
13. 如果最终使用紧急 fallback，用户看到简洁降级提示，系统内部保留完整原因。

## 5. 当前并行更新路线

### 5.1 R0-R5 完成状态

R0-R5 已于 2026-08-23 完成本地实现和审计复跑，不再作为待执行路线：

| 阶段 | 状态 | 已完成结果 |
|---|---|---|
| R0 | 已完成 | 批次、release、实例恢复、统计和证据缺失反例已冻结 |
| R1 | 已完成 | 同批次参考源准入和生成课件 `batch_id` 继承已实现 |
| R2 | 已完成 | current release API 与 Viewer 生命周期隔离已实现 |
| R3 | 已完成 | progress 2.0 和组件实例级状态恢复已实现 |
| R4 | 已完成 | Q5、浏览器恢复和发布候选证据聚合已实现 |
| R5 | 已完成 | 专项、集成、迁移和本地文档已收口 |

这些“已完成”只表示现有本地完整性门通过，不代表真实模型质量、CI、外部部署或生产观察完成。

### 5.2 当前两个并行分支

当前更新拆分为两个文件域隔离的 Luna 任务：

| 分支 | 任务书 | 负责范围 | 禁止范围 |
|---|---|---|---|
| `feature/courseware-quality` | [课件质量提升任务书](./courseware_quality.md) | 课件 S0-S6、20-case、15×3、四个新组件、教学审核和真实模型质量门 | 画像、反馈、报告和文本资源重点策略 |
| `feature/learner-mastery` | [画像能力闭环任务书](../learner_mastery.md) | 问卷先验、能力状态、文本反馈、报告和下一批文本资源重点 | 所有互动课件代码、事件和文档 |

两个执行者并行工作，不互相等待，也不得修改对方业务目录。本轮明确不把互动课件学习结果接入画像掌握度；该边界避免两个分支通过共享事件契约产生阻塞。

### 5.3 课件后续 S0-S6

课件路线固定为：

```text
S0 真实质量基线
→ S1 主链成功率
→ S2 概念级丰富课程
→ S3 四类新互动
→ S4 教学审核与定向修订
→ S5 统一体验与质量汇总
→ S6 冻结评测、真实模型验收和候选聚合
```

字段、算法、预算、测试和最终报告以《课件质量提升任务书（Luna 执行版）》为唯一执行来源，本文不复制任务卡，避免计划分叉。

### 5.4 合并后共同门

两个分支各自通过不等于集成完成。合并后至少重新运行：

- 后端全量测试；
- 前端所有专项和 build；
- 课件 Q5/20-case/15×3 journey；
- learner mastery journey；
- migration 幂等和 SQLite restart；
- `git diff --check` 和工作区运行产物审计。

## 6. 关键技术边界

- 模型只输出结构化契约，不直接输出 HTML、CSS、JavaScript、URL 或 CSP。
- 组件只能来自版本化注册表；未知组件或版本硬拒绝。
- 每个 learner-visible 字段和判分答案必须来源可追溯。
- `batch_id` 表示资源归属，`source_resource_ids` 表示事实引用；单次生成的参考源必须同批次，生成课件继承该批次，但互动课件仍不获得下一次生成的参考源资格。
- 课件批次在来源冻结后不可变；旧数据无法从来源快照证明唯一批次时保留 `NULL`，不得猜测。
- 普通学习事件和 progress API 只服务资源当前 release；历史投影不得污染当前状态。
- 互动状态以稳定的 `scene_id + component_id` 为实例边界。
- AI prompt、模型调用和路由留在 interactive_courseware Agent 工作流。
- CoursewareService 只协调任务、仓储和公开用例。
- core/courseware 保持确定性，不访问数据库或模型。
- Web 不执行长任务；本地仍使用一个 Web 加一个 Durable Worker。
- 新字段优先向后兼容；旧 HTTP 路径、认证和五类学习文档行为不回归。
- 用户界面不提供 deterministic generation、人工审核或人工发布选项。

## 7. 本地验证命令

执行者按改动范围先跑专项，再跑本地完整门：

    python -m pytest backend/tests/unit/agents/test_courseware_worker.py backend/tests/unit/core -q -p no:cacheprovider

    python -m pytest backend/tests/integration/courseware backend/tests/e2e/courseware backend/tests/migrations -q -p no:cacheprovider

    python backend/scripts/courseware_next_journey.py --output backend/.pytest-tmp/courseware-next-journey.json --basetemp backend/.pytest-tmp/courseware-next-journey-tests

    python backend/scripts/courseware_live_model_eval.py --fake --output backend/.pytest-tmp/courseware-ai-fake.json

    python backend/scripts/courseware_eval.py --manifest backend/tests/fixtures/courseware/evals/manifest.json --baseline backend/tests/fixtures/courseware/evals/baseline.json --output backend/.pytest-tmp/courseware-eval.json

    npm --prefix frontend run test:courseware-source-policy
    npm --prefix frontend run test:courseware-events
    npm --prefix frontend run test:courseware-journey
    $env:COURSEWARE_BROWSER_REQUIRED='1'
    npm --prefix frontend run test:courseware-browser
    Remove-Item Env:COURSEWARE_BROWSER_REQUIRED
    npm --prefix frontend run test:workflow-events
    npm --prefix frontend run test:tutor
    npm --prefix frontend run build

    python -m pytest backend/tests -q -p no:cacheprovider

    git diff --check
    git status --short

当前《课件质量提升任务书》已经授权其中定义的 10 组合有界真实模型验收，但仍须先通过全部无计费门并确认运行环境存在预期凭据。缺少凭据时使用 `LIVE_MODEL_CREDENTIALS_PENDING`；不得把 fake provider 结果描述为真实模型质量。

## 8. 执行与交付规则

1. 课件执行者依次执行 S0-S6，不在每阶段结束后等待用户发送“继续”；画像执行者按独立任务书执行 L0-L6。
2. 每阶段先加失败反例，再修改真实实现，再跑专项与上层回归。
3. 不删除或放宽测试来制造成功。
4. 不把“参考源来自同一反馈批次”简化或扩大为“所有课件资源必须属于同一反馈批次”。
5. 不把“生成课件继承来源批次”实现为“互动课件可递归作为下一份课件的事实来源”。
6. 不覆盖用户已有修改，不提交临时报告、数据库、截图目录、构建产物或凭据。
7. 不提交、推送、合并或触发外部系统。
8. 每阶段完成后在各自任务书末尾追加一条简短执行记录：阶段、文件、命令、结果、剩余本地缺口。
9. 已延期的 CI、部署和真实周期不写成失败，也不能写成已经完成。
10. 课件最终交付必须说明主链成功率、课程丰富度、互动多样性、教学审核和质量证据分别改善了什么，并给出准确测试计数。

## 9. 本地开发完成定义

只有同时满足以下条件，才可以写“当前课件链路本地真实可用”：

- [ ] 正常任务由 AI 完成 spec、scene、review 和必要 revision。
- [ ] emergency deterministic fallback 不是正常选项，且与 AI 成功率分开。
- [ ] 单次生成的全部参考源属于唯一 `source_batch_id`。
- [ ] 生成课件持久化并公开返回相同 `batch_id`，资源库在来源反馈批次内展示它。
- [ ] 互动课件属于反馈批次但仍被课件参考源选择器排除。
- [ ] 旧数据只在来源快照能证明唯一批次时安全回填。
- [ ] 用户可从同一反馈批次的文本资源中选择合理组合并看到整合结果和来源。
- [ ] 完整课件至少具备符合资源条件的多种互动模式。
- [ ] 普通学习 API 明确拒绝旧、未知或其他课件 release。
- [ ] 多个同类组件按实例独立保存和恢复，Viewer 切换课件不串用状态。
- [ ] AI full-course、fallback、artifact 和 P95 汇总语义准确且幂等。
- [ ] 课件在桌面和手机上美观、清晰、可操作并能恢复当前 release 的进度。
- [ ] Q5 用户旅程、15×3 浏览器矩阵和 HTTP-origin artifact 恢复进入发布候选强制证据链。
- [ ] 已知 Worker lease 问题修复。
- [ ] 20-case evaluator 2.0、课件专项、迁移、前端专项、强制浏览器、build 和后端全量无非预期回归。
- [ ] release candidate 1.2 同时达到 `LOCAL_READY + LOCAL_QUALITY_READY`。

达到这些条件只代表开发阶段本地真实可用，不代表生产部署完成。
