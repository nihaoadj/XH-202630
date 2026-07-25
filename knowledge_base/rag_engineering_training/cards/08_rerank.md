# 教学卡：Rerank 重排序

**能力节点**：Rerank｜**适用水平**：进阶 RAG｜**卡片 ID**：card_rerank

## 学习目标

理解“先高效召回候选、再高精度重排”的两阶段检索结构，并能说明其性能与延迟权衡。

## 核心概念

Bi-Encoder 可预先编码大量文档，适合快速召回；CrossEncoder 将“查询—候选片段”成对输入模型，通常更准确但计算更慢。因此常见流程是先取几十或上百个候选，再由 Reranker 选出少量最相关片段供生成模块使用。

## 工程步骤

1. 先用向量检索召回候选，例如 Top-50。
2. 以查询和每个候选片段为一对计算相关性分数。
3. 重排后保留 Top-3 或 Top-5 进入 Prompt。
4. 对有标准相关片段的评测集计算 MRR、NDCG 或 Recall。

## 常见错误

- 对整个库逐段使用 CrossEncoder，导致延迟不可接受。
- 只报告重排后结果，不保存初召回排名，无法比较提升。
- 把 Reranker 分数当成事实真实性，而不是相关性。

## 小练习与评测点

用“混合检索如何融合结果？”查询，对比初召回 Top-5 与重排 Top-5。评测：MRR@10、NDCG@10、额外延迟。

## 来源

- Sentence Transformers, [Retrieve & Re-Rank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)，访问日期：2026-07-24。
- Sentence Transformers, [CrossEncoder Reranking Evaluation](https://sbert.net/docs/package_reference/cross_encoder/evaluation.html)，访问日期：2026-07-24。
