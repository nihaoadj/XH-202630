"""Durable per-attempt reservations; unknown provider usage consumes its cap."""

from datetime import datetime, timezone

from app.core.llm.budget import LLMBudgetUnavailable
from app.db.feedback.round_base import BaseRoundRepository
from app.models.shared.llm import LLMCallContext, LLMUsage
from app.models.shared.persistence import canonical_hash


class RoundBudgetGuard:
    def __init__(self, repository: BaseRoundRepository):
        self.repository = repository

    def reserve(self, context: LLMCallContext, attempt: int, tokens: int, runtime_seconds: float = 0) -> str:
        scope = context.budget_scope
        if scope is None or tokens <= 0:
            raise LLMBudgetUnavailable("ROUND_BUDGET_INVALID_SCOPE")
        identity = "br_" + canonical_hash([scope.scope_id, context.call_id, attempt])[:48]
        with self.repository.transaction() as tx:
            previous = tx.one("learning_round_budget_reservations", reservation_id=identity)
            if previous:
                # A real provider dispatch must never reuse a spent attempt ID.
                raise LLMBudgetUnavailable("ROUND_BUDGET_ATTEMPT_ALREADY_RESERVED")
            table, key = (("learning_round_stage_nodes", "stage_node_id") if scope.kind == "production"
                          else ("learning_round_evaluation_sessions", "session_id"))
            owner = tx.one(table, **{key: scope.scope_id})
            if owner is None or owner["stage_id"] != scope.stage_id:
                raise LLMBudgetUnavailable("ROUND_BUDGET_SCOPE_NOT_FOUND")
            stage = tx.one("learning_round_stages", stage_id=scope.stage_id)
            limits = stage["budget_snapshot"].get("scopes", {})
            cap = limits.get(scope.scope_id)
            if not isinstance(cap, int) or cap <= 0:
                raise LLMBudgetUnavailable("ROUND_BUDGET_NOT_CONFIGURED")
            if scope.kind == "production":
                binding = tx.one("learning_round_job_bindings", run_id=context.run_id)
                if binding is None or binding["stage_node_id"] != scope.scope_id:
                    raise LLMBudgetUnavailable("ROUND_BUDGET_RUN_MISMATCH")
            reservations = tx.find("learning_round_budget_reservations", scope_id=scope.scope_id)
            if any(row["known_tokens"] is not None and row["known_tokens"] > row["reserved_tokens"] for row in reservations):
                raise LLMBudgetUnavailable("ROUND_BUDGET_OVERRUN")
            used = sum(row["known_tokens"] if row["state"] == "settled" else row["reserved_tokens"]
                       for row in reservations)
            seconds_cap = stage["budget_snapshot"].get("runtime_scopes", {}).get(scope.scope_id)
            used_seconds = sum(row["known_seconds"] if row["known_seconds"] is not None else row["reserved_seconds"]
                               for row in reservations)
            if runtime_seconds < 0 or (runtime_seconds > 0 and (seconds_cap is None or used_seconds + runtime_seconds > seconds_cap)):
                raise LLMBudgetUnavailable("ROUND_RUNTIME_BUDGET_EXHAUSTED")
            if used + tokens > cap:
                raise LLMBudgetUnavailable("ROUND_BUDGET_EXHAUSTED")
            # Serialize independent reservation identities on the shared owner
            # on PostgreSQL too; SQLite uses BEGIN IMMEDIATE for the same rule.
            fence = ({"budget_counters": {**owner["budget_counters"], "last_reserved_tokens": tokens}}
                     if scope.kind == "production" else {"grading_generation": owner["grading_generation"]})
            tx.compare_and_set(table, scope.scope_id, owner["row_version"], fence)
            now = datetime.now(timezone.utc)
            tx.insert("learning_round_budget_reservations", dict(
                reservation_id=identity, stage_id=scope.stage_id, scope_id=scope.scope_id,
                stage_node_id=scope.scope_id if scope.kind == "production" else None,
                session_id=scope.scope_id if scope.kind == "assessment" else None,
                run_id=context.run_id if scope.kind == "production" else None,
                call_id=context.call_id, gateway_attempt=attempt, reserved_tokens=tokens,
                reserved_seconds=runtime_seconds,
                state="reserved", created_at=now, updated_at=now,
            ))
        return identity

    def settle(self, reservation_id: str, usage: LLMUsage | None, runtime_seconds: float | None = None) -> None:
        # Settlement uses the reservation row version; owner CAS serializes
        # independent reserve attempts before transport dispatch.
        with self.repository.transaction() as tx:
            row = tx.one("learning_round_budget_reservations", reservation_id=reservation_id)
            if row is None:
                raise LLMBudgetUnavailable("ROUND_BUDGET_RESERVATION_NOT_FOUND")
            if row["state"] != "reserved":
                return
            # Persist settlement via the repository's versioned write boundary.
            total = None
            if usage is not None and usage.input_tokens is not None and usage.output_tokens is not None:
                total = usage.input_tokens + usage.output_tokens
            tx.compare_and_set("learning_round_budget_reservations", reservation_id, row["row_version"], {
                "state": "unknown" if total is None else "settled", "known_tokens": total,
                "known_seconds": runtime_seconds,
                "updated_at": datetime.now(timezone.utc),
            })
