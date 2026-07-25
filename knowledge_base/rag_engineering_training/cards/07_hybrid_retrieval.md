# 教学卡：混合检索

**能力节点**：混合检索｜**适用水平**：进阶 RAG｜**卡片 ID**：card_hybrid_retrieval

## 学习目标

理解稠密语义检索与稀疏关键词检索的互补关系，以及使用 RRF 融合排序的基本思路。

## 核心概念

稠密向量擅长理解同义表达；稀疏检索擅长精确匹配缩写、代码符号、版本号和专业术语。混合检索将两种候选排序融合。RRF 使用名次而不是原始分数进行合并，适合不同检索器分数尺度不可直接比较的情况。

## 工程步骤

1. 为技术术语类查询准备关键词检索候选。
2. 同时执行语义检索，得到稠密候选。
3. 用 RRF 或经过校准的权重合并排序。
4. 用同一评测集比较单路与混合检索的 Recall@K。

## 常见错误

- 直接相加不同模型的原始距离或相似度分数。
- 在没有精确术语需求时盲目增加复杂度。
- 使用当前项目未支持的新版云端能力却没有做版本兼容验证。

## 小练习与评测点

设计包含“BM25”“RRF”“Top-K”的查询，比较纯语义与混合结果。评测：术语命中率、Recall@K、延迟。

## 来源

- Chroma, [Hybrid Search with RRF](https://docs.trychroma.com/cloud/search-api/hybrid-search)，访问日期：2026-07-24。
- Chroma, [Sparse Vector Search](https://docs.trychroma.com/cloud/schema/sparse-vector-search)，访问日期：2026-07-24。
