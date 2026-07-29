# API 文档

> 项目编号：XH-202630  
> 文档版本：2.0
> 文档更新时间：2026-07-27
> 说明：本文档以当前后端代码和运行中的 OpenAPI 为准，覆盖 `backend/app/api` 中已实际暴露的接口。

## 1. 基本信息

- 本地服务根地址：`http://127.0.0.1:8000`
- API 前缀：`/api`
- 文档依据：
  - `backend/app/api/*.py`
  - `backend/app/models/schemas.py`
  - 运行中的 `GET /openapi.json`

## 2. 当前业务主流程

当前代码中的学习流程是：

```text
选择领域
-> 选择学习方向
-> GET /api/onboarding/questions
-> POST /api/onboarding/initial-profile
-> POST /api/diagnosis/submit
-> POST /api/generate/
-> GET /api/resources/{learner_id}
-> POST /api/feedback/
-> GET /api/report/{learner_id}
```

说明：

- “学习方向”是前台概念。
- 后端内部仍保留 `knowledge_base_id` 作为稳定的数据边界。
- 问卷与诊断是两套不同的数据结构：
  - 问卷：用于生成初始画像
  - 诊断：用于测量真实掌握情况并回写画像

## 3. 接口总览

| 模块 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 系统 | `GET` | `/` | 服务信息 |
| 系统 | `GET` | `/health` | 脱敏运行时 readiness |
| 系统 | `GET` | `/health/ready` | 与 `/health` 相同的明确 readiness 别名 |
| 管理员 | `GET` | `/api/admin/knowledge-bases/health` | Token 保护的全 KB 脱敏状态 |
| 知识目录 | `GET` | `/api/knowledge/domains` | 查询领域及其下属学习方向 |
| 知识目录 | `GET` | `/api/knowledge/directions` | 查询学习方向列表 |
| 知识目录 | `GET` | `/api/knowledge/info` | 查询知识库统计信息 |
| Onboarding | `GET` | `/api/onboarding/questions` | 获取当前学习方向的问卷定义 |
| Onboarding | `POST` | `/api/onboarding/initial-profile` | 提交问卷并创建初始画像，同时返回诊断题 |
| 画像 | `GET` | `/api/profiles/` | 分页查询画像 |
| 画像 | `GET` | `/api/profiles/{learner_id}` | 查询单个画像 |
| 画像 | `PATCH` | `/api/profiles/{learner_id}` | 白名单字段局部更新画像 |
| 画像 | `DELETE` | `/api/profiles/{learner_id}` | 删除画像及关联诊断记录 |
| 技能图谱 | `GET` | `/api/skills/nodes` | 查询技能节点和边 |
| 诊断 | `GET` | `/api/diagnosis/questions` | 按方向/知识库获取诊断题 |
| 诊断 | `POST` | `/api/diagnosis/submit` | 提交诊断答案并更新画像 |
| 资源生成 | `POST` | `/api/generate/` | 生成学习资源 |
| 资源 | `GET` | `/api/resources/{learner_id}` | 查询某学习者的资源列表 |
| 资源 | `GET` | `/api/resources/file/{resource_id}` | 下载资源文件 |
| 审核 | `GET` | `/api/reviews/{resource_id}` | 查询资源最近一次审核摘要 |
| 反馈 | `POST` | `/api/feedback/` | 提交学习反馈并触发画像更新 |
| 反馈 | `GET` | `/api/feedback/history/{learner_id}` | 查询反馈历史 |
| 报告 | `GET` | `/api/report/{learner_id}` | 查询学习报告 |
| 评测 | `GET` | `/api/evaluation/summary` | 查询评测摘要 |

## 4. 关键数据对象

## 4.1 LearnerProfile

学习者画像是系统中的核心聚合对象。

关键字段：

- `learner_id`
- `learner_type`
- `education`
- `major`
- `target_domain`
- `knowledge_base_id`
- `theory_scores`
- `knowledge_states`
- `skill_level`
- `weak_points`
- `strong_points`
- `learning_goal`
- `learning_preferences`
- `last_feedback_summary`

说明：

- `knowledge_base_id` 在存储层仍然保留。
- `knowledge_states` 会在问卷、诊断、反馈后逐步更新。

## 4.2 InitialProfileQuestionnaire

问卷提交模型：

- `learner_id`：必填
- `learning_direction_id`：可选
- `answers`：对象，键来自 `/api/onboarding/questions` 返回的 `question_id`

补充：

- 模型允许额外字段，兼容旧版平铺提交。
- 当前推荐提交方式始终是结构化 `answers`。

## 4.3 InitialProfileResponse

问卷提交后的返回结构：

- `learner_id`
- `profile`
- `diagnostic_node_ids`
- `not_started_node_ids`
- `screening_results`
- `diagnostic_questions`
- `next_step`

说明：

- `diagnostic_questions` 是当前方向下可直接用于诊断的题目列表。
- 返回的诊断题不包含标准答案和解析。

## 4.4 DiagnosticSubmitRequest

- `learner_id`：必填
- `learning_direction_id`：可选，优先于 `knowledge_base_id`
- `knowledge_base_id`：可选
- `answers`：必填，至少 1 条
- `metadata`：可选

其中 `answers` 的单项结构为：

- `question_id`
- `answer`

## 4.5 DiagnosticResult

- `diagnostic_result_id`
- `learner_id`
- `knowledge_base_id`
- `ability_level`
- `weak_points`
- `strong_points`
- `knowledge_states`
- `recommended_path`
- `created_at`

## 4.6 GenerateRequest

- `learner_id`：必填
- `topic`：必填
- `knowledge_base_id`
- `diagnostic_result_id`
- `target_skill_nodes`
- `resource_types`：至少 1 项，去重并保留请求顺序
- `difficulty_preference`
- `generation_mode`：`draft | standard | strict`，默认 `standard`
- `include_review`：默认 `true`；为 `false` 时跳过 Reviewer，资源状态只能是 `unreviewed_draft`
- `include_claim_check`：默认 `false`；P0-06 接入前，请求该能力会明确返回 `unavailable` 并转人工复核
- `max_iterations`：`0..3`，表示最大业务返工次数；初次生成不计入返工
- `constraints`

请求字段由 `GenerationService` 一次性映射到 `WorkflowState 1.0`。`knowledge_base_id` 以请求值优先，否则使用画像中的默认值；目标节点、难度、生成模式和约束会进入对应 Agent 输入契约，不得在 LangGraph channel 中静默丢失。

## 4.7 GenerateResponse / AgentTrace

`GenerateResponse` 主字段：

- `schema_version`：当前固定为字符串 `1.0`
- `run_id`：请求进入工作流前生成，在 state、trace 和审计记录中保持一致
- `workflow_status`：`running | completed | degraded | failed | human_review`
- `learner_id`
- `topic`
- `resources`
- `trace`
- `report`
- `execution_status`：兼容字段；取值为 `success | degraded | failed | human_review | running`
- `error_codes`：本次生成涉及的稳定、脱敏错误码

`AgentTrace` 契约：

- `schema_version/run_id/step_id/sequence/attempt`：工作流版本及稳定运行、步骤和轮次标识
- `status`：必填，无默认成功；取值为 `running | success | degraded | retryable_error | failed | human_review | skipped`
- `resource_ids/review_ids/evidence_refs`：本步骤关联对象
- `error_code`：可选稳定错误码，不得写入原始上游异常、API Key 或完整学习者画像
- `error`：可选脱敏 `ErrorInfo`，包含 `code/category/message/retryable/source/attempt/occurred_at/safe_detail`
- 发生显式允许的 fallback 时，受影响节点必须使用 `degraded`
- `llm_call_id/model_name/provider_request_id/structured_output_mode/finish_reason`：脱敏模型调用标识和结束原因
- `input_tokens/output_tokens/total_tokens/llm_duration_ms`：Provider 可用时记录的 token 与单次 Gateway 总耗时
- `retry_count`：同一 Gateway 调用中的技术重试次数，不等于资源 `revision_count`

LLM 失败会使用稳定细分码：`LLM_TIMEOUT`、`LLM_RATE_LIMITED`、`LLM_CONNECTION_FAILED`、`LLM_UPSTREAM_5XX`、`LLM_AUTH_FAILED`、`LLM_BAD_REQUEST`、`LLM_CONTENT_REFUSED`、`LLM_OUTPUT_EMPTY`、`LLM_OUTPUT_TRUNCATED`、`LLM_OUTPUT_PARSE_FAILED`、`LLM_OUTPUT_SCHEMA_INVALID`。响应和 trace 不返回 Provider 原始错误 body、prompt、模型原文或凭据。

资源审核状态为：`draft | unreviewed_draft | pending_review | approved | rejected | human_review`。未执行 Reviewer 或 Claim 能力不可用时，资源不得标记为 `approved`。

## 4.8 FeedbackRequest

- `learner_id`：必填
- `resource_id`：必填
- `correct_rate`：必填
- `feedback_type`
- `time_spent_seconds`
- `completed`
- `self_rating`
- `practice_result`
- `answers`

## 5. 接口详情

### 5.0 `GET /health`、`GET /health/ready`

返回当前运行模式及脱敏 readiness。该接口不调用计费 LLM、不下载 Embedding 模型，也不返回 API Key、完整 endpoint、绝对运行路径或 traceback。多 KB 模式下只检查默认 KB 和核心依赖；非默认 KB 异常不会改变公共 readiness。

主字段：

- `status`：`ready`、`degraded` 或 `not_ready`
- `app_mode`：`development`、`demo` 或 `production`
- `degraded_generation_allowed`
- `python`
- `storage`：包含 storage mode 和 `ephemeral` 标记
- `llm`
- `embedding`
- `vector_store`：包含 collection 状态和可选 count
- `resources`
- `error_codes`

状态码：

- `ready`：HTTP 200
- `degraded`：HTTP 200，仅 development/demo 且显式允许 degraded
- `not_ready`：HTTP 503
- production 启动预检为 not_ready 时应用 fail-fast

```json
{
  "status": "degraded",
  "app_mode": "demo",
  "degraded_generation_allowed": true,
  "python": {"status": "ready"},
  "storage": {"status": "ready", "mode": "sqlite", "ephemeral": false},
  "llm": {"status": "not_ready", "code": "CFG_LLM_API_KEY_MISSING"},
  "embedding": {"status": "ready"},
  "vector_store": {"status": "ready", "collection_state": "populated", "count": 8},
  "resources": {"status": "ready"},
  "error_codes": ["CFG_LLM_API_KEY_MISSING"]
}
```

### 5.0a `GET /api/admin/knowledge-bases/health`

返回全部已配置 KB 的脱敏 collection 状态。接口默认关闭，只有设置 `ADMIN_HEALTH_TOKEN` 后才能通过 `X-Admin-Token` 请求头访问。

状态码：

- 未配置管理员 token：HTTP 404 + `ADMIN_HEALTH_DISABLED`
- token 缺失或错误：HTTP 401 + `ADMIN_UNAUTHORIZED`
- 默认 KB/Chroma 核心不可用：HTTP 503 + `status=not_ready`
- 默认 KB 正常、部分非默认 KB 异常：HTTP 200 + `status=degraded`
- 全部 KB 正常：HTTP 200 + `status=ready`

```json
{
  "status": "degraded",
  "default_knowledge_base_id": "rag_engineering_training",
  "knowledge_bases": [
    {
      "knowledge_base_id": "rag_engineering_training",
      "is_default": true,
      "status": "ready",
      "collection_name": "kb_0123456789abcdef",
      "collection_state": "populated",
      "count": 42
    },
    {
      "knowledge_base_id": "optional_training",
      "is_default": false,
      "status": "not_ready",
      "code": "VECTOR_COLLECTION_MISSING",
      "collection_name": "kb_fedcba9876543210",
      "collection_state": "missing"
    }
  ],
  "orphan_collections": [],
  "error_codes": ["VECTOR_COLLECTION_MISSING"]
}
```

接口不返回管理员 token、绝对磁盘路径、原始异常或文档正文。collection name 统一由 `_collection_name(kb_id)` 生成；旧 `CHROMA_COLLECTION_NAME` 在兼容期只作为前缀解释。

### 5.1 `GET /`

返回服务基本信息。

### 5.2 `GET /api/knowledge/domains`

返回领域及其下属学习方向，供前端做“先选领域，再选方向”。

响应主字段：

- `domains`
- `domains[].domain_id`
- `domains[].name`
- `domains[].description`
- `domains[].tracks`
- `domains[].tracks[].track_id`
- `domains[].tracks[].learning_direction_id`
- `domains[].tracks[].knowledge_base_id`
- `domains[].tracks[].name`
- `domains[].tracks[].description`

### 5.3 `GET /api/knowledge/directions`

返回平铺后的学习方向列表。

响应主字段：

- `directions`

### 5.4 `GET /api/knowledge/info`

查询某个知识库的统计信息。

查询参数：

- `knowledge_base_id`：可选

典型返回包含：

- `knowledge_base_id`
- `target_domain`
- `description`
- `document_count`
- `chunk_count`
- `skill_node_count`
- `diagnostic_question_count`
- `version`
- `updated_at`

### 5.5 `GET /api/onboarding/questions`

按学习方向返回问卷定义。

查询参数：

- `learning_direction_id`：可选

响应主字段：

- `learning_direction_id`
- `questions`

每个 `questions[]` 典型字段：

- `question_id`
- `title`
- `type`
- `required`
- `options`
- `show_when`
- `hint`

说明：

- 前端不应硬编码题目和选项。
- 题目来自数据库问卷模板，而不是前端本地 JSON。

### 5.6 `POST /api/onboarding/initial-profile`

提交问卷，创建或更新初始画像，并返回当前方向下需要继续诊断的题目。

请求体：

```json
{
  "learner_id": "stu_001",
  "learning_direction_id": "rag_engineering_training",
  "answers": {
    "identity": "在校学生",
    "education": "本科"
  }
}
```

响应重点：

- `profile`
- `diagnostic_questions`
- `next_step`

当前实现特点：

- 服务端会保存问卷提交记录和问卷答案明细
- 服务端会更新 `learner_profiles`
- 服务端会区分：
  - 可继续诊断的节点
  - 明确尚未开始的节点

### 5.7 `GET /api/profiles/`

分页查询画像。

查询参数：

- `page`：默认 `1`
- `page_size`：默认 `10`
- `skill_level`：可选

### 5.8 `GET /api/profiles/{learner_id}`

查询单个画像。

返回模型：`LearnerProfile`

### 5.9 `PATCH /api/profiles/{learner_id}`

对白名单字段做局部更新。

请求体模型：`LearnerProfileUpdate`

说明：

- 不允许修改 `learner_id`
- 空更新会返回 `400`

成功响应格式：

```json
{
  "status": "success",
  "learner_id": "stu_001",
  "updated_fields": ["learning_goal"]
}
```

### 5.10 `DELETE /api/profiles/{learner_id}`

删除画像及其依赖记录。

返回模型：`StatusResponse`

### 5.11 `GET /api/skills/nodes`

查询技能节点和依赖边。

查询参数：

- `knowledge_base_id`：可选
- `level`：可选
- `target_domain`：保留参数，当前未真正参与筛选

响应主字段：

- `knowledge_base_id`
- `nodes`
- `edges`

### 5.12 `GET /api/diagnosis/questions`

按方向或知识库查询诊断题。

查询参数：

- `learning_direction_id`：可选
- `knowledge_base_id`：可选
- `learner_id`：可选，当前预留
- `skill_node_ids`：可选，逗号分隔
- `level`：可选
- `limit`：可选，`1-39`

响应主字段：

- `knowledge_base_id`
- `total`
- `questions`

说明：

- 当前响应不返回 `answer`
- 当前响应不返回 `explanation`

### 5.13 `POST /api/diagnosis/submit`

提交诊断答案并回写画像。

请求体示例：

```json
{
  "learner_id": "stu_001",
  "learning_direction_id": "rag_engineering_training",
  "answers": [
    {
      "question_id": "dq_rag_001",
      "answer": "检索相关外部证据"
    }
  ]
}
```

响应模型：`DiagnosticResult`

当前实现会：

- 判分
- 持久化诊断答题记录
- 更新 `learner_profiles.skill_level`
- 更新 `learner_profiles.knowledge_states`
- 更新 `weak_points` 和 `strong_points`

### 5.14 `POST /api/generate/`

根据画像生成资源。

前置条件：

- `learner_id` 对应画像必须存在

返回模型：`GenerateResponse`

主字段：

- `schema_version`：`1.0`
- `run_id`
- `workflow_status`：`completed | degraded | failed | human_review`（同步接口完成时不会返回 `running`）
- `learner_id`
- `topic`
- `resources`
- `trace`
- `report`
- `execution_status`：`success | degraded | failed | human_review`
- `error_codes`：稳定、脱敏错误码列表

禁用 degraded 或 production 中依赖失败时，接口返回 HTTP 503，且不会在失败前持久化 fallback 资源。显式允许 fallback 时，HTTP 响应仍必须通过 `execution_status=degraded` 和对应 trace 状态表明降级。

同步预算：后端默认 workflow deadline 为 105 秒，必须小于前端当前 120 秒请求超时；每次模型调用都会读取剩余预算，deadline 不足时不再 sleep 或发起下一次请求。

工作流控制语义：

- `include_review=false`：`generate -> finalize_draft`，审核决策为 `not_requested`。
- Reviewer 返回 `revise` 且 `revision_count < max_iterations`：先增加返工计数，再重新进入 Generator；下一版资源使用新 `resource_id`，并通过 `parent_resource_id/version` 关联上一版。
- 返工额度用尽、Reviewer 无法自动决策或严格模式中存在降级结果：`workflow_status=human_review`。
- Reviewer 只有在 typed decision 为 `approve`、幻觉分低于安全阈值、难度匹配且覆盖率达标时才能批准；模型超时、限流、5xx、空输出、截断、解析或 schema 错误均不得 approve。
- `include_claim_check=true`：P0-06 前返回 `claim_check_status=unavailable`、错误码 `CLAIM_CHECK_NOT_IMPLEMENTED`，不得把空 `claims` 当作通过。

### 5.15 `GET /api/resources/{learner_id}`

查询某个学习者的资源列表。

路径参数：

- `learner_id`

查询参数：

- `resource_type`：可选
- `difficulty`：可选

返回模型：`ResourceListResponse`

### 5.16 `GET /api/resources/file/{resource_id}`

下载某个资源文件。

说明：

- 只允许下载已登记的受控文件
- 不允许任意文件路径访问

### 5.17 `GET /api/reviews/{resource_id}`

查询资源最近一次审核摘要。

返回模型：`ReviewSummary`

### 5.18 `POST /api/feedback/`

提交学习反馈并触发画像更新。

前置条件：

- `learner_id` 对应画像必须存在

返回模型：`FeedbackResponse`

关键返回字段：

- `decision`
- `message`
- `updated_profile`
- `decision_reason`
- `next_action`
- `recommended_topics`
- `updated_knowledge_states`
- `regenerate_suggestion`

### 5.19 `GET /api/feedback/history/{learner_id}`

查询学习反馈历史。

返回模型：`FeedbackHistoryResponse`

### 5.20 `GET /api/report/{learner_id}`

查询学习报告。

返回模型：`ReportResponse`

关键字段：

- `radar`
- `weak_points`
- `strong_points`
- `skill_level`
- `learning_goal`
- `difficulty_curve`
- `learning_path`
- `next_suggestions`
- `recent_resources`
- `recent_feedback`

### 5.21 `GET /api/evaluation/summary`

查询评测摘要。

返回模型：`EvaluationSummary`

主字段：

- `sample_count`
- `metrics`
- `ablation`
- `created_at`

## 6. 当前数据库落库事实

基于当前代码，以下数据会被持久化：

- 问卷模板和问题：
  - `questionnaire_templates`
  - `questionnaire_questions`
- 问卷提交结果：
  - `questionnaire_submissions`
  - `questionnaire_answers`
- 画像：
  - `learner_profiles`
- 诊断题库：
  - `diagnostic_questions`
- 诊断答题结果：
  - `diagnostic_answers`

这意味着：

- 问卷不是只保存在前端状态中
- 诊断结果也不是只回写到内存中
- 当前系统已经具备问卷、诊断、画像三段持久化链路

## 7. 命名说明

当前代码里同时存在两套术语：

- 面向用户和前端：`learning_direction_id`
- 面向内部存储和知识库：`knowledge_base_id`

当前实现关系是：

- 前端先选学习方向
- 服务端把学习方向映射到对应知识库
- 画像、技能图谱、诊断、资源生成等后续能力仍大量使用 `knowledge_base_id`

因此文档中保留这两个字段，但应理解为：

- `learning_direction_id` 是流程入口参数
- `knowledge_base_id` 是后端稳定标识

## 8. 已下线或不再推荐的旧实现

以下旧概念不应再作为当前流程文档的主线：

- 旧版 `/api/learner/profile` 系列接口
- 前端硬编码问卷
- 问卷和诊断混用为同一套题
- 提交问卷后直接在同一块表单下“接着显示旧诊断内容”的旧交互假设

## 9. 错误响应

当前接口由全局异常处理器返回统一、脱敏的错误结构：

```json
{
  "status": "error",
  "code": "HTTP_ERROR",
  "message": "资源不存在",
  "detail": null
}
```

字段说明：

- `status`：固定为 `error`
- `code`：稳定内部错误码
- `message`：安全的公开错误信息
- `detail`：可选脱敏详情；不得包含 API Key、完整画像、原始上游响应或 traceback

常见场景：

- `400`：请求参数不合法、问卷提交不合法、诊断答案不合法
- `404`：画像不存在、知识库不存在、资源不存在、审核记录不存在
- `422`：Pydantic/FastAPI 请求校验失败，`code=REQUEST_VALIDATION_ERROR`
- `500`：未分类内部错误，`code=INTERNAL_ERROR`
- `503`：生成依赖不可用或运行状态 not_ready
