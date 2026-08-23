"""Bounded real-provider smoke for the normal interactive-courseware path.

This module deliberately uses the application service and durable Worker
executor with an in-memory repository.  It is a bounded acceptance probe, not
the production deployment proof (that is covered by the process-level C1
suite).  Only frozen, synthetic resources are constructed here and only
sanitized workflow projections are returned.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from statistics import median
from typing import Any, Iterator

from pydantic import SecretStr

from app.config import get_settings, is_placeholder_api_key
from app.core.courseware.live_model import (
    LiveModelConfig,
    _cost,
    _percentile,
    live_model_config_from_file,
    load_fixture,
)
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.core.llm.transport import LangChainChatTransport
from app.core.storage import file_storage
from app.db.audit.memory import MemoryAuditRepository
from app.db.courseware.repository import MemoryCoursewareRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.courseware import CoursewareJobCreateRequest
from app.models.learning_documents.schemas import ExerciseItem, LearningResource, SourceRef
from app.models.shared.llm import LLMCallOptions, StructuredOutputMode
from app.services.courseware import CoursewareService
from app.services.courseware.executor import CoursewareExecutor
from app.services.learning_documents.resources import ResourceService


LIVE_COMBINATIONS: tuple[dict[str, Any], ...] = (
    {"id": "lecture_only", "types": ("讲义",)},
    {"id": "lecture_practice_assessment", "types": ("讲义", "实操指南", "分阶测试题")},
    {"id": "five_resource_types", "types": ("讲义", "实操指南", "分阶测试题", "复习清单", "案例分析")},
    {"id": "repair_revision_candidate", "types": ("讲义", "实操指南", "分阶测试题"), "learning_goal": "检查练习反馈并观察受预算约束的修订路径"},
)

_TYPE_TO_ID = {
    "讲义": "lecture",
    "实操指南": "practice",
    "分阶测试题": "assessment",
    "复习清单": "checklist",
    "案例分析": "case-study",
}
_STAGE_BY_SCHEMA = {
    "CoursewareSpec": "spec",
    "CoursewareSceneSpec": "scene",
    "CoursewareReviewDecision": "quality_review",
}


def _outcome_counts(statuses: list[str]) -> dict[str, int]:
    """Keep published-with-warning separate from clean publication."""

    return {
        "published": sum(status == "published" for status in statuses),
        "warning": sum(status == "published_with_warnings" for status in statuses),
        "quarantined": sum(status == "quarantined" for status in statuses),
        "rejected": sum(status in {"rejected_admission", "failed", "release_blocked"} for status in statuses),
    }


def redact_workflow_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project one run to fields safe for a committed/CI report."""

    allowed = (
        "combination", "status", "error_code", "warning_codes", "scene_count",
        "scene_statuses", "released", "artifact_sha256", "artifact_count",
        "checkpoint_stages", "outbox_statuses", "attempt", "release_outcome",
    )
    return {key: record[key] for key in allowed if key in record}


class _RecordingGateway:
    """Preserve only sanitized result metadata around the real gateway."""

    def __init__(self, gateway: LLMGateway):
        self._gateway = gateway
        self.records: list[dict[str, Any]] = []

    def options_for(self, *args, **kwargs):
        return self._gateway.options_for(*args, **kwargs)

    def invoke_structured(self, **kwargs):
        context = kwargs["context"]
        stage = _STAGE_BY_SCHEMA.get(kwargs["output_schema"].__name__, "unknown")
        started = time.monotonic()
        try:
            result = self._gateway.invoke_structured(**kwargs)
            trace = result.trace_metadata()
            self.records.append({
                "stage": stage, "success": True,
                "attempt_count": result.attempt_count, "retry_count": result.retry_count,
                "latency_ms": result.latency_ms,
                "input_tokens": trace.get("input_tokens"), "output_tokens": trace.get("output_tokens"),
                "total_tokens": trace.get("total_tokens"),
            })
            return result
        except LLMGatewayError as exc:
            trace = exc.trace_metadata()
            self.records.append({
                "stage": stage, "success": False,
                "attempt_count": max(1, len(exc.attempts)), "retry_count": exc.retry_count,
                "latency_ms": trace.get("llm_duration_ms") or int((time.monotonic() - started) * 1000),
                "input_tokens": trace.get("input_tokens"), "output_tokens": trace.get("output_tokens"),
                "total_tokens": trace.get("total_tokens"),
            })
            raise
        except Exception:
            self.records.append({
                "stage": stage, "success": False, "attempt_count": 1, "retry_count": 0,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "input_tokens": None, "output_tokens": None, "total_tokens": None,
            })
            raise


class _AuditRepository:
    def get_run(self, _run_id: str):
        return None


def _source_ref(resource_id: str) -> SourceRef:
    return SourceRef(
        doc_id=f"frozen-{resource_id}", title="脱敏冻结来源", snippet="脱敏来源摘要",
        score=1.0, provenance_status="verified", knowledge_base_id="kb-live-frozen",
    )


def _build_resource(resource_id: str, resource_type: str, content: str, batch_id: str) -> LearningResource:
    exercises = []
    if resource_type == "分阶测试题":
        exercises = [ExerciseItem(
            question_id=f"{resource_id}-q1", question_type="single_choice",
            question="根据冻结来源，第一步是什么？", options=["检索", "跳过来源"],
            answer="检索", explanation="只使用冻结来源。",
        )]
    return LearningResource(
        resource_id=resource_id, learner_id="live-courseware-learner", topic="冻结脱敏课件验收",
        resource_type=resource_type, difficulty="初级", content_text=content,
        knowledge_points=["冻结来源约束"], source_refs=[_source_ref(resource_id)],
        run_id=f"frozen-run-{resource_id}", batch_id=batch_id,
        publication_status="published", exercise_items=exercises,
    )


def _fixture_content(fixture: dict[str, Any], resource_type: str) -> str:
    if resource_type == "讲义":
        return "输入经过确定规则映射到输出；课件只能依据冻结来源。"
    if resource_type == "实操指南":
        return "先读取冻结来源，再按步骤验证结果，最后记录观察。"
    if resource_type == "分阶测试题":
        return "根据冻结来源判断步骤顺序并说明理由。"
    if resource_type == "复习清单":
        return "复习冻结来源、验证步骤和结果记录。"
    if resource_type == "案例分析":
        return "案例只讨论冻结来源中的输入、过程和输出关系。"
    return str(fixture.get("learner_context", {}).get("language") or "脱敏来源")


def _make_gateway(config: LiveModelConfig) -> _RecordingGateway:
    settings = get_settings()
    key = settings.llm_api_key.get_secret_value().strip()
    if not key:
        key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    live_settings = settings.model_copy(update={
        "llm_api_key": SecretStr(key), "llm_base_url": config.base_url,
        "llm_model": config.model, "llm_structured_output_mode": config.structured_output_mode,
        "llm_request_timeout_seconds": config.timeout_seconds,
    })
    gateway = LLMGateway(
        LangChainChatTransport(settings=live_settings),
        retry_base_delay_seconds=config.retry_base_delay_seconds or 0,
        retry_max_delay_seconds=config.retry_max_delay_seconds or 0,
        default_options=LLMCallOptions(
            max_attempts=config.max_attempts or 1,
            request_timeout_seconds=config.timeout_seconds or 60,
            structured_output_mode=StructuredOutputMode(config.structured_output_mode),
        ),
    )
    return _RecordingGateway(gateway)


@contextmanager
def _artifact_root(root: Path) -> Iterator[None]:
    original = file_storage._get_resources_dir
    file_storage._get_resources_dir = lambda: root
    try:
        yield
    finally:
        file_storage._get_resources_dir = original


def _run_one(combo: dict[str, Any], fixture: dict[str, Any], gateway: _RecordingGateway, root: Path) -> dict[str, Any]:
    resource_repo = MemoryResourceRepository()
    for resource_type in combo["types"]:
        resource_id = f"live-{combo['id']}-{_TYPE_TO_ID[resource_type]}"
        resource_repo.save(
            _build_resource(resource_id, resource_type, _fixture_content(fixture, resource_type), f"live-feedback-{combo['id']}"),
            "live-courseware-learner", "冻结脱敏课件验收",
        )
    courseware_repo = MemoryCoursewareRepository()
    service = CoursewareService(courseware_repo, ResourceService(resource_repo), _AuditRepository(), gateway)
    request = CoursewareJobCreateRequest(
        learner_id="live-courseware-learner",
        source_resource_ids=[f"live-{combo['id']}-{_TYPE_TO_ID[item]}" for item in combo["types"]],
        title=f"脱敏 DeepSeek 验收：{combo['id']}",
        learning_goal=combo.get("learning_goal"),
        publish_mode="automatic",
    )
    created = service.create_job(request)
    executor = CoursewareExecutor(
        repo=courseware_repo, workflow=service.workflow, owner_id=f"live-smoke-{combo['id']}",
        batch_size=1, lease_seconds=120,
    )
    executor_result = executor.run_once(limit=1)
    job = service.get_job(created.run_id)
    detail = service.get_job_detail(created.run_id)
    row = courseware_repo.get_job(created.run_id) or {}
    resource = courseware_repo.get_resource_by_run(created.run_id)
    artifact_sha = resource.get("artifact_sha256") if resource else None
    warnings = row.get("warnings") or []
    checkpoints = [item for item in courseware_repo.checkpoints.values() if item.get("run_id") == created.run_id]
    outbox = courseware_repo.list_outbox(created.run_id, pending_only=False)
    record = {
        "combination": combo["id"], "status": job.status if job else "missing",
        "error_code": job.error_code if job else "JOB_MISSING",
        "warning_codes": sorted({str(item.get("code")) for item in warnings if item.get("code")}),
        "scene_count": len(detail.scenes) if detail else 0,
        "scene_statuses": sorted({scene.status for scene in detail.scenes}) if detail else [],
        "released": bool(row.get("released_release_id")), "artifact_sha256": artifact_sha,
        "artifact_count": len(courseware_repo.list_artifacts(resource["resource_id"])) if resource else 0,
        "checkpoint_stages": sorted({str(item.get("stage")) for item in checkpoints}),
        "outbox_statuses": sorted({str(item.get("status")) for item in outbox}),
        "attempt": int(row.get("attempt") or 0),
        "release_outcome": row.get("released_release_id") and "released" or "not_released",
        "executor": executor_result,
    }
    return redact_workflow_record(record)


def _stage_metrics(records: list[dict[str, Any]], config: LiveModelConfig) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for stage in ("spec", "scene", "quality_review"):
        items = [item for item in records if item["stage"] == stage]
        successful = [item for item in items if item["success"]]
        token_fields = {}
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            values = [item[field] for item in items]
            token_fields[field] = sum(value or 0 for value in values) if values and all(value is not None for value in values) else None
        latencies = [int(item["latency_ms"]) for item in items]
        output[stage] = {
            "calls": len(items), "successes": len(successful),
            "success_rate": round(len(successful) / len(items), 4) if items else None,
            "schema_first_success_rate": round(sum(item["attempt_count"] == 1 for item in items) / len(items), 4) if items else None,
            "schema_repair_rate": round(sum(item["attempt_count"] > 1 for item in items) / len(items), 4) if items else None,
            "provenance_rejection_rate": None, "fallback_rate": None,
            "retry_count": sum(int(item["retry_count"]) for item in items),
            "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
            "tokens": token_fields, "cost": _cost(token_fields, config),
        }
    return output


def run_bounded_live_workflow(*, config_path: Path, enabled: bool = False, artifact_root: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    fixture, fixture_manifest = load_fixture()
    config = live_model_config_from_file(config_path, settings)
    base = {
        "schema_version": "1.0", "mode": "normal_create_job_worker_workflow",
        "config": config.summary(), "fixture": fixture_manifest,
        "combination_count": len(LIVE_COMBINATIONS),
        "redaction": {"raw_prompt": False, "raw_response": False, "authorization_header": False, "api_key": False, "fixture_content": False},
    }
    missing = config.missing_fields()
    if missing:
        return {**base, "status": "CONFIG_MISSING", "reason": "required_live_model_fields_missing", "missing_fields": missing}
    if not enabled:
        return {**base, "status": "NOT_RUN", "reason": "explicit_enable_required"}
    key = settings.llm_api_key.get_secret_value().strip() or (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key or is_placeholder_api_key(key):
        return {**base, "status": "EXTERNAL_PENDING", "reason": "deepseek_credential_missing"}

    fixture_root = artifact_root or (Path.cwd() / ".courseware-live-smoke")
    fixture_root.mkdir(parents=True, exist_ok=True)
    gateway = _make_gateway(config)
    runs: list[dict[str, Any]] = []
    with _artifact_root(fixture_root):
        for combo in LIVE_COMBINATIONS:
            runs.append(_run_one(combo, fixture, gateway, fixture_root))
    stages = _stage_metrics(gateway.records, config)
    statuses = [str(item.get("status")) for item in runs]
    outcomes = _outcome_counts(statuses)
    total_cost = round(sum(item.get("cost") or 0 for item in stages.values()), 8)
    usage_complete = all(
        not stage["calls"] or all(stage["tokens"].get(field) is not None for field in ("input_tokens", "output_tokens", "total_tokens"))
        for stage in stages.values()
    )
    return {
        **base, "status": "DONE" if usage_complete else "LOCAL_READY", "runs": runs,
        "metrics": {
            "stages": stages,
            "quality": {"workflow_success_rate": round((outcomes["published"] + outcomes["warning"]) / len(runs), 4), "spec_success_rate": stages["spec"]["success_rate"], "scene_success_rate": stages["scene"]["success_rate"], "quality_review_success_rate": stages["quality_review"]["success_rate"]},
            "reliability": {"retry_count": sum(item["retry_count"] for item in stages.values()), "fallback_rate": round(sum(1 for item in runs if any(code.endswith("FALLBACK") for code in item["warning_codes"])) / len(runs), 4), "p50_latency_ms": median([item["latency_ms"]["p50"] for item in stages.values() if item["latency_ms"]["p50"] is not None]) if any(item["latency_ms"]["p50"] is not None for item in stages.values()) else None},
            "cost": {"currency": config.price_currency, "total": total_cost, "complete": usage_complete},
        },
        "outcomes": outcomes,
        "bounds": {"max_combinations": 4, "actual_combinations": len(runs), "max_attempts_per_call": config.max_attempts, "unbounded_retry": False},
    }
