# 综合学习模块 04：查询改写、混合召回与 Rerank

> 本模块将查询处理、稀疏与稠密召回、结果融合和重排序合并讲解。
> 主能力节点：混合检索、Rerank。适用层级：Python 基础、进阶 RAG。

## 学习目标与阅读路径

学完后应能识别单路向量检索的盲区，保护查询中的实体、编号和否定词，选择查询改写或 HyDE，组合稀疏与稠密候选，并在延迟预算内使用 CrossEncoder 重排。先理解两阶段架构，再用固定评测集比较各方案。

## 1. 为什么单路向量检索不够

向量检索擅长同义表达和概念相关性，但可能忽略精确编号、产品名、错误码、缩写和版本号；关键词检索擅长字面匹配，却难以处理同义词和自然语言变体。真实查询经常同时需要二者。

例如“Chroma collection 维度不一致报错怎么处理”既需要理解“维度兼容”，也要保留 `Chroma`、`collection` 等精确词。

## 2. 查询处理分层

1. **规范化**：统一空白、大小写和全半角，不改变语义。
2. **实体保护**：提取版本号、错误码和 API 名称，禁止改写丢失。
3. **同义扩展**：加入受控领域词表，如“重排/Rerank”。
4. **多查询改写**：生成不同表述分别检索，再融合。
5. **问题分解**：把多跳问题拆成多个子问题。
6. **HyDE**：生成假设答案型文档，用其向量检索真实资料。

改写必须保留原始问题，每条候选要记录由哪个查询召回，否则无法判断偏差来自哪里。

## 3. HyDE 的机制和边界

HyDE 先让指令模型生成一篇“假设文档”，再编码该文档并检索真实语料。它用答案形态缩小问题与文档的表达差距。

假设文档可能包含虚假细节，只能用于产生检索向量，不能作为最终证据或进入引用列表。最终回答必须由召回到的真实文档支撑。

HyDE 适合零样本检索、问题很短、用户表达与资料术语差距较大的场景。对精确编号、实时信息或已有高质量查询训练数据的场景，未必更好。

## 4. 稀疏、稠密和融合

BM25 一类稀疏方法利用词频和逆文档频率，适合精确术语、代码、编号和专有名词。稠密双编码器能识别同义表达，但会出现近义而不相关的误召回。

不同检索器的原始分数通常不可直接相加。Reciprocal Rank Fusion 使用排名融合：

~~~text
RRF_score(d) = Σ 1 / (k + rank_i(d))
~~~

`rank_i(d)` 是文档在第 i 个检索器的排名。RRF 易于组合不同量纲，但候选规模与参数仍需验证集确定。

## 5. Retrieve & Re-Rank

Sentence Transformers 官方推荐两阶段流程：

1. 稀疏或双编码器快速取得几十到上百条候选。
2. Cross-Encoder 同时读取查询和每条候选，输出相关性分数。
3. 按重排分数保留少量最终证据。

Cross-Encoder 在查询和文档 token 间做联合注意力，相关性更精细；代价是每个查询—文档对都要推理，无法像文档向量那样完全预计算。

## 6. 参数与延迟预算

需要联合调节每路召回 K、融合候选数、重排输入长度、批量大小、最终上下文 K、去重规则、超时和降级策略。CPU 上运行大型 Cross-Encoder 可能成为主要瓶颈，参数必须来自真实硬件压测。

## 7. 去重与多样性

Chunk overlap 会让近似片段同时进入候选。可按 `content_hash` 去重、限制同一文档片段数、合并相邻片段，或用最大边际相关性兼顾相关与多样。去重前后都要保留原始排名。

## 8. 常见失败

- 改写丢失产品名、否定条件或版本号；
- 多查询返回大量重复结果却未去重；
- HyDE 内容被误当成证据；
- 稀疏和稠密原始分数直接相加；
- 候选 K 太小，重排器看不到正确文档；
- Cross-Encoder 输入截断关键结论；
- 只看最终答案正确率，无法定位召回问题。

## 9. 评测

在同一测试集和索引版本下比较稀疏、稠密、混合、混合加重排、查询改写加混合重排。指标包括 Recall@K、MRR、NDCG、候选重复率、空召回率、P50/P95 延迟和每查询成本。

## 10. 查询改写的输入输出契约

改写器的目标是提高可检索性，不是替用户回答。输出应保留原问题，并显式记录变体和保护实体：

~~~json
{
  "original_query": "Python 3.11 下 Chroma 维度报错怎么处理",
  "protected_terms": ["Python 3.11", "Chroma", "维度"],
  "rewrites": [
    "Python 3.11 Chroma embedding dimension mismatch 处理",
    "Chroma collection 向量维度不一致如何重建索引"
  ],
  "strategy": "multi_query",
  "rewrite_version": "rw_v2"
}
~~~

数字、版本号、错误码、专有名词、路径、否定词和比较关系应默认保护。“不要使用 Rerank”和“使用 Rerank”只差否定词，若改写器把“不”删除，检索方向会完全相反。多查询数量也需要限制，否则召回成本和重复候选会线性上升。

HyDE 先生成一个假想答案，再用假想答案的向量寻找真实文档。它可以缩小短问题与长文档之间的表达差距，但假想文本可能含虚构事实，所以只能作为检索探针；最终回答与引用必须来自真实知识库片段。

## 11. RRF 融合的数值示例

Reciprocal Rank Fusion 不要求不同检索器的裸分数可比。对文档 d，可使用：

~~~text
RRF(d) = Σ 1 / (k + rank_i(d))
~~~

假设 `k=60`。关键词检索排序为 A、B、C，向量检索排序为 C、A、D：

| 文档 | 关键词排名 | 向量排名 | RRF 分数近似 |
| --- | ---: | ---: | ---: |
| A | 1 | 2 | 1/61 + 1/62 = 0.03252 |
| C | 3 | 1 | 1/63 + 1/61 = 0.03227 |
| B | 2 | 无 | 1/62 = 0.01613 |
| D | 无 | 3 | 1/63 = 0.01587 |

A 在两路都靠前，因此融合后略高于 C。这里的 `k` 用于减弱头部排名差异，不是 Top-K。实际实现要先按 `chunk_id` 去重，并保存每路排名，才能解释最终候选为什么出现。

## 12. CrossEncoder 重排实现骨架

双编码器提前计算文档向量，适合从大集合快速召回；CrossEncoder 同时读取问题和候选文本，计算更精细但成本更高，所以只处理几十条候选：

~~~python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2")
pairs = [(query, item["text"]) for item in candidates]
scores = reranker.predict(pairs)

reranked = sorted(
    [dict(item, rerank_score=float(score)) for item, score in zip(candidates, scores)],
    key=lambda item: item["rerank_score"],
    reverse=True,
)
final_context = reranked[:5]
~~~

示例模型主要用于说明接口，中文项目必须评估中文或多语种重排模型。重排前保留召回分数和来源，重排后增加新字段，不能覆盖原始排名，否则无法判断问题来自召回还是重排。

## 13. 延迟预算与降级策略

总延迟可以拆为查询改写、各路召回、融合、Rerank、上下文处理和生成。若目标 P95 为 3 秒，不能让每层都独立使用 3 秒超时。建议为各阶段设置预算、超时和可观测字段。

发生故障时按能力降级：改写服务失败可回退原查询；关键词通道失败可保留向量通道；Rerank 超时可使用融合排名；所有检索通道失败则返回检索不可用，不能让生成器无证据继续回答。降级结果要标记 `degraded=true` 和具体原因，避免在评测中与正常链路混合。

## 14. 常见症状—原因—验证方法

| 症状 | 可能原因 | 最小验证 |
| --- | --- | --- |
| 精确错误码搜不到 | 改写删除实体、仅向量召回 | 用原查询跑关键词基线 |
| 候选很多但内容重复 | 多查询未按 chunk_id 去重 | 输出各路 ID 与重复率 |
| 加 Rerank 后 Recall 降低 | 召回候选过少、截断过早 | 扩大 recall_k 后重测 |
| 相关片段被排低 | 重排模型语言或领域不匹配 | 人工标注候选做 NDCG 对比 |
| 延迟偶发升高 | 改写或重排长尾 | 分阶段统计 P50/P95/P99 |
| 改写后语义相反 | 否定词或比较关系丢失 | 对比 original 与 rewrite |

## 诊断与练习

1. 对“Python 3.11 Chroma collection dimension mismatch”设计规范化、实体保护和多查询改写结果，说明哪些词绝不能删除。
2. 给定稀疏与稠密检索排名，使用 RRF 思路生成融合顺序，并分析重复候选如何处理。
3. 比较“仅向量”“混合召回”“混合加 Rerank”三条链路的 Recall@K、MRR、P95 延迟和成本。
4. 验收标准：能解释召回器与重排器的输入输出差异，知道 HyDE 文本不是事实证据，并能排查改写漂移、候选不足和重排截断。

### 参考答案与评分要点

- 第 1 题必须保护 `Python 3.11`、`Chroma`、`collection` 和维度错误含义；可扩展 `dimension mismatch`、索引重建等表达，但不得删除版本或把错误改成一般安装问题。
- 第 2 题按每个文档在各路的排名倒数累加，先用 `chunk_id` 去重，再保留各路排名作为解释字段。直接相加 BM25 与向量裸分数而不归一化不合格。
- 第 3 题必须在同一数据集和版本上比较，质量指标之外还要记录 P95 和成本；若混合加重排收益小但代价大，应如实选择更简单链路。
- 建议总分 10 分：改写保护 2 分，融合计算 3 分，受控对比 3 分，降级和故障定位 2 分。

## 权威来源与延伸阅读

- Gao et al., HyDE：https://arxiv.org/abs/2212.10496
- Sentence Transformers Retrieve & Re-Rank：https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Sentence Transformers CrossEncoder：https://www.sbert.net/docs/package_reference/cross_encoder/model.html
- Sentence Transformers Reranking Evaluation：https://www.sbert.net/docs/package_reference/cross_encoder/evaluation.html
- Chroma Hybrid Search：https://docs.trychroma.com/cloud/search-api/hybrid-search
