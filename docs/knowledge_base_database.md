# 知识库与数据库实现说明

> 项目编号：XH-202630
> 文档版本：2.1
> 文档更新时间：2026-08-16
> 文档定位：说明当前项目中知识库源文件、SQLite 数据库、问卷、诊断、画像与资源的真实落库方式。

## 1. 当前运行方式

开发环境当前使用 SQLite。

`backend/.env` 的关键配置为：

```env
DB_TYPE=sqlite
DATABASE_URL=sqlite:///./data/domain_knowledge.db
```

数据库文件位置：

```text
backend/data/domain_knowledge.db
```

初始化与导入脚本：

```powershell
python scripts/init_db.py
python scripts/ingest_knowledge.py
```

含义：

- `init_db.py`
  - 创建关系表
  - 导入学习目录
  - 导入问卷模板与问卷题目
  - 导入诊断题
  - 初始化知识库元数据与示例画像
- `ingest_knowledge.py`
  - 构建知识库向量索引
  - 将知识文档切片写入 Chroma
  - 可使用 `--knowledge-base-id <id>` 显式重新入库并对账 SQL/Chroma

## 2. 当前知识源目录

### 2.1 学习目录源文件

```text
knowledge_base/learning_catalog_seed.json
```

作用：

- 保存“领域 -> 学习方向”的目录结构
- 初始化后同步到：
  - `learning_domains`
  - `learning_tracks`

### 2.2 通用问卷源文件

```text
knowledge_base/questionnaire_common.json
```

作用：

- 保存所有学习方向共用的初始画像问卷
- 当前只保留动态学习信息题目，不再保存用户长期稳定资料字段

### 2.3 方向专属源文件

每个学习方向目录下可包含：

```text
knowledge_base/<track_id>/
  metadata.json
  questionnaire.json
  diagnostic_questions.json
  assessment_questions.json
  raw/
```

当前已有方向目录：

- `knowledge_base/rag_engineering_training/`
- `knowledge_base/demo_industrial_internet/`

说明：

- `metadata.json`：知识库元数据
- `questionnaire.json`：方向专属问卷源文件
- `diagnostic_questions.json`：诊断题源文件
- `assessment_questions.json`：学习反馈使用的分层测评题库；不参与初始画像诊断
- `raw/`：原始知识文档

## 3. 当前数据库分层

### 3.1 学习目录

| 表 | 作用 |
|---|---|
| `learning_domains` | 保存一级领域 |
| `learning_tracks` | 保存学习方向，并绑定到知识库 |

当前前端的“先选领域，再选方向”就是从这两张表读数据。

### 3.2 问卷

| 表 | 作用 |
|---|---|
| `questionnaire_templates` | 问卷模板 |
| `questionnaire_questions` | 问卷题目定义 |
| `questionnaire_submissions` | 一次问卷提交的主记录 |
| `questionnaire_answers` | 一次问卷提交的逐题答案明细 |

说明：

- 运行时问卷不是从前端硬编码读取
- 也不是直接从 JSON 文件给前端
- 当前 API 会先从数据库读取问卷模板和题目，再组装成前端可渲染结构
- 当前通用问卷只保留：
  - `learning_goals`
  - `learning_modes`
  - `difficulty_preference`
  - `weekly_time_budget`
- `identity`、`education`、`major`、`desired_resource_types` 已不再属于通用问卷题目

### 3.3 用户资料

| 表 | 作用 |
|---|---|
| `users` | 保存用户长期稳定资料 |

当前用户资料包含：

- `user_id`
- `display_name`
- `identity`
- `education`
- `major`
- `job_role`
- `experience_years`
- `metadata`

说明：

- `user_id` 由后端自动生成
- 用户资料与学习者画像已经拆分为两层数据对象

### 3.4 画像

| 表 | 作用 |
|---|---|
| `learner_profiles` | 学习者画像主表 |

当前画像包含：

- 基础背景
- 学习目标
- `knowledge_base_id`
- `theory_scores`
- `knowledge_states`
- `weak_points`
- `strong_points`
- `learning_preferences`

### 3.5 知识库

| 表 | 作用 |
|---|---|
| `knowledge_bases` | 知识库主表 |
| `knowledge_documents` | 文档记录 |
| `knowledge_chunks` | 切片记录 |

同时向量索引位于：

```text
backend/chroma_db/
```

关系数据库与向量库分工：

- SQLite：保存业务事实、文档映射、切片映射、元数据
- Chroma：保存向量与语义检索索引

### 3.6 技能图谱与诊断

| 表 | 作用 |
|---|---|
| `rag_skill_nodes` | 技能节点 |
| `skill_node_relations` | 技能节点关系 |
| `diagnostic_questions` | 诊断题库 |
| `diagnostic_answers` | 诊断作答记录 |
| `knowledge_states` | 节点掌握状态持久化 |

说明：

- 问卷与诊断是两套不同数据结构
- 问卷用于初始画像
- 诊断用于真实测量能力并回写状态

### 3.7 资源、反馈与审核

| 表 | 作用 |
|---|---|
| `generation_jobs` | 异步资源生成任务 |
| `generated_resources` | 已生成资源 |
| `feedback_records` | 学习反馈 |
| `learning_attempts` | P0-07 正式学习尝试与幂等请求摘要 |
| `learning_attempt_point_results` | Attempt 的逐知识点答题汇总 |
| `feedback_decisions` | 确定性反馈决策事实 |
| `knowledge_state_mutations` | 掌握度 before/after 历史 |
| `learner_profile_versions` | 画像版本变化原因与摘要 |
| `learning_paths` / `learning_path_nodes` | 当前持久化路径和节点状态 |
| `learning_path_mutations` | 路径变更审计记录 |
| `feedback_followup_runs` | Attempt/Decision 与后续生成 Run 的来源关系 |
| `agent_runs` | Agent 运行主记录 |
| `agent_steps` | Agent 步骤记录 |
| `resource_reviews` | 资源审核摘要 |
| `resource_claims` | Claim 原文、资源版本、稳定 ID 与抽取元数据（兼容旧字段） |
| `claim_judgements` | Claim 的独立判定、模型/Prompt 版本与置信度 |
| `claim_evidence` | Judgement 到冻结 `retrieval_evidence_snapshots` 的受约束绑定 |

### 3.8 评测

| 表 | 作用 |
|---|---|
| `contest_eval_cases` | 评测样例 |
| `contest_eval_results` | 评测结果 |

## 4. 当前 API 与数据库的关系

### 4.1 学习目录

- `GET /api/knowledge/domains`
- `GET /api/knowledge/directions`

读取：

- `learning_domains`
- `learning_tracks`

### 4.2 问卷

- `GET /api/onboarding/questions`
- `POST /api/onboarding/initial-profile`

读取：

- `questionnaire_templates`
- `questionnaire_questions`

写入：

- `questionnaire_submissions`
- `questionnaire_answers`
- `learner_profiles`

P0-07 正式接口还会原子读写 `learning_attempts`、`learning_attempt_point_results`、`feedback_decisions`、`knowledge_states`、`knowledge_state_mutations`、`learner_profile_versions`、`learning_paths`、`learning_path_nodes` 和 `learning_path_mutations`。事务提交后才创建 `generation_jobs`，随后写 `feedback_followup_runs`；外部生成失败不回滚 Attempt。

### 4.3 P0-07 一致性与迁移

- `learning_attempts` 对 `(learner_id, idempotency_key)` 建唯一约束，并保存 canonical JSON SHA-256 `request_hash`。
- `learner_profiles.profile_version` 从 1 起；请求的 `expected_profile_version` 与当前值不一致时拒绝更新。
- `knowledge_states` additive 增加 `attempt_count`、`last_attempt_id`、`row_version`，继续演进诊断阶段已有表，不另建竞争当前态。
- 所有 mutation 记录 before/after、source attempt 和 reason；同一 Attempt 重放不会二次加权。
- `20260811_p0_07_feedback_profile_path_closed_loop` 是幂等 additive migration；旧 `feedback_records` 不删除、不回填伪造 Attempt。
- 当前开发、演示和部署都使用 SQLite，通过短事务、唯一约束和版本条件控制并发；上线前仍需核验 SQLite DDL、索引、FK 与真实读写行为。

### 4.4 P0-08 WorkflowEvent tail query

P0-08 的 SSE 能力本身不新建事件表：继续复用 `workflow_events` 的 `(run_id,event_sequence)` 唯一约束/索引和 `agent_runs.last_event_sequence`。SSE 每次只执行有界查询：

```sql
WHERE run_id = :run_id AND event_sequence > :cursor
ORDER BY event_sequence
LIMIT :page_size
```

长 SSE 连接不持有 Session、事务或锁，不增加 delivered/ack 字段；不同客户端只读同一 append-only Ledger。当前 SQLite 使用短连接轮询，并需结合一个 Durable Worker、SSE 客户端数和 0.5 秒默认间隔评估锁等待与连接数量。Event retention 尚未在 P0-08 自动清理，删除策略必须保留比赛回放与 `legacy_partial` 语义。

### 4.5 数据库完整性与 P0-09 migration

- SQLite engine 在每个新 DBAPI connection 建立时执行并验证 `PRAGMA foreign_keys=ON`，而不是只设置启动时的单个连接。
- `generated_resources` 对 `(run_id, resource_type, version)` 建数据库级 UNIQUE，同一 Run 的同类型同版本资源只能有一条；legacy `run_id IS NULL` 仍允许并存。
- Resource 的 `run_id`、`generation_step_id` 和 `parent_resource_id` 分别引用 Run、Step 和父资源版本。旧 SQLite 表缺少声明式 FK 时，`20260815_p0_09_database_integrity` 会在预检通过后事务化重建该表。
- migration 不自动删除重复记录、不补造 Run/Step/父资源，也不为非空 Run 的 NULL version 猜测版本；发现这些情况会 fail closed，要求先人工处理。
- SQL Repository 保留业务查重，并将并发下数据库返回的 `IntegrityError` 映射为稳定 `PersistenceConflict`。

只读预检命令：

```powershell
python scripts/check_database_integrity.py
```

预检输出包括 `foreign_keys_enabled`、`foreign_key_violations`、`resource_version_duplicates`、`resource_version_null_count`、`resource_version_unique`、`missing_resource_foreign_keys` 和 `resource_reference_orphans`。团队真实数据升级前必须先备份当前 SQLite 文件、生成资源目录、Chroma collection 与知识库 manifest/hash，再对脱敏副本执行两次 migration 验证幂等。

比赛阶段没有真实历史数据库时，可执行合成旧库演练：

```powershell
python scripts/rehearse_synthetic_database_migration.py
```

脚本基于历史 schema 临时生成正常旧库、资源版本重复库和孤儿引用库。正常库会连续执行两次当前 migration，并核对行数、migration IDs、`legacy_partial`、`legacy_unavailable`、旧资源发布状态以及是否伪造 Claim/Attempt/Evidence 等事实；两类脏库必须 fail closed。脚本不读取或修改配置中的应用数据库。

### 4.5.1 Knowledge SQL/Chroma 崩溃恢复

知识入库开始时先把 `knowledge_index_status.status` 写成 `indexing`。服务启动时会原子扫描超过
`KNOWLEDGE_INDEX_STALE_SECONDS`（默认 900 秒）仍处于该状态的记录，并转换为：

```text
status=not_ready
last_error_code=KNOWLEDGE_INDEXING_INTERRUPTED
```

转换会保留当时的 snapshot hash、SQL/Chroma 计数和上一次成功入库时间，便于管理员判断崩溃窗口。
启动过程只标记异常，不自动运行 Embedding 或重建索引，避免拖慢/阻断服务启动。

管理员确认项目内源文件无误后，可通过以下受保护接口执行完整恢复：

```text
POST /api/admin/knowledge-bases/{knowledge_base_id}/reconcile
X-Admin-Token: <ADMIN_HEALTH_TOKEN>
```

也可以执行本地命令：

```powershell
python scripts/ingest_knowledge.py --knowledge-base-id rag_engineering_training
```

恢复操作不猜测 SQL 和 Chroma 哪一侧较新，而是重新读取权威源文件、生成稳定文档/切片 ID、
替换该 KB 的 Chroma 活跃集合、运行 smoke query，最后才激活 SQL 快照并写入 `ready`。
因此进程可能在 SQL staging、Chroma 替换、smoke 或 SQL activation 任一阶段被中断，后续重试仍然幂等。

### 4.6 用户资料

- `GET /api/users/`
- `GET /api/users/{user_id}`
- `POST /api/users/`
- `PATCH /api/users/{user_id}`

读写：

- `users`

### 4.7 画像

- `GET /api/profiles/`
- `GET /api/profiles/{learner_id}`
- `PATCH /api/profiles/{learner_id}`
- `DELETE /api/profiles/{learner_id}`

读写：

- `learner_profiles`

删除时还会联动清理相关诊断记录。

### 4.8 诊断

- `GET /api/diagnosis/questions`
- `POST /api/diagnosis/submit`

读取：

- `diagnostic_questions`
- `rag_skill_nodes`
- `skill_node_relations`

写入：

- `diagnostic_answers`
- `knowledge_states`
- `learner_profiles`

### 4.9 资源与反馈

- `POST /api/generate/jobs`
- `GET /api/generate/jobs?learner_id={learner_id}`
- `GET /api/generate/jobs/{run_id}`
- `GET /api/resources/{learner_id}`
- `GET /api/resources/file/{resource_id}`
- `GET /api/reviews/{resource_id}`
- `GET /api/feedback/evaluation/run/{learner_id}/{run_id}`
- `POST /api/feedback/attemptsattempts/run/submit`
- `POST /api/feedback/attempts`
- `GET /api/feedback/attempts/{learner_id}`
- `GET /api/learning-history/{learner_id}/timeline`
- `GET /api/report/{learner_id}`

涉及：

- `generated_resources`
- `resource_reviews`
- `resource_claims`
- `feedback_records`
- `agent_runs`
- `agent_steps`
- `learner_profiles`

## 5. 问卷与诊断的边界

### 5.1 问卷负责什么

问卷用于收集：

- 学习目标
- 学习偏好
- 当前学习方向下的动态时间与难度偏好

问卷不会直接判定：

- `mastered`
- `weak`
- `learning`

### 5.2 诊断负责什么

诊断用于：

- 测量真实掌握情况
- 判分
- 回写 `knowledge_states`
- 更新 `skill_level`
- 更新 `weak_points` / `strong_points`

## 6. 当前实现中的真实口径

### 6.1 问卷来源

当前是：

```text
源文件 -> init_db.py 导入 -> questionnaire_templates / questionnaire_questions -> API 从数据库读取
```

所以：

- 源文件存在，是为了开发理解、版本管理和初始化
- 运行时实际读取来源是数据库
- 如果源文件已经更新但数据库未同步，前端看到的仍会是数据库中的旧模板

### 6.2 诊断题来源

当前是：

```text
diagnostic_questions.json -> init_db.py 导入 -> diagnostic_questions -> API 从数据库读取
```

所以：

- 诊断题源文件只是导入来源
- 运行时实际读取来源也是数据库

### 6.3 用户资料来源

当前是：

```text
POST /api/users/ -> users -> onboarding / 画像流程按需读取
```

所以：

- 用户长期稳定资料不应再放入通用问卷
- 用户资料与画像之间是“先建用户资料，再生成学习画像”的关系

## 7. 当前知识库示例状态

当前演示知识库目录：

```text
knowledge_base/rag_engineering_training/
```

当前已知事实：

- `knowledge_base_id = rag_engineering_training`
- 知识库版本：`2.3.0`
- 综合学习模块：6 个，不再拆分教学卡、概要参考和深度参考
- 向量切片：84 个，已经写入该知识库独立的 Chroma 集合
- 在线检索：多查询扩展后分别执行 BM25 关键词召回与 Chroma 向量召回，按 `chunk_id` 去重并使用 RRF 融合，再由 `BAAI/bge-reranker-base` CrossEncoder 对候选精排
- 能力节点：13 个
- 诊断题：39 道
- 学习后测评题：130 道；每个能力节点 10 道，难度分布为简单 3、中等 3、困难 4
- 方向问卷题：6 道

6 个模块统一采用“学习目标与路径 → 原理与工程正文 → 诊断与练习 → 验收标准 → 权威来源”的结构：

- RAG 原理、系统边界与工程契约
- 资料治理、文档解析与 Chunk 实验
- Embedding、向量数据库与相似度检索
- 查询改写、混合召回与 Rerank
- 上下文组装、引用与忠实生成
- RAG 评测、消融实验与生产运营

模块内容依据 RAG、DPR、HyDE、Self-RAG、RAGAS、RAGChecker 原始论文，以及 LangChain、LangSmith、Sentence Transformers 和 Chroma 官方文档整理。每个模块的 `source_urls` 均登记在：

```text
knowledge_base/rag_engineering_training/metadata.json
```

6 个模块共同覆盖 13 个能力节点；一个模块可以承载多个紧密相关的节点，但每个节点只指定一个主模块，避免检索时反复召回内容相似的卡片和参考文档。诊断题仍按 13 个细粒度能力节点组织，不因资料合并而降低诊断粒度。

学习后测评题独立保存在：

```text
knowledge_base/rag_engineering_training/assessment_questions.json
```

它与 `diagnostic_questions.json` 分工不同：诊断题用于初始画像和诊断更新；测评题用于学习反馈。资源中存在 AI 生成且带标准答案的 `exercise_items` 时优先使用资源题，否则按资源对应能力节点从测评题库抽取。题库在服务端保留答案、解析和权威 `source_urls`，对外会话只下发题干、选项和难度。

## 8. 当前测试口径

当前后端回归命令：

```powershell
python -m pytest backend/tests -q
```

当前测试文件已覆盖：

- Agent 工作流
- 问卷 API
- 画像 API
- 知识库 API
- 资源 API
- 审核 API
- 评测 API
- 问卷数据库读写
- SQLite 每连接外键执行与非法审计/反馈引用阻断
- P0-09 资源版本唯一约束、旧表 FK 重建与 migration 幂等
- Resource Repository 数据库冲突映射和 legacy NULL Run 行为
- Feedback 事务回滚、FastAPI lifespan 重启与真实 Uvicorn 进程重启
- SQLite 遗留 GenerationJob/Follow-up 启动对账及幂等重排队
- Knowledge `indexing` 超时检测、启动恢复和显式 SQL/Chroma 重入库
- 学习反馈 AI 资源题优先与独立测评题库回退
- 测评题库 130 道题的节点覆盖、3/3/4 难度分布、答案与来源结构校验

说明：

- 这里不再写死某个过期的 `xx passed`
- 以当前实际测试结果为准

## 9. 当前约束

### 9.1 命名约束

- 前台流程入口：`learning_direction_id`
- 内部知识边界：`knowledge_base_id`
- 用户资料主键：`user_id`
- 学习者画像主键：`learner_id`

### 9.2 存储约束

- 业务事实进 SQLite
- 向量索引进 Chroma
- 生成资源文件进 `backend/data/generated_resources/`
- CrossEncoder 模型缓存在 `backend/data/models/`，该目录已由 Git 忽略

### 9.3 文档约束

文档不得再使用以下旧口径描述当前实现：

- `/api/learner/profile`
- `/api/learner/list`
- 前端硬编码问卷
- 问卷和诊断混为一套题
- 把 `identity`、`education`、`major` 继续写在通用问卷中

## 10. 可信检索与运行时证据

当前知识链路采用“候选排序”和“证据认定”分层：

1. 在按 knowledge_base_id 隔离的 collection 内执行向量召回与 BM25 融合。
2. 可选 CrossEncoder 对候选精排，并保留 hybrid/rerank 元数据。
3. EvidenceRetriever 根据 SQL 中的 active Chunk、document_version、KB 范围和 text_hash 做最终校验。
4. 只有校验通过的候选生成稳定 Evidence ID，并在 Agent Run 中保存不可变 snapshot。
5. Generator 的 SourceRef 只从 Evidence 代码侧绑定，不接受模型或 legacy chunk 自行声明来源。

`CHROMA_COLLECTION_NAME` 兼容期只解释为前缀；创建、写入、查询、删除和 health
统一通过 `_collection_name(kb_id)` 定位集合。公共 readiness 仅以默认 KB 和核心依赖
为准，所有 KB 的详细状态由管理员接口提供。

## 11. P0-09 数据库 Gate

P0-09 preflight 会只读检查 migration 集合、正式 demo 数据库可达性、SQLite `PRAGMA foreign_keys`、`generated_resources(run_id, resource_type, version)` 数据库唯一约束，以及默认 KB 的本地 retrieval smoke。检查失败不会被公共 `/health/ready` 的 200 覆盖。

截至 2026-08-16，SQLite 每连接外键 hook、资源版本数据库唯一约束、旧表重建 migration、完整性检查和合成迁移演练已经进入代码与自动测试。正式 demo 数据仍须先运行只读完整性检查和受控 migration rehearsal，不能仅凭模型层约束宣布放行。代码中的其他数据库方言分支不属于当前部署承诺。

## 12. P0-19 Learner Mastery 迁移

`p0_19_learner_mastery` 对 `knowledge_states` 只做 additive 扩展：`state_schema_version`、`self_report_prior`、`confidence`、`objective_evidence_count`、`distinct_objective_source_count`、`last_evidence_type` 和 `last_evidence_id`。原有 `mastery_score`、`status`、`attempt_count` 与 `row_version` 不降级、不覆盖。

新表 `ability_state_events` 保存版本化 before/after 事件，主键为 `event_id`，并以 `(learner_id, source_type, source_id, skill_node_id)` 唯一约束保证每个来源对每个节点只应用一次。`source_hash` 用于识别同一来源 ID 的 payload 冲突；`verified` 区分自评/旧导入与服务端诊断/正式学习反馈。事件按 `occurred_at, event_id` 稳定读取。

旧画像 JSON 迁移只在当前知识库内按节点 ID或唯一名称映射。已有规范行优先；同名歧义、未知键或无效值不会被猜测。迁移结束后，画像兼容字段由规范行重新投影：`knowledge_states` 只用节点 ID，`theory_scores` 只包含客观节点，弱强项也只依据客观状态。`learner_mastery_migration_reports` 持久化 `mapped_count`、`canonical_preserved_count`、`unmapped_count` 和脱敏的 `unmapped_entries/reason`，供升级验收审计。

已有正式 `learning_attempts + knowledge_state_mutations` 可回填为 verified `learning_attempt` 事件并重算客观证据计数与置信度；无法证明来源的旧画像分数最多形成 `legacy_import, verified=false`。迁移通过 `schema_migrations` 幂等登记；重复执行不增加状态、事件或报告行。当前部署验证口径仍是 SQLite 外键开启、旧库/空库升级和重启恢复；代码中的 PostgreSQL 方言分支不构成已验收的生产承诺。
