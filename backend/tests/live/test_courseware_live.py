"""Opt-in real-model acceptance for the interactive-courseware agents.

This suite is intentionally skipped in normal CI.  A deployment can run it
with COURSEWARE_LIVE_EVAL=1 and a real, permitted LLM_API_KEY to collect the
same structured-output, latency, retry and token evidence used by production
events.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.resource_workflows.interactive_courseware.planner_agent import build_courseware_spec
from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import (
    review_courseware_quality_decision,
)
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
from app.config import get_settings
from app.core.courseware.live_model import live_model_config_from_file
from app.core.llm.gateway import LLMGateway
from app.core.llm.transport import LangChainChatTransport
from app.models.shared.llm import LLMCallOptions


def _live_enabled() -> bool:
    return os.getenv("COURSEWARE_LIVE_EVAL", "").strip().lower() in {"1", "true", "yes"}


@pytest.mark.skipif(not _live_enabled(), reason="set COURSEWARE_LIVE_EVAL=1 for real-model acceptance")
def test_courseware_real_model_contract_permissions_and_observability():
    settings = get_settings()
    config_path = Path(os.getenv("COURSEWARE_LIVE_CONFIG", ""))
    if not config_path.is_file():
        pytest.skip("set COURSEWARE_LIVE_CONFIG to the same explicit config used by the live acceptance script")
    config = live_model_config_from_file(config_path, settings)
    if config.missing_fields():
        pytest.fail(f"live config is incomplete: {','.join(config.missing_fields())}")
    if not settings.courseware_ai_enabled or not settings.llm_api_key.get_secret_value().strip():
        pytest.skip("courseware AI is disabled or LLM_API_KEY is unavailable")
    settings = settings.model_copy(update={
        "llm_base_url": config.base_url,
        "llm_model": config.model,
        "llm_structured_output_mode": config.structured_output_mode,
        "llm_request_timeout_seconds": config.timeout_seconds,
    })

    gateway = LLMGateway(
        LangChainChatTransport(settings=settings),
        default_options=LLMCallOptions(
            request_timeout_seconds=min(settings.llm_request_timeout_seconds, 60),
            max_attempts=min(settings.llm_max_attempts, 2),
            max_output_tokens=min(settings.llm_max_output_tokens, 2048),
        ),
    )
    snapshots = [{
        "resource_id": "live-lecture-v1", "role": "intro", "topic": "函数的定义",
        "version": 1, "content_hash": "live-content-hash",
        "blocks": [{"block_id": "live-block-1", "text": "函数把输入映射到确定的输出。"}],
    }]

    plan, plan_trace = build_courseware_spec(gateway, "live-courseware-run", snapshots)
    assert plan is not None
    assert plan_trace and plan_trace["code"] == "LLM_TRACE"
    assert plan_trace["trace"]["model_name"]
    assert plan_trace["trace"]["llm_duration_ms"] >= 0

    deterministic_scene = {
        "kind": "intro", "title": "函数", "source_refs": ["live-lecture-v1"],
        "source_block_ids": ["live-block-1"],
        "blocks": ["函数把输入映射到确定的输出。"],
        "source_map": {"blocks": [["live-block-1"]]},
    }
    scene, scene_trace = compose_courseware_scene(
        gateway, "live-courseware-run", "live-scene-1", deterministic_scene, snapshots[0],
    )
    assert scene is not None
    assert scene_trace and scene_trace["trace"]["total_tokens"] is not None

    decision, _ = review_courseware_quality_decision(
        gateway, "live-courseware-run", {"title": "函数", "scenes": [scene]},
    )
    assert decision.decision in {"approved", "revision_required", "rejected"}
    assert decision.trace_metadata["model_name"]
    assert decision.trace_metadata["llm_duration_ms"] >= 0
