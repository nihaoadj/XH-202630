# RAG 可信生成验收事实

## RRF 融合

Reciprocal Rank Fusion 使用各检索通道中的排名倒数进行融合，不直接累加不同检索器不可比较的原始分数。

## Evidence Gate

只有通过知识库、文档版本、Chunk 内容哈希和相关度校验的候选才能成为生成证据。证据不足时系统必须停止事实型资源生成，不能编造来源。

## Claim 审核

事实 Claim 必须绑定当前 Run 的冻结 Evidence。存在 contradicted 或 not_in_evidence 判定时，当前资源版本不能自动发布。
