# API 文档

> 项目编号：XH-202630
> 文档版本：2.0
> 文档更新时间：2026-07-31
> 说明：本文档以当前代码实现为准，覆盖 `backend/app/api` 中已经启用的核心接口。

## 1. 基本信息

- 服务地址：`http://127.0.0.1:8000`
- API 前缀：`/api`
- 当前资源生成模式：异步任务模式`

## 2. 当前主流程

```text
创建用户资料
-> 选择学习方向
-> GET /api/onboarding/questions
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> POST /api/generate/jobs
-> GET /api/generate/jobs?learner_id={learner_id}
-> GET /api/generate/jobs/{run_id}
-> GET /api/resources/{learner_id}?run_id={run_id}
-> GET /api/resources/file/{resource_id}
-> GET /api/feedback/evaluation/run/{learner_id}/{run_id}
-> POST /api/feedback/evaluation/run/submit
-> POST /api/feedback/
-> GET /api/feedback/history/{learner_id}
-> GET /api/learning-history/{learner_id}/timeline
-> GET /api/report/{learner_id}
```

## 3. 本次变更要点

- 用户基础信息已经从问卷中拆出，改由 `users` 相关接口维护。
- `user_id` 由后端自动生成，前端不应再要求用户手填。
- 通用问卷 `common_initial_profile_v1` 当前只保留 4 个动态问题：
  `learning_goals`、`learning_modes`、`difficulty_preference`、`weekly_time_budget`
- 异步资源生成已经成为唯一对外生成入口。
- 生成任务列表接口已经提供，前端可默认展示当前任务并切换查看历史任务。
- 资源列表支持按 `run_id` 过滤查看某一次生成任务的结果。
- 学习反馈已支持按生成任务聚合测评，并可基于选中的历史反馈主动发起重新生成。
- 学习历史时间线接口已提供统一查看问卷、诊断、生成任务的入口。

## 4. 接口总览

| 模块 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 系统 | `GET` | `/` | 服务信息 |
| 系统 | `GET` | `/health` | 健康检查 |
| 系统 | `GET` | `/health/ready` | 就绪检查 |
| 用户资料 | `GET` | `/api/users/` | 查询用户列表 |
| 用户资料 | `GET` | `/api/users/{user_id}` | 查询单个用户 |
| 用户资料 | `POST` | `/api/users/` | 创建用户，`user_id` 自动生成 |
| 用户资料 | `PATCH` | `/api/users/{user_id}` | 更新用户资料 |
| 知识目录 | `GET` | `/api/knowledge/domains` | 查询领域及学习方向 |
| 知识目录 | `GET` | `/api/knowledge/directions` | 查询学习方向列表 |
| 知识目录 | `GET` | `/api/knowledge/info` | 查询知识库信息 |
| Onboarding | `GET` | `/api/onboarding/questions` | 获取入门问卷 |
| Onboarding | `POST` | `/api/onboarding/initial-profile` | 创建初始画像并返回诊断题 |
| 画像 | `GET` | `/api/profiles/` | 查询画像列表 |
| 画像 | `GET` | `/api/profiles/{learner_id}` | 查询单个画像 |
| 画像 | `PATCH` | `/api/profiles/{learner_id}` | 更新画像 |
| 画像 | `DELETE` | `/api/profiles/{learner_id}` | 删除画像 |
| 诊断 | `GET` | `/api/diagnosis/questions` | 获取诊断题 |
| 诊断 | `POST` | `/api/diagnosis/submit` | 提交诊断结果 |
| 资源生成 | `POST` | `/api/generate/jobs` | 创建异步资源生成任务 |
| 资源生成 | `GET` | `/api/generate/jobs` | 按学习者查询生成任务列表 |
| 资源生成 | `GET` | `/api/generate/jobs/{run_id}` | 查询生成任务状态 |
| 资源 | `GET` | `/api/resources/{learner_id}` | 查询资源列表 |
| 资源 | `GET` | `/api/resources/file/{resource_id}` | 下载资源文件 |
| 审核 | `GET` | `/api/reviews/{resource_id}` | 查询资源审核摘要 |
| 反馈 | `GET` | `/api/feedback/evaluation/run/{learner_id}/{run_id}` | 获取任务级测评题 |
| 反馈 | `POST` | `/api/feedback/evaluation/run/submit` | 提交任务级测评与反馈 |
| 反馈 | `POST` | `/api/feedback/` | 提交学习反馈 |
| 反馈 | `GET` | `/api/feedback/history/{learner_id}` | 查询反馈历史 |
| 学习历史 | `GET` | `/api/learning-history/{learner_id}/timeline` | 查询学习过程时间线 |
| 报告 | `GET` | `/api/report/{learner_id}` | 查询学习报告 |

## 5. 用户资料接口

### 5.1 `POST /api/users/`

用途：

- 创建用户资料。
- 后端自动生成 `user_id`。

请求体：

```json
{
  "display_name": "张三",
  "identity": "在校学生",
  "education": "本科",
  "major": "软件工程",
  "job_role": null,
  "experience_years": 0,
  "metadata": {}
}
```

返回重点字段：

- `user_id`
- `display_name`
- `identity`
- `education`
- `major`
- `job_role`
- `experience_years`
- `created_at`

说明：

- 前端不应展示“手动输入 user_id”的表单项。

### 5.2 `PATCH /api/users/{user_id}`

用途：

- 部分更新用户资料。

说明：

- 至少提交一个待更新字段。

## 6. Onboarding 接口

### 6.1 `GET /api/onboarding/questions`

查询参数：

- `learning_direction_id`：可选，学习方向或知识库 ID

用途：

- 获取当前学习方向对应的问卷定义。
- 返回的是服务端实际生效的题目，而不是前端本地写死内容。

返回重点字段：

- `learning_direction_id`
- `questions`

说明：

- 通用问卷已经去掉 `identity`、`education`、`major`、`desired_resource_types`。
- 这些信息改由用户资料接口维护。

### 6.2 `POST /api/onboarding/initial-profile`

用途：

- 根据问卷答案创建或更新学习者画像。
- 同时返回当前应进入的诊断题集合。

请求体重点字段：

```json
{
  "learner_id": "user_xxx__rag_engineering_training",
  "learning_direction_id": "rag_engineering_training",
  "answers": {
    "learning_goals": ["了解基础概念"],
    "learning_modes": ["先讲概念，再做练习"],
    "difficulty_preference": "从基础开始",
    "weekly_time_budget": "1-2 小时"
  }
}
```

返回重点字段：

- `learner_id`
- `profile`
- `diagnostic_node_ids`
- `not_started_node_ids`
- `diagnostic_questions`
- `next_step`

说明：

- `profile.learner_type` 现在优先使用用户资料中的 `identity`。
- 问卷只负责补充本次学习方向的动态偏好，不再承担用户长期背景信息采集。

## 7. 诊断接口

### 7.1 `POST /api/diagnosis/submit`

用途：

- 提交诊断答案并生成诊断结果。

请求体重点字段：

- `learner_id`
- `learning_direction_id`
- `knowledge_base_id`
- `answers`
- `metadata`

返回结果重点：

- 学习者能力等级
- 强弱项
- 知识状态
- 推荐学习路径

## 8. 资源生成接口

### 8.1 `POST /api/generate/jobs`

用途：

- 创建一次异步资源生成任务。

请求体重点字段：

- `learner_id`
- `topic`
- `knowledge_base_id`
- `diagnostic_result_id`
- `target_skill_nodes`
- `resource_types`
- `difficulty_preference`
- `generation_mode`
- `include_review`
- `include_claim_check`
- `max_iterations`
- `constraints`

示例：

```json
{
  "learner_id": "user_xxx__rag_engineering_training",
  "topic": "RAG 基础概念与文档解析",
  "knowledge_base_id": "rag_engineering_training",
  "target_skill_nodes": ["rag_basics", "document_parsing"],
  "resource_types": ["讲义", "实操指南", "分阶段测试题"],
  "difficulty_preference": "从基础开始",
  "generation_mode": "standard",
  "include_review": true,
  "include_claim_check": false,
  "max_iterations": 2,
  "constraints": {}
}
```

返回字段：

- `run_id`
- `learner_id`
- `topic`
- `knowledge_base_id`
- `job_status`

说明：

- 此接口只返回任务信息，不直接返回资源正文。
- 当前推荐前端流程：
  提交任务 -> 轮询任务状态 -> 完成后拉取资源列表。

### 8.2 `GET /api/generate/jobs/{run_id}`

用途：

- 查询任务状态。

返回字段：

- `run_id`
- `learner_id`
- `topic`
- `knowledge_base_id`
- `job_status`
- `resource_ids`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

说明：

- 当 `job_status=completed` 时，前端应展示“查看资源”按钮，或跳转到资源页。
- 当 `job_status=failed` 时，前端应展示失败原因并允许用户重试。

### 8.3 `GET /api/generate/jobs`

用途：

- 按 `learner_id` 查询某个学习者的生成任务列表。

查询参数：

- `learner_id`：必填

返回字段：

- `learner_id`
- `total`
- `items`

每个任务的重要字段：

- `run_id`
- `topic`
- `knowledge_base_id`
- `job_status`
- `resource_ids`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

说明：

- 前端可据此默认展示当前 `running/queued` 任务，并允许切换查看历史任务。
- 当前资源生成页已按任务维度展示，不再只依赖单个 `run_id` 查询参数驱动整页。

## 9. 资源接口

### 9.1 `GET /api/resources/{learner_id}`

用途：

- 查询某个学习者的资源列表。

查询参数：

- `run_id`：可选，仅查看某一次生成任务的结果
- `resource_type`：可选
- `difficulty`：可选

返回字段：

- `learner_id`
- `total`
- `resources`

每个资源的重要字段：

- `resource_id`
- `resource_type`
- `difficulty`
- `storage_type`
- `content_text`
- `file_path`
- `mime_type`
- `knowledge_points`
- `source_refs`
- `review_status`
- `run_id`
- `exercise_items`

资源列表语义说明：

- `resources` 表示“该学习者已经生成并入库的资源记录”。
- 它不是知识库原始文档列表，而是面向用户交付的学习资源列表。
- 同一次生成任务产出的多个资源，会通过同一个 `run_id` 关联起来。
- `source_refs[].score` 是 0 到 1 的最终相关度；精排可用时为 CrossEncoder logits 经 sigmoid 映射后的分数，降级时为归一化 RRF 分数，数值越大排名越靠前。
- `source_refs[].metadata.retrieval_method` 正常为 `hybrid_rrf_cross_encoder`，精排关闭或不可用时回退为 `hybrid_rrf`；`retrieval_channels` 标识片段来自 `vector`、`bm25` 或两路共同召回。
- `source_refs[].metadata` 保留 `vector_rank`、`vector_score`、`lexical_rank`、`lexical_score`、`hybrid_rank`、`hybrid_score`、`rerank_rank`、`rerank_raw_score`、`rerank_score`、`reranker_model`、`rerank_latency_ms` 和 `rerank_candidate_count`，用于检索审计和消融评测。

### 9.2 `GET /api/resources/file/{resource_id}`

用途：

- 下载指定资源对应的文件。

说明：

- 只有文件型资源才能下载。
- 如果资源只有 `content_text`、没有 `file_path`，则该接口会返回 404。

## 10. 学习历史接口

### 10.1 `GET /api/learning-history/{learner_id}/timeline`

用途：

- 统一查看某个学习者从问卷、诊断、生成任务到反馈的学习过程时间线。

适用场景：

- 历史学习记录页
- 展示诊断记录
- 展示资源生成记录
- 串联整个学习过程

## 11. 反馈与测评接口

### 11.1 `GET /api/feedback/evaluation/run/{learner_id}/{run_id}`

用途：

- 按生成任务聚合获取学习后测评题。

返回重点字段：

- `learner_id`
- `run_id`
- `topic`
- `resource_ids`
- `total`
- `questions`

说明：

- 当前学习反馈页优先按任务而不是单个资源加载测评题。
- 题目优先取该任务资源内的练习题；不足时再回退到知识库诊断题。

### 11.2 `POST /api/feedback/evaluation/run/submit`

用途：

- 提交某次生成任务的测评结果与主观反馈。

请求体重点字段：

- `learner_id`
- `run_id`
- `answers`
- `completed`
- `time_spent_seconds`
- `self_rating`
- `practice_result`

返回重点字段：

- `run_id`
- `resource_count`
- `correct_rate`
- `correct_count`
- `total_questions`
- `wrong_knowledge_points`
- `feedback`

说明：

- 提交成功后，后端会保存反馈记录并回写学习者画像。
- 反馈页“基于反馈重新生成”当前采用“选中某条反馈记录 + 当前最新画像”的方式发起新任务。

## 12. 前端调用约定

- 用户资料页：
  `POST /api/users/` 创建用户，`PATCH /api/users/{user_id}` 更新资料
- 新建学习方向页：
  `GET /api/onboarding/questions` 拉取题目
- 提交问卷后：
  `POST /api/onboarding/initial-profile`
- 提交诊断后：
  `POST /api/diagnosis/submit`
- 资源生成：
  `POST /api/generate/jobs`
- 任务列表：
  `GET /api/generate/jobs?learner_id={learner_id}`
- 任务轮询：
  `GET /api/generate/jobs/{run_id}`
- 任务完成后查看资源：
  `GET /api/resources/{learner_id}?run_id={run_id}`
- 任务级测评加载：
  `GET /api/feedback/evaluation/run/{learner_id}/{run_id}`
- 任务级测评提交：
  `POST /api/feedback/evaluation/run/submit`
- 反馈历史：
  `GET /api/feedback/history/{learner_id}`
- 下载资源文件：
  `GET /api/resources/file/{resource_id}`
- 历史学习记录：
  `GET /api/learning-history/{learner_id}/timeline`

## 13. 当前状态

- 已执行：用户资料从问卷中拆出
- 已执行：`user_id` 改为后端自动生成
- 已执行：通用问卷同步为 4 道动态题
- 已执行：同步生成接口 `POST /api/generate/` 已移除
- 已执行：前端统一切到异步生成任务模式
- 已执行：生成任务列表接口可用，资源生成页支持当前任务与历史任务切换
- 已执行：资源列表支持按 `run_id` 查看本次结果
- 已执行：学习反馈页支持按任务加载测评题与提交反馈
- 已执行：资源文件下载接口可用
- 已执行：学习历史时间线接口可用
- 未执行：实时推送
- 未执行：独立任务队列
- 未执行：任务取消
- 未执行：失败任务自动重试
## 14. Agent 可靠执行、审核返工与回放接口

异步生成任务的 `run_id` 同时作为 Agent Run 的稳定 ID。后台任务调用
`GenerationService.generate_with_run_id()` 后，正式执行顺序为：

```text
GenerationJob 预分配 run_id
-> AgentRun created/running
-> RecordedNode 持久化 Step
-> Generator / Reviewer 节点状态合并
-> WorkflowArtifactRecorder 保存资源版本与审核轮次
-> WorkflowCheckpoint
-> Run finalizing
-> 仅最终 approve 的叶子资源 published
-> Run completed/degraded/human_review/failed
-> GenerationJob 同步终态
```

关键契约：

- `max_iterations` 是最大业务返工次数，不包含首次生成；LLM 技术重试不增加该值。
- Reviewer 决策为 `approve | revise | reject | human_review`。
- `issues` 是带 code、severity、目标资源/知识点的结构化数组。
- `revision_instructions` 包含 issue_codes、target_resource_type、action、priority 和系统生成的 instruction_id。
- revise 必须携带可执行指令；指令无效、证据不足、Reviewer 异常或额度耗尽时进入 human_review。
- Generator 返工时读取上一版本，只为指令命中的资源类型创建新 resource_id/version；未命中类型沿用当前版本。
- `review_status` 与 `publication_status` 分离。只有最终 approve 的当前叶子版本可以 published。
- 默认资源列表及文件下载只暴露 published；unpublished 与不存在的下载统一返回 404。
- 历史字符串 issues/instructions 在读取时兼容归一化，但不会补造不存在的审核事实。

### 14.1 `GET /api/runs/{run_id}`

返回脱敏 Run 摘要，包括状态、当前节点、generation_attempt、revision_count、
retrieval_status、final_decision、时间戳和 replay_completeness。不存在时返回
`404 + WORKFLOW_RUN_NOT_FOUND`。

### 14.2 `GET /api/runs/{run_id}/timeline`

按 event_sequence 返回 Step、Event、Checkpoint、Evidence、resource_versions 和
reviews。查询参数：

- `after_sequence`：默认 0。
- `limit`：1..500。
- `next_event_sequence`：存在下一页时返回。

该接口只读数据库，不调用 LLM、Embedding 或 Chroma，也不等于自动 resume。

### 14.3 `GET /api/runs/{run_id}/evidence`

返回运行时不可变 Evidence snapshot，包括 query_hash、excerpt、locator、score 和
config hash；不返回原始 query。后续知识库更新不会改写历史 snapshot。

### 14.4 健康与错误语义

公共 `/health`、`/health/ready` 只检查默认 KB 和核心依赖；非默认 KB 异常不使
公共服务返回 503。管理员 `/api/admin/knowledge-bases/health` 返回全部 KB 脱敏状态。

工作流持久化不可用时 fail closed。常用稳定错误包括
`WORKFLOW_PERSISTENCE_UNAVAILABLE`、`WORKFLOW_PERSISTENCE_CONFLICT`、
`EVIDENCE_INSUFFICIENT`、`EVIDENCE_PROVENANCE_INVALID` 和细分 LLM 错误码。
响应不得包含 prompt、模型原文、API Key、数据库连接串或原始 provider 异常。
