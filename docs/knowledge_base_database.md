# 知识库与数据库实现说明

> 项目编号：XH-202630
> 文档版本：2.0
> 文档更新时间：2026-07-31
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
  raw/
```

当前已有方向目录：

- `knowledge_base/rag_engineering_training/`
- `knowledge_base/demo_industrial_internet/`

说明：

- `metadata.json`：知识库元数据
- `questionnaire.json`：方向专属问卷源文件
- `diagnostic_questions.json`：诊断题源文件
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

### 4.7 P0-07 一致性与迁移

- `learning_attempts` 对 `(learner_id, idempotency_key)` 建唯一约束，并保存 canonical JSON SHA-256 `request_hash`。
- `learner_profiles.profile_version` 从 1 起；请求的 `expected_profile_version` 与当前值不一致时拒绝更新。
- `knowledge_states` additive 增加 `attempt_count`、`last_attempt_id`、`row_version`，继续演进诊断阶段已有表，不另建竞争当前态。
- 所有 mutation 记录 before/after、source attempt 和 reason；同一 Attempt 重放不会二次加权。
- `20260811_p0_07_feedback_profile_path_closed_loop` 是幂等 additive migration；旧 `feedback_records` 不删除、不回填伪造 Attempt。
- SQLite 开发环境通过单事务和版本条件控制并发；PostgreSQL 生产环境还使用行锁语义。上线前数据库负责人仍需核验 DDL、索引、FK 与真实并发行为。

### 4.8 P0-08 WorkflowEvent tail query

P0-08 零 migration：继续复用 `workflow_events` 的 `(run_id,event_sequence)` 唯一约束/索引和 `agent_runs.last_event_sequence`。SSE 每次只执行有界查询：

```sql
WHERE run_id = :run_id AND event_sequence > :cursor
ORDER BY event_sequence
LIMIT :page_size
```

长 SSE 连接不持有 Session、事务或锁，不增加 delivered/ack 字段；不同客户端只读同一 append-only Ledger。SQLite 用短连接轮询，PostgreSQL 上线时需结合 worker 数、SSE 客户端数和 0.5 秒默认间隔评估连接池。Event retention 尚未在 P0-08 自动清理，删除策略必须保留比赛回放与 `legacy_partial` 语义。

### 4.3 用户资料

- `GET /api/users/`
- `GET /api/users/{user_id}`
- `POST /api/users/`
- `PATCH /api/users/{user_id}`

读写：

- `users`

### 4.4 画像

- `GET /api/profiles/`
- `GET /api/profiles/{learner_id}`
- `PATCH /api/profiles/{learner_id}`
- `DELETE /api/profiles/{learner_id}`

读写：

- `learner_profiles`

删除时还会联动清理相关诊断记录。

### 4.5 诊断

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

### 4.6 资源与反馈

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
- 知识库版本：`2.2.0`
- 综合学习模块：6 个，不再拆分教学卡、概要参考和深度参考
- 向量切片：84 个，已经写入该知识库独立的 Chroma 集合
- 在线检索：多查询扩展后分别执行 BM25 关键词召回与 Chroma 向量召回，按 `chunk_id` 去重并使用 RRF 融合，再由 `BAAI/bge-reranker-base` CrossEncoder 对候选精排
- 能力节点：13 个
- 诊断题：39 道
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
