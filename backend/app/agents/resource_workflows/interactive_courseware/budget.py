"""Deterministic, persisted budget gates for courseware model calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
from typing import Any


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    max_output_tokens: int
    warning: dict[str, Any] | None = None
    call_id: str | None = None
    estimated_input_tokens: int = 0
    timeout_seconds: float = 0.0


class CoursewareBudgetCoordinator:
    _STAGES = ("planner", "scene", "quality_review", "revision")
    _reservation_lock = RLock()

    def __init__(self, repo, settings_provider):
        self.repo = repo
        self.settings_provider = settings_provider

    def before_call(self, run_id: str, stage: str, *, requested_output_tokens: int | None = None,
                    estimated_input_tokens: int | None = None, attempts: int = 1,
                    phase: str = "model", input_hash: str | None = None) -> BudgetDecision:
        from .content_review.persistence import read_state
        state, _ = read_state(self.repo, run_id)
        if state is not None:
            return self._before_content(run_id, stage, state, requested_output_tokens, estimated_input_tokens, attempts, phase, input_hash)
        settings = self.settings_provider()
        stage = stage if stage in self._STAGES else "revision"
        job = self.repo.get_job(run_id) or {}
        now = datetime.now(timezone.utc)
        total_token_budget = int(getattr(settings, "courseware_total_llm_token_budget", 32768))
        stage_limits = {
            "planner": float(getattr(settings, "courseware_planner_max_seconds", 90.0)),
            "scene": float(getattr(settings, "courseware_scene_composition_max_seconds", 450.0)),
            "quality_review": float(getattr(settings, "courseware_quality_review_max_seconds", 120.0)),
            "revision": float(getattr(settings, "courseware_revision_max_seconds", 180.0)),
        }
        stage_names = {"planner": "design_reviewing", "scene": "composing", "quality_review": "quality_reviewing", "revision": "auto_revising"}
        started = [event.get("created_at") for event in self.repo.list_events(run_id)
                   if event.get("stage") == stage_names[stage] and event.get("status") == "started"]
        if started:
            stage_start = started[0]
            if isinstance(stage_start, datetime):
                if stage_start.tzinfo is None:
                    stage_start = stage_start.replace(tzinfo=timezone.utc)
                if (now - stage_start).total_seconds() >= stage_limits[stage]:
                    return self._deny(stage, "stage", "COURSEWARE_STAGE_TIMEOUT", "当前课件阶段时限已耗尽")
        deadline = job.get("deadline_at")
        if deadline is not None:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline <= now:
                return self._deny(stage, "task", "COURSEWARE_RUN_TIMEOUT", "课件任务 deadline 已到")

        traces = self._traces(run_id)
        reservations = self._reservations(run_id)
        total_used = sum(self._tokens(item) for item in traces)
        total_reserved = sum(int(item.get("estimated_input") or 0) + int(item.get("max_output") or 0)
                             for item in reservations if item.get("status") == "reserved")
        if total_used >= total_token_budget:
            return self._deny(stage, "task", "COURSEWARE_LLM_TOKEN_BUDGET_EXHAUSTED", "课件任务 token 总预算已耗尽")

        budgets = {
            "planner": int(getattr(settings, "courseware_planner_token_budget", 4096)),
            "scene": int(getattr(settings, "courseware_scene_composition_token_budget", 14336)),
            "quality_review": int(getattr(settings, "courseware_quality_review_token_budget", 4096)),
            "revision": int(getattr(settings, "courseware_revision_token_budget", 10240)),
        }
        used = {name: self._stage_tokens(traces, name) for name in self._STAGES}
        prior_credit = sum(max(0, budgets[name] - used[name]) for name in self._STAGES[: self._STAGES.index(stage)])
        future_reserve = 0
        quality_reserved = int(getattr(settings, "courseware_quality_review_reserved_tokens", 4096))
        revision_reserved = int(getattr(settings, "courseware_revision_reserved_tokens", 10240))
        if stage in {"planner", "scene"}:
            future_reserve = quality_reserved + revision_reserved
        elif stage == "quality_review":
            future_reserve = revision_reserved
        available = max(0, budgets[stage] + prior_credit - used[stage])
        remaining_total = max(0, total_token_budget - total_used - total_reserved - future_reserve)
        available = min(available, remaining_total)
        requested = requested_output_tokens or int(getattr(settings, "courseware_scene_call_max_tokens", 4096))
        estimated_input = max(1, int(estimated_input_tokens or getattr(settings, "courseware_llm_estimated_input_tokens", 1024)))
        # Stage allowance is an output cap; estimated input is accounted for
        # separately in the task-wide reservation and must not silently shrink
        # the public per-stage output limit.
        max_output = min(requested, available)
        if max_output < 256:
            return self._deny(stage, "stage", "COURSEWARE_STAGE_BUDGET_EXHAUSTED", "当前阶段剩余额度不足以发起安全模型调用")
        call_id = f"cwc_{run_id}_{stage}_{uuid4().hex[:12]}"
        stage_remaining = max(0.0, stage_limits[stage] - sum(
            float(item.get("duration_seconds") or 0) for item in reservations
            if item.get("stage") == stage
        ))
        timeout_seconds = min(float(getattr(settings, "courseware_llm_call_timeout_seconds", 30.0)), stage_remaining)
        if deadline is not None:
            timeout_seconds = min(timeout_seconds, max(0.0, (deadline - now).total_seconds()))
        if timeout_seconds < 0.25:
            return self._deny(stage, "task", "COURSEWARE_STAGE_TIMEOUT", "模型调用剩余时限不足")
        decision = BudgetDecision(True, int(max_output), None, call_id, estimated_input, timeout_seconds)
        self._reserve(run_id, stage, decision)
        return decision

    def reconcile(self, run_id: str, call_id: str | None, *, actual_input: int | None = None,
                  actual_output: int | None = None, status: str = "completed", trace: dict | None = None) -> None:
        if not call_id:
            return
        from .content_review.persistence import read_state, mutate_spec
        from .content_review.telemetry import latest_tickets, append_ticket
        state, _ = read_state(self.repo, run_id)
        if state is not None:
            def settle(spec):
                ledger = spec["content_review"]["ledger"]
                old = next(t for t in latest_tickets(ledger) if t["ticket_id"] == call_id)
                if old["status"] != "reserved":
                    return
                values = {k: v for k, v in old.items() if k not in {"record_hash", "prev_record_hash"}}
                known = actual_input is not None and actual_output is not None
                values.update(status="completed" if known else "unknown", actual_input=actual_input, actual_output=actual_output,
                    charged_tokens=actual_input + actual_output if known else old["charged_tokens"],
                    call_id=(trace or {}).get("llm_call_id"), attempts=min(3, len((trace or {}).get("llm_attempts") or []) or 1),
                    duration_ms=int((trace or {}).get("llm_duration_ms") or 0), error_code=None if status == "completed" else "model_unavailable")
                spec["content_review"]["ledger"] = append_ticket(ledger, values)
            mutate_spec(self.repo, run_id, settle)
            return
        payload = {"call_id": call_id, "status": status, "actual_input": actual_input,
                   "actual_output": actual_output, "finished_at": datetime.now(timezone.utc).isoformat()}
        self._append_event(run_id, "llm_reservation", "reconciled", payload)

    def _before_content(self, run_id, stage, state, requested, estimated, attempts, phase, input_hash):
        from .content_review.persistence import mutate_spec
        from .content_review.telemetry import latest_tickets, append_ticket
        from app.models.courseware.content_review import ContentReviewBlocked
        if stage not in self._STAGES:
            raise ContentReviewBlocked("unknown budget stage")
        requested, estimated = int(requested or 8192), int(estimated or 0)
        if requested < 1 or estimated < 1 or attempts not in {1, 2, 3}:
            raise ContentReviewBlocked("complete call estimate required")
        ticket_id = f"cwt_{uuid4().hex}"
        now = datetime.now(timezone.utc)
        timeout = 0.0
        def reserve(spec):
            nonlocal timeout
            current = spec["content_review"]; policy = state.policy; budget = policy.budget
            if current["execution_owner"] != state.execution_owner or not state.execution_owner:
                raise ContentReviewBlocked("budget execution lease mismatch")
            if datetime.fromisoformat(current["lease_until"]) <= now:
                raise ContentReviewBlocked("budget execution lease expired")
            ledger = current["ledger"]; tickets = latest_tickets(ledger)
            if len(ledger) >= 254:
                raise ContentReviewBlocked("ledger capacity exhausted")
            charged = sum(t["charged_tokens"] for t in tickets)
            used = {s: sum(t["charged_tokens"] for t in tickets if t["stage"] == s) for s in self._STAGES}
            future = budget.quality_reserve + budget.revision_reserve if stage in {"planner", "scene"} else budget.revision_reserve if stage == "quality_review" else 0
            credit = sum(max(0, budget.stage_tokens[s] - used[s]) for s in self._STAGES[:self._STAGES.index(stage)])
            allowance = min(budget.total_tokens - charged - future, budget.stage_tokens[stage] + credit - used[stage])
            reserve_tokens = (estimated + requested) * attempts
            if reserve_tokens > allowance:
                raise ContentReviewBlocked("call token budget exhausted")
            elapsed = sum(t["duration_ms"] for t in tickets if t["stage"] == stage) / 1000
            starts = [datetime.fromisoformat(t["started_at"]) for t in tickets if t["stage"] == stage]
            if starts:
                elapsed = max(elapsed, (now - min(starts)).total_seconds())
            timeout = min(budget.call_seconds, budget.stage_seconds[stage] - elapsed,
                          (datetime.fromisoformat(budget.deadline) - now).total_seconds())
            if timeout < .25:
                raise ContentReviewBlocked("call deadline/stage timeout")
            current["ledger"] = append_ticket(ledger, dict(ticket_id=ticket_id, stage=stage, phase=phase, status="reserved",
                input_reserved=estimated, output_reserved=requested, attempts_reserved=attempts, charged_tokens=reserve_tokens,
                input_hash=input_hash or "0"*64, started_at=now.isoformat()))
            # Reserve capacity for settlement before the provider starts.
            from app.models.courseware.content_review import canonical_json, MAX_SPEC_BYTES
            if len(canonical_json(spec).encode("utf-8")) + 4096 > MAX_SPEC_BYTES:
                raise ContentReviewBlocked("audit storage budget exhausted")
        try:
            mutate_spec(self.repo, run_id, reserve)
        except ContentReviewBlocked:
            return self._deny(stage, "task", "COURSEWARE_CONTENT_REVIEW_BUDGET", "冻结审核预算或时限不足")
        return BudgetDecision(True, requested, None, ticket_id, estimated, timeout)

    def bind_gateway(self, run_id, gateway, stage, phase, guard):
        return BudgetedCoursewareGateway(self, run_id, gateway, stage, phase, guard)

    def _reserve(self, run_id: str, stage: str, decision: BudgetDecision) -> None:
        payload = {"call_id": decision.call_id, "stage": stage, "estimated_input": decision.estimated_input_tokens,
                   "max_output": decision.max_output_tokens, "status": "reserved",
                   "started_at": datetime.now(timezone.utc).isoformat()}
        with self._reservation_lock:
            self._append_event(run_id, "llm_reservation", "reserved", payload)

    def _reservations(self, run_id: str) -> list[dict[str, Any]]:
        rows = []
        for event in self.repo.list_events(run_id):
            if event.get("stage") != "llm_reservation":
                continue
            payload = event.get("payload") or {}
            rows.append(payload)
        reconciled = {row.get("call_id"): row for row in rows if row.get("status") != "reserved"}
        return [row for row in rows if row.get("status") == "reserved" and row.get("call_id") not in reconciled]

    def _append_event(self, run_id: str, stage: str, status: str, payload: dict[str, Any]) -> None:
        method = getattr(self.repo, "append_event_once", None)
        if method:
            method(run_id, f"{stage}:{payload.get('call_id')}:{status}", stage, status, payload)

    def _traces(self, run_id: str) -> list[dict[str, Any]]:
        return [
            (event.get("payload") or {}).get("trace") or {}
            for event in self.repo.list_events(run_id)
            if event.get("stage") == "llm_observation"
        ]

    @staticmethod
    def _tokens(trace: dict[str, Any]) -> int:
        return int(trace.get("input_tokens") or 0) + int(trace.get("output_tokens") or 0)

    def _stage_tokens(self, traces: list[dict[str, Any]], stage: str) -> int:
        names = {
            "planner": {"courseware_spec_builder", "courseware_practice_structure_extractor"},
            "scene": {"courseware_scene_composer"},
            "quality_review": {"courseware_quality_reviewer"},
            "revision": {"courseware_scene_composer", "courseware_quality_reviewer"},
        }[stage]
        # Every workflow call records the coordinator stage explicitly.  This
        # avoids charging a revision re-review to the original generation
        # stage and makes the persisted accounting auditable after recovery.
        return sum(
            self._tokens(trace)
            for trace in traces
            if trace.get("node_name") in names
            and trace.get("budget_stage") == stage
        )

    @staticmethod
    def _deny(stage: str, scope: str, code: str, message: str) -> BudgetDecision:
        return BudgetDecision(False, 0, {
            "code": code, "message": message, "fallback_version": "deterministic-v1",
            "budget_scope": scope, "budget_stage": stage,
        })


class BudgetedCoursewareGateway:
    """One reservation for every actual structured request, including retries."""
    def __init__(self, coordinator, run_id, gateway, stage, phase, guard):
        self.coordinator, self.run_id, self.underlying_gateway = coordinator, run_id, gateway
        self.stage, self.phase, self.guard = stage, phase, guard

    def options_for(self, *args, **kwargs):
        return self.underlying_gateway.options_for(*args, **kwargs)

    def invoke_structured(self, *, messages, output_schema, context, options):
        from .content_review.persistence import read_state
        from .content_review.batching import resolve_estimator
        from .runtime import courseware_ai_available
        from app.models.courseware.content_review import ContentReviewBlocked, json_hash
        self.guard()
        if not courseware_ai_available(self.underlying_gateway):
            raise ContentReviewBlocked("underlying gateway disabled")
        state, _ = read_state(self.coordinator.repo, self.run_id)
        from .content_review.persistence import model_configuration_fingerprint
        if state.policy.model_fingerprint != model_configuration_fingerprint(self.coordinator.settings_provider()):
            raise ContentReviewBlocked("model configuration changed since creation")
        estimator = resolve_estimator(state.policy, self.underlying_gateway)
        input_tokens = estimator.count_input_upper_bound(messages, output_schema.model_json_schema(), options.structured_output_mode)
        # Every additional attempt can carry the bounded previous response,
        # validation error and schema-repair wrapper (gateway clips at 12000).
        if options.max_attempts > 1:
            from app.models.courseware.content_review import canonical_json
            repair_schema = canonical_json(output_schema.model_json_schema())
            input_tokens += estimator.count_output_upper_bound("x" * 48000 + repair_schema + "x" * 2048)
        if input_tokens + options.max_output_tokens > state.policy.context_tokens:
            raise ContentReviewBlocked("complete request exceeds context")
        decision = self.coordinator.before_call(self.run_id, self.stage, requested_output_tokens=options.max_output_tokens,
            estimated_input_tokens=input_tokens, attempts=options.max_attempts, phase=self.phase,
            input_hash=json_hash({"messages": [(m.type, m.content) for m in messages], "schema": output_schema.model_json_schema()}))
        if not decision.allowed:
            raise ContentReviewBlocked("model request denied before invocation")
        bounded = options.model_copy(update={"request_timeout_seconds": min(options.request_timeout_seconds, decision.timeout_seconds / options.max_attempts)})
        try:
            self.guard()
            result = self.underlying_gateway.invoke_structured(messages=messages, output_schema=output_schema, context=context, options=bounded)
        except BaseException as exc:
            trace = exc.trace_metadata() if callable(getattr(exc, "trace_metadata", None)) else {}
            self.guard()
            self.coordinator.reconcile(self.run_id, decision.call_id, actual_input=trace.get("input_tokens"), actual_output=trace.get("output_tokens"), status="failed", trace=trace)
            raise
        self.guard()
        trace = result.trace_metadata() if callable(getattr(result, "trace_metadata", None)) else {}
        self.coordinator.reconcile(self.run_id, decision.call_id, actual_input=trace.get("input_tokens"), actual_output=trace.get("output_tokens"), trace=trace)
        return result
