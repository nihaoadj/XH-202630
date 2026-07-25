# 知识库与数据库实现说明

## 运行方式

开发与演示环境使用 SQLite。复制 `backend/.env.example` 为 `backend/.env` 后，保持：

```env
DB_TYPE=sqlite
DATABASE_URL=sqlite:///./data/domain_knowledge.db
```

在项目根目录执行：

```powershell
python scripts/init_db.py
python scripts/ingest_knowledge.py
```

`init_db.py` 创建关系表，并同步当前 `KNOWLEDGE_BASE_DIR` 指向知识库的元数据、文档、切片、能力图谱、诊断题及示例学习者画像。`ingest_knowledge.py` 只构建对应知识库的 Chroma collection；默认使用稳定片段 ID 上插入，可安全重复执行。只有知识库源文件被删除或希望完全刷新索引时才使用：

```powershell
python scripts/ingest_knowledge.py --rebuild
```

## 知识库目录约定

每个知识库目录包含：

- `metadata.json`：知识库 ID、版本、文档清单、能力图谱和适用人群。
- `raw/`：Markdown 或 TXT 原始资料。
- `diagnostic_questions.json`：可版本管理的诊断题数据（可选）。

每个向量片段都保留 `knowledge_base_id`、`document_id`、`chunk_id`、`chunk_index`、`title`、`source_path`、`knowledge_points` 与 `content_hash`。前端展示、资源引用和 Claim 审核均应使用这些稳定字段，不应依赖本机绝对路径或向量库返回顺序。

## 关系数据分层

| 范围 | 主要表 | 用途 |
| --- | --- | --- |
| 知识源 | `knowledge_bases`、`knowledge_documents`、`knowledge_chunks` | 管理知识库版本、文档和向量片段的可追溯映射 |
| 能力诊断 | `rag_skill_nodes`、`skill_node_relations`、`diagnostic_questions`、`diagnostic_answers`、`knowledge_states` | 建立知识点、题目、学习者掌握度之间的结构化关系 |
| Agent 与审核 | `agent_runs`、`agent_steps`、`resource_reviews`、`resource_claims` | 保存协同过程、证据、Claim 支持情况与修订结果 |
| 比赛评测 | `contest_eval_cases`、`contest_eval_results` | 记录检索命中、覆盖率、幻觉率、难度适配和消融实验 |

现有 `learner_profiles`、`generated_resources` 与 `feedback_records` 表继续保留，以保证当前服务层兼容。资源生成服务会将每次工作流的 `agent_runs`、`agent_steps` 以及每项资源的 `resource_reviews` 自动落库；当审核 Agent 提供 Claim 时，同时写入 `resource_claims`。新增表不替代现有 API，而是为后续 `/api/skills/*`、`/api/knowledge/*` 与评测接口提供数据源。

## AI 生成资源的持久化与知识库边界

AI 生成的学习资源需要保存，但它与“权威知识库资料”是两类数据，不能混存，也不能因为生成成功就自动进入向量检索库。

| 数据对象 | 保存位置 | 保存内容 | 是否参与 RAG 检索 |
| --- | --- | --- | --- |
| 权威知识库资料 | `knowledge_bases`、`knowledge_documents`、`knowledge_chunks` 与 Chroma collection | 已整理的参考资料、教学知识卡、稳定片段 ID、来源元数据与内容哈希 | 是 |
| AI 生成学习资源 | `generated_resources`；有正文时另存 `backend/data/generated_resources/` | 学习者、主题、类型、难度、正文/文件、知识点、来源引用、版本、审核摘要 | 否 |
| 生成过程审计 | `agent_runs`、`agent_steps` | 请求摘要、Agent 步骤、决策依据、证据引用、重试和异常信息 | 否 |
| 审核结果 | `resource_reviews`、`resource_claims` | 审核状态、幻觉风险、Claim、支持与否、证据片段、修正建议 | 否 |

`POST /api/generate/` 的资源保存链路为：生成 Agent 产出 `LearningResource` → 若有文本正文，写入受控目录并记录相对路径、大小和 MIME 类型 → 写入 `generated_resources` → 写入本次 `agent_runs` 与 `agent_steps` → 审核结果写入 `resource_reviews`；只有审核 Agent 实际返回 Claim 时才写入 `resource_claims`。资源读取只允许按 `resource_id` 访问，服务端会验证文件仍位于 `backend/data/generated_resources/` 内，避免把任意本机路径暴露给客户端。

生成资源的 `source_refs` 和 Claim 的 `evidence_refs` 应指向稳定的知识库文档/片段标识，用于展示“这份资源依据了什么”。当前实现**不会**将生成内容自动写回 `knowledge_documents`、`knowledge_chunks` 或 Chroma。若后续希望把某份生成内容升级为知识库资料，应先由人工核验内容、来源、版权和版本，再走显式的资料导入与索引重建流程；这一环节目前没有自动接口，属于有意保留的人审边界。

## 数据质量规则

1. `knowledge_base_id` 是知识隔离边界；检索、文档、图谱和诊断题必须属于同一知识库。
2. `document_id`、`chunk_id`、`question_id` 与 `node_id` 一经发布不得随意变更。
3. 每条诊断题必须绑定至少一个知识点或能力节点；每条评测样本必须给出期望证据。
4. Claim 审核记录使用 `resource_claims.evidence_refs` 关联稳定片段 ID，不能只保存自然语言来源描述。

## 当前实现清单（数据库、知识库、接口与测试）

本节只描述仓库中已经实现和验证过的内容，不把后续设想写成已完成功能。开发环境当前使用 SQLite（`backend/data/domain_knowledge.db`）；语义向量索引由本地 Chroma 独立保存。两者分工如下：SQLite 保存业务事实、关系、审计和历史记录，Chroma 保存可语义检索的知识文档切片及其来源元数据。

### 数据库当前保存的数据

| 数据类别 | 表 | 保存内容 | 主要用途 |
| --- | --- | --- | --- |
| 学习者画像 | `learner_profiles` | 背景、目标领域、所属知识库、能力等级、理论得分、知识状态、强弱项、学习偏好、最近反馈摘要 | 个性化诊断、路径规划和资源生成 |
| 已生成资源 | `generated_resources` | 资源类型、难度、正文或文件路径、覆盖知识点、来源引用、审核状态、版本 | 向学习者展示资源并保留资源历史 |
| 学习反馈 | `feedback_records` | 正确率、答案详情、耗时、自评、决策、推荐主题、知识状态更新 | 驱动下一轮补弱、练习或进阶挑战 |
| 知识库目录 | `knowledge_bases`、`knowledge_documents`、`knowledge_chunks` | 知识库版本、文档路径与哈希、切片正文、切片哈希、来源元数据 | 追溯“某段回答来自哪篇文档、哪个片段” |
| 能力图谱 | `rag_skill_nodes`、`skill_node_relations` | 节点名称、层级、前置/后继关系、关联知识点、考核方式 | 组织教学顺序与诊断维度 |
| 诊断过程 | `diagnostic_questions`、`diagnostic_answers`、`knowledge_states` | 题目、标准答案、作答、判分、节点掌握度及证据题号 | 服务器判分并更新学习者画像 |
| Agent 过程与审核 | `agent_runs`、`agent_steps`、`resource_reviews`、`resource_claims` | 每次生成的输入输出摘要、Agent 步骤、审核结果、Claim 与证据切片 | 演示多 Agent 过程，审计资源的证据支撑 |
| 量化评测 | `contest_eval_cases`、`contest_eval_results` | 标准评测题、实验名称、检索命中、覆盖率、幻觉率、难度匹配等结果 | 汇总比赛用的真实评测指标；评测样例仍待后续录入 |

画像中的灵活字段（如 `knowledge_states`、`learning_preferences`）以 JSON 保存；需要过滤和关联的关键字段（如 `learner_id`、`knowledge_base_id`、`resource_id`、`node_id`）保留为独立列。删除画像时会删除其诊断答案和知识状态，并将 Agent 审计记录中的学习者标识匿名化。

### 当前知识库保存的数据

当前演示知识库位于 `knowledge_base/rag_engineering_training/`，其 `knowledge_base_id` 为 `rag_engineering_training`，版本为 `1.0.0`。本次入库已验证为 **22 篇文档、57 个 Chroma 向量切片、13 个能力节点、39 道诊断题**。

| 位置/文件 | 当前内容 | 保存方式和用途 |
| --- | --- | --- |
| `metadata.json` | 知识库 ID、版本、文档清单、来源 URL、能力图谱、适用层级 | 知识库的总目录；初始化时同步到关系数据库 |
| `references/` | 9 篇 RAG 工程权威资料整理，覆盖架构、切分、嵌入、检索、重排、引用、审核、评测、调优 | 面向事实依据和工程方法，保留原始来源链接 |
| `cards/` | 13 张教学知识卡，分别对应能力图谱节点 | 面向教学和个性化生成，提供可直接学习的内容 |
| `diagnostic_questions.json` | 39 道题：每个能力节点 3 题，覆盖概念、情境、误区 | 服务器读取并判分；对外获取题目时不返回答案和解析 |
| `raw/` | 预留的原始资料归档目录；当前为空 | 之前的 4 篇非权威原始资料已按要求删除，不参与检索或入库 |
| Chroma collection | 57 个片段的文本向量与基础来源元数据 | 用于语义检索；片段保留 `knowledge_base_id`、`document_id`、`chunk_id`、标题、来源路径、知识点、内容哈希等可追溯字段 |

向量切片采用稳定 ID 上插入：重复执行入库不会产生重复片段；显式执行 `python scripts/ingest_knowledge.py --rebuild` 时，才会先删除该知识库原有的 Chroma collection 再重建。

### 当前后端接口

以下接口均已注册在 FastAPI 应用中；详细请求体和响应字段见 [api.md](api.md)。

| 模块 | 已实现接口 |
| --- | --- |
| 健康检查 | `GET /` |
| 学习者画像 | `POST /api/learner/profile`、`GET /api/learner/profile/{learner_id}`、`PATCH /api/learner/profile/{learner_id}`、`GET /api/learner/list`、`DELETE /api/learner/profile/{learner_id}` |
| 初始画像与自适应诊断 | `GET /api/onboarding/questions`、`POST /api/onboarding/initial-profile` |
| 知识库与能力图谱 | `GET /api/knowledge/info`、`GET /api/skills/nodes` |
| 诊断 | `GET /api/diagnosis/questions`、`POST /api/diagnosis/submit` |
| 个性化生成 | `POST /api/generate/` |
| 资源 | `GET /api/resources/{learner_id}`、`GET /api/resources/file/{resource_id}` |
| 审核与证据 | `GET /api/reviews/{resource_id}` |
| 反馈与报告 | `POST /api/feedback/`、`GET /api/feedback/history/{learner_id}`、`GET /api/report/{learner_id}` |
| 评测 | `GET /api/evaluation/summary` |

`GET /api/diagnosis/questions` 不返回题目答案和解析，正确性只由服务端在 `POST /api/diagnosis/submit` 时计算。`GET /api/evaluation/summary` 只汇总已经落库的真实评测结果，不会生成虚假的比赛指标。

### 测试文件与覆盖范围

当前完整回归命令为：

```powershell
python -m pytest backend/tests -q
```

截至本说明更新时，完整测试结果为 **26 passed**。各文件覆盖范围如下：

| 测试文件 | 覆盖内容 |
| --- | --- |
| `backend/tests/test_agents.py` | Agent 工作流能运行；达到最大重试次数时能够停止；生成节点会正确增加迭代计数 |
| `backend/tests/test_services.py` | 学习者服务增删查改、内存仓储选择、反馈降级决策、反馈决策 Agent、学习报告服务 |
| `backend/tests/test_knowledge_base.py` | 稳定切片与来源字段、Chroma 元数据序列化/还原、目录幂等同步与过期文档清理、检索的知识库隔离、Agent 审计和 Claim 证据持久化、诊断判分及 SQLite 持久化 |
| `backend/tests/test_knowledge_api.py` | 知识库信息和诊断接口可用，且诊断题答案不会泄露给客户端 |
| `backend/tests/test_learner_api.py` | 学习者列表、部分更新和删除接口 |
| `backend/tests/test_onboarding_api.py` | 问卷创建/更新初始画像、仅向自称了解的节点发放诊断题、未开始节点保留、Embedding 场景筛查失败时跳过深度诊断 |
| `backend/tests/test_resource_api.py` | 资源类型/难度过滤、按资源 ID 下载、拒绝访问生成资源目录之外的路径 |
| `backend/tests/test_review_api.py` | 审核详情接口返回 Claim 证据，并正确处理资源不存在的情况 |
| `backend/tests/test_evaluation_api.py` | 评测汇总按实验名称聚合真实已落库结果 |

> 当前测试重点是数据库、知识库和 API 的回归保障。前端联调、正式比赛评测样例扩充、生产环境权限与隐私策略不属于本轮已完成范围。

## 初始画像与自适应诊断

新增 `GET /api/onboarding/questions` 与 `POST /api/onboarding/initial-profile` 后，问卷数据仍保存于既有 `learner_profiles` 表，不新增一张孤立的问卷表：身份映射为 `learner_type`，问卷直接采集 `education` 和 `major`，学习目标映射为 `learning_goal`；Python、API、Prompt、RAG 自评保存为带“自评”前缀的理论得分；资源类型、难度偏好与学习方式写入 `learning_preferences`，资源语言当前固定为中文默认值；原始问卷答案保留在 `learning_preferences.metadata.onboarding`，以便追溯初始判断依据。

第 7 题“已了解的 RAG 节点”只用于选择诊断范围：被选择的节点写为 `self_reported` 并返回对应诊断题；未选择节点写为 `not_started` 并进入画像的待补弱项，但不会出诊断题。用户随后通过 `/api/diagnosis/submit` 对已选择节点作答，服务端真实判分后会覆盖这些节点的状态；未开始节点会继续保留在待补列表中，供第一轮资源生成优先补齐。

知识状态的受控值为 `not_started`、`self_reported`、`weak`、`learning`、`mastered`。其中前两种用于初始画像：`not_started` 表示用户明确不了解，`self_reported` 表示用户自称了解、待诊断验证；后三种只能由诊断题服务端判分或学习反馈产生。`not_started` 不是 `unknown`：前者有明确的问卷证据，后者表示没有任何判断依据。

Embedding 节点在返回深度诊断题前还需通过一个条件式场景筛查题。该筛查题不是直接询问定义，而是要求区分语义向量召回、文档切分、Prompt 约束和重排序；回答错误时不会把“自称了解 Embedding”误当成掌握，也不会继续发放该节点的诊断题。
