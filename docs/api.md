# API 指南

本地 Web 默认地址为 `http://127.0.0.1:8000`。运行后可用 `/docs` 或 `/openapi.json` 查完整端点、字段和校验规则。后端公开 DTO 位于 [models](../backend/app/models)，前端使用 [导出的契约](../frontend/src/contracts/generated)。本文说明主流程和跨请求约束。

## 认证与错误

| 方法和路径 | 行为 |
|---|---|
| `POST /api/auth/register` | 提交用户名、密码和确认密码，成功 201 并建立会话 |
| `POST /api/auth/login` | 200 并建立会话 |
| `GET /api/auth/me` | 读取会话用户 |
| `POST /api/auth/logout` | 清除会话 Cookie |

注册和登录返回用户资料，认证使用 HttpOnly JWT Cookie。浏览器请求保留凭据，同源 EventSource 使用当前 Cookie。私有端点检查账号和画像归属，未认证通常为 401，私有对象不可见通常为 404。知识目录和技能节点可公开读取，管理员知识库端点使用 `X-Admin-Token`。

API 错误响应包含 `status`、`code`、`message`、`detail`。按 HTTP 状态和稳定错误码处理失败。请求校验返回 422，业务冲突按接口返回 409，依赖未就绪可返回 503。

## 方向、画像与诊断

| 方法和路径 | 用途 |
|---|---|
| `GET /api/knowledge/domains`、`GET /api/knowledge/directions` | 领域和学习方向目录 |
| `GET /api/users/{user_id}`、`PATCH /api/users/{user_id}` | 读取或更新本人长期资料 |
| `GET /api/onboarding/questions`、`POST /api/onboarding/initial-profile` | 按方向读取问卷，提交答案建立初始画像 |
| `GET /api/diagnosis/questions`、`POST /api/diagnosis/submit` | 加载诊断题并提交作答 |
| `GET /api/profiles/{learner_id}/initial-node-candidates` | 读取首批可选主节点 |
| `GET /api/profiles/{learner_id}/ability-nodes` | 读取能力节点、先修关系和掌握状态 |

## 轮次创建与文本生产

| 方法和路径 | 用途 |
|---|---|
| `GET /api/generate/capabilities` | 查询 `round_creation_enabled` 和轮次读取及恢复能力 |
| `POST /api/generate/rounds` | 202，创建首轮及生成任务 |
| `GET /api/generate/jobs?learner_id={learner_id}` | 查询画像下的文本任务 |
| `GET /api/generate/jobs/{run_id}` | 查询单个 Job、资源进度和真实轮次绑定 |
| `POST /api/resources/batches/{batch_id}/continuations` | 同批次追加或整任务重试 |
| `POST /api/generate/jobs/{run_id}/resource-specs/{resource_spec_id}/representations/{representation}/retry` | 精确重试一个资源执行项 |

首轮请求传 `learner_id`、`topic`、资源类型及 `selection_key`，可指定 `knowledge_base_id`。选定目标时，`target_skill_nodes` 仅提交一个节点。返回 `round_id`、`stage_id`、`members[].job_ids` 和默认入口 `primary_default_run_id`。创建能力关闭时新建轮次返回 409 `ROUND_CREATION_DISABLED`，已有轮次仍可读取和测评。需要直接提交异步文本任务时，使用 `POST /api/generate/jobs`。

`include_review` 默认开启，Claim 和补检默认关闭。补检要求同时开启普通审核和 Claim，首轮创建请求须只选一个资源类型。实操指南的直接生成请求需关闭 Claim。追加和手动重试创建关联的 Run，文本表示为 `text`。为支持请求重放，轮次沿用原 `selection_key`，文本任务提交、追加和单项重试可提供 `Idempotency-Key`。

## 资源读取、审核与事件

| 方法和路径 | 用途 |
|---|---|
| `GET /api/resources/{learner_id}` | 文本列表，可按 `run_id` 过滤 |
| `GET /api/resources/items/{resource_id}`、`GET /api/resources/file/{resource_id}` | 已发布正文与文件 |
| `GET /api/resource-library/{learner_id}` | 文本与课件统一书架 |
| `GET /api/reviews/{resource_id}` | 普通审核摘要 |
| `GET /api/runs/{run_id}/timeline` | 步骤与版本关系 |
| `GET /api/runs/{run_id}/evidence`、`GET /api/runs/{run_id}/claims` | 冻结来源与公开 Claim 判定 |
| `GET /api/runs/{run_id}/claim-evidence-retrieval`、`GET /api/runs/{run_id}/resource-quality` | 补检结果与版本化质量指标 |
| `POST /api/resources/items/{resource_id}/claim-publication-decision` | 对待用户决策的资源提交 `{"publish": true}` 或 `false` |

文本 Run SSE 为 `GET /api/runs/{run_id}/events`。先收到 `snapshot`，再按 `sequence` 回放和追踪。重连游标优先使用 `Last-Event-ID`，否则读取 `after_sequence`，默认从 0 开始。客户端按序号去重，`ping` 不推进游标。已排队 Job 可能暂时没有 AgentRun，终态发送完 backlog 后关闭流。

事件只提供脱敏进度。正文、完整证据和 Claim 通过各自详情接口读取。测评题的答案和评分要点按权限裁剪，未完成或未知的质量指标保留对应状态。

## 阶段测评与后续选择

| 方法和路径 | 用途 |
|---|---|
| `GET /api/feedback/rounds` | 按 `learner_id` 分页读取轮次 |
| `GET /api/feedback/rounds/{round_id}` | 读取阶段、成员与任务绑定 |
| `POST /api/feedback/rounds/{round_id}/stages/{stage_id}/evaluation-session` | 创建或读取已冻结的分组题目 |
| `POST /api/feedback/rounds/{round_id}/stages/{stage_id}/attempts` | 提交整个阶段的作答，分别按节点评分 |
| `GET /api/feedback/rounds/{round_id}/stages/{stage_id}/result` | 查询正式结果、评分中或未提交状态 |
| `GET /api/feedback/rounds/{round_id}/candidates` | 带 `source_attempt_id` 读取候选和已确认选择 |
| `POST /api/feedback/rounds/next/select` | 202，基于来源 Attempt 创建下一轮 |
| `POST /api/feedback/rounds/{round_id}/corrections` | 202，本轮追加纠错阶段 |

提交时提供 `learner_id`、`session_id`、`manifest_hash`、`expected_profile_version`、`idempotency_key`、含时区的 `submitted_at` 与 `answers`，可附学习反思。评分中为 202，正式结果为 200。资源或题组未就绪时返回 409，重复或缺失题目等校验失败返回 422。同一会话的幂等重放须使用相同键和请求内容。

再次测评通过 `evaluation-session` 的 `retake_from_session_id` 获取新会话，复用该阶段冻结题组。结果默认读取最新会话，可带 `session_id` 查看指定会话。

下一轮用 `source_attempt_id`、主节点、主节点学习意图、资源组合及 `selection_key` 提交，符合资格时传 `review_node_id`。纠错提交 1–2 个互不重复的节点目标，每项包含 `node_id` 和 `source_attempt_id`。候选响应中的 `confirmed_selection` 反映服务端持久化的选择。

## 互动课件与 Tutor

课件路径统一以 `/api/resources/courseware` 为前缀。

| 方法和路径 | 用途 |
|---|---|
| `POST /api/resources/courseware/jobs` | 200，使用一个 `source_resource_ids` 项创建任务 |
| `POST /api/resources/courseware/jobs/batch` | 202，提交 `resource_ids`，每个来源创建独立任务 |
| `GET /api/resources/courseware/jobs`、`GET /api/resources/courseware/jobs/{run_id}` | 按画像列出或读取单个任务 |
| `GET /api/resources/courseware/jobs/{run_id}/detail`、`GET /api/resources/courseware/jobs/{run_id}/events` | 任务详情和独立事件流，流使用 `after_sequence` |
| `GET /api/resources/courseware/items/{resource_id}/preview`、`GET /api/resources/courseware/items/{resource_id}/file` | 当前 release 的预览与下载 |
| `POST /api/resources/courseware/items/{resource_id}/learning-events` | 按当前 release 批量上传事件 |
| `GET /api/resources/courseware/items/{resource_id}/learning-progress` | 读取当前 release 的学习投影 |

学习事件按 `occurrence_id` 去重，客户端按 `acknowledged_event_ids` 确认发送。旧 release 或混合 release 的提交返回 409。课件发布受自动校验与 artifact 完整性保护。

Tutor 通过 `POST /api/tutor/sessions` 创建或恢复会话，`GET /api/tutor/sessions/{session_id}` 恢复上下文，`POST /api/tutor/sessions/{session_id}/turns` 提交一轮求助。服务端核对来源与会话归属，并控制提示和证据范围。

## 历史、报告与计量

- `GET /api/learning-history/{learner_id}/journey` 返回轮次、阶段和学习记录。
- `GET /api/report/{learner_id}` 支持 `window_days=7|30|90` 与 `If-None-Match`。报告未变化时为 304。对应 `GET /api/report/{learner_id}/events` 发送 `report_snapshot` 和 `report_changed`，客户端按 revision 重新拉取快照。
- `GET /api/runs/{run_id}/llm-accounting` 与 `GET /api/resources/courseware/jobs/{run_id}/llm-accounting` 读取各自任务的计量。按可用性和完整性状态展示，记录缺失时不补零。
