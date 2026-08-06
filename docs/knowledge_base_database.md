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
| `agent_runs` | Agent 运行主记录 |
| `agent_steps` | Agent 步骤记录 |
| `resource_reviews` | 资源审核摘要 |
| `resource_claims` | Claim 与证据记录 |

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
- `POST /api/feedback/evaluation/run/submit`
- `POST /api/feedback/`
- `GET /api/feedback/history/{learner_id}`
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
- 当前已存在文档、切片、技能节点和诊断题的数据库记录

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

### 9.3 文档约束

文档不得再使用以下旧口径描述当前实现：

- `/api/learner/profile`
- `/api/learner/list`
- 前端硬编码问卷
- 问卷和诊断混为一套题
- 把 `identity`、`education`、`major` 继续写在通用问卷中

