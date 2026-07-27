# 教学卡：RAG 调优与消融实验

**能力节点**：RAG 调优｜**适用水平**：进阶 RAG｜**卡片 ID**：card_rag_tuning

## 学习目标

掌握以评测证据驱动调优，并通过消融实验说明各模块的实际贡献。

## 核心概念

调优不是随意更换模型或增大 Top-K。应先定位失败发生在解析、切分、Embedding、检索、重排、Prompt 还是审核，再只改变一个变量进行比较。消融实验通过移除或加入某模块，比较同一评测集上的指标，证明 RAG、多 Agent、审核纠偏等设计的作用。

## 工程步骤

1. 固定评测集、模型版本和随机配置。
2. 记录基线：直接生成。
3. 依次比较 RAG、RAG+重排、RAG+多 Agent、RAG+多 Agent+审核。
4. 为每组保存检索命中率、忠实度、幻觉率、延迟和成本。
5. 根据失败样本制定下一轮改动，而不是只挑最好看的平均值。

## 常见错误

- 同时改模型、Chunk、Top-K 和 Prompt，无法判断哪个变量有效。
- 只比较一次运行结果，不固定数据集与版本。
- 为追求一个指标而显著牺牲延迟或证据可追溯性。

## 小练习与评测点

用同一批问题比较“无检索”“仅向量检索”“检索+审核”三种方案。评测：检索命中率、Claim 支持率、幻觉率、平均延迟。

## 来源

- LangChain, [LangSmith Evaluation](https://docs.langchain.com/langsmith/evaluation)，访问日期：2026-07-24。
- Sentence Transformers, [CrossEncoder Reranking Evaluation](https://sbert.net/docs/package_reference/cross_encoder/evaluation.html)，访问日期：2026-07-24。
