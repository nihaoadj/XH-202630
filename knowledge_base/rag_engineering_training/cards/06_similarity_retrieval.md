# 教学卡：相似度检索与 Top-K

**能力节点**：相似度检索｜**适用水平**：Python 基础｜**卡片 ID**：card_similarity_retrieval

## 学习目标

掌握查询向量、相似度排序、Top-K 和 metadata 过滤的作用，并理解召回不等于最终答案正确。

## 核心概念

检索器将查询编码后，从向量库返回最相近的 K 个候选片段。Top-K 太小可能遗漏关键证据；太大则把噪声带入提示词。metadata 过滤可将检索限制在指定知识库、章节、难度或文档版本内，避免无关领域混入。

## 工程步骤

1. 用“主题 + 薄弱知识点”构造多个检索查询。
2. 设置初始 Top-K，例如 3 到 10。
3. 按 `knowledge_base_id` 过滤，并保留查询、排序和距离分数。
4. 标注每个问题期望命中的文档或片段，计算命中率。

## 常见错误

- 将距离分数误解为概率或事实可信度。
- 不保存 rank 与 query，后续无法解释为什么召回该证据。
- 只评估“是否返回内容”，不评估是否命中目标片段。

## 小练习与评测点

对“Top-K 过小的风险是什么？”分别测试 K=1、3、5。评测：Recall@K、目标片段排名、无关片段比例。

## 来源

- Chroma, [Query and Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)，访问日期：2026-07-24。
- Chroma, [Metadata Filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)，访问日期：2026-07-24。
