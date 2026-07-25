# 教学卡：向量数据库与元数据

**能力节点**：向量数据库｜**适用水平**：Python 基础｜**卡片 ID**：card_vector_store

## 学习目标

理解向量数据库为何需要 collection、唯一 ID、文本、向量和 metadata，并能将不同知识库隔离存储。

## 核心概念

Collection 是向量数据的逻辑集合。每条记录应包含唯一 ID、原文片段、向量与 metadata。对本项目，`knowledge_base_id` 是隔离边界，`document_id` 和 `chunk_id` 是证据追溯边界；不能只依赖向量库内部顺序或临时文件名。

## 工程步骤

1. 每个知识库使用独立 collection 或严格 metadata 过滤。
2. 以稳定 `chunk_id` 执行 upsert，保证重复入库不产生重复片段。
3. 记录 embedding 模型、索引版本和片段数。
4. 使用 collection 的计数和抽样查询检查索引是否完整。

## 常见错误

- 把多个领域混入默认 collection，检索时串库。
- 每次重建都生成 `chunk_0`、`chunk_1`，但内容已经变化。
- 只存向量，不存原文和 metadata，无法展示证据。

## 小练习与评测点

分别入库 RAG 与工业互联网资料，查询同一关键词，确认结果不跨知识库。评测：隔离正确率、入库幂等性、可追溯字段完整率。

## 来源

- Chroma, [Manage Collections](https://docs.trychroma.com/docs/collections/manage-collections)，访问日期：2026-07-24。
- Chroma, [Collection Reference](https://docs.trychroma.com/reference/python/collection)，访问日期：2026-07-24。
