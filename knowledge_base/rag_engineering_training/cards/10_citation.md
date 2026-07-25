# 教学卡：引用溯源

**能力节点**：引用溯源｜**适用水平**：Python 基础｜**卡片 ID**：card_citation

## 学习目标

掌握让生成资源中的每个关键结论都能回到原始文档与片段的方法。

## 核心概念

一个可用引用至少包含 `document_id`、`chunk_id`、标题、片段摘要、检索分数、查询词和排名。来源路径仅用于定位文件，不能代替稳定 ID。引用既服务于学习者复查，也服务于审核 Agent 判断 Claim 是否有证据支撑。

## 工程步骤

1. 入库时生成稳定文档 ID 与片段 ID。
2. 检索时保留 query、rank、score 和 metadata。
3. 资源生成时把证据映射为 `source_refs`。
4. 前端提供“查看证据”入口，展示片段而不是只显示文件名。
5. 审核时复用相同 ID 检查 Claim 支持关系。

## 常见错误

- 用“参考了知识库”这种泛化描述代替具体证据。
- 资源改版后仍复用无法定位的旧引用。
- 引用与文中 Claim 没有一一对应关系。

## 小练习与评测点

为“向量数据库为什么要持久化？”生成一条解释和两条引用。评测：引用可解析率、片段存在率、Claim 证据支持率。

## 来源

- LangChain, [Evaluate a RAG Application](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)，访问日期：2026-07-24。
