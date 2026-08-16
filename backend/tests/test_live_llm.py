"""Opt-in provider smoke test; excluded from the default offline suite."""

import os

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings, is_placeholder_api_key
from app.core.llm_gateway import default_llm_gateway
from app.models.agent_contracts import GeneratedResourceBatch
from app.models.claims import (
    ClaimExtractionLLMOutput,
    ClaimJudgementLLMOutput,
    materialize_claims,
)
from app.models.llm import LLMCallContext


pytestmark = pytest.mark.live_llm


def test_live_llm_generation_and_claim_schema_compatibility():
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1" and os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 to enable live provider smoke")

    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value().strip()
    if not api_key or is_placeholder_api_key(api_key):
        pytest.skip("a real LLM_API_KEY is required")

    gateway = default_llm_gateway()
    options = gateway.options_for("generator", temperature=0.0).model_copy(update={
        "max_attempts": 1,
        "request_timeout_seconds": min(30.0, settings.llm_request_timeout_seconds),
    })
    generation = gateway.invoke_structured(
        messages=[
            SystemMessage(content="返回严格结构的一份初级教程，只陈述给定证据。"),
            HumanMessage(content="证据：RRF 使用排名倒数进行融合。知识点：kp-rrf。"),
        ],
        output_schema=GeneratedResourceBatch,
        context=LLMCallContext(
            run_id="live-smoke",
            step_id="live-generation",
            node_name="generator",
            schema_name=GeneratedResourceBatch.__name__,
        ),
        options=options,
    )
    resource = generation.output.resources[0]
    assert isinstance(generation.output, GeneratedResourceBatch)

    extraction = gateway.invoke_structured(
        messages=[
            SystemMessage(content="按资源逐条抽取事实 Claim，source_text 必须是正文中的原文片段并给出精确字符偏移。"),
            HumanMessage(content=f"resource_id=live-resource-1\ncontent={resource.content_text}"),
        ],
        output_schema=ClaimExtractionLLMOutput,
        context=LLMCallContext(
            run_id="live-smoke",
            step_id="live-claim-extract",
            node_name="claim_extractor",
            schema_name=ClaimExtractionLLMOutput.__name__,
        ),
        options=gateway.options_for("claim_extractor", temperature=0.0).model_copy(update={
            "max_attempts": 1,
            "request_timeout_seconds": min(30.0, settings.llm_request_timeout_seconds),
        }),
    )
    candidates = extraction.output.resources[0].claims
    claims = materialize_claims(
        candidates=candidates,
        resource_content=resource.content_text,
        resource_id="live-resource-1",
        resource_version=1,
        review_id="live-review-1",
        run_id="live-smoke",
        allowed_evidence_ids={"ev-live-smoke"},
        allowed_knowledge_point_ids={"kp-rrf"},
        extractor_prompt_version="live-smoke-v1",
        extractor_model=settings.llm_model,
    )
    assert claims

    judgement = gateway.invoke_structured(
        messages=[
            SystemMessage(content="只依据冻结证据判断每个 Claim；每个 claim_id 恰好返回一次。"),
            HumanMessage(content=(
                f"证据 ev-live-smoke：RRF 使用排名倒数进行融合。\n"
                f"Claims：{[{'claim_id': item.claim_id, 'claim_text': item.claim_text, 'claim_type': item.claim_type.value} for item in claims]}"
            )),
        ],
        output_schema=ClaimJudgementLLMOutput,
        context=LLMCallContext(
            run_id="live-smoke",
            step_id="live-claim-judge",
            node_name="claim_judge",
            schema_name=ClaimJudgementLLMOutput.__name__,
        ),
        options=gateway.options_for("claim_judge", temperature=0.0).model_copy(update={
            "max_attempts": 1,
            "request_timeout_seconds": min(30.0, settings.llm_request_timeout_seconds),
        }),
    )

    assert isinstance(extraction.output, ClaimExtractionLLMOutput)
    assert isinstance(judgement.output, ClaimJudgementLLMOutput)
    assert {item.claim_id for item in judgement.output.judgements} == {
        item.claim_id for item in claims
    }
