# 教学卡：RAG 评测设计

**能力节点**：RAG 评测｜**适用水平**：进阶 RAG｜**卡片 ID**：card_rag_evaluation

## 学习目标

建立能重复运行的评测集，并区分检索质量、答案质量与证据忠实度。

## 核心概念

离线评测样本应至少包含：问题、目标知识点、期望文档或片段、参考答案和难度。检索命中率衡量是否找到目标证据；回答正确性需要参考答案；忠实度检查答案是否受已检索证据支持；相关性检查答案是否真正回应问题。这些指标不能只取一个平均分，应保留每个样本的结果以定位失败原因。

## 工程步骤

1. 为每个能力节点人工编写若干代表性问题。
2. 为问题标注期望 `document_id` 或 `chunk_id`。
3. 执行检索、生成和审核，保存每步结果。
4. 计算 Recall@K、正确性、忠实度、覆盖率和难度适配。
5. 对失败样本回看切分、检索、重排和 Prompt，而非只调模型。

## 常见错误

- 只有问题，没有期望证据或参考答案。
- 只展示总体平均值，掩盖某类知识点完全失败。
- 用模型自身打分作为唯一结论，缺少人工抽样复核。

## 小练习与评测点

为“Rerank 的作用是什么？”建立一条评测样本。评测：目标片段是否进入 Top-K、回答是否包含正确机制、是否附带可解析引用。

## 来源

- LangChain, [Evaluate a RAG Application](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)，访问日期：2026-07-24。
- LangChain, [Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts?mode=ui)，访问日期：2026-07-24。
