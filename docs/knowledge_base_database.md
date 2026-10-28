# 知识库与数据库实现说明

> 项目编号：XH-202630
> 文档版本：2.3
> 文档更新时间：2026-10-09
> 文档定位：说明当前项目中知识库源文件、SQLite 数据库、问卷、诊断、画像与资源的真实落库方式。

## 1. 当前运行方式

开发环境当前使用 SQLite。

`backend/.env.example` 的默认配置如下，本机 `backend/.env` 可覆盖实际路径：

```env
DB_TYPE=sqlite
DATABASE_URL=sqlite:///./data/domain_knowledge.db
```

默认数据库文件位置（相对路径按 `backend/` 解析）：

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

初始化和入库会修改配置中的数据，不属于只读文档检查。当前库是否已应用迁移、是否可检索，分别以完整性检查和环境 / KB health 为准；文档不将某次本地重建结果视为所有环境的状态。

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
- `username` 与账号启用状态；密码哈希只在持久化 / 认证内部使用，不进入用户资料响应

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
| `knowledge_documents` / `knowledge_chunks` | 当前文档与切片的稳定身份投影 |
| `knowledge_document_versions` / `knowledge_chunk_versions` | 不可变文档/Chunk 版本；`is_current`、`active` 决定当前可检索快照 |
| `knowledge_chunk_skill_node_mappings` | Chunk 版本与能力节点的可审计多对多映射 |
| `knowledge_index_status` | SQL/Chroma 快照计数、smoke 结果和索引状态 |

同时向量索引位于：

```text
backend/chroma_db/
```

关系数据库与向量库分工：

- SQLite：保存业务事实、文档/Chunk 版本、Chunk—节点映射和可审计元数据
- Chroma：保存向量与语义检索索引

`knowledge_chunk_skill_node_mappings` 不是第二个向量库：它只保存
`knowledge_base_id`、文档/版本、`chunk_id`、`skill_node_id`、映射来源和创建时间，
用于先确定允许参与检索的 Chunk。表以 `(chunk_id, skill_node_id)` 去重，并建立
`(knowledge_base_id, skill_node_id)` 与 `chunk_id` 索引；实际查询还会联结
`knowledge_chunk_versions.active = true`，因此历史映射可以保留但不会重新进入当前检索。

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
| `generation_jobs` | 文本任务、冻结输入、持久领取租约与关联重试 |
| `resource_specs` | 每 Run 冻结的资源类型、family、目标、Evidence 和表示预算 |
| `resource_executions` | 每 `(run_id, resource_spec_id, representation)` 当前执行投影 |
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
| `workflow_events` / `workflow_checkpoints` | append-only 事件与运行检查点 |
| `retrieval_evidence_snapshots` | 每 Run 冻结的来源、版本、哈希和摘录 |
| `resource_reviews` | 资源审核摘要 |
| `resource_claims` | Claim 原文、资源版本、稳定 ID 与抽取元数据（兼容旧字段） |
| `claim_judgements` | Claim 的独立判定、模型/Prompt 版本与置信度 |
| `claim_evidence` | Judgement 到冻结 `retrieval_evidence_snapshots` 的受约束绑定 |

### 3.8 评测

| 表 | 作用 |
|---|---|
| `contest_eval_cases` | 评测样例 |
| `contest_eval_results` | 评测结果 |

### 3.9 掌握度与课程进度

| 表 | 作用 |
|---|---|
| `knowledge_states` / `ability_state_events` | 唯一规范掌握态与来源幂等能力事件 |
| `learner_curriculum_nodes` | 已安排、已接触、待验证、完成和欠债等课程流程投影 |
| `learner_tier_progress` | 起始阶、当前阶、最高解锁阶和补救返回阶 |

掌握度与课程进度是不同事实。旧画像 JSON 仅为规范状态的兼容缓存；自评为低置信度，客观写入来自服务端诊断与 run/batch 正式反馈，低阶准入豁免不等于正式掌握。

### 3.10 Tutor 与互动课件

| 表 | 作用 |
|---|---|
| `tutor_sessions` / `tutor_turns` | 活动会话、幂等轮次、提示等级和受控引用 |
| `courseware_generation_jobs` / `courseware_outbox` | 持久课件任务、租约和 Worker 消费 |
| `courseware_workflow_checkpoints` | 课件工作流恢复边界 |
| `courseware_specs` / `courseware_source_links` | 冻结单文本来源和结构契约 |
| `courseware_scenes` / `courseware_scene_revisions` / `courseware_reviews` | 场景、修订与自动审核事实 |
| `courseware_events` | 课件任务事件，独立于文本 Run 的事件流 |
| `courseware_resources` / `courseware_releases` / `courseware_artifacts` | 资源、不可变候选与当前发布指针 |
| `courseware_learning_events` | occurrence 幂等且按 resource / release 隔离的学习事件 |

ORM 入口是 `db/shared/models.py` 与 `db/courseware/models.py`，初始化与迁移装配位于 `db/shared/database.py`。Tutor 不写掌握度；课件交互自评不替代正式反馈成绩。

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

run/batch 正式反馈会原子读写 `learning_attempts`、`learning_attempt_point_results`、`feedback_decisions`、`knowledge_states`、`ability_state_events`、`knowledge_state_mutations`、`learner_profile_versions`、`learning_paths`、`learning_path_nodes` 和 `learning_path_mutations`。提交后先返回候选；学习者确认下一步时才创建 `generation_jobs` 并写 `feedback_followup_runs`，外部生成失败不回滚 Attempt。SQLite 持久投递将子任务、冻结输入、mastery 调度、反馈关联和生成创建事件放入同一事务；关联写入失败时不会留下可执行的半成品。

`p0_34_generation_dispatch` 为 `generation_jobs` 增量添加内部字段：`dispatch_mode`、`dispatch_snapshot`、`submission_hash`、`claim_owner`、`claim_epoch`、`claim_count`、`lease_expires_at`、`next_attempt_at`、`retry_of_run_id`。旧行归属 `legacy`，新持久任务归属 `worker`；HTTP DTO 不暴露这些字段。冻结快照保存版本化 workflow、LearnerProfile 和请求摘要。`retry_of_run_id` 唯一索引及前序 `superseded_by_run_id IS NULL` 的事务 CAS 保证同一失败任务不会并发分叉。

Worker 原子领取时置 running，owner/epoch 及有效租约约束续租和终态写入；执行中的 SQL 写入在 flush/commit 前于同一事务验证归属并持有 SQLite 写锁。周期对账每轮最多 100 个候选，运行任务以 AgentRun 租约和终态为准，新 queued 持久任务不按创建年龄失败。反馈与 curriculum 另按已确认失败事实修复崩溃窗口，条件更新不会释放已归属新 run 的节点。文本 Markdown 文件只允许相同内容幂等复用，已存在的不同内容拒绝覆盖。

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

长 SSE 连接不持有 Session、事务或锁，不增加 delivered/ack 字段；不同客户端只读同一 append-only Ledger。当前 SQLite 使用短连接轮询，并需结合文本和课件各一个 Worker、SSE 客户端数和 0.5 秒默认间隔评估锁等待与连接数量。Event retention 尚未在 P0-08 自动清理，删除策略必须保留比赛回放与 `legacy_partial` 语义。

### 4.5 数据库完整性与 P0-09 migration

- SQLite engine 在每个新 DBAPI connection 建立时执行并验证 `PRAGMA foreign_keys=ON`，而不是只设置启动时的单个连接。
- `generated_resources` 对 `resource_spec_id IS NULL` 的 legacy 记录按 `(run_id, resource_type, version)` 建部分 UNIQUE；`run_id IS NULL` 仍允许并存。
- `resource_spec_id IS NOT NULL` 的资源级记录按 `(run_id, resource_spec_id, representation, version)` 建部分 UNIQUE，`resource_executions` 对 `(run_id, resource_spec_id, representation)` 唯一；文本表示保持 `text`，课件使用独立表。
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

删除由 Profile 仓储协调清理画像相关的问卷、诊断、资源、反馈、审核和运行记录；认证用户本身仍由账号资料维护。具体关联和事务范围以当前仓储与删除集成测试为准。

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
- `GET /api/feedback/evaluation/batch/{learner_id}/{batch_id}`
- `POST /api/feedback/attempts/run/submit`
- `POST /api/feedback/attempts/batch/submit`
- `POST /api/feedback/followups/select`
- `GET /api/feedback/attempts/{learner_id}`
- `GET /api/feedback/results/{learner_id}`
- `GET /api/learning-history/{learner_id}/timeline`
- `GET /api/learning-history/{learner_id}/journey`
- `GET /api/report/{learner_id}`

涉及：

- `generated_resources`
- `resource_reviews`
- `resource_claims`
- `feedback_records`
- `agent_runs`
- `agent_steps`
- `learner_profiles`

旧 `POST /api/feedback/attempts` 因聚合分数缺少服务端题目证据返回 422 `FEEDBACK_EVIDENCE_UNVERIFIED`，不写 Attempt、掌握度或画像版本。

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
POST /api/auth/register -> users -> PATCH /api/users/{user_id} -> onboarding / 画像流程按需读取
```

所以：

- 用户长期稳定资料不应再放入通用问卷
- 用户资料与画像之间是“先建用户资料，再生成学习画像”的关系

## 7. 当前知识库示例状态

当前演示知识库目录：

```text
knowledge_base/rag_engineering_training/
```

按受版本控制的知识库源文件可核对：

- `knowledge_base_id = rag_engineering_training`
- 知识库版本：`2.3.0`
- 综合学习模块：6 个，不再拆分教学卡、概要参考和深度参考；当前文件教材修订为 `teaching-2026-10-v2`，详见7.6；未同步旧SQL/Chroma。
- 迁移前本地验收快照（2026-10-26，T8）：56份权威原始资料（英文21＋官方中文/译本35）和6个教学模块，共62文档、3180活动切片、7896活动节点映射；当时SQL/Chroma正文/ID/完整元数据及跨新进程向量查询验证通过。此为T9直接移动前的历史状态，不代表当前磁盘路径与旧SQL/Chroma metadata仍一致，也不代表他人环境已经同步。
- 首批完整官方原始资料：3 份（2026-10-26），与教学模块分层保存，不将整理模块冒充官方原文；详见下方 7.2。
- 首批实际入库快照：9份文档、179个活动切片（旧模块84＋新原文95）、358条活动节点映射；SQL/Chroma计数及切片ID集合一致。新原文分别32、46、17个切片；这是2026-10-26本地对账结果，不是其他环境的实时状态。
- 向量切片：2026-08-29 本地验证快照为 84 个；当前配置中的 SQL / Chroma 入库状态需单独核实
- 在线检索：多查询扩展后分别执行 BM25 关键词召回与 Chroma 向量召回，按 `chunk_id` 去重并使用 RRF 融合，再由 `BAAI/bge-reranker-base` CrossEncoder 对候选精排
- 能力节点：13 个
- 模块级 Chunk—节点映射：上述本地快照的 84 个活动 Chunk 对应 182 条映射记录；映射表迁移在应用初始化时幂等回填
- 诊断题：39 道
- 学习后测评题：130 道；每个能力节点 10 道，难度分布为简单 3、中等 3、困难 4
- 方向问卷题：5 道

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

6 个教学模块共同覆盖 13 个能力节点；一个模块可以承载多个紧密相关的节点，每个节点保留一个主教学模块。新增权威原文可作为多个节点的补充证据，不受“一节点一份资料”的限制。诊断题仍按 13 个细粒度能力节点组织，不因资料扩充而降低诊断粒度。

2026-08-29 本地快照的模块级映射如下。这里的“映射 Chunk 数”是该快照中模块的所有 Chunk 数；
每一个 Chunk 映射到本行列出的全部节点，因此映射记录总数大于 Chunk 总数。

| 模块文档 | 历史快照活动 Chunk | 映射能力节点 |
|---|---:|---|
| `module_rag_foundations` | 13 | `rag_basics`（RAG 基础概念） |
| `module_ingestion_chunking` | 14 | `document_parsing`（文档解析）、`chunking`（Chunk 切分） |
| `module_embeddings_vector_retrieval` | 13 | `embedding`、`vector_store`、`similarity_retrieval` |
| `module_hybrid_rerank` | 14 | `hybrid_retrieval`、`rerank` |
| `module_context_citation_grounding` | 14 | `prompt_assembly`、`citation`、`hallucination_control` |
| `module_evaluation_tuning` | 16 | `rag_evaluation`、`rag_tuning` |

映射只使用 `knowledge_chunk_versions.knowledge_points` 与
`rag_skill_nodes.name` 的精确字符串匹配，不调用 LLM 推断标签。若模块声明了未知
知识点，该知识点不会生成映射，后续请求会走全库回退，而不是猜测节点归属。

### 7.1 入库、重切分与版本失效范围

入库顺序为：读取 manifest 和模块文档 → 切分 Chunk → upsert 知识库与能力节点 →
暂存 SQL 文档/Chunk 版本及模块级映射 → 同步 Chroma → 对账与 smoke → 激活当前
快照。映射和 Chunk 使用稳定 ID；重复入库不会产生重复映射。

修改或重切分某份文档时，新 Chunk 会获得新的版本/映射；旧 Chunk 和旧映射保留作
审计，但因为不再 `active` 而不会进入节点范围检索。未变化文档的 Chunk ID 与映射
保持可查询，完整快照重新激活后不需要重新标注。新增模块同样只需在 manifest 中声明
文档 `knowledge_points` 和对应能力节点，无需为每段文本另行人工打标签。

学习后测评题独立保存在：

```text
knowledge_base/rag_engineering_training/assessment_questions.json
```

它与 `diagnostic_questions.json` 分工不同：诊断题用于初始画像和诊断更新；测评题用于学习反馈。正式会话优先使用已发布且 hash 校验通过的结构化测试题节点题组，再兼容可判分的 `exercise_items`，最后回退独立测评题库。题库在服务端保留答案、解析和权威 `source_urls`，对外会话只下发题干、选项和难度。

> 历史路径说明：下方 7.2–7.4 记录 T8 收录与处理事实，出现的 `modules/`、`sources/` 等路径以及各自准备命令均是迁移前路径/操作记录，不是当前目录树或统一入口。T9 当前布局、离线命令和索引兼容边界见 7.5。T8 的 1710/3180 切片 metadata 一致性结论只适用于直接移动前；T9 更改了 metadata 中的物理来源路径，而旧 SQL/Chroma 未同步这些字段。

### 7.2 完整官方原文首批试点

首批新增三份官方仓库中的完整文档源文件，非 AI 摘要或重写：

| 文档 ID | 原始资料 | 固定仓库版本 | 许可 |
|---|---|---|---|
| `source_langchain_markdown_splitter` | LangChain Markdown 标题与重叠切分指南 | `langchain-ai/docs@4506df5fb4105a39b84c2b7390d21bed89e28668` | MIT |
| `source_sbert_semantic_search` | Sentence Transformers Semantic Search | `huggingface/sentence-transformers@33f9bd81610560e48ff5eac80e910496b49ae193` | Apache-2.0 |
| `source_sbert_retrieve_rerank` | Sentence Transformers Retrieve & Re-Rank | 同上 | Apache-2.0 |

所有路径相对 `knowledge_base/rag_engineering_training/`：

- `sources/originals/*.source`：完整上游字节快照，共 29,353 字节，不进入向量索引。
- `sources/normalized/*.md`：检索正文。SBERT 两篇原样保留；LangChain 仅去掉 YAML frontmatter、将原 title 补为 H1，不概述、不翻译、不改写。
- `sources/registry.json`：完整固定 URL、commit、抓取时间、原文 SHA256、派生正文 SHA256、许可路径和 `passthrough-v1` 转换版本。
- `sources/licenses/*/LICENSE`：保留完整上游许可；不用版权/许可文字污染向量检索。

“完整”指选定文件的原始全文，不表示下载整个官网。图片和关联示例链接仍为上游链接，`eval-rst`/`literalinclude`/动态 API 指令保留为源文本，未展开运行或递归下载。资料包含英文原文，不将中文教学整理标为原文。该批不包含论文 PDF/HTML 抽取、OCR、图像理解或整站镜像。

新增原文在 manifest 显式设置 `document_type=authoritative_original` 和
`chunking_strategy=markdown_structure_v1`。loader 校验原始快照及派生 md 哈希；篡改或缺失会在 SQL/Chroma 写入前拒绝。未启用新策略的旧教学模块保持原 `recursive-v1`、500字符/100重叠及旧元数据，84个切片ID用冻结fixture验证不变；顶层清单版本保持2.3.0，新增原文使用明确的上游commit作为source_version。

结构切分识别代码围栏外的真实 H1–H6 标题；按章节、段落组织内容，普通长段落沿用长度兜底与段内重叠，不跨章节。代码围栏和管道表格单独保留，可以超过500字符目标；超过12000字符或代码围栏不闭合则拒绝入库，不静默截断。`oversized_block` 可识别超目标片段。字符边界不等于token边界，Embedding/精排模型仍可能截断长代码；本轮没有提高模型512 token上限。

原文使用 `section_knowledge_points` 标注真实标题路径，最长匹配路径优先，子章节可继承最近祖先映射，也可用空列表明确排除；找不到映射则保持空，不强行凑节点。映射仍写现有Chunk—节点关联表，不新建第二套标签系统、不调用LLM推断。旧模块仍沿用文档级标签。定位的 `section`/`line_start`/`line_end` 对应 normalized md，原始文件通过snapshot/hash反查，不伪称为PDF页码。映射或来源说明变更仍受现有不可变版本约束，不应直接覆盖已入库的版本元数据。

复现命令（仓库根，已有项目依赖）：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_authoritative_sources.py --check
# 仅文件尚未准备时联网下载固定版本；拒绝覆盖有冲突的本地文件
.\.venv\Scripts\python.exe scripts/prepare_authoritative_sources.py
# 完成备份、确认无运行任务后才对账实际库
.\.venv\Scripts\python.exe scripts/ingest_knowledge.py --knowledge-base-id rag_engineering_training
```

检索继续使用现有BM25＋向量召回、RRF和CrossEncoder，不因增加全文而把所有资料放进Prompt。当前向量同步仍是全量原地替换，不是影子索引原子切换；运行前应停下该项目Web/Worker并备份SQLite和Chroma。首批不建设语义去重、父子块回填、新查询API或全量来源扩容。

### 7.3 完整论文与长教程批量扩容

2026-10-26 在首批三份原文之后，增加 **18份完整来源**：6篇ACL正式论文全文（100个物理页）、10份官方教程文档源文件和2份完整Python实现。原始PDF与文档字节均保存，不以摘要替代正文。

| 原始论文 | 物理页数 | 出版方固定来源 |
|---|---:|---|
| Dense Passage Retrieval for Open-Domain Question Answering | 13 | `2020.emnlp-main.550` |
| Precise Zero-Shot Dense Retrieval without Relevance Labels（HyDE） | 16 | `2023.acl-long.99` |
| RAGAs: Automated Evaluation of Retrieval Augmented Generation | 9 | `2024.eacl-demo.16` |
| Enabling Large Language Models to Generate Text with Citations（ALCE） | 24 | `2023.emnlp-main.398` |
| Lost in the Middle: How Language Models Use Long Contexts | 17 | `2024.tacl-1.9` |
| Searching for Best Practices in Retrieval-Augmented Generation | 21 | `2024.emnlp-main.981` |

上述ACL原文采用出版方PDF，保留作者、题名、出版年份与原有版权信息；许可依据及CC BY4.0链接见 `sources/bulk/licenses/ACL-CC-BY-4.0`。其他12份仍来自首批相同固定commit的LangChain（MIT）与Sentence Transformers（Apache-2.0）官方仓库，主题包括：

- RAG/检索架构、PDF语义搜索与RAG完整教程；
- HTML结构切分、Docling文档加载；
- Sentence Transformers Embedding接入、Chroma生命周期与检索；
- Elasticsearch稠密/稀疏/BM25检索策略、CrossEncoder精排；
- 完整Embedding训练手册、MS MARCO训练；
- FAISS近邻检索及Bi-encoder＋CrossEncoder两份完整实现。

新增规范正文共 **521,333个非空白字符、约83,250个英文词**；包含代码、链接、引用和参考文献，不能当作中文字数或纯教学正文词数。连同首批，21份权威原始资料的规范正文共546,686个非空白字符、约87,190个英文词。6个教学模块另外保留。源文件集合现为27份文档、1710个切片；原179个切片及完整metadata保持不变，新增1531个。2026-10-26本地入库已ready，SQL/Chroma全部1710个ID、正文和元数据一致、活动节点映射4011条；100个物理页和全部行号可回读，18来源关键词冒烟通过。实际其他环境状态仍需查看入库报告，不能仅以文件数推断已上线。

路径相对 `knowledge_base/rag_engineering_training/`：

- `sources/bulk_catalog.json`：18份固定URL、sha256、官方commit、题名、初始主题和许可位置；不支持任意URL导入。
- `sources/bulk/originals/`：6份完整PDF及12份完整上游源文件；原始hash必须匹配目录。
- `sources/bulk/normalized/`：可检索派生Markdown。论文逐页保留全部可抽取文字及参考文献/附录，标记物理页，不生成摘要/翻译；实现文件完整围栏封装，不执行代码。
- `sources/bulk/bulk_registry.json`：原文/派生hash、下载时间、转换版本、100页范围与核对摘录、章节/页主题标签、格式限制和可追加的manifest spec。

PDF转换固定使用已有锁定依赖pypdf5.1.0。新增 `page_spans` 显式记录连续的物理页号和规范正文行范围；loader只对新PDF投影该字段，切片器按范围分段后再递归切分，不能跨页。PDF正文里的`#`、围栏或Prompt例子不被猜成Markdown结构。`page` 经既有SQL字段、Chroma、Evidence和SourceRef保留，`source_type=pdf`；`source_path`/行号仍指向派生md，原PDF由`source_snapshot`反查。页范围错位、缺页、越界、原文/派生hash不符均拒绝入库。

教程章节使用真实ATX层级（忽略代码内伪标题）映射节点；论文页使用来源主题与显式规则辅助标注，参考文献纯页不强行补标签。覆盖报告显示13个节点均有本批来源映射，但这不等于每个细分知识点都完整覆盖，也不等于所有标签经过逐片人工审核。训练手册有一个约14KB的`eval-rst`容器，派生文本按原有架构tab边界拆成5个完整块，不截断内部代码；原文件不变，转换版本及警告单独记录。

已知限制：

- PDF文字抽取不等于OCR/多模态理解；双栏、公式、复杂表格和图像以原PDF复核。抽样渲染检查每篇首页及代表性第4页，不声称逐页视觉验收。
- LangChain语义搜索教程的4个UI组件导入和精排页的维护状态组件未展开，注册表有明确警告；保存的是完整上游文件，而不是整套官网依赖或所有链接内容。
- 英文原文为主；未执行真实生成模型的中文教学质量评测。长代码/文档块虽完整保留，现有Embedding、512-token精排上限、最多8条Evidence及摘录预算未扩大，仍可能发生模型侧截断。
- 官方源固定commit不等于项目依赖版本：部分教程使用更新的上游SDK。示例是未经执行的学习材料，应按原文版本理解，不能直接替换当前项目代码；本轮未安装示例依赖或运行其程序。
- 本批是经过选择的21份原始资料，不声称旧清单23个来源URL都已逐一全文收录；未改变生成、审核或Claim策略，也未实现父子块回填/语义去重/影子索引切换。

离线复核与准备（仓库根，使用项目已有环境）：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_authoritative_sources.py --check
.\.venv\Scripts\python.exe scripts/expand_authoritative_sources.py --check
# 缺文件时只下载固定来源；匹配快照/验证缓存复用，冲突不覆盖
.\.venv\Scripts\python.exe scripts/expand_authoritative_sources.py
```

真实库扩容必须先停下本项目Web/Worker并完成SQLite/Chroma/源文件备份；T7使用既有Service的免初始化入口，不运行会调用`init_database()`的通用入库CLI。除目标知识库九张目录/版本/映射/索引表外，其他业务表及其他知识库记录按完整行集合摘要与数量保护，不以行数相同代替内容相同。短时专项报告位于 `output/test-runs/kb-bulk/`，并不等于全量、CI或真实模型质量验证。

### 7.4 官方中文完整资料扩容

本批收录范围由 `sources/chinese_catalog.json` 固定：35份完整官方中文说明/章节/Notebook，而非四个网站的所有页面。原有21份英文原始资料与6个教学模块保留。35份已完成原文/许可/规范正文准备与离线校验，共51559汉字、353795非空白总字符，新增1470切片。2026-10-26本地已实际入库ready：62文档、3180个SQL/Chroma活动切片、7896活动节点映射，13个能力节点均有新增资料映射；原1710切片ID/正文/完整元数据及原27份spec保持不变。

以上收录统计和入库/metadata 对账结论均为 T8 历史快照。T9 将原件、正文与许可直接移动并更新 metadata 路径；原始正文 bytes、Chunk ID 和 Chunk text 保持不变，但 `source_path`、`source_snapshot`、`license` 等完整 metadata 已使用新物理路径，旧 SQL/Chroma 仍保存旧路径值。因此不能把 T8 的完整 metadata 一致性外推为 T9 当前状态，也不能用相同知识库版本直接 reconcile 并覆盖不可变旧 metadata。

| 官方来源 | 本批范围 | 语种来源与许可 |
| --- | --- | --- |
| [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) | BGE中文说明1份 | 项目官方中文说明；MIT |
| [MinerU](https://github.com/opendatalab/MinerU) | 完整中文说明、解析使用、输出协议、SDK/API、运行档位、RAGFlow/Dify文档9份 | 项目官方中文资料；MinerU自定义许可（Apache-2.0加附加条款），不是纯Apache |
| [Milvus官方文档源](https://github.com/milvus-io/web-content) | RAG、调优、混合/全文/多向量检索、模型重排、图/多模态RAG、管道10份 | 官方中文译本；Apache-2.0 |
| [Hugging Face Cookbook](https://github.com/huggingface/cookbook) | 高级RAG、评测、来源高亮、非结构化解析、重排、知识图谱、多智能体、语义缓存等15份完整Notebook | 官方仓库zh-CN译本；Apache-2.0 |

规范正文统计（含原文题名、代码、链接；不含Notebook outputs，汉字与总字符不是同一单位）：

| 来源 | 份数 | 汉字数 | 非空白总字符 |
| --- | ---: | ---: | ---: |
| FlagEmbedding | 1 | 2104 | 12759 |
| MinerU | 9 | 8561 | 76103 |
| Milvus | 10 | 15336 | 129531 |
| Hugging Face | 15 | 25558 | 135402 |
| 合计 | 35 | 51559 | 353795 |

15份Notebook共569个cell，Milvus格式转换保留193个代码块和5个表格。6处data:image引用在派生正文转为原文件图像提示，原Notebook完整保存；复杂图像和表格视觉布局仍应回原始文件复核，不声称多模态内容已无损文字化。

**MinerU来源与许可披露：本项目使用MinerU官方中文文档作为教学知识来源，不表示已安装、集成或运行MinerU软件，也不代表上游背书。** 完整自定义协议随资料保存于 `sources/chinese/licenses/mineru/LICENSE`，其引用的完整Apache-2.0正文另存 `sources/chinese/licenses/Apache-2.0`。协议包含高规模商业使用门槛及基于MinerU提供在线服务时的显著标识义务；后续若实际集成/部署，须按完整协议重新检查，不能把本次资料收录当作免除条件的依据。每家许可与归属说明均在`licenses/`保留。

资料处理与边界：

- `sources/chinese/originals/*.source`保存固定commit的完整原始文件；`normalized/*.md`为格式派生正文；`registry.json`记录双hash、题名、语种来源、许可、转换版本、正文统计、Notebook全部cell来源摘要和未纳入的output数量。原始文件和许可不使用md/txt扩展，不会重复索引。
- Milvus的.md实际上含HTML。使用不执行内容的标准库解析器去掉按钮/SVG/脚本/样式等UI噪声，标题、段落、列表、完整代码及表格转为Markdown；原HTML不修改。中文目录里的全英文重排序页被语种门禁拒绝，改用同版本真正中文的模型重排序章节，不自行机器翻译冒充原文。
- Notebook提取全部Markdown、代码和raw cell，不执行任何代码，不复制outputs至检索正文、不下载外链图像/数据集/模型。内嵌data:image在派生正文保留alt并指向“原Notebook内嵌图像”，不把base64作为正文；完整原Notebook保留所有字节。相对Markdown链接在非代码区域解析到官方固定版本。不能把派生正文称为包含全部执行输出和媒体的无损镜像，也不能声称已对图片OCR。
- 正文按既有500字符目标、100 overlap和结构策略切片，代码/表格原子块硬上限12000字符不变；不改变Embedding、reranker、生成模型、检索算法或上下文预算。资料中的SDK/产品版本与本项目可能不同，未经本项目环境逐例执行验证。
- 中文汉字数统计`U+3400–U+9FFF`范围；总字符数另按非空白统计，包含英文、代码和链接。官方译本不称为中文原创论文，完整章节不代表所有细分知识已覆盖；相似教程仍可能存在语义重叠，本次只排除完全相同文件，不声称完成语义去重。

从仓库根复核：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_chinese_sources.py --check
# 仅准备固定原文及派生资产，不自动修改manifest或业务库
.\.venv\Scripts\python.exe scripts/prepare_chinese_sources.py
```

`--check`离线验证目录、原文/派生正文/所有许可与registry一致性；正式manifest需按registry的`manifest_documents`追加并保持旧spec不变。实际入库仍需停止仅属于本项目的服务，验证成对备份后调用既有IngestionService，不运行初始化/seed。T8操作与专项证据位于`output/test-runs/kb-zh/`；未执行真实生成模型或多语言Embedding替换。

本轮发现并修复的Windows持久化前置问题：锁定依赖`chroma-hnswlib 0.7.6`的原生文件接口在当前CP936环境不能正确处理UTF-8中文路径，可能出现仅保存`index_metadata.pickle`却缺少`header.bin`等二进制文件的情况；SQL的`get/count`可成功，但新进程向量查询失败。`core/retrieval/hnsw_windows.py`只在Windows/该依赖版本启用，在HNSW的init/load调用边界将非ASCII路径严格编码为系统ACP，保留Python侧Unicode路径；ASCII、已有bytes和非Windows不变。不搬存储目录、不改配置或模型、不修改已安装第三方包。系统ACP不能表示的路径字符仍显式拒绝，不能宣称任意Unicode/emoji路径都支持。

兼容适配不会凭空修复已损坏的旧索引：本地仅目标Chroma集合经备份核实后从完整资料重建，SQL正文及旧版本不删除。原损坏备份保留现场，但不能当作已验证可加载的工作索引；工作恢复需使用保留正文和相同Embedding重新reconcile。验收必须在新进程执行向量query，并确认四个HNSW文件存在；单纯ID/count/元数据对账不足以证明重启可用。因涉及共享后端适配，本轮额外执行后端全量回归，结果以最终报告为准。

本地验收结果：78项直接专项通过；路径适配9项通过（含真实中文索引四文件及子进程加载/query）；后端全量988 passed、9 skipped、0 failed，300.48秒，报告`output/test-runs/kb-zh/full-backend-rerun.xml`。初轮24项来源快照漂移在核对51项金标evidence及旧题库/正文不变后显式更新`sources.json`解决，评分门槛和金标未改；一次Edge清理竞态在原样单测及全量复测均未重现，初次失败证据保留。本地向量化1651.08秒（约27.5分钟），与测试耗时分开记录。实际入库smoke通过，独立进程全量对账及新/旧资料向量query通过，35来源持久化正文回读/关键词来源冒烟通过，非目标业务行集合不变。此为持久化/来源一致性证据，不是中文语义召回benchmark、真实生成质量评测或生产就绪证明；未执行真实生成LLM、前端构建或CI，Embedding/reranker/LLM配置未更换。

### 7.5 T9当前物理目录与准备入口

T9 将资料直接迁移到按用途、语言、出版方和文档 slug 组织的物理目录；没有保留 `modules/`、`sources/` 或运行时 path alias。相对 `knowledge_base/rag_engineering_training/` 的当前布局：

```text
README.md
metadata.json
teaching/zh/*.md                              # 6篇项目整理的中文教学模块
references/zh/{flagembedding,mineru,milvus,huggingface}/{slug}/
  original.{md,ipynb}
  content.md
references/en/{langchain,sentence_transformers,papers}/{slug}/
  original.{md,mdx,pdf,py}
  content.md
licenses/{langchain,sentence-transformers,flag,mineru,milvus,huggingface}/
licenses/Apache-2.0
licenses/acl/CC-BY-4.0
provenance/catalogs/{bulk,chinese}.json
provenance/import_batches/{pilot,bulk,chinese}.json
provenance/registry.json                         # 统一资料与资产 hash 清单
questionnaire.json
diagnostic_questions.json
assessment_questions.json
```

manifest 的 `documents[].file`、`source_snapshot`、`license` 直接指向当前物理路径；loader 按 `manifest_only` 读取 manifest 正文，不递归把 `original.*`、许可或归档清单当作教学文档。三个独立 import batch 保留对应来源批次记录，统一 registry 汇总当前文档/资产路径及 hash。旧 `sources/...`、`modules/...` 字符串只用于解释迁移前历史，运行时不再解析这些路径。

从仓库根使用统一准备/离线校验入口：

```powershell
# 只读离线核对 catalog、原文、派生正文、许可、batch registry 与统一 registry
.\.venv\Scripts\python.exe scripts/prepare_knowledge_sources.py --check
# 仅在明确需要准备缺失的固定来源资产时使用；默认模式可能联网并写入资料文件
.\.venv\Scripts\python.exe scripts/prepare_knowledge_sources.py
```

`prepare_authoritative_sources.py`、`expand_authoritative_sources.py`、`prepare_chinese_sources.py` 保留为按来源格式执行的底层转换器；日常准备与离线验收使用上述统一入口。T9 物理移动前备份位于 `output/test-runs/kb-layout-direct/backup-20261026-215648`；移动前 Web/API、Worker 与前端三端均未运行，本次未自动启动服务。

重要兼容边界：直接移动没有重建旧 SQL/Chroma。旧索引仍含迁移前的 `source_path`/快照/许可 metadata；即使物理正文 bytes、Chunk ID 与 Chunk text 相同，也不能声称磁盘新 manifest 与旧索引的完整 metadata 一致。不要在相同 `knowledge_base_version` 下对旧记录执行 reconcile/覆盖；未来更换 Embedding 或切换资料版本时，应先创建新的知识库版本，备份 SQLite/Chroma 后受控重建、对账并切换索引。此目录迁移本身不证明生产部署已就绪。

T9验收结果（2026-10-27）：55项路径/资料专项通过；后端全量1002 passed、9项真实模型评测按配置跳过，0 failed，201.31秒，报告`output/test-runs/kb-layout-direct/full-backend.xml`；相关Python文件Ruff及`git diff --check`通过。原SQL切片完整metadata摘要及全部实际向量值摘要只读核对均未改变，本轮没有重新入库。仅提高metadata.json的version或只清空Chroma不足以处理旧SQL不可变metadata冲突；未来重建应采用隔离的新knowledge_base_id、版本化文档身份或明确的SQL目录迁移方案，并新建匹配模型的向量索引后对账切换，具体方案留待换模任务确定。

### 7.6 六模块教材修订（T10，2026-10-27）

六篇 `teaching/zh/*.md` 改为显式 `teaching-2026-10-v2`，保留13节点与旧编号章节主题。每章增加入门/实现/进阶阅读路径、固定实验输入与预期产物、失败排查、练习答案和10分课堂评分，并给出官方来源ID、相对链接、具体章节/页码及支持范围。课堂分数不自动写入画像。

共用 `teaching/lab_case.json` 的 `rag-lab-v2`：4份合成短文、Q1–Q4，贯穿解析/切片、候选与过滤、RRF手算、Claim核验、指标计算；所有构造排名、分数和政策均非实测或真实业务。该JSON不在文档manifest中，不独立索引。明确字符≠token、裸分≠RRF名次、候选召回≠重排、引用存在≠语义支持、review_unavailable≠passed、HitRate≠多证据Recall；消融从共同V0分叉，组合另列。

当前文件层可派生 **3222片**：56篇权威资料的 **3096片ID/正文/完整metadata不变**，新版教材126片（旧版84片）。旧快照保留为历史，新教材独立冻结在 `backend/tests/fixtures/knowledge_pilot/teaching_v2.json`；重新核对78条旧Claim与51处证据章节后刷新来源行号/hash，不修改Claim文本、标签或门槛。注意旧Claim将单题RR简称MRR，教材已严格区分RR与逐题平均MRR，不把旧简写推广为公式。

**未换任何模型，未入库，未执行真实模型/检索benchmark。** 旧SQL/Chroma仍是迁目录、改教材前的内容与metadata，3222不是已入库数量；不会自动影响当前生成。后续换模与受控重建沿用7.5的隔离、对账和回滚约束。统一registry仅更新文件清单与内容hash，不代表数据库同步。课程备份和人工复核记录位于 `output/test-runs/teaching-v2/`（本地验收产物，不提交）。本轮只做3个指定测试文件及离线资料检查，不用T9全量结果冒充本轮回归。

### 7.7 多语言Embedding与受控重建（T11，2026-10-27）

7.5–7.6的“待换模/未入库”及3096旧官方切片身份不变是T9/T10历史状态。本批换用 **BAAI/bge-m3 dense**，固定commit `5617a9f61b028005a4858fdac845db406aefb181`，1024维归一化，CPU batch=4；不引入其sparse/ColBERT，也不更换生成LLM或CrossEncoder。来源文件、许可、题库、13节点、逻辑文档ID和知识库ID不变。模型卡最大8192token不等于精排模型输入预算，精排截断限制未在本轮扩大；旧分数阈值未作完整校准。

当前manifest顶层新增`document_identity_revision=layout-v1-teaching-v2-m3-20261027`，为新版路径与不可变元数据创建新document_version/chunk ID；未提供该字段的旧manifest继续使用旧ID算法。正文content_hash仍只计算正文，不掺入revision。P0-34给`knowledge_document_versions`增加非空`identity_revision`（历史默认空串），唯一键扩为`(knowledge_base_id, document_id, content_hash, identity_revision)`。SQLite事务重建这一个表，复制历史值、恢复索引并检查FK；不改写旧来源locator，不删除历史版本。当前只验收SQLite，非SQLite明确拒绝该迁移。

运维入口`python scripts/rebuild_multilingual_index.py prepare-model|build|audit`（三个子命令分别执行）：固定模型下载到`backend/data/models/bge-m3/<commit>/`；build用SQLite backup API复制当前库到**新**`backend/data/domain_knowledge_m3.db`，只显式执行P0-34，不调用init_database/其它旧迁移，向**新**`backend/data/chroma_bge_m3/`入库。目标已存在、模型/资料不匹配、前置schema缺失、超模型长度均拒绝构建，不静默覆盖。失败现场保留；脚本不改.env、不自动激活。

审计要求：62文档/3222活动切片（56权威资料3096片＋教材126片），SQL/Chroma精确ID、正文与全部metadata一致，13节点映射覆盖，SQLite完整性/FK通过，旧版本除active/current外的值未变，非知识业务表数据hash不变。audit必须在新进程执行，确认全部向量1024维、有限、归一化，并做约6题dense-only小冒烟；前三题限定英文官方语料，防止中文译文掩盖跨语言方向。build/audit进程临时`RERANK_ENABLED=false`，不调用生成或精排模型，不修改线上精排开关；manifest原有入库smoke仍执行。

报告位于`output/test-runs/kb-m3/`：model.json、lengths.json、build.json、audit.json、source-before.json及短测试JUnit。`backend.env.before`是含本机配置的敏感本地备份，已处于Git忽略目录，不得上传/打印。只有短验收和新进程audit均通过才修改本机.env的Embedding/SQL/向量路径。其他人不能仅拉Git就认为模型/索引已安装。

**本机实际完成状态（2026-10-27）**：模型固定快照已下载并本地encode验证；3222片最长3816token，超8192的片段为0。影子入库ready，62文档、3222 SQL活动片、3222向量片、原有2条manifest smoke通过；新进程audit精确内容/metadata、全部向量有限/归一化、13节点覆盖、SQLite完整性/FK、旧62文档版本和3180片段版本保留、非知识业务数据（含117条学习状态、1条状态变更）hash校验及6条dense查询均通过。随后本机.env已切换到固定模型绝对路径、新SQL和新向量目录，batch=4/local-files-only=true；其余配置（含生成LLM/精排）逐键比较未变。本轮未启动Web/Worker，下次启动读取新库。

短验证为4文件42个不同用例：首轮41通过/1失败（27.74秒），迁移修正保留旧SQL字段默认值后仅复跑该失败用例，1通过（2.30秒）；其余41项未在修正后重跑。指定改动Python的Ruff、离线来源校验（10.03秒）、最终布局/差异检查通过。按用户要求未跑后端全量、浏览器、生成LLM或精排实测；这不是正式质量benchmark，不能据此宣称中文教学质量提升百分比。日志中的Chroma telemetry参数兼容和LangChain弃用警告不影响本次审计结果，本轮未为此升级依赖。

历史fixture保持：`teaching_v2.json`及原pilot/bulk等是旧身份epoch；测试显式投影去掉revision再比较原文与历史metadata摘要，同时`teaching_v2_m3.json`和`multilingual_index.json`独立冻结本批新身份及完整metadata，不能把新ID冒称旧ID。competition仅更新metadata来源hash，Claim正文/标签/证据主题/门槛不变。

回滚需停Web/Worker，将Embedding/SQL/向量路径及manifest revision同组恢复；旧SQL/Chroma没有被清空。保留旧schema原件时，须使用匹配旧schema的应用版本，或再复制旧SQL到新回滚文件、只在副本上显式执行P0-34后配旧模型/向量和旧manifest epoch，不让新代码启动链隐式升级旧原件。`metadata.before.json`仅移除本批新增两根键，保留T10六章教材，不退回更早教材。旧chunk正文/locator仍能SQL回读，但已迁移的旧物理路径不保证还能打开原文件。切换后若新增学习记录，不能直接指回旧DB丢弃新数据，须先迁移增量。本轮短验证不构成全量回归、正式质量benchmark或生产就绪证明。

### 7.8 跨语言候选保留与术语扩展（T14）

新配置`query_aliases.json`是知识库运行时配置，不是权威原文或教学正文，不加入documents、不切片/编码/入库。T14最初RAG库含17条有界术语规则（T16细化后的当前规模见7.9）：最长词/拉丁边界匹配，非对称不误扩为对称；通用RAG与HyDE、通用Embedding与非对称/编码术语分开，避免强加未请求主题。最多6条规则合成1条不超过400字符的英文关键词probe，不是完整翻译；纯英文/无匹配/缺失/非法词表不扩展，有明确状态和配置hash。核心模块不硬编码RAG词表。

默认`RETRIEVAL_BALANCED_CANDIDATES_ENABLED=true`、`RETRIEVAL_DENSE_RESERVE=10`：每原query保留其真实dense候选并可增加1个英文probe，同一allowed/节点范围始终适用；全局跨query轮询保留最多10条语言无关dense候选，再按RRF补足20预算，避免先各截10、合并时再次丢掉dense结果。精排始终使用原query而非英文关键词，输出query/node归属不变，去重、SQL历史/哈希门禁和阈值不变。精排禁用时不做alias，失败/不可用时只使用原query候选，不能用alias-only关键词高分直接放行。alias失败不抹掉原query正常结果，原query失败仍记录partial/error。

策略版本与词表/选择参数进入Evidence config_hash；profile记录状态、版本、hash、预算计数和有界probe阶段指标，不记录全文query或正文。所有公开请求/DTO/认证/状态码不变，无需重建3222切片或替换模型。关闭新开关并重启可回旧选择策略；dense reserve必须<=现有全局精排预算。单query精排可能从10增加到20，不能宣称没有额外时延。

本地小冒烟只比较2条中文问题（非对称语义检索、HyDE），在临时索引副本上用相同模型各跑旧/新选择。两题进入精排的英文候选均从0/10变为11/20，目标英文官方源均不再被提前淘汰；所有输出仍关联原query且无重复，临时副本已清理。**两题最终前三仍为中文资料**，不能声称英文引用率或总体准确率已提高；本轮解决的是候选阶段机会不足，不强行按语言插入结果。记录见`output/test-runs/cross-language/local-smoke.json`，不是正式benchmark。

### 7.9 基于原始资料的术语细化（T16）

`query_aliases.json` v1.1.0从17组/84触发词细化为**124组/679种触发写法**，其中407种含中文、272种为英文术语/标识符。原有84种写法全部保留，迁入相应细组；它是概念多对一的检索别名配置，不是679个独立概念或自动翻译系统。每组英文输出短而有界；规则总量仍受128/64KiB限制，每规则最多16触发词、英文组160字符，单问最多6组/400字符/1条probe，未提高候选或精排预算。

覆盖基础架构、文档解析/OCR/结构输出、16类分块相关概念、嵌入/编码/距离/近邻、存储过滤、词法与融合、查询增强、精排训练、上下文证据、评测调优及语义缓存。新增“嵌入、切片、交叉编码器、倒数排名融合”等中文表达；BM25、RRF、词面、稠密、稀疏和中性向量检索分开，Recall、MRR、NDCG、HitRate、Precision、引文/主张指标也不再共用一串英文。泛称“向量检索”不强制扩为dense；泛称“覆盖率”不强制等同Claim Recall。对称/非对称依既有最长非重叠匹配处理，允许显式比较二者；不新增全局排除误伤比较问句。

逐组出处位于[query_aliases_sources.json](../knowledge_base/rag_engineering_training/provenance/query_aliases_sources.json)：34份manifest声明的权威原始资料（16份中文、18份英文），使用其`content.md`规范化原文定位，绑定document_id、anchor_text、原始快照/原文hash和正文hash。原始快照仍是`original.*`，逐字定位基于可检索正文，不把PDF二进制当文本匹配。中文别称为人工等价表达，项目兼容标识符如source_ref/Claim review不宣称是原文API。来源记录及词表都不进documents、不形成新切片；统一registry维护其文件hash。

示例：“BM25是什么”只增加BM25相关关键词，不顺带指定RRF或dense；“倒数排名融合”扩为`RRF reciprocal rank fusion`；“按token分块”对应token-aware splitting，不改写为字符分块。没有命中仍只用原问题，原问题/节点与allowed范围/中文精排/禁用失败回退保持原有契约。配置每问读取，新version/hash随下次检索自然生效，不需重启或重新编码；正在执行的请求不保证切换。

边界：别名扩展不实现词条所命名的OCR/MMR/训练/缓存等算法，不自动理解整句否定、数字约束或未知长尾词，不保证英文占比或答案质量提高。“覆盖率”“幻觉率”等兼容泛称不定义统一公式。T15仅4题的完整翻译对照最终前三相同，不是本批扩表收益实测；本批只做规则/来源/布局短验收，不调用LLM、下载模型、实际检索或生成资源，不改SQL/Chroma/原文/教材/manifest及13节点。

本批仅运行术语与布局2个测试文件，23项通过（17.93秒），验证逐组原文定位/hash、84旧写法兼容、124组各一中文触发、误匹配/上限及62文档布局；测试文件Ruff、git diff --check通过。真实SQL/Chroma 7文件前后SHA一致。结果与命令记录于`docs/update_plan/T16.md`及`output/test-runs/query-aliases-v2/`；源配置备份可用于按本批范围回滚，不能撤销既有其他修改。文档所述规模不是正式评测成绩。当前已占124/128组，后续扩充必须先校验容量，超过128组会使整份词表显式降级，而不是只忽略多出的规则。

### 7.10 英文选材加权与单query Top-6（T17）

本批默认`RETRIEVAL_TOP_K_DEFAULT=6`，显式请求constraints.retrieval_top_k仍覆盖默认（1..10）；全局证据最多8、精排池20、原相关性门槛0.35不变。`RETRIEVAL_ENGLISH_SCORE_BONUS=0.08`是可关闭的温和起点（有限0..0.25），不是已校准最优值。成功CrossEncoder且原相关性达门槛、SQL可信来源为规范`references/en/...`时，选材分为`min(1, original_normalized_score+bonus)`；低分英文、中文、未知/非法路径及禁用/降级不加。仅提高合格英文参与最终选材的机会，不保证每问有英文。

加权前对完整20候选池调用EvidenceRetriever提供的SQL身份/正文hash/active验证回调，覆盖不可信向量路径后才精排与截取前6。适配器无可信回调时不加语言分，Chroma自带的verified标记不被信任。最终Evidence再次校验、按SQL locator重算选材分；跨query合并、节点保底、去重及节点证据排序一致使用选材分，防止后续按原分重排抵消偏好。HTTP/DTO字段、来源/权限边界和错误契约不变，不写SQL或重建索引。

原始`raw_score`、`rerank_raw_score`、`rerank_score`、`normalized_score`、历史`final_score`及`rerank_rank`语义保留；新增selection_score/selection_rank/source_language/language_bonus，只是选材偏好，不是正确概率。config_hash绑定新策略`english-relevance-bonus-v1`及bonus/路径判定/原分门槛，旧Evidence不改写；内部profile.evidence_selection记录最终证据原分/选材分和有效加分（不含正文或query）。bonus=0回原相关性选材；TopK=3另需显式配置才能恢复旧返回数量。

“取前6”不等于模型一定收到6条：返回项还要过原始分数、SQL、节点与全局8条预算，进入prompt也不保证最终被引用。此前T16只是检索返回前三检查，非完整生成输入。T17只做4文件定点测试与同4问本地离线模型小检查，实际合格证据通过只读SQL校验；同一20池的无加分/有加分、Top3/Top6重算不额外推理，不冒充独立模型实测。定点100项通过（4.96秒）；实际每题返回6，校验后证据3/4/5/1、英文1/0/0/0。英文返回总数1→3但合格英文未增，不能宣称英文采纳率改善；未生成答案。Web/Worker已空闲重启，宿主健康检查通过，前端复用。结果和覆盖边界见`docs/update_plan/T17.md`及`output/test-runs/english-selection/`。

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

Embedding 按模型名与本地加载配置缓存进程内实例，冷加载由锁保护，避免并发生成
重复初始化 Transformer 权重；失败不会进入缓存，后续请求可重试。编码推理不持有
初始化锁。该缓存只在单个进程内共享，重启后重新加载。

`learner_curriculum_nodes` 初始化在 SQLite 中使用针对
`(learner_id, knowledge_base_id, skill_node_id)` 的原子冲突忽略，同一节点被并发请求
时只写入一次，并保留原有学习进度；外键等其他错误仍会抛出。保留的 PostgreSQL
方言采用相同冲突目标，但不代表已完成真实 PostgreSQL 部署验收。

当前知识链路采用“候选范围 → 候选排序 → 证据认定”三层：

1. 请求含 `target_skill_nodes` 时，先从 `knowledge_chunk_skill_node_mappings` 查询同一知识库、活动 Chunk 的映射并取多节点并集；不含目标节点时直接从全库开始。
2. 节点范围内的 Chroma 向量召回和 BM25 关键词召回共享同一 `chunk_id` 白名单，RRF 融合与可选 CrossEncoder 也只处理这一范围内的候选。
3. 节点范围没有映射，或结果为 `no_hit` / `evidence_insufficient` 时，用相同查询和既有 policy 执行一次全库混合检索；节点范围发生底层检索错误时不回退，避免把故障误报为正常结果。
4. EvidenceRetriever 根据 SQL 中的 active Chunk、document_version、KB 范围和 text_hash 做最终校验。全库回退仍不足时，沿用 Evidence Gate，事实型生成不会继续。
5. 只有校验通过的候选生成稳定 Evidence ID，并在 Agent Run 中保存不可变 snapshot；Generator 的 SourceRef 只从 Evidence 代码侧绑定，不接受模型或 legacy chunk 自行声明来源。

检索 profile 与 trace 记录 `node_scoped`、`global_fallback`、`global` 或
`evidence_insufficient`，并保留映射候选数和回退原因。它们用于运行审计；公共资源
API、前端资源来源展示和 Evidence/Claim 的多文档结构没有变化。

模块级映射是候选范围优化，不是“知识越多越不会幻觉”的保证。它减少无关上下文混入
的机会，但最终可靠性仍依赖证据数量/相关度门槛、版本与哈希校验、Claim 审核和发布
门禁。

本地真实链路验证（2026-08-29）以当前 SQLite 快照的副本回填映射、读取现有 84 条
Chroma 索引，依次测试了 13 个真实能力节点：13/13 返回 `available` 且最终来源为
`node_scoped`，每次得到 6 个候选和 1～6 条有效 Evidence，CrossEncoder 均可用。
另以无映射目标验证了 `global_fallback`，得到 6 个候选和 4 条有效 Evidence。该结果
证明当前本地数据链路可用，不等同于对真实用户问题、生产并发或长期幻觉率的统计承诺。

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

## 13. 后续迁移与当前状态核对

当前初始化链还装配课程进度 / 学习阶、复习清单 V2、实操指南 JSON、掌握证据门禁、测评维度、准入重新验证、反馈多 Run、用户 Claim 发布决定、审核状态及 `p0_33_chunk_skill_node_mappings`、`p0_34_knowledge_identity_revision`、`p0_34_generation_dispatch`、`p0_35_report_read_model` 等迁移，并包含 Tutor 和课件迁移。两项p34职责不同，知识身份revision先于生成调度迁移，保留已应用的知识迁移ID；不能按编号重复而覆盖其中一项。具体顺序与 migration ID 以 `backend/app/db/shared/database.py`、`backend/app/db/migrations/` 和 `backend/app/db/courseware/migrations.py` 为准。

迁移写入由初始化 / 应用 lifespan 显式触发；只读文档核对不执行初始化、回填或真实库演练。当前前端样式和布局优化继续使用上述既有表和 API。实际数据库是否已升级不能从源码、文档日期或浏览器 fixture 推断，验收应记录目标库的 `schema_migrations`、完整性预检和受控副本演练结果。


## 14. P0-35 报告读模型

SQLite additive 迁移 `p0_35_report_read_model` 新增 `report_read_watermarks`、81个来源触发器和5个报告索引，不修改/重命名/回填原学习事实。水位唯一 `global` 行保存 `installation_id`、覆盖 `protocol` 和单调 `epoch`。27张来源表覆盖画像、资源/任务、旧反馈、正式 Attempt/point results、decision/mutation/profile versions/path/nodes/path mutations/followup、diagnostic、mastery events/states/curriculum/tier、review/Claim/judgement/evidence、skill nodes/relations 和知识目录三表；精确表名/列清单以 [watermarks.py](../backend/app/db/reports/watermarks.py) 为准。新增来源/投影依赖须同步清单与协议。

INSERT/DELETE 计数，UPDATE 仅在受监视列实际变化时计数；generation job 的 claim/lease/dispatch 运维列不触发报告失效。直接 SQL、旧时间戳修订、删除同样覆盖，事务回滚会同时回滚 epoch。全局水位保证保守失效，可能因其他学习者写入多做一次重建；它不携带学习者内容。每次缓存读取验证水位协议与完整触发器定义，缺失/未知时安全回到完整读取。重复迁移保留有效身份；修复触发器/协议或 rollback 后重装生成新身份。

索引服务资源 learner/publication/published_at/id、parent、run/type、Attempt 稳定时间/id排序及最新审核。SQL 分页只装载页资源，正式 Attempt 明细按500分块读取；报告聚合不再截断到10000，默认仓储 `limit=20` 仍保留。

回滚入口 `rollback_p0_35_report_read_model_migration(engine)` 仅删除本迁移拥有的触发器/索引/水位表，保留所有业务表与事实，读路径随即无缓存降级。维护命令和先停写/备份要求见 [部署文档](deployment.md)。本次仅在隔离合成/旧结构数据库执行迁移与回滚；未对实际业务数据库执行。

## 15. 远程E1与本地跨语言检索整合

E1仍默认关闭；开启时先保留公共节点/资源用途，再在剩余20条预算与每query配额内保护dense候选，可能不足10条并记录`dense_reserve_shortfall`。SQL全池校验同时支持query bindings，英文选材偏好保留，原始相关性、owner query与冻结Evidence分配不变。精排降级时alias-only匹配不能赋予资源用途。接口与审计字段详见[API说明](api.md)。

本次同步仅在真实库的一致性副本验证初始化链与重复执行，未升级真实数据库、重建向量或修改本机`.env`；恢复运行前需按当前部署文档受控初始化，并同时启动文本生成Worker（8082）及原有课件Worker（8081）。

## 16. 内容级去冗余（T19）

位置：候选通过SQL身份/版本/hash/active校验及原相关性门槛后，先按既有英文选材分排序，再去冗余，最后执行节点保留/E1用途分配与全局8条截断。每query返回Top6及20条精排预算不变；补位只使用这次返回的其他合格候选，不追加检索、不用重复/低分凑满条数。

默认`RETRIEVAL_REDUNDANCY_ENABLED=true`；至少160字符的SQL全文参与。NFC/空白归一化后的全文相同可跨来源去重（代码/表格保留换行与缩进）；近重复只比较同文档、同版本、同章节，长度比至少0.85，5字符shingle Jaccard默认至少0.90。数字、否定词或比较运算符签名不同时不作近重复合并，代码/表格也不作近重复。它是保守词面规则，不是语义等价证明，不识别中英文译文之间的重复，短定义继续保留。

按原优先序保留强者，仅当一个已保留重复项覆盖当前项全部节点/资源用途时才抑制当前项。独有用途保护，不能把被删项的query、node或Evidence ID搬到代表项；被抑制项同步退出节点候选，防止后续复活。原文/教学卡/SQL/Chroma及历史Evidence不删除、不重写，不改变相关性分与门槛。少于最低独立合格证据数时沿原证据不足门禁，不用重复内容补数。

内部`retrieval_profile.redundancy`记录输入/保留/抑制/覆盖保护/近似比较次数，以及最多20条chunk-ID删除原因、代表ID与相似度；不记录正文。开启时`config_hash`绑定算法/阈值/固定参数，关闭时省略新增hash键以保持原兼容。关闭设置或阈值调整需Web和两个Worker空闲重启；无需换模型、入库或数据库迁移。当前运行进程未由T19自动重启。

## 17. 公开来源上限与知识库字数快照（T20）

新生成文本文档的`source_refs_from_evidence`默认最多5条（此前3条），按资源已分配Evidence顺序投影。前端SourceRefList逐条展示，无额外3条限制；来源不足则少于5条，也不保证来自5篇不同文档。原分/身份/E1范围、Top6/总证据8不变；内部显式limit仍优先，Tutor预算不变。旧资源的持久引用不回填，Web/文本Worker空闲重启后新生成资源采用新上限。

2026-10-27只读统计：manifest唯一启用正文路径与当前SQL `knowledge_document_versions` enabled/is_current的62行路径及content_hash全部一致。按入库的NFC/换行/行尾空白规范化正文统计，不重复加original快照或重叠chunk，不计metadata、题库、术语表、许可等辅助文件。字符包含Markdown、代码、标点和空白；汉字单独统计，不能把中文资料中的英文/代码也称为汉字。

| 分组 | 篇数 | 汉字数 | 正文总字符（含空白） | 非空白字符 |
|---|---:|---:|---:|---:|
| 中文权威原文/译本 references/zh | 35 | 51,559 | 420,412 | 353,795 |
| 中文教学模块 teaching/zh | 6 | 23,853 | 44,971 | 41,226 |
| 中文资料合计 | 41 | 75,412 | 465,383 | 395,021 |
| 英文权威原文 references/en | 21 | 28（少量中文标签） | 647,494 | 546,686 |

统计脚本与结果：本地忽略目录`output/test-runs/source-limit/count_corpus.py`、`corpus-counts.json`；此快照不随以后新增资料自动更新，亦不是去掉代码/Markdown后的纯自然语言词数。

## 18. Tutor生成契约（T21部分回退后）

按用户要求已撤销每轮补检索、独立支持审核、确定性正文拦截、双阶段预算与前端来源折叠；恢复Frozen Evidence→SourceRef→仅缺失时Ready知识库检索的原顺序。只保留生成契约，不宣称已解决所有超范围乱答。

内部生成契约允许`evidence_insufficient`+空引用；服务端保存固定安全拒答、空来源及原状态。正常动作仍必须有合法引用，幂等/权限/画像不写副作用不变；不新增表/公开状态，不覆盖历史turn。引用ID合法不等于事实支持已审核。

保留Prompt正文与引用分离：不主动报内部证据库存、ID或路径，输入最小化为id/title/snippet，引用仅放结构字段。前端来源恢复原直接展示，不再有正文确定性拦截或独立审核。

恢复单阶段生成25秒/4096输出tokens和原网关重试/修复语义；auto预先选JSON文本并严格schema解析以兼容当前接口，显式模式/其他Agent不改。没有换模型、入库或SQL/Chroma变更；回退前审核测试不代表当前仍有审核能力。

后续T22按用户要求单独将Tutor来源展示设为默认收起，可主动展开查看，来源数据/数量和后端逻辑不变；不恢复此前已撤销的独立审核或每轮补检索。

## 19. 单份资源重生成的存储增量（T23）

不新增表、不重建知识库/向量索引。`generation_jobs` 已有 dispatch_snapshot JSON 保存服务端构造的 `ResourceRetryContext v1`：源 Run/spec/checkpoint hash、冻结画像/请求、诊断/计划、源 spec/Evidence/分配、可选旧正文、该份审核反馈及 context_hash；公开请求不能提供此可信输入。分发版本为 `learning_documents.resource_retry.v1`，重启后从持久化快照读取，不依赖进程内变量。新任务使用既有事务和幂等提交，同 batch，不覆盖源失败记录。

新 `agent_runs` 请求快照记录源 ID/hash lineage；`agent_steps` 首节点为 reuse_context，导入证据存入新 Run/step 的 `retrieval_evidence_snapshots`，保留原 excerpt/locator/文档版本/原分/config hash，重新生成 evidence_id/snapshot_hash。E1 仅投影所选类型的公共/专属证据并重算绑定 hash。`resource_specs` 使用新 spec ID、原 family；`generated_resources` 为新 ID、version+1、parent_resource_id（无旧正文则 v1），原资源、审核和 Claim 不变。新审核与 Claim 只引用 child Run 的新 Evidence，不拿旧判定充当新审核。

历史 Evidence 只存 query_hash；若旧 SourceRef 留有且 hash 匹配，则恢复原查询，否则显式显示“历史检索文本未持久化，仅保留哈希”，不重新检索或伪造查询。缺少可信 dispatch/checkpoint/证据/版本关系时拒绝局部重试（409），旧记录仍可读取。API 和重启/回滚边界分别见 [API 文档 9.7](api.md) 与 [部署说明](deployment.md)。

专项测试：`backend/tests/unit/services/test_resource_retry_service.py` 覆盖冻结准备、幂等、权限/状态码、事务回滚与 worker/background 快照恢复；`backend/tests/integration/workflow/test_resource_retry.py` 覆盖五类资源、legacy/E1、Claim 开关、无上游重跑，以及临时 SQLite 的 RecordedNode/Evidence/spec/版本/Claim 存储闭环。均为离线固定模型响应，不等于真实生成质量验证。

## 20. 官方HTML正文清洗（T24）

清洗范围为35篇中文官方资料中10篇HTML转换正文：`prepare_chinese_sources.py` 删除仅剩徽章的空标签链接，代码围栏外最多保留一个空白行。共移除10处空链接和2659个多余空白行；标题、有效文字链接、代码内部空白、表格/列表及全部original原始快照保留。其余25篇中文、21篇英文和6份教材不作语义改写。parser仅对正文确实改变的10篇升级为`official-zh-structure-v2`，不更新未变正文的不可变metadata。

当前文件可派生62文档、3214切片（英文1626、中文1462、教材126），相对清洗前3222少8片；这不是删除8段教学知识，而是清洁正文重新按原500/overlap100分块的结果。英文冻结切片hash不变。中文批次registry、metadata与统一registry的派生正文hash同步；原始来源commit/hash、许可和模型不变。

显式`--refresh-derived --receipt <新目录>`先校验旧清单/源hash，再备份后原子刷新派生资产；默认prepare仍拒绝覆盖冲突，`--check`仍只读。`refresh_cleaned_knowledge.py --apply --receipt <新目录>`是停服务维护工具，保留SQL旧版本和冻结Evidence，复用完全相同正文/分块配置且已验证同embedding profile的旧向量到新chunk ID，只重新编码真正变化的正文。维护前必须索引ready、SQL/Chroma旧ID/正文/数量精确一致，且有持久profile或已核实历史建库receipt；无法证明时拒绝复用。

清洗后是新document_version/新切片，不改旧Run中被冻结的脏片段。已有Run详情仍如实展示当时证据；T23单份重生成复用旧证据，也不自动获得清洗后的片段。需要发起含新检索的完整生成/追加流程，才能使用新知识版本。不得为美化历史截图而改写原Evidence/hash。

受控入库和恢复状态以本次`output/test-runs/kb-cleaning/`维护receipt为准；备份含本机业务数据，不得提交或公开。专项包含空链接、空白压缩、代码/表格保留、刷新漂移拒绝/回滚、同文向量复用与profile/历史门禁；不做全量回归或真实LLM生成测试。

本机T24实际入库已完成：SQL/Chroma均3214、index ready、2条smoke通过；3094条向量复用（2826原ID、268同文新ID），仅120条重新嵌入，396条过期活动向量移出当前集合并留完整备份。全部旧SQL不可变行、24条冻结Evidence hash/条数不变，56份original快照hash不变。53项专项通过，额外1次Graph资料本地检索返回清洁正文。Web与两个Worker已恢复ready；结果只代表该本机库，不自动代表其他部署已更新。

## 21. 全库清洗候选构建（T25历史阶段）

按用户当时“全库清洗、先别入库”要求，`scripts/knowledge_corpus_cleaning.py`作为独立文件构建层读取全部62篇，输出`output/knowledge-cleaning/T25/`。T25交付时未修改canonical、SQL、Chroma或模型，运行索引当时仍为T24的3214片；后续用户授权T26入库后为3177片（见22节），再由T28切换v2（见24节）。冻结T25审计中的`ingested=false`是构建当时事实，不代表后续激活状态。

本轮42篇有变、20篇原样保留。除了徽章、logo、空链接、展示容器与多余空白，还处理有证据的PDF断词1205处、保留连字符的复合词换行91处、印刷连字103处、连续页码offset验证的页边数字99处；100个物理PDF page定位标记保留并重建page_spans。代码/表格/公式/行内代码/Notebook code与raw内容保护，许可/引用及有效技术图片保留，技术徽章转换为普通论文/示例链接。10个T24去徽章时丢失的Notebook链接从固定original HTML逐字恢复，仅添加固定标签，不生成URL或新知识。不是对其余52篇一律强制改字。

105处未获足够自动修复依据的断词保持原文，在候选`audit.json`的每篇`unresolved`中按物理页定位；不宣称所有PDF阅读顺序、OCR或未知HTML已被修复。`audit.json`记录前后hash/保护区/规则计数/修复依据，`changes.diff`可逐行审查，`candidate-snapshot.json`冻结候选62篇/3177片身份。56份original及许可与canonical逐字一致。

候选manifest/三批导入registry/统一registry已同步派生hash和页跨度，原upstream commit/source_hash/来源ID不变；改变正文的官方资料才追加cleaning parser标记。此层不改固定上游采集器的原转换定义：T26激活后原采集器`--check`先在临时目录重建保存基线、验证原始采集转换，再重放清洗结果；候选独立`--check`也使用同一基线，不把基础采集测试误当清洗构建验证。

51项限定测试、候选/原采集器检查和Ruff通过；抽查8处正确断词、5个保护反例，以及BGE模型表/引用/许可、MinerU技术契约与62个代码块，未发现误伤。仅做文件处理与内存分片，没有调用数据库、Embedding/LLM、网络或服务生命周期接口；未运行全量/前端/真实模型测试。输出受Git忽略，协作方需运行构建命令重建，不能误认为已有线上索引会自动更新。

## 22. 清洗版资料激活与入库（T26）

用户后续授权入库和运行。`knowledge_corpus_promotion.py`备份后把T25核验文件切换到既有canonical路径；未仅改`.env`指向临时目录，因为按知识库ID解析仍优先仓库canonical。62篇保留、42个文档版本更新、20个版本不变，物理页100个及节点映射保留；没有同版本metadata冲突。Embedding/精排/生成模型和存储路径不变。

canonical新增`provenance/cleaning-base/manifest.json`与按hash命名的旧派生blob，保存重建T24所需差异。这里只含知识源字节，不含用户数据库或凭据；manifest-only加载保证blob不进入索引。新根metadata的`active_corpus_cleaning`及`provenance/active-cleaning-snapshot.json`记录profile和3177片身份。原采集器及候选检查能通过完整基线hash重建输入、离线校验固定来源并确定性重放清洗；不依赖某个开发者的私有绝对备份路径。

本机入库结果：预期/SQL/Chroma均3177，index ready，2条既有检索smoke通过；快照`86890a07018effb97fd5dbcbdc1abc196cb11e5ca3b4e36e873ca28798422895`。387条原ID向量保留、1666条同文向量复制到新ID，共复用2053条；其余1124条用原bge-m3重编码。2827条旧活动向量移出当前集合，完整向量备份可恢复，旧SQL版本不删。

维护前24条冻结Evidence全字段hash与条数不变；旧SQL不可变文档/切片行验证保留，文档版本134→176、切片历史6790→9580。私有source/index备份在`backend/data/knowledge_backups/T26/`，由`.gitignore`保护，禁止提交；文件切换与索引维护receipt分开记录。105处待核查断词仍保留，不因入库宣称已全部修复。

原英文1626/pilot95等历史fixture通过重建保存基线验证；当前清洗版另用`backend/tests/fixtures/knowledge_pilot/corpus_clean_v1.json`冻结62篇/3177片、官方56篇/3051片的完整metadata SHA，旧fixture未覆盖。64项切换专项、2项补充保护/重建测试、9项来源版本校验及Ruff通过；原采集器/候选激活后重放检查通过。未做全量回归、前端构建或真实生成LLM测试；本机ready不等于其他环境已部署。

## 23. 教学单元分片候选（T27，构建时未入库，后由T28激活）

用户当时要求改进信息密度，包含原六模块，少测试且先不入库。新增opt-in `markdown_evidence_v2`，T27构建时仅`output/knowledge-cleaning/T27/`的62篇候选manifest启用。默认recursive/markdown_structure_v1和旧3177片完整metadata/ID指纹保持，当时canonical/SQL/Chroma/.env/服务不变；后续激活见24节。

策略900字符目标、1200软限、overlap最多100：合并同物理页/同节点集合的相邻短单元，标题跟正文、说明跟代码/输出，不跨页扩大节点范围。长普通段落fallback，代码/表格/公式不截断；超软限标记oversized，安全上限12000。标题-only保留在原文及section路径，不独立作为证据，每片真实字符/行号和sections列表可审计。候选全局identity revision加`-evidence-v2`，避免未来未变正文的新策略metadata冲突；原文hash不伪造。

27篇163条纯辅助URL移至`provenance/auxiliary_links.json`（完整标签/URL/原文位置保留），36篇正文产生辅助/格式剥离；技术叙述、代码和表格内有效URL保留。全部original/许可不变，旧Evidence不回写。Graph首片423字符/URL218变为864字符/必要API URL43，两个配套Notebook网址不再占证据正文。

候选62篇1121片，中位877（原356），<200字符26/约2.3%（原1111/约35%），<50字符0（原359），纯格式0（原11）。六教材126→44，逐模块18→6、20→7、19→7、23→9、21→7、25→8，全部v2且代码/表格保留。82个超软限原子标记保留，最长11866，所以不宣称每片固定900字符。

`chunks.jsonl`为新子片；`parent-contexts.jsonl`只为同页/同节点相邻片的离线父级预览（1600目标/2400最大，超长原子自身例外）。**运行时EvidenceRetriever未读取父级回填，摘录预算仍1200；未来正式启用还需单独验收长原子摘录/上下文预算，不能描述为已上线父子检索。**不改当前排序/模型/查询返回数。

26项有限专项通过（16新策略+10旧Markdown）、candidate --check/Ruff通过；全清单内存分片统计与代码/表格/数学完整保护、有效正文覆盖、页节点/稳定性检查通过。T27未做模型检索/生成、全量回归或浏览器测试，不用片数减少代替效果评测。最终入口`output/knowledge-cleaning/T27/README.md`，构建时未入库/promotion/重启；后续T28入库不改写冻结候选的历史`ingested=false`。

## 24. 教学单元v2激活与入库（T28）

用户另行授权入库后，`scripts/evidence_corpus_promotion.py`校验候选与全源hash、备份完整canonical，按文件原子切换；失败回滚，遇未知并发编辑则拒绝覆盖。62篇都使用独立`-evidence-v2`身份epoch，不覆盖同版本不可变metadata。纯辅助URL从正文移入`provenance/auxiliary_links.json`，原始快照/许可、代码/表格/公式保留；六教材统一v2共44片。`provenance/evidence-base`按hash保存重建T26所需差异，再由旧`cleaning-base`追溯T24；这些基线blob不进入manifest索引，原采集器和候选检查均支持两层确定性重放。

活动版本使用单独`backend/tests/fixtures/knowledge_pilot/evidence_units_v2.json`冻结62篇1121片（官方1077、教材44）的完整metadata/hash，保留旧3177片fixture并显式重建T26验证。34项切换/分片专项、5项活动/历史fixture兼容及1项并发删除保护测试通过。当前本机文件与索引均已激活ready；结果由`backend/data/knowledge_backups/T28/index/receipt.json`与健康检查确认，私有source/index备份均受Git忽略保护，禁止提交。

运行时Evidence摘录预算仍1200字符；82个超软限原子保留SQL全文，但可能按旧预算截断后才进入冻结Evidence，审核也只能依据实际摘录。parent-context仅离线预览，未启用父级回填。模型、HTTP/DTO、表结构、TopK、排序算法和历史Evidence均不借本次调整；不宣称完成长代码完整入模或真实生成效果评测。未做全量回归、浏览器、真实生成LLM、Worker故障注入、CI或部署环境验收。

本机中断恢复使用同维护入口显式`--resume`，不覆盖原备份；同路径/profile、SQL历史/Evidence、旧向量备份完整可恢复副本、现存每个向量ID/正文/metadata及有限值均须通过，才可复用稳定ID继续幂等ingest。原2smoke及ready门槛不降低。补9个纯数据校验用例通过；这不代表做过全套Worker故障注入，详见T28计划与维护receipt。

本机最终结果：预期/SQL/Chroma均1121，ready快照`0deef2d2c3501dba78d1b44ee1362750e6c9f672a58305a893a9d040b7bd4457`，原2smoke通过；中断前编码864片、续入复用864并补257片，总1121新片都沿用原bge-m3。3177旧活动向量移出当前集合，原始完整备份保留；旧SQL不可变文档176→238、历史chunk9580→10701，13条冻结Evidence全字段hash与条数不变。最终只读核对每个向量ID/正文/完整metadata与SQL/源文件完全一致，1024维有限单位向量最大范数误差1.70e-7；安全报告`output/test-runs/kb-activate-t28/final-index-audit.json`。本机13条为本轮维护实际基线，不与T26当时24条历史数字混用。

服务恢复后Web/文本Worker/课件Worker均ready，前端HTTP200。单次Graph RAG本地检索返回6条Evidence，第一条命中`source_zh_milvus_graph`864字符，Notebook辅助长URL不再进入摘录；其余5条1013–1140字符。没有保存新学习Run或调用生成LLM，此抽查不能替代系统性生成效果评测。

## 25. 学习检索任务与来源选材（T29）

默认`LEARNING_RETRIEVAL_REFINEMENT_ENABLED=true`，仅新legacy学习文本文档使用。按主题、最多3个目标节点/2个薄弱点构造两类任务：原理与概念区别、操作验证与边界；轮询进入最多6查询预算。保留用户具体问题并围绕原问补充，不固定先搜孤立宽topic。无锚点才使用主题通用问题；超2000字符或预算不能覆盖节点时显式回退旧路径，不默默截断/丢节点。资源类型影响第二问题关注点，不调用LLM翻译。

新可选入口把最多20精排候选完整交给可信证据边界，不按owner提前截6。SQL来源/版本/内容hash、原相关性门槛0.35及去重均不降低。最终预算`min(max_evidence, top_k_per_query×query_count)`：默认单query最多6，多query全局最多8。旧注入后端仍可执行，但profile明确`learning_candidate_window=legacy_adapter`，不能宣称获得完整窗口。

选材先保护节点覆盖，再软保留2条合格原文、限制教材合计2条和同文档2条。原文预留需原相关性达到原门槛及“平衡前固定预算末位原分-0.15”。填充先尝试质量合格且多样的来源；不足时先放宽来源/文档软限制保留较强证据，最后才回填其余达到原门槛的候选，避免为了多样性硬选明显更弱的资料。`relaxations`记录教材/文档限制、原文不足及相对质量回填；节点覆盖优先。不保证英文比例，中文官方资料同样属于原文。

分类要求可信SQL document_id/path与manifest id/file/document_type匹配，缺失或不匹配为unknown，不信任Chroma自报类型。配置hash绑定新查询/选材版本、来源清单hash及规则常量。最终排序仍用原选材分，不改模型原分、0.08英文偏好或1200字符摘录。profile记录策略、完整候选能力、来源数量、节点保护、基准原分及回填原因。

关闭开关并空闲重启可恢复旧查询、截断及旧policy/hash路径；Tutor、E1/resource-aware-v1、旧冻结Evidence与单份resource_retry不改。不迁移数据库、不更换模型、不对1121片重新入库。本次有限验证不等于全共享层回归或真实生成质量评测。

本机有限验证：26个不同确定性专项通过（初始25、补强后仅复验14个受影响用例），相关Ruff/架构检查通过。共3次本地检索：最终宽RAG任务20候选→8证据，3教材/5原文，因更强证据及覆盖放宽软限并记录原因，仍没有英文；具体encode_query/encode_document问题5条中3条英文原文且官方英文第一。不能据此宣称英文比例必增或教材永不超过2条。Web/两个Workers已空闲重启ready，索引保持1121 ready。汇总output/test-runs/retrieval-t29/summary.json；未跑全量、完整API/Claim/发布/Markdown链、浏览器或生成LLM评测。

## 26. 讲义教学契约（T30）

讲义Prompt升级`text-resource-v6-teaching-contract`，输入新增`teaching_contract`和`knowledge_point_display_names`，共享版本`lecture-pedagogy-v1`。按显式difficulty、其次target_tier、最后画像水平组织受众；初级目标1800–3200字符、中级3200–6000、高级4500–7500，原12000字符Prompt上限和模型token/超时预算不变。单节点可2–4小节，不因凑字数/节数引入额外知识，不新增字数硬门。

示例/练习须在当前正文提供必要材料、完整问题及解释，不能要求读者自行找lab-B、Q1–Q4；重述冻结证据已有短例，不补造技术结论、日期/参数或成绩。主示例按问题→材料→处理/检索→结果→核对展开。初级不因来源提到hash/revision/迁移就展开治理手册；通用原理、项目约定和合成实验分清，术语集中解释，不每节重复警告/自检。

显示名只从已分配证据的单一KB manifest读取已知目标节点，混合KB/未知来源不猜。仅投影Prompt的topic/display_title/learning_objective/path，机器knowledge_points、真实ResourceSpec/context、Evidence正文/ID与SourceRef绑定保留；真正的API名如encode_query不被笼统删除。旧资料/资源不回填，不重新入库。

既有讲义review调用追加同版本教学准则及显示名，按语义而非内部ID字符串判断覆盖，使用原structure_quality/difficulty_mismatch/evidence_gap/factual_risk和revision_instructions；不新增模型调用、关键词语义硬判、状态或发布路径。其他四类资源不追加此rubric；单份retry仍沿原规格/冻结证据。未做真实生成评测，不能宣称已彻底消除悬空实验名或重复。

T30本机19个不同专项通过（新契约10、预算及五类型流程7、Claim和已发布资源服务读取2），Ruff/架构检查通过；现有HTTP下载用例等待超时中断，未通过且未查明原因，服务读取不能替代它。Web/两Worker已空闲重启ready、前端HTTP200；未授权资源端点401仅证明响应及认证。无真实生成调用、无新知识入库或旧产物覆盖。明细output/test-runs/lecture-t30/summary.json及T30计划，未完成完整接口/发布链、浏览器或真实模型质量验收。

## 27. 新建方向前端草稿与旧记录提示（T34）

本次没有新增数据库表、字段或API。问卷`validation.exclusive_option_values`现由前端用于多选互斥，诊断中的明确“都不了解”选项也遵守相同规则；后端既有问卷校验仍保留。

草稿是当前标签页的账号隔离会话缓存，不是数据库记录。它保留当前选择、答题和当前诊断轮次，离开页面/刷新后恢复；24小时失效，退出/切换账号或成功提交生成任务清理。已提交画像需通过GET核对归属、知识库和版本；无效时只保留合法问卷答案回到方向确认，接口失败保留原草稿并提供重试。其他页面的全局当前画像不作为本流程可提交画像的兜底。

重复方向检查通过分页`GET /api/profiles/`读取本人记录，使用实际`knowledge_base_id`及`learning_preferences.metadata.onboarding.learning_direction_id`匹配；不从`user__direction`猜测ID，因为新画像实际附随机后缀。弹窗默认不选记录，“保留进度并继续”切至所选历史画像；“删除所选记录并重新开始”必须二次确认，复核目标及任务状态、成功读取问卷后，仅调用所选真实ID的DELETE，再进入空白问卷，不自动提交新画像。其他同方向记录和其他方向不删除；失败或数据不完整时不继续。

这只是既有永久删除契约的前端入口，不新增后端锁、事务原子性或Worker取消机制。任务状态预检不能保证跨客户端并发删除安全；未通过本次测试证明旧数据库/课件物理文件完整清理。验证全部使用合成数据与mock接口，未访问或删除真实进度。具体功能与边界见[功能说明21](features.md#21-新建方向的续填与旧进度处理t34)。
