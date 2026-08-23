"""Versioned, redacted live-model acceptance and fake-provider evidence."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import Settings, get_settings, is_placeholder_api_key
from app.core.llm.gateway import LLMGateway
from app.core.llm.transport import LangChainChatTransport
from app.models.shared.llm import (
    LLMCallContext,
    LLMCallOptions,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewareReviewDecision,
    CoursewareSceneSpec,
    CoursewareSpec,
)


SCHEMA_VERSION = "1.0"
# ``live_model.py`` is under ``backend/app/core/courseware``.  The frozen
# fixture deliberately lives under ``backend/tests`` so it cannot accidentally
# resolve to a workspace-level ``tests`` directory when the acceptance script
# is launched from the repository root.
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "courseware" / "live_model" / "resource_bundle_snapshot.v1.json"


@dataclass(frozen=True)
class LiveModelConfig:
    config_version: int
    provider: str
    base_url: str
    model: str
    structured_output_mode: str
    timeout_seconds: float | None
    max_attempts: int | None
    retry_base_delay_seconds: float | None
    retry_max_delay_seconds: float | None
    input_price_per_1k_tokens: float | None
    output_price_per_1k_tokens: float | None
    price_currency: str
    price_version: str
    price_effective_date: str
    api_key_present: bool

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "LiveModelConfig":
        settings = settings or get_settings()
        key = settings.llm_api_key.get_secret_value().strip()
        return cls(
            config_version=settings.courseware_live_model_config_version,
            provider=settings.courseware_live_model_provider.strip(),
            base_url=settings.courseware_live_model_base_url.strip(),
            model=settings.courseware_live_model.strip(),
            structured_output_mode=settings.courseware_live_structured_output_mode.strip().lower(),
            timeout_seconds=settings.courseware_live_timeout_seconds,
            max_attempts=settings.courseware_live_max_attempts,
            retry_base_delay_seconds=settings.courseware_live_retry_base_delay_seconds,
            retry_max_delay_seconds=settings.courseware_live_retry_max_delay_seconds,
            input_price_per_1k_tokens=settings.courseware_live_input_price_per_1k_tokens,
            output_price_per_1k_tokens=settings.courseware_live_output_price_per_1k_tokens,
            price_currency=settings.courseware_live_price_currency.strip().upper(),
            price_version=settings.courseware_live_price_version.strip(),
            price_effective_date=settings.courseware_live_price_effective_date.strip(),
            api_key_present=bool(key and not is_placeholder_api_key(key)),
        )

    def missing_fields(self) -> list[str]:
        missing = []
        for field in ("provider", "base_url", "model", "structured_output_mode", "price_currency", "price_version", "price_effective_date"):
            if not getattr(self, field):
                missing.append(field)
        for field in ("timeout_seconds", "max_attempts", "retry_base_delay_seconds", "retry_max_delay_seconds",
                      "input_price_per_1k_tokens", "output_price_per_1k_tokens"):
            if getattr(self, field) is None:
                missing.append(field)
        try:
            date.fromisoformat(self.price_effective_date)
        except ValueError:
            if "price_effective_date" not in missing:
                missing.append("price_effective_date")
        try:
            StructuredOutputMode(self.structured_output_mode)
        except ValueError:
            if "structured_output_mode" not in missing:
                missing.append("structured_output_mode")
        if self.retry_max_delay_seconds is not None and self.retry_base_delay_seconds is not None and self.retry_max_delay_seconds < self.retry_base_delay_seconds:
            missing.append("retry_policy")
        return sorted(set(missing))

    def summary(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "structured_output_mode": self.structured_output_mode,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "retry_base_delay_seconds": self.retry_base_delay_seconds,
            "retry_max_delay_seconds": self.retry_max_delay_seconds,
            "input_price_per_1k_tokens": self.input_price_per_1k_tokens,
            "output_price_per_1k_tokens": self.output_price_per_1k_tokens,
            "price_currency": self.price_currency,
            "price_version": self.price_version,
            "price_effective_date": self.price_effective_date,
            "api_key_present": self.api_key_present,
        }


def live_model_config_from_file(path: Path, settings: Settings | None = None) -> LiveModelConfig:
    """Load explicit non-secret C0 metadata without falling back to defaults."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("live model config must be a JSON object")
    settings = settings or get_settings()
    key = settings.llm_api_key.get_secret_value().strip()
    return LiveModelConfig(
        config_version=payload.get("config_version"),
        provider=str(payload.get("provider") or "").strip(),
        base_url=str(payload.get("base_url") or "").strip(),
        model=str(payload.get("model") or "").strip(),
        structured_output_mode=str(payload.get("structured_output_mode") or "").strip().lower(),
        timeout_seconds=payload.get("timeout_seconds"),
        max_attempts=payload.get("max_attempts"),
        retry_base_delay_seconds=payload.get("retry_base_delay_seconds"),
        retry_max_delay_seconds=payload.get("retry_max_delay_seconds"),
        input_price_per_1k_tokens=payload.get("input_price_per_1k_tokens"),
        output_price_per_1k_tokens=payload.get("output_price_per_1k_tokens"),
        price_currency=str(payload.get("price_currency") or "").strip().upper(),
        price_version=str(payload.get("price_version") or "").strip(),
        price_effective_date=str(payload.get("price_effective_date") or "").strip(),
        api_key_present=bool(key and not is_placeholder_api_key(key)),
    )


def load_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = FIXTURE_PATH.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    return fixture, {
        "source_type": "redacted_frozen_resource_bundle_snapshot",
        "fixture_version": fixture["fixture_version"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sensitive_data_included": False,
        "resource_count": len(fixture.get("resources") or []),
    }


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _cost(usage: dict[str, int | None], config: LiveModelConfig) -> float | None:
    if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    return round(
        (usage["input_tokens"] or 0) / 1000 * (config.input_price_per_1k_tokens or 0)
        + (usage["output_tokens"] or 0) / 1000 * (config.output_price_per_1k_tokens or 0),
        8,
    )


def _stage_metrics(records: list[dict[str, Any]], config: LiveModelConfig) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for stage in ("spec", "scene", "quality_review"):
        items = [item for item in records if item["stage"] == stage]
        successes = [item for item in items if item["success"]]
        usage = {
            "input_tokens": sum(item["input_tokens"] or 0 for item in items) if all(item["input_tokens"] is not None for item in items) else None,
            "output_tokens": sum(item["output_tokens"] or 0 for item in items) if all(item["output_tokens"] is not None for item in items) else None,
            "total_tokens": sum(item["total_tokens"] or 0 for item in items) if all(item["total_tokens"] is not None for item in items) else None,
        }
        latencies = [int(item["latency_ms"]) for item in items]
        result[stage] = {
            "calls": len(items),
            "successes": len(successes),
            "success_rate": round(len(successes) / len(items), 4) if items else None,
            "schema_first_success_rate": round(sum(item["attempt_count"] == 1 for item in items) / len(items), 4) if items else None,
            "schema_repair_rate": round(sum(item["attempt_count"] > 1 for item in items) / len(items), 4) if items else None,
            "provenance_rejection_rate": round(sum(item["provenance_rejected"] for item in items) / len(items), 4) if items else None,
            "fallback_rate": round(sum(item["fallback"] for item in items) / len(items), 4) if items else None,
            "retry_count": sum(max(0, int(item["attempt_count"]) - 1) for item in items),
            "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
            "tokens": usage,
            "cost": _cost(usage, config),
            "outcomes": {
                "published": sum(item["outcome"] == "published" for item in items),
                "warning": sum(item["outcome"] == "warning" for item in items),
                "quarantined": sum(item["outcome"] == "quarantined" for item in items),
                "rejected": sum(item["outcome"] == "rejected" for item in items),
            },
        }
    return result


class _FakeTransport:
    model_name = "fake-courseware-provider-v1"

    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self.scene_calls = 0

    def invoke(self, *, messages, output_schema, mode, timeout_seconds, temperature, max_output_tokens):
        name = output_schema.__name__
        self.calls.append({"schema": name, "mode": mode.value, "message_count": len(messages)})
        usage = LLMUsage(input_tokens=40, output_tokens=20, total_tokens=60)
        if name == "CoursewareSpec":
            payload: Any = {"title": "脱敏函数课件", "learning_objectives": ["理解映射"], "scenes": [{"source_resource_id": "fixture-lecture", "kind": "intro", "title": "函数", "source_block_ids": ["block-1"]}]}
        elif name == "CoursewareSceneSpec":
            self.scene_calls += 1
            if self.scene_calls == 1:
                payload = "{invalid-json"
            else:
                block_id = "missing-block" if self.scene_calls == 2 else "block-1"
                payload = {"kind": "intro", "title": "函数", "blocks": [{"component": "callout", "block_id": "scene-block", "text": "输入映射到输出。", "source_refs": [{"source_resource_id": "fixture-lecture", "source_block_ids": [block_id]}]}]}
        else:
            payload = {"decision": "approved", "confidence": 0.9}
        return RawLLMResponse(content=payload, usage=usage, provider_request_id="fake-request", finish_reason="stop", structured_output_mode=mode)


def live_fixture_input(fixture: dict[str, Any]) -> dict[str, Any]:
    """Return only approved frozen snapshot fields for a live-model message."""
    return {
        "sources": [
            {
                "resource_id": str(resource.get("resource_id") or ""),
                "resource_type": str(resource.get("resource_type") or ""),
                "version": resource.get("version"),
                "content_hash": str(resource.get("content_hash") or ""),
                "blocks": [
                    {"block_id": str(block.get("block_id") or ""), "text": str(block.get("text") or "")[:1600]}
                    for block in (resource.get("blocks") or [])[:12]
                ],
            }
            for resource in (fixture.get("resources") or [])[:12]
        ],
        "learner_context": {
            key: fixture.get("learner_context", {}).get(key)
            for key in ("level", "pace", "language", "accessibility")
            if key in (fixture.get("learner_context") or {})
        },
    }


def _invoke(gateway: LLMGateway, schema: type, run_id: str, step_id: str, options: LLMCallOptions, fixture: dict[str, Any]):
    return gateway.invoke_structured(
        messages=[
            SystemMessage(content="仅依据给定冻结脱敏来源返回结构化结果；不得新增来源以外的事实。"),
            HumanMessage(content=json.dumps(live_fixture_input(fixture), ensure_ascii=False, separators=(",", ":"))),
        ],
        output_schema=schema,
        context=LLMCallContext(run_id=run_id, step_id=step_id, node_name=step_id, schema_name=schema.__name__),
        options=options,
    )


def run_fake_provider_acceptance() -> dict[str, Any]:
    fixture, fixture_manifest = load_fixture()
    config = LiveModelConfig(1, "fake", "fake://local", "fake-courseware-provider-v1", "json_schema", 10, 2, 0, 1, 0.01, 0.02, "CNY", "fake-price-v1", "2026-08-23", False)
    transport = _FakeTransport()
    gateway = LLMGateway(transport, default_options=LLMCallOptions(max_attempts=2, request_timeout_seconds=10, structured_output_mode=StructuredOutputMode.JSON_SCHEMA), sleep=lambda _seconds: None)
    options = gateway.options_for("generator").model_copy(update={"max_attempts": 2, "structured_output_mode": StructuredOutputMode.JSON_SCHEMA})
    records: list[dict[str, Any]] = []
    for stage, schema, step in (("spec", CoursewareSpec, "spec"), ("scene", CoursewareSceneSpec, "scene-valid"), ("scene", CoursewareSceneSpec, "scene-provenance-reject"), ("quality_review", CoursewareReviewDecision, "quality-review")):
        try:
            result = _invoke(gateway, schema, "fake-courseware-run", step, options, fixture)
            trace = result.trace_metadata()
            provenance_rejected = stage == "scene" and step == "scene-provenance-reject"
            records.append({"stage": stage, "success": not provenance_rejected, "provenance_rejected": provenance_rejected, "fallback": provenance_rejected, "outcome": "quarantined" if provenance_rejected else "published", "attempt_count": result.attempt_count, "latency_ms": result.latency_ms, "input_tokens": trace["input_tokens"], "output_tokens": trace["output_tokens"], "total_tokens": trace["total_tokens"]})
        except Exception:
            records.append({"stage": stage, "success": False, "provenance_rejected": False, "fallback": True, "outcome": "rejected", "attempt_count": options.max_attempts, "latency_ms": 0, "input_tokens": None, "output_tokens": None, "total_tokens": None})
    stages = _stage_metrics(records, config)
    return {"schema_version": SCHEMA_VERSION, "status": "LOCAL_READY", "mode": "fake_provider", "config": config.summary(), "fixture": fixture_manifest, "metrics": {"stages": stages, "quality": {"success_rate": stages["quality_review"]["success_rate"]}, "reliability": {"retry_count": sum(item["retry_count"] for item in stages.values()), "fallback_rate": sum(item["fallback_rate"] or 0 for item in stages.values()) / 3}, "cost": {"currency": config.price_currency, "total": round(sum(item["cost"] or 0 for item in stages.values()), 8)}}, "outcomes": {"published": 3, "warning": 0, "quarantined": 1, "rejected": 0}, "redaction": {"raw_prompt": False, "raw_response": False, "authorization_header": False, "api_key": False, "fixture_content": False}, "fixture_inputs": {"resource_count": len(fixture.get("resources") or [])}}


def run_live_model_acceptance(*, config_path: Path | None = None, enabled: bool | None = None) -> dict[str, Any]:
    settings = get_settings()
    config = live_model_config_from_file(config_path, settings) if config_path else LiveModelConfig.from_settings(settings)
    fixture, fixture_manifest = load_fixture()
    base = {"schema_version": SCHEMA_VERSION, "config": config.summary(), "fixture": fixture_manifest, "redaction": {"raw_prompt": False, "raw_response": False, "authorization_header": False, "api_key": False, "fixture_content": False}}
    missing = config.missing_fields()
    if missing:
        return {**base, "status": "CONFIG_MISSING", "reason": "required_live_model_fields_missing", "missing_fields": missing}
    is_enabled = enabled if enabled is not None else os.getenv("COURSEWARE_LIVE_EVAL", "").strip().lower() in {"1", "true", "yes"}
    if not is_enabled:
        return {**base, "status": "NOT_RUN", "reason": "COURSEWARE_LIVE_EVAL_not_enabled"}
    if not config.api_key_present:
        return {**base, "status": "EXTERNAL_PENDING", "reason": "real_provider_credential_missing"}
    live_settings = settings.model_copy(update={"llm_base_url": config.base_url, "llm_model": config.model, "llm_structured_output_mode": config.structured_output_mode, "llm_request_timeout_seconds": config.timeout_seconds})
    gateway = LLMGateway(LangChainChatTransport(settings=live_settings), retry_base_delay_seconds=config.retry_base_delay_seconds or 0, retry_max_delay_seconds=config.retry_max_delay_seconds or 0, default_options=LLMCallOptions(max_attempts=config.max_attempts or 1, request_timeout_seconds=config.timeout_seconds or 60, structured_output_mode=StructuredOutputMode(config.structured_output_mode)))
    records: list[dict[str, Any]] = []
    options = gateway.options_for("generator")
    for stage, schema, step in (("spec", CoursewareSpec, "spec"), ("scene", CoursewareSceneSpec, "scene"), ("quality_review", CoursewareReviewDecision, "quality-review")):
        try:
            result = _invoke(gateway, schema, "live-courseware-run", step, options, fixture)
            trace = result.trace_metadata()
            records.append({"stage": stage, "success": True, "provenance_rejected": False, "fallback": False, "outcome": "published", "attempt_count": result.attempt_count, "latency_ms": result.latency_ms, "input_tokens": trace["input_tokens"], "output_tokens": trace["output_tokens"], "total_tokens": trace["total_tokens"]})
        except Exception:
            records.append({"stage": stage, "success": False, "provenance_rejected": False, "fallback": True, "outcome": "rejected", "attempt_count": options.max_attempts, "latency_ms": 0, "input_tokens": None, "output_tokens": None, "total_tokens": None})
    stages = _stage_metrics(records, config)
    # This probe now transmits the frozen fixture, but it still invokes three
    # schemas directly.  It is not a candidate/release workflow and must not
    # convert schema parse success into a published outcome.
    return {**base, "status": "LIVE_RERUN_REQUIRED", "mode": "direct_schema_probe",
            "metrics": {"stages": stages},
            "outcomes": {"schema_success": sum(item["success"] for item in records),
                         "warning": 0, "quarantined": 0, "rejected": sum(not item["success"] for item in records)},
            "reason": "real_courseware_workflow_and_release_evidence_required"}
