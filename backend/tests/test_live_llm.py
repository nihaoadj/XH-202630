"""Opt-in provider smoke test; excluded from the default offline suite."""

import os

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings, is_placeholder_api_key
from app.core.llm_gateway import default_llm_gateway
from app.models.agent_contracts import DiagnosisLLMOutput
from app.models.llm import LLMCallContext


pytestmark = pytest.mark.live_llm


def test_live_llm_minimal_diagnosis_schema():
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("set RUN_LIVE_LLM_TESTS=1 to enable live provider smoke")

    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value().strip()
    if not api_key or is_placeholder_api_key(api_key):
        pytest.skip("a real LLM_API_KEY is required")

    gateway = default_llm_gateway()
    options = gateway.options_for("diagnosis", temperature=0.0).model_copy(update={
        "max_attempts": 1,
        "request_timeout_seconds": min(15.0, settings.llm_request_timeout_seconds),
    })
    result = gateway.invoke_structured(
        messages=[
            SystemMessage(content="返回严格的学情诊断结构。"),
            HumanMessage(content="初学者希望学习向量检索。"),
        ],
        output_schema=DiagnosisLLMOutput,
        context=LLMCallContext(
            run_id="live-smoke",
            step_id="live-diagnosis",
            node_name="diagnosis",
            schema_name=DiagnosisLLMOutput.__name__,
        ),
        options=options,
    )

    assert isinstance(result.output, DiagnosisLLMOutput)
