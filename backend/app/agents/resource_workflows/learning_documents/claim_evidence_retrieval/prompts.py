"""Versioned prompts for query construction and round-1 rejudgement."""

from __future__ import annotations

from app.models.reviews.claim_evidence_retrieval import (
    QUERY_PROMPT_VERSION,
    REJUDGE_PROMPT_VERSION,
    ClaimQueryBatchOutputV1,
    ClaimSupplementJudgementLLMOutput,
)
from app.models.shared.persistence import canonical_hash


QUERY_PROMPT = """你是 Claim 缺证补检的查询构造器。输入是本轮首次判定为“证据不足”的事实 Claim。
请为每条 Claim 构造 1–3 条可在当前知识库检索的中文或英文查询，默认 2 条；第 3 条仅在存在明确不同的验证角度时使用。
要求：
- 保留 Claim 中的实体、数字、否定、版本与限定条件，允许检索反证，不得把待核验结论改写成“预设正确”的解释题；
- 不得输出 URL、SQL、过滤条件、证据 ID、工具调用、个人资料或与输入无关的 Claim；
- 每条查询 1–512 字符，不得重复；
- 只能使用输入中给出的 claim_id，每条恰好出现一次，不得遗漏或新增；
- 逐字回填输入中的 batch_id 与 input_hash；
- 只输出一个 JSON 对象：{"batch_id":"...","input_hash":"...","items":[{"claim_id":"...","queries":[{"text":"..."}]}]}，
  禁止解释、Markdown 或 schema 外字段。"""

REJUDGE_PROMPT = """你是补证后的独立 Claim 证据判定器。仅依据本次给出的冻结 Evidence 判定每条 Claim。
每个 claim_id 必须恰好出现一次，不得判定输入之外的 Claim。
事实 Claim 只能判 supported、contradicted、not_in_evidence；
supported/contradicted 必须引用白名单 evidence_ids，not_in_evidence 禁止引用证据。
若两条及以上证据对同一 Claim 给出互相冲突且适用条件无法区分的结论，置 evidence_conflict=true，
并在 conflicting_evidence_ids 中列出这些证据（最多 8 条，必须来自白名单）；这不改变 verdict 枚举。
不得使用常识补全，不得创造 ID，不得通过“引用更多证据”把冲突当作支持。
只输出一个 JSON 对象：{"judgements":[{"claim_id":"...","verdict":"...","evidence_ids":[...],
"reason":"...","confidence":0.0,"evidence_conflict":false,"conflicting_evidence_ids":[]}]}。"""


def query_prompt_hash() -> str:
    return canonical_hash({"version": QUERY_PROMPT_VERSION, "prompt": QUERY_PROMPT})


def rejudge_prompt_hash() -> str:
    return canonical_hash({"version": REJUDGE_PROMPT_VERSION, "prompt": REJUDGE_PROMPT})


def query_schema_hash() -> str:
    return canonical_hash(ClaimQueryBatchOutputV1.model_json_schema())


def rejudge_schema_hash() -> str:
    return canonical_hash(ClaimSupplementJudgementLLMOutput.model_json_schema())


__all__ = [
    "QUERY_PROMPT",
    "REJUDGE_PROMPT",
    "query_prompt_hash",
    "query_schema_hash",
    "rejudge_prompt_hash",
    "rejudge_schema_hash",
]
