# API 接口文档

> 项目编号：XH-202630  
> 项目名称：领域知识个性化生成与多智能体协同决策系统  
> 基础路径：`http://localhost:8000`  
> 文档版本：v1.0  
> 文档定位：以分工任务书要求为目标，定义通用领域知识生成系统的 API 契约、字段类型、必填规则、链路逻辑和当前建设状态。

## 1. 设计原则

- **字段通用**：接口字段不硬编码任何特定领域。领域由 `knowledge_base_id`、`target_domain`、`topic`、能力节点、画像和知识库内容决定。
- **示例可具体**：JSON 示例可使用 RAG 工程训练作为演示数据，但字段本身必须能迁移到其他领域。
- **闭环完整**：接口需要支撑“画像 -> 能力诊断 -> 知识检索 -> 路径规划 -> 资源生成 -> 审核纠偏 -> 反馈更新 -> 报告评测”的完整链路。
- **分阶段落地**：当前代码优先跑通最小闭环；能力图谱、诊断题、Claim 审核、评测等接口先以契约明确，再逐步实现。

## 2. 状态说明

| 状态 | 含义 |
|------|------|
| 当前参考路由 | 当前代码已有路由，可用于最小功能联调 |
| 待增强路由 | 当前有基础能力，但字段、持久化或展示仍需增强 |
| 设计待建设 | 为完整分工目标预留的接口，当前代码可能尚未实现 |

## 3. 完整业务闭环

```text
POST /api/learner/profile
→ GET /api/skills/nodes
→ GET /api/diagnosis/questions
→ POST /api/diagnosis/submit
→ POST /api/generate/
→ GET /api/resources/{learner_id}
→ GET /api/reviews/{resource_id}
→ POST /api/feedback/
→ GET /api/feedback/history/{learner_id}
→ GET /api/report/{learner_id}
→ GET /api/evaluation/summary
→ POST /api/generate/ 进入下一轮
```

最小演示链路：

```text
POST /api/learner/profile
→ POST /api/generate/
→ POST /api/feedback/
→ GET /api/report/{learner_id}
```

## 4. 接口总览

| 模块 | 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|------|
| 系统 | GET | `/` | 健康检查 | 当前参考路由 |
| 学习者 | POST | `/api/learner/profile` | 创建或更新画像 | 当前参考路由 |
| 学习者 | GET | `/api/learner/profile/{learner_id}` | 查询画像 | 当前参考路由 |
| 能力图谱 | GET | `/api/skills/nodes` | 查询当前知识库的能力节点 | 设计待建设 |
| 诊断 | GET | `/api/diagnosis/questions` | 获取诊断题 | 设计待建设 |
| 诊断 | POST | `/api/diagnosis/submit` | 提交诊断并更新知识状态 | 设计待建设 |
| 生成 | POST | `/api/generate/` | 多 Agent 协同生成资源 | 当前参考路由 |
| 资源 | GET | `/api/resources/{learner_id}` | 查询资源历史 | 当前参考路由 |
| 审核 | GET | `/api/reviews/{resource_id}` | 查询资源审核详情 | 设计待建设 |
| 反馈 | POST | `/api/feedback/` | 提交反馈并更新画像 | 当前参考路由 |
| 反馈 | GET | `/api/feedback/history/{learner_id}` | 查询反馈历史 | 当前参考路由 |
| 报告 | GET | `/api/report/{learner_id}` | 查询学情报告 | 待增强路由 |
| 评测 | GET | `/api/evaluation/summary` | 查询量化评测摘要 | 设计待建设 |
| 知识库 | GET | `/api/knowledge/info` | 查询知识库信息 | 设计待建设 |

## 5. 通用数据对象

### 5.1 LearnerProfile

学习者画像用于诊断、生成、反馈和报告。字段必须描述“学习者状态”，不能描述固定领域实现细节。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者唯一标识 |
| `learner_type` | string | 是 | 学习者类型，如初学者、有基础、进阶；允许业务自定义 |
| `education` | string | 是 | 学历或学习背景 |
| `major` | string | 是 | 专业、岗位或学习方向 |
| `target_domain` | string | 否 | 当前目标领域名称，由用户或知识库决定 |
| `knowledge_base_id` | string | 否 | 当前使用的知识库标识 |
| `theory_scores` | object<string, number> | 否 | 主题或能力维度得分，通常为 0-100 |
| `knowledge_states` | object<string, KnowledgeState> | 否 | 知识点掌握状态 |
| `skill_level` | string | 否 | 综合能力等级 |
| `weak_points` | string[] | 否 | 当前薄弱知识点或能力节点 |
| `strong_points` | string[] | 否 | 当前优势知识点或能力节点 |
| `learning_goal` | string | 是 | 学习目标 |
| `learning_preferences` | LearningPreferences | 否 | 学习偏好 |
| `last_feedback_summary` | object | 否 | 最近反馈摘要，用于下一轮调整 |

```json
{
  "learner_id": "learner_001",
  "learner_type": "有基础学习者",
  "education": "本科",
  "major": "计算机科学与技术",
  "target_domain": "RAG 工程训练",
  "knowledge_base_id": "kb_rag_demo",
  "theory_scores": {
    "文档解析": 70,
    "检索策略": 45
  },
  "knowledge_states": {
    "检索策略": {
      "score": 0.45,
      "status": "weak",
      "last_updated": "2026-07-23T09:30:00"
    }
  },
  "skill_level": "中级",
  "weak_points": ["检索策略"],
  "strong_points": ["文档解析"],
  "learning_goal": "掌握从知识库检索到生成审核的完整工程流程",
  "learning_preferences": {
    "preferred_resource_types": ["定制讲义", "实操指南"],
    "difficulty_preference": "自适应",
    "time_budget_minutes": 30
  },
  "last_feedback_summary": {
    "resource_id": "res_001",
    "correct_rate": 0.55,
    "decision": "降维解释"
  }
}
```

### 5.2 KnowledgeState

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `score` | number | 否 | 掌握度，建议 0-1 |
| `status` | string | 否 | 状态，如 unknown、learning、weak、mastered |
| `evidence` | string[] | 否 | 状态依据，如诊断题、反馈、资源记录 |
| `last_updated` | string(datetime) | 否 | 最近更新时间 |

### 5.3 LearningPreferences

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `preferred_resource_types` | string[] | 否 | 偏好的资源类型 |
| `difficulty_preference` | string | 否 | 难度偏好，如自适应、基础、进阶 |
| `time_budget_minutes` | integer | 否 | 单次学习时间预算 |
| `language` | string | 否 | 输出语言 |
| `metadata` | object | 否 | 扩展偏好 |

### 5.4 SkillNode

能力节点用于构建当前知识库的训练图谱。字段名保持通用，节点内容由知识库决定。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | string | 是 | 节点唯一标识 |
| `knowledge_base_id` | string | 是 | 所属知识库 |
| `name` | string | 是 | 节点名称 |
| `description` | string | 否 | 节点说明 |
| `level` | string | 否 | 节点层级或难度 |
| `prerequisites` | string[] | 否 | 前置节点 ID 或名称 |
| `children` | string[] | 否 | 后继节点 ID 或名称 |
| `knowledge_points` | string[] | 否 | 关联知识点 |
| `assessment_methods` | string[] | 否 | 适合的诊断或评测方式 |
| `metadata` | object | 否 | 扩展信息 |

```json
{
  "node_id": "skill_retrieval",
  "knowledge_base_id": "kb_rag_demo",
  "name": "检索策略",
  "description": "理解相似度检索、混合检索和召回质量评估",
  "level": "中级",
  "prerequisites": ["skill_embedding"],
  "children": ["skill_rerank"],
  "knowledge_points": ["Top-K", "相似度", "混合检索"],
  "assessment_methods": ["选择题", "实操任务"],
  "metadata": {}
}
```

### 5.5 DiagnosticQuestion

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `question_id` | string | 是 | 诊断题唯一标识 |
| `knowledge_base_id` | string | 是 | 所属知识库 |
| `skill_node_id` | string | 否 | 绑定能力节点 |
| `knowledge_point` | string | 否 | 绑定知识点 |
| `question_type` | string | 是 | 题型，如 single_choice、multiple_choice、short_answer、practice |
| `difficulty` | string | 否 | 难度 |
| `question` | string | 是 | 题干 |
| `options` | string[] | 否 | 选项，客观题使用 |
| `answer` | any | 否 | 标准答案，前端展示时可隐藏 |
| `explanation` | string | 否 | 解析 |
| `metadata` | object | 否 | 扩展信息 |

```json
{
  "question_id": "q_001",
  "knowledge_base_id": "kb_rag_demo",
  "skill_node_id": "skill_retrieval",
  "knowledge_point": "Top-K",
  "question_type": "single_choice",
  "difficulty": "基础",
  "question": "当 Top-K 设置过小，最可能带来什么问题？",
  "options": ["召回不足", "索引无法构建", "文档无法切分", "模型无法输出"],
  "answer": "召回不足",
  "explanation": "Top-K 太小可能遗漏相关片段，影响后续生成质量。",
  "metadata": {}
}
```

### 5.6 DiagnosticResult

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `diagnostic_result_id` | string | 是 | 诊断结果唯一标识 |
| `learner_id` | string | 是 | 学习者 ID |
| `knowledge_base_id` | string | 否 | 当前知识库 |
| `ability_level` | string | 是 | 综合能力等级 |
| `weak_points` | string[] | 否 | 薄弱点 |
| `strong_points` | string[] | 否 | 优势点 |
| `knowledge_states` | object<string, KnowledgeState> | 否 | 诊断后的知识状态 |
| `recommended_path` | LearningPathItem[] | 否 | 推荐学习路径 |
| `created_at` | string(datetime) | 否 | 创建时间 |

```json
{
  "diagnostic_result_id": "diag_001",
  "learner_id": "learner_001",
  "knowledge_base_id": "kb_rag_demo",
  "ability_level": "中级",
  "weak_points": ["检索策略"],
  "strong_points": ["文档解析"],
  "knowledge_states": {},
  "recommended_path": [
    {"order": 1, "topic": "检索策略", "reason": "当前得分低，建议优先补齐"}
  ],
  "created_at": "2026-07-23T09:30:00"
}
```

### 5.7 GenerateRequest

生成请求需要把画像、诊断、目标主题、资源类型和协同控制参数传入服务层。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `topic` | string | 是 | 当前学习或生成主题 |
| `knowledge_base_id` | string | 否 | 指定知识库；缺省使用画像或系统默认知识库 |
| `diagnostic_result_id` | string | 否 | 指定诊断结果 |
| `target_skill_nodes` | string[] | 否 | 本次重点训练的能力节点 |
| `resource_types` | string[] | 否 | 需要生成的资源类型 |
| `difficulty_preference` | string | 否 | 难度偏好 |
| `generation_mode` | string | 否 | 生成模式，如讲解、实操、测评、综合训练 |
| `include_review` | boolean | 否 | 是否进入审核纠偏 |
| `include_claim_check` | boolean | 否 | 是否进行 Claim 级审核 |
| `max_iterations` | integer | 否 | 审核不通过时最大重试次数 |
| `constraints` | object | 否 | 生成约束，如字数、语言、是否必须引用 |

```json
{
  "learner_id": "learner_001",
  "topic": "检索策略入门到实操",
  "knowledge_base_id": "kb_rag_demo",
  "diagnostic_result_id": "diag_001",
  "target_skill_nodes": ["skill_retrieval"],
  "resource_types": ["定制讲义", "实操指南", "分阶测试题"],
  "difficulty_preference": "自适应",
  "generation_mode": "综合训练",
  "include_review": true,
  "include_claim_check": true,
  "max_iterations": 2,
  "constraints": {
    "must_include_citations": true,
    "max_words": 2000,
    "language": "zh-CN"
  }
}
```

### 5.8 LearningPlan

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learning_path` | LearningPathItem[] | 否 | 推荐学习顺序 |
| `skip_points` | string[] | 否 | 可跳过内容 |
| `remedial_points` | string[] | 否 | 需要补救内容 |
| `challenge_points` | string[] | 否 | 进阶挑战内容 |
| `resource_requirements` | object<string, string> | 否 | 不同资源类型的生成要求 |
| `decision_reason` | string | 否 | 规划理由 |

```json
{
  "learning_path": [
    {"order": 1, "topic": "相似度检索", "reason": "先补齐基础概念"},
    {"order": 2, "topic": "混合检索", "reason": "再理解召回策略差异"}
  ],
  "skip_points": ["文档解析"],
  "remedial_points": ["Top-K 参数"],
  "challenge_points": ["混合检索对比实验"],
  "resource_requirements": {
    "定制讲义": "解释核心概念和常见错误",
    "实操指南": "提供可执行步骤",
    "分阶测试题": "覆盖基础、应用和反思题"
  },
  "decision_reason": "根据画像得分、薄弱点和检索证据安排路径"
}
```

### 5.9 SourceRef

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_id` | string | 是 | 来源文档 ID |
| `chunk_id` | string | 否 | 来源片段 ID |
| `title` | string | 是 | 来源标题 |
| `snippet` | string | 是 | 引用片段摘要 |
| `score` | number | 是 | 检索相关度或证据分数 |
| `knowledge_point` | string | 否 | 关联知识点 |
| `section` | string | 否 | 文档章节 |
| `page` | integer | 否 | 页码 |
| `source_path` | string | 否 | 来源路径或 URL |
| `retrieval_query` | string | 否 | 召回该片段的查询词 |
| `rank` | integer | 否 | 检索排序 |
| `metadata` | object | 否 | 扩展信息 |

### 5.10 LearningResource

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `resource_id` | string | 是 | 资源唯一标识 |
| `learner_id` | string | 否 | 所属学习者 |
| `topic` | string | 否 | 资源主题 |
| `resource_type` | string | 是 | 资源类型 |
| `difficulty` | string | 是 | 资源难度 |
| `storage_type` | string | 否 | `text` 或 `file` |
| `content_text` | string | 否 | 文本正文或文件摘要 |
| `file_path` | string | 否 | 文件相对路径 |
| `file_size` | integer | 否 | 文件大小 |
| `mime_type` | string | 否 | MIME 类型 |
| `knowledge_points` | string[] | 是 | 覆盖知识点 |
| `source_refs` | SourceRef[] | 是 | 知识溯源 |
| `learning_path_node` | string | 否 | 对应学习路径节点 |
| `review_status` | string | 否 | 审核状态，如 pending、passed、revision_required |
| `review_id` | string | 否 | 审核记录 ID |
| `claim_count` | integer | 否 | Claim 总数 |
| `hallucination_rate` | number | 否 | 幻觉率 |
| `difficulty_match` | boolean | 否 | 难度是否匹配画像 |
| `version` | integer | 否 | 资源版本 |
| `parent_resource_id` | string | 否 | 重写前资源 ID |
| `created_at` | string(datetime) | 否 | 创建时间 |
| `exercise_items` | ExerciseItem[] | 否 | 测试题或练习项 |

```json
{
  "resource_id": "res_001",
  "learner_id": "learner_001",
  "topic": "检索策略入门到实操",
  "resource_type": "实操指南",
  "difficulty": "中级",
  "storage_type": "text",
  "content_text": "资源正文",
  "file_path": "data/generated_resources/text/learner_001/res_001.md",
  "file_size": 2048,
  "mime_type": "text/markdown",
  "knowledge_points": ["Top-K", "混合检索"],
  "source_refs": [
    {
      "doc_id": "doc_001",
      "chunk_id": "chunk_001",
      "title": "retrieval.md",
      "snippet": "Top-K 控制检索阶段返回的候选片段数量。",
      "score": 0.89,
      "knowledge_point": "Top-K",
      "section": "检索策略",
      "rank": 1
    }
  ],
  "learning_path_node": "检索策略",
  "review_status": "passed",
  "review_id": "review_001",
  "claim_count": 12,
  "hallucination_rate": 0.03,
  "difficulty_match": true,
  "version": 1,
  "parent_resource_id": null,
  "created_at": "2026-07-23T09:30:00",
  "exercise_items": [
    {
      "question_id": "q1",
      "knowledge_point": "Top-K",
      "difficulty": "基础",
      "question": "Top-K 过小可能造成什么问题？",
      "answer": "召回不足",
      "explanation": "候选片段太少会遗漏相关证据。"
    }
  ]
}
```

### 5.11 ExerciseItem

`exercise_items` 是资源内的练习或测试题条目，用于后续反馈接口。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `question_id` | string | 是 | 题目唯一标识 |
| `knowledge_point` | string | 否 | 关联知识点 |
| `difficulty` | string | 否 | 题目难度 |
| `question` | string | 是 | 题干 |
| `answer` | any | 否 | 参考答案 |
| `explanation` | string | 否 | 解析 |

### 5.12 AgentTrace / AgentRun

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `run_id` | string | 否 | 本次 Agent 运行 ID |
| `step_id` | string | 否 | 当前步骤 ID |
| `agent_name` | string | 是 | Agent 名称 |
| `action` | string | 是 | 当前动作 |
| `status` | string | 否 | success、failed、skipped、retrying |
| `input_summary` | string | 否 | 输入摘要 |
| `output_summary` | string | 是 | 输出摘要 |
| `input_payload` | object | 否 | 结构化输入 |
| `output_payload` | object | 否 | 结构化输出 |
| `decision_reason` | string | 否 | 决策理由 |
| `evidence_refs` | string[] | 否 | 证据引用 ID 或路径 |
| `review_summary` | object | 否 | 审核摘要 |
| `retry_count` | integer | 否 | 重试次数 |
| `error_message` | string | 否 | 错误信息 |
| `timestamp` | string(datetime) | 否 | 兼容字段，记录时间 |
| `started_at` | string(datetime) | 否 | 开始时间 |
| `ended_at` | string(datetime) | 否 | 结束时间 |
| `duration_ms` | integer | 否 | 耗时毫秒 |

```json
{
  "run_id": "run_001",
  "step_id": "step_003",
  "agent_name": "planner",
  "action": "学习路径规划",
  "status": "success",
  "input_summary": "画像等级中级，薄弱点为检索策略",
  "output_summary": "规划 2 个学习节点和 3 类资源要求",
  "input_payload": {},
  "output_payload": {},
  "decision_reason": "优先补齐召回策略，再进入实验任务",
  "evidence_refs": ["doc_001#chunk_001"],
  "review_summary": {},
  "retry_count": 0,
  "timestamp": "2026-07-23T09:30:00"
}
```

### 5.13 GenerateReport

`POST /api/generate/` 的 `report` 字段使用该对象，描述本次生成和审核摘要。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `ability_level` | string | 否 | 本次判断的能力等级 |
| `ability_tags` | string[] | 否 | 能力标签 |
| `weak_points` | string[] | 否 | 本次生成关注的薄弱点 |
| `recommended_difficulty` | string | 否 | 推荐难度 |
| `learning_plan` | object | 否 | 学习路径规划摘要 |
| `review_summary` | object | 否 | 审核摘要 |
| `hallucination_rate` | number | 否 | 幻觉率 |
| `coverage_rate` | number | 否 | 知识点覆盖率 |
| `difficulty_match` | boolean | 否 | 难度是否匹配 |
| `retrieval_hit_rate` | number | 否 | 检索命中率 |
| `revision_count` | integer | 否 | 审核修正次数 |
| `next_suggestions` | string[] | 否 | 下一步建议 |

### 5.14 ReviewSummary / ResourceClaim

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `review_id` | string | 是 | 审核记录 ID |
| `resource_id` | string | 是 | 被审核资源 ID |
| `status` | string | 是 | passed、revision_required、failed |
| `claim_total` | integer | 否 | Claim 总数 |
| `claim_supported` | integer | 否 | 证据支持数量 |
| `claim_unsupported` | integer | 否 | 证据不足数量 |
| `suspected_hallucinations` | integer | 否 | 疑似幻觉数量 |
| `hallucination_rate` | number | 否 | 幻觉率 |
| `review_pass_rate` | number | 否 | 审核通过率 |
| `revision_count` | integer | 否 | 修正次数 |
| `issues` | object[] | 否 | 审核问题列表 |
| `claims` | ResourceClaim[] | 否 | Claim 级审核明细 |

ResourceClaim 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `claim_id` | string | 是 | Claim ID |
| `text` | string | 是 | Claim 文本 |
| `knowledge_point` | string | 否 | 关联知识点 |
| `supported` | boolean | 是 | 是否被证据支持 |
| `confidence` | number | 否 | 可信度 |
| `evidence_refs` | SourceRef[] | 否 | 支撑证据 |
| `issue_type` | string | 否 | 问题类型 |
| `correction` | string | 否 | 修正建议 |
| `review_comment` | string | 否 | 审核说明 |

```json
{
  "review_id": "review_001",
  "resource_id": "res_001",
  "status": "passed",
  "claim_total": 12,
  "claim_supported": 11,
  "claim_unsupported": 1,
  "suspected_hallucinations": 1,
  "hallucination_rate": 0.083,
  "review_pass_rate": 0.917,
  "revision_count": 1,
  "issues": [],
  "claims": [
    {
      "claim_id": "claim_001",
      "text": "Top-K 会影响候选片段召回数量。",
      "knowledge_point": "Top-K",
      "supported": true,
      "confidence": 0.91,
      "evidence_refs": [],
      "issue_type": null,
      "correction": null,
      "review_comment": "证据支持"
    }
  ]
}
```

### 5.15 FeedbackRequest / FeedbackResponse

FeedbackRequest 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `resource_id` | string | 是 | 反馈对应资源 |
| `feedback_type` | string | 否 | feedback、quiz、practice、manual_review 等 |
| `correct_rate` | number | 是 | 正确率，0-1 |
| `time_spent_seconds` | integer | 否 | 学习或实操耗时 |
| `completed` | boolean | 否 | 是否完成 |
| `self_rating` | integer | 否 | 自评，建议 1-5 |
| `practice_result` | object | 否 | 实操反馈结果 |
| `answers` | FeedbackAnswer[] | 否 | 答题明细 |

FeedbackAnswer 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `question_id` | string | 是 | 题目 ID |
| `knowledge_point` | string | 否 | 关联知识点 |
| `difficulty` | string | 否 | 题目难度 |
| `correct` | boolean | 是 | 是否正确 |
| `answer` | any | 否 | 学习者答案 |
| `expected_answer` | any | 否 | 参考答案 |
| `error_type` | string | 否 | 错误类型 |

```json
{
  "learner_id": "learner_001",
  "resource_id": "res_001",
  "feedback_type": "quiz",
  "correct_rate": 0.55,
  "time_spent_seconds": 600,
  "completed": true,
  "self_rating": 3,
  "practice_result": {
    "success": false,
    "error_summary": "混合检索参数选择错误"
  },
  "answers": [
    {
      "question_id": "q1",
      "knowledge_point": "Top-K",
      "difficulty": "基础",
      "correct": false,
      "answer": "越小越好",
      "expected_answer": "需要结合召回和噪声平衡",
      "error_type": "concept"
    }
  ]
}
```

FeedbackResponse 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `decision` | string | 是 | 反馈决策 |
| `decision_reason` | string | 否 | 决策理由 |
| `message` | string | 是 | 面向前端展示的提示 |
| `next_action` | string | 否 | 下一步动作，如 regenerate、practice、challenge、continue |
| `recommended_topics` | string[] | 否 | 推荐下一轮主题 |
| `updated_knowledge_states` | object<string, KnowledgeState> | 否 | 更新后的知识状态 |
| `regenerate_suggestion` | object | 否 | 再生成建议 |
| `updated_profile` | LearnerProfile | 否 | 更新后的画像 |

反馈响应字段由反馈决策 Agent 产生，API service 只负责保存反馈记录、应用画像更新并返回结果。Agent 的内部输出还包含 `profile_updates` 和 `trace`，后续如需展示反馈 Agent 过程，可扩展到反馈历史或 Agent 运行记录接口。

### 5.16 FeedbackRecord

反馈历史接口返回该对象。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `feedback_id` | string | 是 | 反馈记录 ID |
| `learner_id` | string | 是 | 学习者 ID |
| `resource_id` | string | 是 | 资源 ID |
| `correct_rate` | number | 是 | 正确率，0-1 |
| `decision` | string | 是 | 反馈决策 |
| `answers` | FeedbackAnswer[] | 否 | 答题明细 |
| `feedback_type` | string | 否 | 反馈类型 |
| `time_spent_seconds` | integer | 否 | 耗时 |
| `completed` | boolean | 否 | 是否完成 |
| `self_rating` | integer | 否 | 自评，建议 1-5 |
| `practice_result` | object | 否 | 实操反馈结果 |
| `decision_reason` | string | 否 | 决策理由 |
| `next_action` | string | 否 | 下一步动作 |
| `recommended_topics` | string[] | 否 | 推荐主题 |
| `updated_knowledge_states` | object<string, KnowledgeState> | 否 | 更新后的知识状态 |
| `regenerate_suggestion` | object | 否 | 再生成建议 |
| `created_at` | string(datetime) | 否 | 创建时间 |

### 5.17 ReportRadar / DifficultyCurveItem

ReportRadar 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dimensions` | string[] | 是 | 雷达图维度 |
| `values` | number[] | 是 | 各维度得分 |

DifficultyCurveItem 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `topic` | string | 是 | 主题或知识点 |
| `score` | number | 是 | 当前得分 |
| `recommended_difficulty` | string | 是 | 推荐难度 |

## 6. 关键接口契约

### 6.1 POST `/api/learner/profile`

创建或更新学习者画像。

请求体字段：见 `LearnerProfile`。

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | string | 是 | 响应状态 |
| `message` | string | 否 | 响应消息 |
| `learner_id` | string | 是 | 学习者 ID |

响应示例：

```json
{
  "status": "success",
  "message": null,
  "learner_id": "learner_001"
}
```

### 6.2 GET `/api/learner/profile/{learner_id}`

查询学习者画像。

路径参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |

响应字段：见 `LearnerProfile`。

### 6.3 GET `/api/skills/nodes`

查询当前知识库的能力节点图谱。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | string | 否 | 知识库 ID |
| `target_domain` | string | 否 | 目标领域 |
| `level` | string | 否 | 节点难度或层级 |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | string | 是 | 知识库 ID |
| `nodes` | SkillNode[] | 是 | 能力节点 |
| `edges` | object[] | 否 | 节点关系 |

```json
{
  "knowledge_base_id": "kb_rag_demo",
  "nodes": [],
  "edges": [
    {"source": "skill_embedding", "target": "skill_retrieval", "relation": "prerequisite"}
  ]
}
```

### 6.4 GET `/api/diagnosis/questions`

获取诊断题。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | string | 否 | 知识库 ID |
| `learner_id` | string | 否 | 学习者 ID，用于个性化出题 |
| `skill_node_ids` | string | 否 | 逗号分隔的目标节点 ID |
| `level` | string | 否 | 难度 |
| `limit` | integer | 否 | 返回数量 |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `questions` | DiagnosticQuestion[] | 是 | 诊断题列表 |

```json
{
  "questions": []
}
```

### 6.5 POST `/api/diagnosis/submit`

提交诊断结果并更新知识状态。

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `knowledge_base_id` | string | 否 | 知识库 ID |
| `answers` | FeedbackAnswer[] | 是 | 诊断答题明细 |
| `metadata` | object | 否 | 扩展信息 |

响应字段：见 `DiagnosticResult`。

### 6.6 POST `/api/generate/`

多 Agent 协同生成资源。

请求字段：见 `GenerateRequest`。

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `topic` | string | 是 | 生成主题 |
| `resources` | LearningResource[] | 是 | 生成资源 |
| `trace` | AgentTrace[] | 是 | Agent 协同轨迹 |
| `report` | GenerateReport | 是 | 本次生成摘要 |

```json
{
  "learner_id": "learner_001",
  "topic": "检索策略入门到实操",
  "resources": [],
  "trace": [],
  "report": {
    "learner_id": "learner_001",
    "ability_level": "中级",
    "weak_points": ["检索策略"],
    "recommended_difficulty": "中级",
    "hallucination_rate": 0.03,
    "coverage_rate": 0.9,
    "difficulty_match": true
  }
}
```

### 6.7 GET `/api/resources/{learner_id}`

查询学习者历史生成资源。

路径参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `total` | integer | 是 | 资源数量 |
| `resources` | LearningResource[] | 是 | 资源列表 |

```json
{
  "learner_id": "learner_001",
  "total": 1,
  "resources": []
}
```

### 6.8 GET `/api/reviews/{resource_id}`

查询资源审核详情。

路径参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `resource_id` | string | 是 | 资源 ID |

响应字段：见 `ReviewSummary`。

### 6.9 POST `/api/feedback/`

提交学习反馈，触发反馈决策 Agent，并动态更新画像与下一轮学习建议。

请求字段：见 `FeedbackRequest`。

响应字段：见 `FeedbackResponse`。

### 6.10 GET `/api/feedback/history/{learner_id}`

查询学习反馈历史。

路径参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `total` | integer | 是 | 反馈数量 |
| `items` | FeedbackRecord[] | 是 | 反馈记录 |

```json
{
  "learner_id": "learner_001",
  "total": 1,
  "items": []
}
```

### 6.11 GET `/api/report/{learner_id}`

查询学情报告。

路径参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `learner_id` | string | 是 | 学习者 ID |
| `radar` | ReportRadar | 是 | 能力雷达图数据 |
| `weak_points` | string[] | 是 | 薄弱点 |
| `strong_points` | string[] | 是 | 优势点 |
| `skill_level` | string | 是 | 能力等级 |
| `learning_goal` | string | 是 | 学习目标 |
| `difficulty_curve` | DifficultyCurveItem[] | 是 | 难度适配曲线 |
| `learning_path` | LearningPathItem[] | 否 | 推荐路径 |
| `blind_spot_heatmap` | object[] | 否 | 知识盲区热力图数据 |
| `agent_flow` | AgentTrace[] | 否 | Agent 流程展示数据 |
| `resource_difficulty_match` | object[] | 否 | 资源难度匹配结果 |
| `review_summary` | object | 否 | 审核摘要 |
| `feedback_trend` | object[] | 否 | 反馈趋势 |
| `metric_summary` | object | 否 | 指标摘要 |
| `next_suggestions` | string[] | 否 | 下一步建议 |
| `recent_resources` | LearningResource[] | 否 | 最近资源 |
| `recent_feedback` | FeedbackRecord[] | 否 | 最近反馈 |

```json
{
  "learner_id": "learner_001",
  "radar": {"dimensions": ["文档解析", "检索策略"], "values": [70, 45]},
  "weak_points": ["检索策略"],
  "strong_points": ["文档解析"],
  "skill_level": "中级",
  "learning_goal": "掌握完整工程流程",
  "difficulty_curve": [
    {"topic": "检索策略", "score": 45, "recommended_difficulty": "初级"}
  ],
  "learning_path": [],
  "blind_spot_heatmap": [],
  "agent_flow": [],
  "resource_difficulty_match": [],
  "review_summary": {},
  "feedback_trend": [],
  "metric_summary": {},
  "next_suggestions": [],
  "recent_resources": [],
  "recent_feedback": []
}
```

### 6.12 GET `/api/evaluation/summary`

查询量化评测摘要。

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sample_count` | integer | 是 | 评测样本数量 |
| `metrics` | object<string, number> | 是 | 指标集合 |
| `ablation` | object[] | 否 | 消融实验结果 |
| `created_at` | string(datetime) | 否 | 统计时间 |

```json
{
  "sample_count": 50,
  "metrics": {
    "hallucination_rate": 0.04,
    "knowledge_coverage_rate": 0.91,
    "difficulty_match_accuracy": 0.86,
    "retrieval_hit_rate": 0.92,
    "post_feedback_improvement": 0.18
  },
  "ablation": [
    {
      "method": "baseline",
      "description": "无检索或无审核的基线方法",
      "hallucination_rate": 0.18,
      "coverage_rate": 0.68
    }
  ],
  "created_at": "2026-07-23T09:30:00"
}
```

### 6.13 GET `/api/knowledge/info`

查询当前知识库信息。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | string | 否 | 知识库 ID |

响应字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | string | 是 | 知识库 ID |
| `target_domain` | string | 否 | 领域名称 |
| `description` | string | 否 | 知识库说明 |
| `document_count` | integer | 否 | 文档数量 |
| `chunk_count` | integer | 否 | 片段数量 |
| `skill_node_count` | integer | 否 | 能力节点数量 |
| `updated_at` | string(datetime) | 否 | 更新时间 |

```json
{
  "knowledge_base_id": "kb_rag_demo",
  "target_domain": "RAG 工程训练",
  "description": "用于演示的工程技能知识库",
  "document_count": 12,
  "chunk_count": 96,
  "skill_node_count": 10,
  "updated_at": "2026-07-23T09:30:00"
}
```

## 7. 当前实现与目标差异

当前代码已支持最小闭环：

- 创建/查询画像。
- 调用多 Agent 生成资源。
- 返回 Agent trace。
- 保存生成资源。
- 提交反馈并保存反馈历史。
- 聚合画像、资源和反馈生成报告。

仍需逐步增强：

- 能力图谱、诊断题、诊断提交接口。
- Agent run/step 结构化持久化。
- Claim 级审核、资源审核记录和修正版本。
- 报告中的热力图、Agent 流程图、难度匹配、审核汇总和反馈趋势。
- 评测样本、指标统计和消融实验接口。

## 8. 错误响应

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | string | 是 | 固定为 `error` |
| `message` | string | 是 | 错误描述 |
| `detail` | any | 否 | 详细错误信息 |

```json
{
  "status": "error",
  "message": "学习者画像不存在",
  "detail": null
}
```
