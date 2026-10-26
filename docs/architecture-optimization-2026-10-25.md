# 代码结构与工程架构优化记录

日期：2026-10-25。范围：保持现有功能与合同的结构重构。当前状态：实现与本地验收完成，初轮失败及修复证据保留。

## 结论与现有架构

项目已有可延续的分层和领域归属。本轮保留 FastAPI / Pydantic / SQLAlchemy / LangGraph 与 Vue 3 / Pinia / Vite，处理实际职责交叉、API 归属不一致及边界检查缺口。没有引入新业务层、依赖、数据库迁移或部署方式，也没有按固定行数拆分文件。

审查覆盖后端363个 Python 实现文件的目录和静态导入、前端87个 JS/Vue 文件的领域/请求依赖、组合根、工作流/平台边界、测试/构建入口及现有文档；数量为改前基线。对高复杂度候选进一步核对源码和直接测试。工作区原有未提交修改作为基线保留，本轮不提交、推送或合并。

```text
backend/app/
  api/<domain>/              HTTP、授权、错误映射
  services/<domain>/         用例、仓储读取、事务与领域门面
    learners/ability_projection.py   已读快照的确定性计算
  agents/learning_agents/    反馈分析、短答评分、Tutor 等学习 Agent
  agents/resource_workflows/ 文本与课件工作流
  core/                     确定性平台、运行时、安全、LLM/检索适配
  db/<domain>/              持久化与迁移
  models/<domain>/          跨层契约
  main.py / containers.py   应用与依赖组合根
frontend/src/
  features/<domain>/        页面、同域 API、交互逻辑与投影
  api/client.js             共享 Axios 实例
  api/index.js              旧导出的兼容入口
  stores/                   认证和当前学习上下文
  contracts/                后端生成契约和运行时校验
  components/、ui/、styles/  公共展示与样式
```

## 成熟工程实践的实际应用

| 参考来源 | 采用方式 | 本项目的取舍 |
|---|---|---|
| [FastAPI Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[官方 full-stack-fastapi-template 路由组合](https://raw.githubusercontent.com/fastapi/full-stack-fastapi-template/master/backend/app/api/main.py) | 按职责拆模块，由组合根连接路由与依赖；HTTP 层经应用门面完成用例 | 保留现有 APIRouter、Service、容器，不复制模板的数据库或前端技术选型 |
| [Vue Composables：按逻辑关注点组织](https://vuejs.org/guide/reusability/composables.html#extracting-composables-for-code-organization) | 页面继续使用已有同域 composable；端点按领域归属；确定性计算采用普通函数 | 不为大组件的行数增加全局状态或新的生命周期控制器，本轮模板/样式保持 |
| [SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) | 计算只接收已读模型，不接收 Session；事务与读写继续由原用例负责 | 不调整现有连接、Session、Worker、DI provider 或事务提交顺序 |
| [ESLint no-restricted-imports](https://eslint.org/docs/latest/rules/no-restricted-imports) | 复用已有 lint 工具阻止内部静态导入集中 API 入口，用真实正负例验证 | 不新增依赖，不把静态检查描述成对动态执行和任意依赖的完整证明 |
| [PEP 8：命名、接口与项目内一致性](https://peps.python.org/pep-0008/) | Python 新模块/函数使用具名 snake_case，保留既有公开服务方法和导入合同，模块说明交代职责 | 不因风格指南破坏兼容，不做整仓格式重写 |
| [Google Engineering Practices：设计、复杂度、测试和注释](https://google.github.io/eng-practices/review/reviewer/looking-for.html) | 按真实职责拆分，检查边界与调用关系，用有效正负例及集成验证行为；注释说明归属/取舍 | 不为猜测的未来需求添加通用框架，不用文件行数代替复杂度判断 |

这些实践用于明确归属和验证边界，不构成增加分层的理由。

## 六方面审查及本轮处理

| 关注点 | 当前证据与判断 | 本轮处理 |
|---|---|---|
| 目录与分层 | 后端已按 api/services/agents/core/db/models 分层，前端已有 features；集中 API 仍实现九个业务对象 | 保留整体目录，将端点实现归到六个实际功能域 |
| 解耦与职责 | 掌握度 Service 混合读取和投影；反馈 Service 持有两类 Prompt；课件 review 路由直接读取 service.repo | 提取同域纯计算、两个学习 Agent；场景查询经过 Service 门面 |
| 大文件与复杂度 | MasteryService 的分阶编排、证据写入和排序投影混杂；其他大文件有复杂状态机/契约历史 | 物理行（含空行）：mastery.py 1200→1058，feedback.py 1718→1648；减少职责混杂，保留用例和状态机所有权 |
| 复用与抽象 | 旧 API 集中入口与领域入口两种归属并存；已有 generation/reports 等纯投影可沿用 | 每个端点对象只有一份实现，旧入口转出同一对象；不新增泛型仓储、万能 Service 或工具集合 |
| 工程规范 | 已有统一 runner、锁文件、Ruff/ESLint、局部 checkJs；models/db 和前端入口缺少回归边界约束 | 扩大现有 AST 门禁，补 ESLint 静态导入规则与负例；新增模块使用具名导出、显式依赖和既有类型契约 |
| 架构成熟度 | 当前结构适合继续按领域扩展，类型覆盖、部分跨域用例和 ORM 聚合仍有演进空间 | 本轮将约定落实为代码归属和可执行检查，保留渐进演进路径；不声称完成所有长期治理 |

静态图中的两组相互引用为 `generation/jobs ↔ continuation` 和 `learning_documents/resources ↔ publication`，反向边均位于 TYPE_CHECKING。它们不是运行时循环故障的证据，本轮未为消除类型引用另造接口层。

## 实际改动与兼容约束

`services/learners/ability_projection.py` 持有客观趋势、能力节点、课程计数、全图弱项排序和 focus 选择。`MasteryService` 的公开方法、仓储调用顺序、输入校验、证据写入、时钟和快照 hash 保留。排序继续区分零分与未测，保留 group、下游数、时间与 node ID tie-break；兼容旧节点形状、naive/UTC 时间、显式去重和 auto 覆盖选择。

两个反馈 Agent 分别持有短答评分和学习小结的输入投影、消息及结构化调用。Service 保留既有方法入口、缺少 gateway 时的行为、错误码/状态码、fallback、analysis_status、上限截断、Decimal HALF_UP 和双评编排。没有修改 Prompt 文本、JSON 分隔符、schema、context、温度或调用次数。

`CoursewareService.get_scene_review` 先检查任务场景成员关系，再读取 spec/scene/revisions 并投影原字段；API 保留原授权、404 及响应。全局/当前场景 review 的过滤及 revision.reason 均保持。顶层内部存储字段不加入响应；不改变课件生成、发布、事件或安全策略。

前端九个 API 对象归到 auth、learners、onboarding、learning-documents、feedback、reports。全部内部消费者改为直接导入所属域，底层共享一个 Axios 实例；中央入口保留全部15个旧导出的同对象兼容转出。URL、编码差异、默认参数、Cookie、超时、Axios response 和错误传播保持。旧 reportApi 仍不附加窗口/ETag，learningReportApi 的原有校验保持。12个涉及的 Vue 文件，其 script 之外部分与改前字节一致。

AST 门禁新增 models/db 保护，API 禁止直接导入 db、SQLAlchemy 和 LLM。既有动态导入解析和两项精确兼容例外保留。前端 ESLint 针对集中入口的静态 import/export 失败，允许共享 client 和同/跨域 API。它不解析动态 import()；本轮另核对运行时动态导入仍为路由页面懒加载。AST 门禁也不证明属性访问、间接 SQL 或事务所有权。

## 验证与证据

命令均从仓库根运行。当前使用已存在的独立锁环境 `output/test-runs/t20-clean-py311-20261023/venv/Scripts/python.exe`（Python 3.11.15）与 Node 24.14.0，没有升级/替换实际服务环境。统一 runner 固定 live 关闭，浏览器必须运行。

| 检查 | 已取得结果与证据 |
|---|---|
| 改前基线 | 5/5套件 PASS；后端1069 passed /9 live skipped；[summary](../output/test-runs/t25-baseline-20261025/summary.json) |
| 重构后后端与工程 | 后端1100 passed /9 live skipped，0失败/错误；架构、契约漂移、Ruff、ESLint、checkJs、依赖/锁、比赛金标、13个前端unit文件及构建均PASS；[后端日志](../output/test-runs/t25-acceptance-20261025/backend-full.log) |
| 模型/投影/OpenAPI 比对 | 两类 Prompt 消息字节、schema、稳定 context/options、合成能力投影/focus、完整72条 OpenAPI 路径与143个 schema一致；[结果](../output/test-runs/t25-planning-20261025/compatibility-result.json) |
| 后端专项 | 首轮73 passed/1测试准备失败，补齐 fixture 必填 learning_goal 后该文件5/5 PASS；原失败证据保留，全部将在全量中再次执行 |
| 前端 API 与 lint/typecheck | 15同一性导出、38请求契约、错误传播、6拒绝/3允许导入 PASS；[专项日志](../output/test-runs/t25-focused-20261025/frontend-api.log)、[静态检查](../output/test-runs/t25-frontend-focused-20261025/summary.json) |
| 前端导入图 | 改前87、改后92个 JS/Vue 模块均无循环，改后10处运行时动态导入均为路由页面；[静态图](../output/test-runs/t25-planning-20261025/frontend-import-graph.json)，不含样式/资产或任意动态表达式的分析 |
| 消费者实现比对 | 18个涉及的前端消费者/客户端模块，除 import 外的语句一致，Vue 非 script 部分字节一致；[结果](../output/test-runs/t25-planning-20261025/consumer-equivalence.json) |
| 课件冻结 | 20/20通过；精确状态、硬门及 fallback 期望匹配，13份冻结 renderer 产物 hash 与基线一致；实际 workflow 的状态及产物存在性匹配。两种产物 hash 不作相等声明；[冻结报告](../output/test-runs/t25-acceptance-20261025/courseware.json) |
| 初轮 acceptance | 12个工程套件 PASS，browser14/15 PASS；唯一动效中间态观测超时，原 [summary](../output/test-runs/t25-acceptance-20261025/summary.json) 保留 FAIL |
| 动效对照与观测修复 | 改前完整原测试也 FAIL；修复后完整九场景 PASS，7跳原生过渡、120/260ms原时长、中间态与shell/残留断言通过，错误/外网/业务写入均0；[专项结果](../output/test-runs/t25-motion-fixed-20261025/summary.json) |
| 最终全部浏览器 | 同一生产构建完整15/15专项PASS、exit0；完整矩阵内动效亦PASS、7跳、0异常/外网/业务写入；[runner汇总](../output/test-runs/t25-browser-final-20261025/summary.json)、[逐项结果](../output/test-runs/t25-browser-final-20261025/frontend-browser.json) |
| 验收证据汇总 | 13/13验收成员具有exit0证据；初轮12个未受影响的工程套件与最新完整browser合并，原FAIL不改写；[最终汇总](../output/test-runs/t25-final-20261025/summary.json) |
| 范围与输入 | 1003个原文件保留，34个原文件修改、13个新增；987份文件hash在末轮期间保持，diff检查通过；[范围清单](../output/test-runs/t25-final-20261025/scope-check.json)、[仅本轮增量](../output/test-runs/t25-final-20261025/task-changes.patch) |

兼容探针仅使用合成数据；忽略每次新生成的 context.call_id、能力响应 generated_at 和课程 updated_at，完整 OpenAPI 另行严格比对。真实模型和生产数据不参与。提取初期的残留 self 引用由兼容探针发现并修正；首次比较也识别出随机 UUID/时钟字段，明确限定后再比较稳定合同。未将过程失败当作通过，也没有降低业务验收门槛。

首次完整命令及失败后受影响范围的最终命令：

```powershell
python scripts/run_tests.py --profile acceptance --output output/test-runs/t25-acceptance-20261025
python scripts/run_tests.py --suite frontend-browser --output output/test-runs/t25-browser-final-20261025
```

acceptance 包含后端全量、API/工作流/Claim/发布/迁移/e2e、课件冻结评测、比赛金标、导入/契约/依赖检查、前端全部单元、生产构建和十五个浏览器专项。具体实绩以本轮报告为准。

初轮失败及同构建复现定位到进入 `/generate` 的短动画观测窗口。隔离的改前构建和改后构建诊断均记录原生 ready/finished 正常，但主线程约137–145ms的采样间隔跨过120ms离场；改前完整原测试也同类超时。原失败、改前基线及诊断证据分别保存在 `t25-motion-initial-20261025`、`t25-before-browser-20261025` 和 `t25-motion-diagnostic-20261025`，没有覆盖为通过。

该验收修订另经 Luna 计划门禁，只修改既有动效测试夹具。依据 [ViewTransition.ready](https://developer.mozilla.org/en-US/docs/Web/API/ViewTransition/ready) 与 [Web Animations 暂停能力](https://developer.mozilla.org/en-US/docs/Web/API/Animation/pause)，在真实伪元素已创建后获取两条平台 CSS Animation，采样期间暂停并定位到共同60ms，finally恢复，再检查真实结束与无残留。原opacity阈值、七跳路由、shell和其他八场景保留，并增加原生伪元素身份/原120与260ms时长检查；没有修改CSS、业务代码或超时，不添加重试。这是确定性观测修复，不代表改善或证明了帧率性能。

本节测试报告和快照是本地验收产物，按现有规则不随 Git 分发。课件事件/重复写入/终态流的回归来自后端 integration/e2e（包括 `test_q5_local_user_journey.py`），不能把冻结 renderer 的 hash 当成真实模型、实际 workflow 字节或生产部署的完整证明。

## 后续候选与证据边界

- `db/shared/models.py` 仍聚合多个领域。拆分需单独核对同一 Base/metadata、模型注册顺序、旧导入及全部迁移，不因1225行直接迁移。
- `FeedbackService` 仍包含多种正式/兼容反馈用例；`MasteryService` 仍编排分阶与证据。后续可沿实际业务边界拆分，保留本轮已独立的投影和 Agent。
- 课件学习事件路由仍编排“写入→自评汇总→掌握度更新”，部分 API 仍访问 Service 私有知识库校验或仓储属性。本轮没有改变这些跨域写入和注入时机，不能将新增导入门禁等同于全部用例已解耦。
- 严格 checkJs 仍覆盖选定 JS 边界，未覆盖全部 Vue 页面。未知动态表达式、运行时属性访问和所有跨域依赖不在静态门禁的证明范围。

本地确定性、冻结评测和浏览器 fixture 证据分列。真实模型、远端 CI/Python 3.12、目标部署、Worker 生产故障注入、容量和 SCORM/xAPI 完整兼容均未新增证据。原有运行环境/依赖告警不因本次结构重构自动消除。

本次构建仍报告大于500 kB的 chunk；没有进行加载性能前后测量或调整分包策略。清理本次 baseline/focused 测试临时目录时，已先校验绝对目标位于 T25 的 output/test-runs 路径内，但递归删除命令被自动审批审查以 `blocked by policy` 拒绝，命令未执行；这些临时目录连同日志保留，未绕过策略或删除已有工作区文件。
