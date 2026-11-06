"""Single frozen version-selection entry for neutral extraction (T42 §3.1).

One place decides Prompt, output schema and payload/validator version from the
frozen policy; the executor, budget window check, gateway schema_name, observer
and persistence revalidation all share it instead of scattered if/else.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.reviews.claim_extraction import (
    BatchOutput,
    BatchOutputV2,
    EstimatePolicy,
    ExtractionPolicy,
    PROMPT_VERSION,
    PROMPT_VERSION_V2,
    digest,
)

from .prompts.extract import PROMPT as PROMPT_V1
from .prompts.extract_v2 import PROMPT as PROMPT_V2


@dataclass(frozen=True)
class ContractSelection:
    prompt_version: str
    prompt: str
    output_schema: type
    is_v2: bool

    @property
    def schema_name(self) -> str:
        return self.output_schema.__name__


def select_contract(policy: ExtractionPolicy | EstimatePolicy) -> ContractSelection:
    """Resolve the frozen extraction contract; rejects unknown/unsupported combos."""
    is_v2 = getattr(policy, "source_locating", None) is not None
    if is_v2:
        if policy.prompt_version != PROMPT_VERSION_V2:
            raise ValueError("source locating policy requires the neutral-v2 prompt")
        frozen = policy.source_locating
        if (digest(PROMPT_V2) != frozen.extractor_prompt_hash
                or digest(BatchOutputV2.model_json_schema()) != frozen.output_schema_hash):
            raise ValueError("frozen extraction Prompt/schema drift")
        return ContractSelection(PROMPT_VERSION_V2, PROMPT_V2, BatchOutputV2, True)
    if policy.prompt_version != PROMPT_VERSION:
        raise ValueError("unknown neutral extraction prompt version")
    return ContractSelection(PROMPT_VERSION, PROMPT_V1, BatchOutput, False)
