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
from dataclasses import dataclass
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
    {"id": "lecture_checklist", "types": ("讲义", "复习清单")},
    {"id": "lecture_case", "types": ("讲义", "案例分析")},
    {"id": "practice_case", "types": ("实操指南", "案例分析")},
    {"id": "assessment_checklist", "types": ("分阶测试题", "复习清单")},
    {"id": "all_sources_repair", "types": ("讲义", "实操指南", "分阶测试题", "复习清单", "案例分析"), "learning_goal": "观察跨资源融合和高互动配额"},
    {"id": "localized_feedback_repair", "types": ("讲义", "实操指南", "分阶测试题"), "learning_goal": "观察局部反馈修订和候选隔离"},
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

MAX_LIVE_CALLS = 120
MAX_LIVE_TOKENS = 400_000
MAX_LIVE_DURATION_SECONDS = 3_600


@dataclass(frozen=True)
class LiveWorkflowBudget:
    """Explicit, stage-isolated bounds for a paid live-model acceptance run."""

    max_provider_calls: int
    max_tokens: int
    max_duration_seconds: int
    stage_provider_calls: dict[str, int]
    stage_tokens: dict[str, int]

    def __post_init__(self) -> None:
        stages = set(_STAGE_BY_SCHEMA.values())
        if (
            self.max_provider_calls < 1
            or self.max_tokens < 1
            or self.max_duration_seconds < 1
            or set(self.stage_provider_calls) != stages
            or set(self.stage_tokens) != stages
            or any(value < 1 for value in self.stage_provider_calls.values())
            or any(value < 1 for value in self.stage_tokens.values())
        ):
            raise ValueError("invalid_live_workflow_budget")


DEFAULT_LIVE_WORKFLOW_BUDGET = LiveWorkflowBudget(
    max_provider_calls=MAX_LIVE_CALLS,
    max_tokens=MAX_LIVE_TOKENS,
    max_duration_seconds=MAX_LIVE_DURATION_SECONDS,
    stage_provider_calls={"spec": 24, "scene": 72, "quality_review": 24},
    stage_tokens={"spec": 60_000, "scene": 280_000, "quality_review": 60_000},
)


def live_workflow_budget_from_config(payload: dict[str, Any] | None) -> LiveWorkflowBudget:
    """Load a non-secret stage budget; old configs retain the strict default."""

    if not payload:
        return DEFAULT_LIVE_WORKFLOW_BUDGET
    stages = payload.get("stages") or {}
    return LiveWorkflowBudget(
        max_provider_calls=int(payload["max_provider_calls"]),
        max_tokens=int(payload["max_total_tokens"]),
        max_duration_seconds=int(payload["max_duration_seconds"]),
        stage_provider_calls={name: int((stages.get(name) or {})["max_provider_calls"]) for name in _STAGE_BY_SCHEMA.values()},
        stage_tokens={name: int((stages.get(name) or {})["max_tokens"]) for name in _STAGE_BY_SCHEMA.values()},
    )


class LiveWorkflowBudgetExceeded(RuntimeError):
    """Raised before a provider call would exceed a live-evaluation bound."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _outcome_counts(statuses: list[str]) -> dict[str, int]:
    """Keep published-with-warning separate from clean publication."""

    return {
        "published": sum(status == "published" for status in statuses),
        "warning": sum(status == "published_with_warnings" for status in statuses),
        "quarantined": sum(status == "quarantined" for status in statuses),
        "rejected": sum(status in {"rejected_admission", "failed", "release_blocked"} for status in statuses),
    }


def acceptance_report_status(*, usage_complete: bool, quality_gate_passed: bool) -> str:
    """Reserve ``DONE`` for reports that also pass the live quality gate."""

    return "DONE" if usage_complete and quality_gate_passed else "LOCAL_READY"


def redact_workflow_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project one run to fields safe for a committed/CI report."""

    allowed = (
        "combination", "status", "error_code", "warning_codes", "scene_count",
        "scene_statuses", "released", "artifact_sha256", "artifact_count",
        "checkpoint_stages", "outbox_statuses", "attempt", "release_outcome",
        "quality_summary",
    )
    return {key: record[key] for key in allowed if key in record}


class _RecordingGateway:
    """Preserve only sanitized result metadata around the real gateway."""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        budget: LiveWorkflowBudget | None = None,
        max_calls: int | None = None,
        max_tokens: int | None = None,
        max_duration_seconds: float | None = None,
    ):
        self._gateway = gateway
        self.records: list[dict[str, Any]] = []
        self.budget = budget or LiveWorkflowBudget(
            max_provider_calls=max_calls or MAX_LIVE_CALLS,
            max_tokens=max_tokens or MAX_LIVE_TOKENS,
            max_duration_seconds=int(max_duration_seconds or MAX_LIVE_DURATION_SECONDS),
            stage_provider_calls={"spec": max_calls or MAX_LIVE_CALLS, "scene": max_calls or MAX_LIVE_CALLS, "quality_review": max_calls or MAX_LIVE_CALLS},
            stage_tokens={"spec": max_tokens or MAX_LIVE_TOKENS, "scene": max_tokens or MAX_LIVE_TOKENS, "quality_review": max_tokens or MAX_LIVE_TOKENS},
        )
        self.max_calls = self.budget.max_provider_calls
        self.max_tokens = self.budget.max_tokens
        self.max_duration_seconds = self.budget.max_duration_seconds
        self.started_at = time.monotonic()
        self.reserved_calls = 0
        self.reserved_tokens = 0
        self.reserved_calls_by_stage = {name: 0 for name in _STAGE_BY_SCHEMA.values()}
        self.reserved_tokens_by_stage = {name: 0 for name in _STAGE_BY_SCHEMA.values()}
        self.budget_exceeded_reason: str | None = None

    @staticmethod
    def _estimated_input_tokens(messages: list[Any]) -> int:
        # This is intentionally very conservative for a preflight bound:
        # provider tokenizers are not available in the acceptance runner, and
        # treating every character as one token prevents under-reserving
        # Chinese prompts.  It may stop early, but it must never silently
        # spend beyond the declared acceptance budget.
        content = "".join(str(getattr(message, "content", "")) for message in messages)
        return max(1, len(content))

    def _reserve_call(self, kwargs: dict[str, Any], stage: str) -> None:
        if time.monotonic() - self.started_at >= self.max_duration_seconds:
            self.budget_exceeded_reason = "duration_budget"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        if sum(int(item.get("total_tokens") or 0) for item in self.records) >= self.max_tokens:
            self.budget_exceeded_reason = "token_budget"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        options = kwargs.get("options")
        max_attempts = max(1, int(getattr(options, "max_attempts", 1)))
        requested_output = max(1, int(getattr(options, "max_output_tokens", 1)))
        estimated_tokens = self._estimated_input_tokens(kwargs.get("messages") or []) + requested_output
        if self.reserved_calls + max_attempts > self.max_calls:
            self.budget_exceeded_reason = "call_budget"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        if self.reserved_tokens + estimated_tokens > self.max_tokens:
            self.budget_exceeded_reason = "token_budget"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        if self.reserved_calls_by_stage[stage] + max_attempts > self.budget.stage_provider_calls[stage]:
            self.budget_exceeded_reason = f"stage_call_budget:{stage}"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        if self.reserved_tokens_by_stage[stage] + estimated_tokens > self.budget.stage_tokens[stage]:
            self.budget_exceeded_reason = f"stage_token_budget:{stage}"
            raise LiveWorkflowBudgetExceeded(self.budget_exceeded_reason)
        self.reserved_calls += max_attempts
        self.reserved_tokens += estimated_tokens
        self.reserved_calls_by_stage[stage] += max_attempts
        self.reserved_tokens_by_stage[stage] += estimated_tokens

    def options_for(self, *args, **kwargs):
        return self._gateway.options_for(*args, **kwargs)

    def invoke_structured(self, **kwargs):
        stage = _STAGE_BY_SCHEMA.get(kwargs["output_schema"].__name__, "unknown")
        self._reserve_call(kwargs, stage)
        context = kwargs["context"]
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
            if sum(int(item.get("total_tokens") or 0) for item in self.records) >= self.max_tokens:
                self.budget_exceeded_reason = "token_budget"
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
            if sum(int(item.get("total_tokens") or 0) for item in self.records) >= self.max_tokens:
                self.budget_exceeded_reason = "token_budget"
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


def _make_gateway(config: LiveModelConfig, budget: LiveWorkflowBudget) -> _RecordingGateway:
    settings = get_settings()
    key = settings.llm_api_key.get_secret_value().strip()
    if not key:
        key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    live_settings = settings.model_copy(update={
        "llm_api_key": SecretStr(key), "llm_base_url": config.base_url,
        "llm_model": config.model, "llm_structured_output_mode": config.structured_output_mode,
        "llm_request_timeout_seconds": config.timeout_seconds,
        "llm_thinking_mode": config.thinking_mode,
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
    return _RecordingGateway(gateway, budget=budget)


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
    quality_summary = detail.quality_summary if detail else None
    if hasattr(quality_summary, "model_dump"):
        quality_summary = quality_summary.model_dump(mode="json")
    quality_summary = quality_summary if isinstance(quality_summary, dict) else {}
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
        "quality_summary": {
            key: quality_summary.get(key)
            for key in (
                "ai_full_course_success", "required_scene_recovery_rate",
                "deterministic_fallback_count", "rubric_passed", "interaction_quota_status",
            )
            if key in quality_summary
        },
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
        "schema_version": "1.1", "mode": "normal_create_job_worker_workflow",
        "config": config.summary(), "fixture": fixture_manifest,
        "combination_count": len(LIVE_COMBINATIONS),
        "redaction": {"raw_prompt": False, "raw_response": False, "authorization_header": False, "api_key": False, "fixture_content": False},
    }
    missing = config.missing_fields()
    if missing:
        return {**base, "status": "CONFIG_MISSING", "reason": "required_live_model_fields_missing", "missing_fields": missing}
    try:
        budget = live_workflow_budget_from_config(config.acceptance_budget)
    except (KeyError, TypeError, ValueError):
        return {**base, "status": "CONFIG_MISSING", "reason": "invalid_live_workflow_budget", "missing_fields": ["acceptance_budget"]}
    if not enabled:
        return {**base, "status": "NOT_RUN", "reason": "explicit_enable_required"}
    key = settings.llm_api_key.get_secret_value().strip() or (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key or is_placeholder_api_key(key):
        return {**base, "status": "EXTERNAL_PENDING", "reason": "deepseek_credential_missing"}

    fixture_root = artifact_root or (Path.cwd() / ".courseware-live-smoke")
    fixture_root.mkdir(parents=True, exist_ok=True)
    gateway = _make_gateway(config, budget)
    runs: list[dict[str, Any]] = []
    with _artifact_root(fixture_root):
        for combo in LIVE_COMBINATIONS:
            runs.append(_run_one(combo, fixture, gateway, fixture_root))
            if gateway.budget_exceeded_reason:
                break
    stages = _stage_metrics(gateway.records, config)
    statuses = [str(item.get("status")) for item in runs]
    outcomes = _outcome_counts(statuses)
    total_cost = round(sum(item.get("cost") or 0 for item in stages.values()), 8)
    usage_complete = all(
        not stage["calls"] or all(stage["tokens"].get(field) is not None for field in ("input_tokens", "output_tokens", "total_tokens"))
        for stage in stages.values()
    )
    quality_rows = [item.get("quality_summary") or {} for item in runs]
    recovery_values = [item.get("required_scene_recovery_rate") for item in quality_rows]
    quota_values = [item.get("interaction_quota_status") for item in quality_rows]
    rubric_pass_count = sum(item.get("rubric_passed") is True for item in quality_rows)
    fallback_count = sum(int(item.get("deterministic_fallback_count") or 0) for item in quality_rows)
    quality_gate = {
        "publishable_count": outcomes["published"] + outcomes["warning"],
        "publishable_target": 8,
        "required_scene_recovery_rate": min(recovery_values) if recovery_values and all(value is not None for value in recovery_values) else None,
        "required_scene_recovery_target": 0.85,
        "full_course_success_count": sum(item.get("ai_full_course_success") is True for item in quality_rows),
        "full_course_success_target": 7,
        "deterministic_fallback_count": fallback_count,
        "deterministic_fallback_target_max": 2,
        "rubric_pass_count": rubric_pass_count,
        "rubric_pass_target": 8,
        "interaction_quota_measured_count": sum(value in {"met", "not_met"} for value in quota_values),
        "interaction_quota_target_rate": 0.90,
    }
    quality_gate["passed"] = bool(
        quality_gate["publishable_count"] >= quality_gate["publishable_target"]
        and quality_gate["required_scene_recovery_rate"] is not None
        and quality_gate["required_scene_recovery_rate"] >= quality_gate["required_scene_recovery_target"]
        and quality_gate["full_course_success_count"] >= quality_gate["full_course_success_target"]
        and quality_gate["deterministic_fallback_count"] <= quality_gate["deterministic_fallback_target_max"]
        and quality_gate["rubric_pass_count"] >= quality_gate["rubric_pass_target"]
        and quality_gate["interaction_quota_measured_count"] == len(quality_rows)
        and sum(value == "met" for value in quota_values) / len(quality_rows) >= quality_gate["interaction_quota_target_rate"]
    ) if quality_rows else False
    actual_calls = sum(int(item.get("attempt_count") or 0) for item in gateway.records)
    actual_tokens = sum(int(item.get("total_tokens") or 0) for item in gateway.records)
    return {
        **base,
        "status": acceptance_report_status(
            usage_complete=usage_complete,
            quality_gate_passed=bool(quality_gate["passed"]),
        ),
        "quality_status": "LOCAL_QUALITY_READY" if quality_gate["passed"] else "QUALITY_PARTIAL",
        "runs": runs,
        "metrics": {
            "stages": stages,
            "quality": {"workflow_success_rate": round((outcomes["published"] + outcomes["warning"]) / len(LIVE_COMBINATIONS), 4), "spec_success_rate": stages["spec"]["success_rate"], "scene_success_rate": stages["scene"]["success_rate"], "quality_review_success_rate": stages["quality_review"]["success_rate"], "gate": quality_gate},
            "reliability": {"retry_count": sum(item["retry_count"] for item in stages.values()), "fallback_rate": round(sum(1 for item in runs if any(code.endswith("FALLBACK") for code in item["warning_codes"])) / len(runs), 4), "p50_latency_ms": median([item["latency_ms"]["p50"] for item in stages.values() if item["latency_ms"]["p50"] is not None]) if any(item["latency_ms"]["p50"] is not None for item in stages.values()) else None},
            "cost": {"currency": config.price_currency, "total": total_cost, "complete": usage_complete},
        },
        "outcomes": outcomes,
        "bounds": {
            "max_combinations": len(LIVE_COMBINATIONS), "actual_combinations": len(runs),
            "max_calls": budget.max_provider_calls, "actual_calls": actual_calls,
            "max_tokens": budget.max_tokens, "actual_tokens": actual_tokens,
            "reserved_tokens": gateway.reserved_tokens,
            "reserved_calls_by_stage": gateway.reserved_calls_by_stage,
            "reserved_tokens_by_stage": gateway.reserved_tokens_by_stage,
            "stage_max_calls": budget.stage_provider_calls,
            "stage_max_tokens": budget.stage_tokens,
            "max_duration_seconds": budget.max_duration_seconds,
            "max_attempts_per_call": config.max_attempts, "unbounded_retry": False,
            "budget_exceeded": bool(gateway.budget_exceeded_reason),
            "budget_stop_reason": gateway.budget_exceeded_reason,
        },
    }
