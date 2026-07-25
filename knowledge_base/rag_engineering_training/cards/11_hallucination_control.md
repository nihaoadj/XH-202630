# 教学卡：Claim 审核与幻觉控制

**能力节点**：幻觉控制｜**适用水平**：进阶 RAG｜**卡片 ID**：card_hallucination_control

## 学习目标

理解如何将资源内容拆为可核验 Claim，并用检索证据评估其是否被支持。

## 核心概念

Claim 是可以判断真伪的具体断言，例如“CrossEncoder 通常用于重排候选片段”。审核时不应只判断整篇文章“看起来合理”，而要逐条检查：是否有证据、证据是否相关、是否夸大了证据结论。没有足够证据的 Claim 应标记为风险、删除或改写为条件性表达。

## 工程步骤

1. 从生成资源抽取定义、因果关系、参数建议等关键 Claim。
2. 对每条 Claim 检索对应证据或复用初始证据。
3. 保存 `supported`、置信度、证据 ID、问题类型和修订建议。
4. 计算 `unsupported / total` 作为待复核幻觉率指标。

## 常见错误

- 用“有引用”替代“引用真的支持该 Claim”。
- 将相关性分数误当作真实性分数。
- 把没有证据的内容直接判错，却没有给出改写或补检索策略。

## 小练习与评测点

从一段 RAG 教学文字抽取三条 Claim，分别标注支持、证据不足或冲突。评测：Claim 覆盖率、证据支持率、疑似幻觉率、修订次数。

## 来源

- LangChain, [Application-specific Evaluation Approaches](https://docs.langchain.com/langsmith/evaluation-approaches)，访问日期：2026-07-24。
- RAGAS, [Automated Evaluation of Retrieval Augmented Generation](https://arxiv.org/abs/2309.15217)。
