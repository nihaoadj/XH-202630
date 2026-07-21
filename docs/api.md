# API 接口文档

> 项目编号：XH-202630
> 项目名称：领域知识个性化生成与多智能体协同决策系统
> 基础路径：`http://localhost:8000`
> 文档版本：v1.0

## 使用原则

本文档中的接口定义是当前阶段的 API 基线，用于统一请求、响应和状态口径，不是不可调整的最终实现约束。并行开发过程中，若业务需要、验证结果或架构调整导致接口变更，可以在保持接口语义清晰和文档同步更新的前提下修改实现。

本文档主要覆盖基础接口和设计接口，后续开发可以根据实际情况替换、补充或重构接口实现，但需要保持字段含义、状态码和联调说明一致。

***

## 接口建设状态说明

本项目当前处于设计与架构搭建阶段，本文档同时记录当前代码可参考路由和后续设计接口。分工开发时请按建设状态判断联调范围，不要把当前代码视为最终交付。

| 状态 | 含义 | 当前处理方式 |
|------|------|--------------|
| 当前参考路由 | 代码中已有对应 FastAPI 路由，可进入早期联调和测试 | 作为当前阶段联调基线，后续可替换 |
| 设计待建设 | 为后续开发预留的设计接口，当前代码可能尚未接入 | 由总架构组补路由骨架，再分配业务组实现 |

## 接口总览

| 模块  | 方法     | 路径                                   | 说明     | 建设状态 | 版本   |
| --- | ------ | ------------------------------------ | ------ | ---- | ---- |
| 系统  | GET    | `/`                                  | 健康检查   | 当前参考路由 | v1.0 |
| 系统  | GET    | `/api/system/stats`                  | 系统统计   | 设计待建设 | v1.0 |
| 学习者 | POST   | `/api/learner/profile`               | 创建/更新画像 | 当前参考路由 | v1.0 |
| 学习者 | GET    | `/api/learner/profile/{learner_id}`  | 查询画像   | 当前参考路由 | v1.0 |
| 学习者 | PATCH  | `/api/learner/profile/{learner_id}`  | 部分更新画像 | 设计待建设 | v1.0 |
| 学习者 | GET    | `/api/learner/list`                  | 画像列表   | 设计待建设 | v1.0 |
| 学习者 | DELETE | `/api/learner/profile/{learner_id}`  | 删除画像   | 设计待建设 | v1.0 |
| 资源  | POST   | `/api/generate/`                     | 生成资源   | 当前参考路由 | v1.0 |
| 资源  | GET    | `/api/resources/{learner_id}`        | 资源列表   | 设计待建设 | v1.0 |
| 资源  | GET    | `/api/resources/file/{path}`         | 文件下载   | 设计待建设 | v1.0 |
| 反馈  | POST   | `/api/feedback/`                     | 提交反馈   | 当前参考路由 | v1.0 |
| 反馈  | GET    | `/api/feedback/history/{learner_id}` | 反馈历史   | 设计待建设 | v1.0 |
| 报告  | GET    | `/api/report/{learner_id}`           | 学情报告   | 当前参考路由 | v1.0 |
| 知识库 | GET    | `/api/knowledge/info`                | 知识库信息  | 设计待建设 | v1.0 |

> **版本说明：** `v1.0` 为首版定义的所有接口，后续如有新增或变更将标记为 `v1.1`、`v1.2` 等。
> **实现说明：** 设计待建设接口属于后续开发任务，不作为当前代码能力验收；当前参考路由也允许后续按架构需要替换实现。

***

# 一、系统接口

## 1.1 健康检查

**GET /**

建设状态：当前参考路由

返回系统基本信息。

**响应：**

```json
{
  "message": "领域知识个性化生成与多智能体协同决策系统 API"
}
```

***

## 1.2 系统统计

**GET /api/system/stats**

建设状态：设计待建设

返回系统运行统计数据。

**响应：**

```json
{
  "total_learners": 10,
  "total_resources": 25,
  "total_feedbacks": 50,
  "avg_correct_rate": 0.72,
  "knowledge_base_docs": 3,
  "knowledge_base_chunks": 45
}
```

***

# 二、学习者画像接口

## 2.1 创建/更新画像

**POST /api/learner/profile**

建设状态：当前参考路由

创建或更新学习者画像。

### 请求

```json
{
  "learner_id": "stu_001",
  "education": "本科",
  "major": "计算机科学与技术",
  "theory_scores": {
    "工业互联网架构": 65,
    "OPC UA": 40,
    "MQTT": 70
  },
  "skill_level": "初级",
  "weak_points": ["OPC UA", "边缘计算"],
  "strong_points": ["Python编程"],
  "learning_goal": "掌握工业互联网数据采集"
}
```

### 字段说明

| 字段             | 类型     | 必填 | 说明                 |
| -------------- | ------ | -- | ------------------ |
| learner\_id    | string | ✅  | 唯一标识               |
| education      | string | ✅  | 学历：专科/本科/硕士/博士     |
| major          | string | ✅  | 专业方向               |
| theory\_scores | object | ❌  | 理论得分，键为知识点，值为0-100 |
| skill\_level   | string | ❌  | 技能水平，默认"初级"        |
| weak\_points   | array  | ❌  | 知识盲区               |
| strong\_points | array  | ❌  | 优势领域               |
| learning\_goal | string | ✅  | 学习目标               |

### 响应

```json
{
  "status": "success",
  "learner_id": "stu_001"
}
```

### 错误码

| 状态码 | 说明      |
| --- | ------- |
| 400 | 参数校验失败  |
| 500 | 服务器内部错误 |

***

## 2.2 查询画像

**GET /api/learner/profile/{learner\_id}**

建设状态：当前参考路由

查询指定学习者画像。

### 路径参数

| 参数          | 类型     | 说明    |
| ----------- | ------ | ----- |
| learner\_id | string | 学习者ID |

### 响应

```json
{
  "learner_id": "stu_001",
  "education": "本科",
  "major": "计算机科学与技术",
  "theory_scores": {
    "工业互联网架构": 65.0,
    "OPC UA": 40.0,
    "MQTT": 70.0
  },
  "skill_level": "初级",
  "weak_points": ["OPC UA", "边缘计算"],
  "strong_points": ["Python编程"],
  "learning_goal": "掌握工业互联网数据采集"
}
```

### 错误码

| 状态码 | 说明     |
| --- | ------ |
| 404 | 学习者不存在 |

***

## 2.3 部分更新画像

**PATCH /api/learner/profile/{learner\_id}**

建设状态：设计待建设

部分更新学习者画像字段，仅更新请求中包含的字段。

### 路径参数

| 参数          | 类型     | 说明    |
| ----------- | ------ | ----- |
| learner\_id | string | 学习者ID |

### 请求

```json
{
  "skill_level": "中级",
  "weak_points": ["OPC UA", "边缘计算", "MQTT"]
}
```

### 字段说明

| 字段             | 类型     | 必填 | 说明   |
| -------------- | ------ | -- | ---- |
| education      | string | ❌  | 学历   |
| major          | string | ❌  | 专业方向 |
| theory\_scores | object | ❌  | 理论得分 |
| skill\_level   | string | ❌  | 技能水平 |
| weak\_points   | array  | ❌  | 知识盲区 |
| strong\_points | array  | ❌  | 优势领域 |
| learning\_goal | string | ❌  | 学习目标 |

### 响应

```json
{
  "status": "success",
  "learner_id": "stu_001",
  "updated_fields": ["skill_level", "weak_points"]
}
```

### 错误码

| 状态码 | 说明     |
| --- | ------ |
| 404 | 学习者不存在 |

***

## 2.4 画像列表

**GET /api/learner/list**

建设状态：设计待建设

获取所有学习者画像列表。

### 查询参数

| 参数           | 类型     | 默认值 | 说明      |
| ------------ | ------ | --- | ------- |
| page         | int    | 1   | 页码      |
| page\_size   | int    | 10  | 每页数量    |
| skill\_level | string | -   | 按技能水平筛选 |

### 响应

```json
{
  "total": 10,
  "page": 1,
  "page_size": 10,
  "items": [
    {
      "learner_id": "stu_001",
      "education": "本科",
      "major": "计算机科学与技术",
      "skill_level": "初级",
      "learning_goal": "掌握工业互联网"
    }
  ]
}
```

***

## 2.5 删除画像

**DELETE /api/learner/profile/{learner\_id}**

建设状态：设计待建设

删除指定学习者画像。

### 响应

```json
{
  "status": "success",
  "message": "学习者画像已删除"
}
```

***

# 三、资源生成接口

## 3.1 生成个性化资源

**POST /api/generate/**

建设状态：当前参考路由

触发多智能体协同生成流程。

说明：测试题由本接口生成。当 `resource_types` 包含 `分阶测试题` 时，响应中的 `resources[]` 会包含一个或多个测试题资源。后续提交学习反馈时，应使用对应测试题资源的 `resource_id`。

### 请求

```json
{
  "learner_id": "stu_001",
  "topic": "工业互联网边缘计算网关配置",
  "resource_types": ["讲义", "实操指南", "分阶测试题"]
}
```

### 字段说明

| 字段              | 类型     | 必填 | 说明        |
| --------------- | ------ | -- | --------- |
| learner\_id     | string | ✅  | 学习者ID     |
| topic           | string | ✅  | 学习主题      |
| resource\_types | array  | ❌  | 资源类型，默认全部 |

### 响应

```json
{
  "learner_id": "stu_001",
  "topic": "工业互联网边缘计算网关配置",
  "resources": [
    {
      "resource_id": "550e8400-e29b-41d4-a716-446655440000",
      "resource_type": "讲义",
      "difficulty": "中级",
      "storage_type": "text",
      "content_text": "# 工业互联网边缘计算网关配置\n\n## 概述...",
      "file_path": "data/generated_resources/text/stu_001/550e8400.md",
      "file_size": 2048,
      "mime_type": "text/markdown",
      "knowledge_points": ["边缘计算", "网关配置"],
      "source_refs": [
        {
          "doc_id": "doc_0",
          "title": "02_edge_gateway.md",
          "snippet": "边缘计算网关是工业互联网的关键设备...",
          "score": 0.89
        }
      ]
    }
  ],
  "trace": [
    {
      "agent_name": "diagnosis",
      "action": "学情诊断",
      "output_summary": "推荐难度：中级; 盲区：['OPC UA']"
    },
    {
      "agent_name": "retriever",
      "action": "知识检索",
      "output_summary": "召回 5 条知识片段"
    },
    {
      "agent_name": "generator",
      "action": "内容生成",
      "output_summary": "生成 3 种资源"
    },
    {
      "agent_name": "reviewer",
      "action": "内容审核",
      "output_summary": "通过：True; 幻觉分：0.12"
    },
    {
      "agent_name": "supervisor",
      "action": "协同决策",
      "output_summary": "最终决策：通过"
    }
  ],
  "report": {
    "ability_tags": ["Python编程", "网络基础"],
    "weak_points": ["OPC UA"],
    "recommended_difficulty": "中级",
    "hallucination_score": 0.12,
    "coverage_rate": 0.92,
    "difficulty_match": true
  }
}
```

### 响应字段

| 字段                             | 说明               |
| ------------------------------ | ---------------- |
| resources\[].resource\_id      | 资源唯一标识           |
| resources\[].resource\_type    | 类型：讲义/实操指南/分阶测试题 |
| resources\[].difficulty        | 难度：初级/中级/高级      |
| resources\[].storage\_type     | 存储方式：text/file   |
| resources\[].content\_text     | 文本内容（text类型）     |
| resources\[].file\_path        | 文件路径（file类型）     |
| resources\[].knowledge\_points | 覆盖知识点            |
| resources\[].source\_refs      | 知识溯源             |
| trace                          | Agent 执行轨迹       |
| report                         | 生成报告摘要           |

### 错误码

| 状态码 | 说明                   |
| --- | -------------------- |
| 404 | 学习者画像不存在             |
| 500 | LLM 调用失败（检查 API Key） |

***

## 3.2 资源列表

**GET /api/resources/{learner\_id}**

建设状态：设计待建设

获取指定学习者的所有已生成资源。

### 查询参数

| 参数             | 类型     | 默认值 | 说明    |
| -------------- | ------ | --- | ----- |
| resource\_type | string | -   | 按类型筛选 |
| difficulty     | string | -   | 按难度筛选 |

### 响应

```json
{
  "learner_id": "stu_001",
  "total": 5,
  "resources": [
    {
      "resource_id": "550e8400...",
      "resource_type": "讲义",
      "difficulty": "中级",
      "topic": "工业互联网边缘计算",
      "created_at": "2026-07-20T10:30:00"
    }
  ]
}
```

***

## 3.3 文件下载

**GET /api/resources/file/{path}**

建设状态：设计待建设

下载生成的资源文件。

### 路径参数

| 参数   | 类型     | 说明     |
| ---- | ------ | ------ |
| path | string | 文件相对路径 |

### 响应

返回文件二进制流，Content-Type 为对应 MIME 类型。

***

# 四、学习反馈接口

## 4.1 提交反馈

**POST /api/feedback/**

建设状态：当前参考路由

提交学习者对测试题或练习资源的答题结果，触发动态迭代。

题目来源：题目通常来自 `POST /api/generate/` 生成结果中的 `分阶测试题` 类型资源。前端应先调用生成接口，找到 `resources[]` 中 `resource_type` 为 `分阶测试题` 的资源，再把该资源的 `resource_id` 作为本接口的 `resource_id` 提交。

当前基础设计中没有单独的“生成题目 API”。题目属于学习资源的一种，由资源生成接口统一生成。后续如果需要独立题库、单题批改或逐题反馈，可以扩展独立题目接口。

### 请求

```json
{
  "learner_id": "stu_001",
  "resource_id": "550e8400-e29b-41d4-a716-446655440002",
  "correct_rate": 0.55,
  "answers": [
    {
      "question_id": "q1",
      "correct": false
    },
    {
      "question_id": "q2",
      "correct": true
    }
  ]
}
```

### 字段说明

| 字段            | 类型     | 必填 | 说明              |
| ------------- | ------ | -- | --------------- |
| learner\_id   | string | ✅  | 学习者ID           |
| resource\_id  | string | ✅  | 测试题/练习资源ID，来源于生成接口返回的 `resources[].resource_id` |
| correct\_rate | number | ✅  | 正确率 \[0.0, 1.0] |
| answers       | array  | ❌  | 答题详情，可记录每道题的 `question_id`、作答结果、是否正确等 |

### 响应

```json
{
  "learner_id": "stu_001",
  "decision": "降维解释",
  "message": "根据正确率 55%，系统决定：降维解释",
  "updated_profile": {
    "learner_id": "stu_001",
    "skill_level": "初级",
    "weak_points": ["OPC UA", "边缘计算", "res_001（基础薄弱）"]
  }
}
```

### 决策逻辑

| 正确率         | 决策     | 说明        |
| ----------- | ------ | --------- |
| < 0.6       | 降维解释   | 更新画像，降低难度 |
| 0.6 \~ 0.85 | 保持当前难度 | 无变化       |
| > 0.85      | 进阶挑战任务 | 更新画像，提升难度 |

***

## 4.2 反馈历史

**GET /api/feedback/history/{learner\_id}**

建设状态：设计待建设

查询学习者的历史反馈记录，用于分析学习趋势。

### 路径参数

| 参数          | 类型     | 说明    |
| ----------- | ------ | ----- |
| learner\_id | string | 学习者ID |

### 查询参数

| 参数         | 类型  | 默认值 | 说明   |
| ---------- | --- | --- | ---- |
| page       | int | 1   | 页码   |
| page\_size | int | 10  | 每页数量 |

### 响应

```json
{
  "learner_id": "stu_001",
  "total": 15,
  "page": 1,
  "page_size": 10,
  "items": [
    {
      "feedback_id": "fb_001",
      "resource_id": "550e8400...",
      "correct_rate": 0.55,
      "decision": "降维解释",
      "created_at": "2026-07-20T10:30:00"
    },
    {
      "feedback_id": "fb_002",
      "resource_id": "550e8401...",
      "correct_rate": 0.72,
      "decision": "保持当前难度",
      "created_at": "2026-07-20T11:00:00"
    }
  ],
  "statistics": {
    "avg_correct_rate": 0.68,
    "total_feedbacks": 15,
    "decision_distribution": {
      "降维解释": 5,
      "保持当前难度": 8,
      "进阶挑战任务": 2
    }
  }
}
```

### 响应字段

| 字段                     | 说明     |
| ---------------------- | ------ |
| items\[].feedback\_id  | 反馈记录ID |
| items\[].correct\_rate | 正确率    |
| items\[].decision      | 决策结果   |
| statistics             | 统计信息汇总 |

***

# 五、学情报告接口

## 5.1 获取报告

**GET /api/report/{learner\_id}**

建设状态：当前参考路由

获取学习者可视化报告数据。

### 响应

```json
{
  "learner_id": "stu_001",
  "radar": {
    "dimensions": ["工业互联网架构", "OPC UA", "MQTT"],
    "values": [65.0, 40.0, 70.0]
  },
  "weak_points": ["OPC UA", "边缘计算"],
  "strong_points": ["Python编程"],
  "skill_level": "初级",
  "learning_goal": "掌握工业互联网数据采集",
  "difficulty_curve": [
    {"topic": "工业互联网架构", "score": 65.0, "recommended_difficulty": "中级"},
    {"topic": "OPC UA", "score": 40.0, "recommended_difficulty": "初级"},
    {"topic": "MQTT", "score": 70.0, "recommended_difficulty": "中级"}
  ],
  "learning_path": [
    {"order": 1, "topic": "OPC UA", "reason": "当前最薄弱环节"},
    {"order": 2, "topic": "边缘计算", "reason": "与学习目标相关"},
    {"order": 3, "topic": "工业互联网架构", "reason": "巩固提升"}
  ]
}
```

### 响应字段

| 字段                | 说明     |
| ----------------- | ------ |
| radar             | 雷达图数据  |
| weak\_points      | 知识盲区   |
| strong\_points    | 优势领域   |
| skill\_level      | 技能水平   |
| difficulty\_curve | 难度匹配曲线 |
| learning\_path    | 学习路径规划 |

***

# 六、知识库接口

## 6.1 知识库信息

**GET /api/knowledge/info**

建设状态：设计待建设

获取当前知识库的基本信息，用于前端展示知识库状态。

### 响应

```json
{
  "knowledge_base_name": "demo_industrial_internet",
  "domain": "工业互联网",
  "total_docs": 3,
  "total_chunks": 45,
  "embedding_model": "BAAI/bge-large-zh-v1.5",
  "last_updated": "2026-07-20T10:00:00",
  "documents": [
    {
      "doc_id": "doc_0",
      "title": "01_architecture.md",
      "chunk_count": 15,
      "size_kb": 25.6
    },
    {
      "doc_id": "doc_1",
      "title": "02_edge_gateway.md",
      "chunk_count": 18,
      "size_kb": 32.1
    },
    {
      "doc_id": "doc_2",
      "title": "03_protocols.md",
      "chunk_count": 12,
      "size_kb": 18.5
    }
  ]
}
```

### 响应字段

| 字段                    | 说明     |
| --------------------- | ------ |
| knowledge\_base\_name | 知识库名称  |
| domain                | 领域     |
| total\_docs           | 文档总数   |
| total\_chunks         | 切片总数   |
| embedding\_model      | 向量化模型  |
| last\_updated         | 最后更新时间 |
| documents             | 文档列表   |

***

# 七、错误码汇总

| 状态码 | 说明      |
| --- | ------- |
| 200 | 成功      |
| 400 | 请求参数错误  |
| 404 | 资源不存在   |
| 422 | 请求体验证失败 |
| 500 | 服务器内部错误 |

### 通用错误格式

后端基础 API 统一使用以下错误响应格式。业务路由抛出的 `HTTPException`、Pydantic 请求体验证失败和未处理异常都应收敛到该结构。

```json
{
  "status": "error",
  "message": "错误描述",
  "detail": "详细信息（可选）"
}
```

***

# 八、调用示例

## Python

```python
import httpx

BASE = "http://localhost:8000"

# 创建画像
r = httpx.post(f"{BASE}/api/learner/profile", json={
    "learner_id": "stu_001",
    "education": "本科",
    "major": "计算机",
    "learning_goal": "掌握工业互联网"
})
print(r.json())

# 生成资源
r = httpx.post(f"{BASE}/api/generate/", json={
    "learner_id": "stu_001",
    "topic": "边缘计算"
})
result = r.json()
print(f"生成 {len(result['resources'])} 个资源")
for t in result['trace']:
    print(f"  [{t['agent_name']}] {t['output_summary']}")
```

## JavaScript (Axios)

```javascript
import axios from 'axios'

const BASE = 'http://localhost:8000'

// 创建画像
await axios.post(`${BASE}/api/learner/profile`, {
  learner_id: 'stu_001',
  education: '本科',
  major: '计算机',
  learning_goal: '掌握工业互联网'
})

// 生成资源
const res = await axios.post(`${BASE}/api/generate/`, {
  learner_id: 'stu_001',
  topic: '边缘计算'
})

console.log('Agent轨迹:', res.data.trace)
console.log('资源:', res.data.resources)
```
