# AI 互动课件整体更新计划

> 文档用途：交付给后续执行者连续实施。本文只保留已实现基础的简要说明和后续更新路线，不再重复历史任务卡与执行流水。
>
> 当前阶段：开发更新与本地真实可用。不要求生产级完整部署、GitHub Actions 证据、真实发布周期或多 Worker 扩容。
>
> 执行原则：用户当前请求优先于本文。执行者必须先阅读仓库根目录 AGENTS.md、README.md、git-workflow.md 和当前代码，保护已有 dirty worktree。

## 0. 已实现基础简述

当前仓库已经具备独立互动课件领域、来源快照与 ProvenanceGraph、AI-first planner/scene/reviewer 主链、版本化结构化契约、受控组件注册表、确定性 renderer/runtime、安全检查、HTML/ZIP 产物、SQLite Durable Worker、任务进度、课件播放器、学习事件、3 套主题、8 类基础组件及 flashcard、matching、ordering 3 类新增组件，并具备本地专项测试基础。

上一轮审计整改已经完成主要实现入口，这些基础不再逐项重做。后续直接解决当前最重要的质量收口项：

- AI-first 已成为默认配置，下一阶段需补齐可查询的 AI full-course、fallback 与 artifact 成功汇总，继续防止确定性兜底被计入 AI 成功。
- 资源选择已按产品要求限定在同一反馈批次并支持多选；下一阶段继续完善批次内的跨资源融合、覆盖解释和冲突处理，不放开跨批次来源。
- 后端已接受学习目标、预计时长、互动强度和视觉风格，但前端尚未把这些选项接入真实创建请求。
- 学习事件和 progress API 已存在，但 Viewer 尚未把服务端进度恢复到当前场景及受控组件状态。
- 11 类组件已经注册和渲染，但新增三类组件仍需逐组件严格 payload、完整反馈、恢复和来源约束。
- 当前“用户旅程”主要由长轮询测试和多个独立检查聚合而成，尚需一条真实状态驱动的完整本地旅程。
- 浏览器测试已有三主题和组件矩阵，仍需真实 200% 缩放、forced-colors 生效断言及 Viewer 组合门。

## 1. 产品目标

后续课件能力只围绕三个核心价值方向展开。

### 1.1 现有资源的整合学习

用户从自己已有的讲义、实操指南、测试题、案例分析和复习清单中选择一到多份资源，AI 不是简单拼接，而是：

- 所有来源必须属于同一反馈批次；跨反馈批次资源在前端不可选，后端准入再次拒绝；
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

- 打通本地真实用户链路：选择现有资源 → AI 生成 → 查看进度 → 自动打开 → 互动学习 → 保存进度 → 继续学习。
- 修正 AI-first 运行语义和 fallback 顺序。
- 提升多资源融合质量和来源可解释性。
- 扩展高价值互动模式并完善反馈与恢复。
- 提升视觉完整度、趣味性和响应式体验。
- 修复直接影响本地用户生成成功的 Worker 租约问题。
- 完成本地后端、前端、浏览器和用户旅程回归。

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
3. 选择器只展示当前反馈批次内该用户可用的已发布资源；支持按主题和资源类型筛选，不允许跨反馈批次混选。
4. 系统推荐一个资源组合，并说明讲义、实操、案例、测验和复习清单各自作用。
5. 用户可填写可选学习目标、期望时长和互动偏好；不要求理解模型或技术参数。
6. 创建任务前检查 AI 服务是否可用；不可用时给出明确说明，不静默生成模板课件。
7. 生成窗口持续展示“整合资源、设计课程、生成互动、教学审核、优化页面、完成”等用户可理解阶段。
8. 任务完成后自动刷新资源库、选中新课件并打开播放器。
9. 用户在课件中导航、答题、获得反馈、查看来源和完成进度。
10. 关闭后再次打开能够恢复到上次位置和互动状态。
11. 某场景失败时提供“优化这个场景”或“重新生成课件”，不要求用户理解 checkpoint、revision 或 release。
12. 如果最终使用紧急 fallback，用户看到简洁降级提示，系统内部保留完整原因。

## 5. 后续更新路线

执行顺序固定为 U0 → U1 → U2 → U3 → U4 → U5。完成一阶段后继续下一阶段，不等待用户逐项发送“继续”。

### U0：AI-first 与本地链路修正

目标：确保正常任务真正由 AI 生成，并修复阻塞本地真实使用的直接缺陷。

主要工作：

- 将正常生成模式改为 AI-first；兼容旧 COURSEWARE_AI_ENABLED 配置，但 false 不再代表一个正常确定性生成选项。
- AI 不可用时返回明确状态，或在 resilient 策略完整耗尽 AI 恢复链后进入紧急 fallback。
- planner、scene composer、quality reviewer 和 revision 成为正常任务的必经 AI 节点。
- 将确定性 scaffold 限制为来源、目标、槽位、组件和安全约束；AI 成功时 learner-visible 内容必须来自 AI 结构化输出。
- 分离 AI 成功、artifact 成功和 degraded fallback 指标。
- 修复 Executor heartbeat 与 lease 精度问题，确保一个本地 Worker 能稳定完成长任务。
- 移除新任务界面的人工“发布”语义；保持旧 API 兼容，但新任务自动变成可学习资源。

完成条件：

- fake provider 驱动完整公开 workflow；
- 正常 fixture AI path attempted=100%，AI full-course success=100%，deterministic fallback=0；
- AI 不可用不会被静默记成正常 AI 课件；
- 已复现租约反例通过；
- 用户创建任务后可以等待到终态并自动打开课件。

### U1：多资源整合学习

目标：让课件体现多份现有资源的整合价值。

主要工作：

- 资源选择器只读取当前反馈批次内该学习者可用的已发布资源，提供主题、类型、批次和版本信息；互动课件及其他反馈批次资源不可选。
- 保持 1 到 8 个来源限制；默认推荐同主题且角色互补的组合，避免无关资源混合。
- ResourceBundleSnapshot 保留每个资源的角色、版本、hash、知识点和来源块。
- 建立 SourceConceptGraph 或等价结构，记录概念、资源覆盖、重复、互补和冲突。
- AI planner 输出课程主线、目标、每个目标的来源集合、资源使用计划和未使用原因。
- Storyboard 每个场景绑定 objective、source resources、source blocks 和 interaction purpose。
- recap 不只是摘要单篇资源，而是帮助用户建立资源之间的联系。
- 前端在生成前显示“将如何整合”，生成后显示“本课件使用了哪些资源和目标”。

完成条件：

- lecture-only、lecture+practice、lecture+assessment、五类齐全、重复来源、冲突来源和同批次同主题组合均有测试；跨反馈批次混选有前后端拒绝测试；
- 所有被采用的资源至少绑定一个目标或场景；
- 未采用资源有机器原因；
- learner-visible 字段来源覆盖率 100%；
- 无来源内容和跨 snapshot 引用无法进入最终课件。

### U2：互动学习模式

目标：让互动与学习目标匹配，而不是随机插入控件。

保留并完善现有 8 类组件，同时优先增加受控高价值组件：

- flashcard：概念回忆与翻转；
- matching：术语、概念或案例配对；
- ordering：步骤和流程排序；
- branching_scenario：基于来源的轻量情境决策。

每个新增组件必须同时具备：

- 版本化 payload schema；
- ComponentCatalog 注册；
- renderer 和 runtime；
- keyboard、touch、a11y；
- source mapping；
- 即时反馈、解释和可选提示；
- learning event；
- progress/resume；
- 手机端和 reduced-motion；
- 浏览器测试和迁移适配。

AI 根据 objective、资源类型和 learner context 选择互动。缺少可验证答案时只使用探索或反思型互动，不生成可判分答案。

完成条件：

- 资源充分时，每份完整课件至少包含两种不同互动模式；
- 每个判分互动的答案和解释都有来源；
- 重复提交幂等；
- 刷新、离线后重开和跨场景导航不丢进度；
- 互动失败不破坏整个课件。

### U3：美观与趣味性

目标：让生成结果达到完整课件而非技术演示页面的观感。

主要工作：

- 为 editorial、midnight、paper 主题建立完整视觉 recipe：封面、章节页、内容页、互动页、反馈页和完成页。
- AI 只能选择注册的 theme/layout/motion/icon/decoration ID。
- 增加平台维护的图标和轻量装饰注册表；不允许模型输出任意远程 URL。
- 优化排版、留白、卡片层级、色彩、按钮、反馈、进度条、场景切换和完成动画。
- 同一课件保持主题一致，同时允许不同 scene kind 使用适合的注册布局。
- 趣味性使用即时反馈、进度、轻量成就提示和探索节奏，不使用干扰学习的随机动画。
- 320、768、1280 像素与 200% 内容缩放均无内容丢失。

完成条件：

- 三主题覆盖所有基础与新增组件；
- 主题切换不改变正文、答案和来源；
- 浏览器无 console error、横向内容丢失和不可见焦点；
- forced-colors、reduced-motion、键盘和触控通过；
- 截图矩阵能明显区分主题并保持统一品质。

### U4：真实用户体验闭环

目标：用户不需要理解内部工作流即可完成一次学习。

主要工作：

- 改造资源选择弹窗为信息清晰的资源组合选择器。
- 增加可选学习目标、期望学习时长、互动强度和视觉风格；默认值必须可直接使用。
- 生成前显示 AI 可用状态和预计处理阶段，不承诺无法保证的精确时间。
- useCoursewareJob 支持持续 SSE、断线轮询、页面关闭后恢复和长任务等待，不以固定 10 秒作为完成边界。
- 生成进度使用用户语言，隐藏 run、checkpoint、release 等内部术语。
- 完成后自动选中新课件并打开；不要求用户点击人工发布。
- Viewer 增加全屏、继续学习、重新开始、来源查看、进度和降级提示。
- 错误提示提供可执行动作：重试场景、重试整课、修改资源组合。
- Tutor 可读取当前课件、scene、objective 和来源上下文，但不改变课件状态。

完成条件：

- 从资源页到完成第一项互动的本地浏览器用户旅程通过；
- 生成中关闭弹窗或刷新页面后能恢复任务；
- 完成后无需手动刷新或查找新课件；
- 用户界面不出现必须理解的内部状态名；
- 手机端可完成同一旅程。

### U5：本地质量门与优化

目标：用本地证据证明三个核心方向和用户链路，而不是证明生产部署。

建立本地评测集，至少覆盖：

- 单讲义；
- 讲义+实操；
- 讲义+测试；
- 五类完整资源；
- 同批次同主题多资源；
- 跨反馈批次混选拒绝；
- 重复内容；
- 来源冲突；
- 缺少 assessment；
- AI schema repair；
- scene retry；
- AI revision；
- emergency fallback；
- 320px 与桌面用户旅程。

自动化评测使用 fake provider 驱动真实 AI workflow。全部本地门完成后，如果用户明确授权真实模型调用，再选取 lecture-only、lecture+practice+assessment、五类完整资源和可恢复 schema 错误等少量脱敏组合执行本地 live smoke，检查真实 AI 内容、互动、来源、时延、token 和 fallback。该 smoke 不涉及生产部署。

报告必须分离：

- 资源融合：来源覆盖、目标覆盖、跨资源关联、冲突处理、未使用原因；
- AI：主路径尝试、spec/scene/review/revision 成功、整课 AI 成功、fallback；
- 互动：模式数、完成率、答案来源、事件和恢复；
- 视觉：主题、布局、响应式、a11y、console、截图；
- UX：创建成功、终态耗时、自动打开、继续学习和错误恢复。

完成条件：

- 本地后端、课件专项、迁移、前端专项、浏览器和 build 全绿；
- 用户旅程测试通过；
- 三个核心方向均有可复验证据；
- 不以 CI、部署或真实发布周期是否完成阻塞本轮开发验收。

## 6. 关键技术边界

- 模型只输出结构化契约，不直接输出 HTML、CSS、JavaScript、URL 或 CSP。
- 组件只能来自版本化注册表；未知组件或版本硬拒绝。
- 每个 learner-visible 字段和判分答案必须来源可追溯。
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

真实模型测试只有用户另行明确授权并提供预期凭据时才运行。不得把 fake provider 结果描述为真实模型质量；未授权时使用 LIVE_MODEL_AUTHORIZATION_PENDING，而不是 passed 或 failed。

## 8. 执行与交付规则

1. 依次执行 U0-U5，不在每阶段结束后等待用户发送“继续”。
2. 每阶段先加失败反例，再修改真实实现，再跑专项与上层回归。
3. 不删除或放宽测试来制造成功。
4. 不覆盖用户已有修改，不提交临时报告、数据库、截图目录、构建产物或凭据。
5. 不提交、推送、合并或触发外部系统。
6. 每阶段完成后在本文末尾追加一条简短执行记录：阶段、文件、命令、结果、剩余本地缺口。
7. 已延期的 CI、部署和真实周期不写成失败，也不能写成已经完成。
8. 最终交付必须分别说明资源整合、互动、美观趣味和用户链路改善了什么，并给出准确测试计数。

## 9. 本地开发完成定义

只有同时满足以下条件，才可以写“当前课件链路本地真实可用”：

- [ ] 正常任务由 AI 完成 spec、scene、review 和必要 revision。
- [ ] emergency deterministic fallback 不是正常选项，且与 AI 成功率分开。
- [ ] 用户可从已有资源中选择合理组合并看到整合结果和来源。
- [ ] 完整课件至少具备符合资源条件的多种互动模式。
- [ ] 课件在桌面和手机上美观、清晰、可操作并能恢复进度。
- [ ] 用户从点击生成到打开课件并完成互动的本地旅程通过。
- [ ] 已知 Worker lease 问题修复。
- [ ] 后端全量、前端专项、浏览器和 build 无非预期回归。

达到这些条件只代表开发阶段本地真实可用，不代表生产部署完成。
