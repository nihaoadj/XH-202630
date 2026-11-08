"""Per-attempt budget authorisation for Claim evidence retrieval.

The ledger is the only authority.  A transport send may happen only after a CAS
reservation of ``estimated_input + max_output``; unknown usage is charged at the
reserved amount and never rewritten to zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.claim.supplement import (
    BaseClaimSupplementRepository,
    SupplementBudgetExceeded,
    SupplementRunLedger,
)
from app.core.llm.budget import LLMBudgetUnavailable
from app.core.llm.gateway import LLMGatewayError
from app.core.security.errors import ErrorCode
from app.models.shared.agent_contracts import make_error_info
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceAttemptStatus,
    ClaimEvidenceRetrievalPolicyV1,
    attempt_id_for,
)


class SupplementUnavailable(RuntimeError):
    """A bounded, expected failure that keeps round 0 intact."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SupplementDeadline:
    started_at: datetime
    deadline_at: datetime

    @property
    def remaining_seconds(self) -> float:
        return (self.deadline_at - datetime.now(timezone.utc)).total_seconds()


def compute_deadline(
    *,
    first_started_at: datetime,
    workflow_deadline_at: datetime | None,
    policy: ClaimEvidenceRetrievalPolicyV1,
    now: datetime | None = None,
) -> datetime:
    """``min(first + wall, workflow - reserve)``; never extends the workflow."""

    now = now or first_started_at
    wall = first_started_at + timedelta(seconds=policy.max_wall_seconds)
    if workflow_deadline_at is None:
        return wall
    workflow = workflow_deadline_at
    if workflow.tzinfo is None:
        workflow = workflow.replace(tzinfo=timezone.utc)
    reserved = workflow - timedelta(seconds=policy.downstream_reserve_seconds)
    return min(wall, reserved)


class SupplementBudget:
    def __init__(
        self,
        *,
        repository: BaseClaimSupplementRepository,
        ledger: SupplementRunLedger,
        policy: ClaimEvidenceRetrievalPolicyV1,
        owner: str,
        epoch: int,
    ):
        self.repository = repository
        self.ledger = ledger
        self.policy = policy
        self.owner = owner
        self.epoch = epoch

    @property
    def deadline_at(self) -> datetime:
        return self.ledger.deadline_at

    def remaining_seconds(self, now: datetime | None = None) -> float:
        return (self.deadline_at - (now or utcnow())).total_seconds()

    def require_window(self, minimum_seconds: float = 5.0) -> None:
        if self.remaining_seconds() <= minimum_seconds:
            raise SupplementBudgetExceeded("supplement deadline exhausted")

    def begin_logical_call(self) -> None:
        """Count one logical call under CAS; a retry never opens a new one."""

        self.ledger = self.repository.count_logical_call(
            run_id=self.ledger.run_id,
            owner=self.owner,
            epoch=self.epoch,
            now=utcnow(),
        )


class SupplementAttemptObserver:
    """Reserve immediately before the real send, settle immediately after."""

    def __init__(
        self,
        *,
        budget: SupplementBudget,
        batch_id: str,
        logical_call_id: str,
        attempt_no: int,
        estimated_input_tokens: int,
        output_cap: int,
    ):
        self.budget = budget
        self.batch_id = batch_id
        self.logical_call_id = logical_call_id
        self.attempt_no = attempt_no
        self.estimated_input_tokens = estimated_input_tokens
        self.output_cap = output_cap
        self.attempt_id = attempt_id_for(
            batch_id=batch_id, logical_call_id=logical_call_id, attempt_no=attempt_no,
        )
        self.reserved = False
        self.dispatched = False
        self.settled = False

    def before_attempt(
        self, context, attempt, prepared_messages, output_schema, mode,
        max_output_tokens, timeout_seconds,
    ):
        remaining = self.budget.remaining_seconds()
        if remaining <= 1.0:
            raise SupplementBudgetExceeded("supplement deadline exhausted")
        if timeout_seconds > remaining:
            # The gateway receives the shortened value; a transport timeout can
            # never extend the frozen wall clock.
            raise SupplementBudgetExceeded("supplement attempt would exceed the deadline")
        reserved = self.estimated_input_tokens + int(max_output_tokens)
        self.budget.ledger = self.budget.repository.reserve_attempt(
            run_id=self.budget.ledger.run_id,
            owner=self.budget.owner,
            epoch=self.budget.epoch,
            reserved_tokens=reserved,
            attempt_id=self.attempt_id,
            batch_id=self.batch_id,
            logical_call_id=self.logical_call_id,
            attempt_no=self.attempt_no,
            output_cap=int(max_output_tokens),
            now=utcnow(),
        )
        self.reserved = True
        return self.attempt_id

    def on_dispatch(self, ticket) -> None:
        """Persist the send boundary immediately before the transport call."""

        if not self.reserved or self.settled or self.dispatched:
            return
        self.budget.ledger = self.budget.repository.mark_dispatched(
            run_id=self.budget.ledger.run_id,
            attempt_id=self.attempt_id,
            owner=self.budget.owner,
            epoch=self.budget.epoch,
            now=utcnow(),
        )
        self.dispatched = True

    def on_attempt_not_sent(self, ticket, exception) -> None:
        """Release a reservation only when dispatch is provably not started."""

        if not self.reserved or self.settled:
            return
        if self.dispatched:
            # The intent was committed; treat as an unknown-usage failure rather
            # than pretending the provider was never called.
            self._settle(ClaimEvidenceAttemptStatus.FAILED, None)
            return
        self._settle(ClaimEvidenceAttemptStatus.NOT_SENT, None)

    def _settle(self, status: ClaimEvidenceAttemptStatus, known_tokens: int | None) -> None:
        self.budget.ledger = self.budget.repository.settle_attempt(
            run_id=self.budget.ledger.run_id,
            attempt_id=self.attempt_id,
            owner=self.budget.owner,
            epoch=self.budget.epoch,
            status=status,
            known_tokens=known_tokens,
            now=utcnow(),
        )
        self.settled = True

    def after_attempt(self, ticket, raw_response, elapsed_ms) -> bool:
        usage = getattr(raw_response, "usage", None)
        known = (
            usage is not None
            and usage.input_tokens is not None
            and usage.output_tokens is not None
            and usage.total_tokens == usage.input_tokens + usage.output_tokens
        )
        if not self.dispatched:
            # A response can only exist after the transport was entered; record
            # the intent defensively so the settlement transition stays legal.
            self.on_dispatch(ticket)
        self._settle(
            ClaimEvidenceAttemptStatus.SUCCEEDED if known
            else ClaimEvidenceAttemptStatus.USAGE_UNKNOWN,
            usage.total_tokens if known else None,
        )
        return False

    def on_attempt_error(self, ticket, exception, elapsed_ms) -> bool:
        if self.settled:
            return False
        if not self.dispatched:
            # Every local pre-check refused before the send boundary.  This is
            # the only class of failure that may release the token reservation.
            self._settle(ClaimEvidenceAttemptStatus.NOT_SENT, None)
            return False
        self._settle(ClaimEvidenceAttemptStatus.FAILED, None)
        return False


def estimated_input_tokens(messages: list[Any], schema) -> int:
    from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.queries import (
        estimate_tokens,
    )

    text = "\n".join(str(getattr(item, "content", "")) for item in messages)
    return estimate_tokens(text) + estimate_tokens(str(schema.model_json_schema()))


def _truncated_result_error(result, attempt_no: int) -> LLMGatewayError:
    """Turn a schema-valid but length-terminated answer into the normal failure.

    A provider can stop exactly at a valid JSON boundary; parsing alone cannot
    prove the answer was complete.  Only callers that froze a larger retry cap
    opt into this stricter reading, so no other node silently gains a retry.
    """

    return LLMGatewayError(
        error=make_error_info(
            ErrorCode.LLM_OUTPUT_TRUNCATED,
            source="claim_evidence_retrieval",
            attempt=attempt_no,
            category="parse",
            safe_detail="finish_reason_length",
        ),
        call_id=getattr(result, "call_id", f"attempt-{attempt_no}"),
        retry_count=getattr(result, "retry_count", 0),
        latency_ms=getattr(result, "latency_ms", 0),
        attempts=list(getattr(result, "attempts", []) or []),
        finish_reason="length",
        model_name=getattr(result, "model_name", None),
        usage=getattr(result, "usage", None),
    )


def call_with_budget(
    *,
    gateway,
    budget: SupplementBudget,
    batch_id: str,
    logical_call_id: str,
    messages: list[Any],
    output_schema,
    output_cap: int,
    context_factory,
    estimated_input: int,
    max_attempts: int,
    truncated_output_cap: int | None = None,
) -> tuple[Any, int]:
    """Run up to ``max_attempts`` bounded sends for one logical call."""

    last_error: Exception | None = None
    active_cap = output_cap
    upgraded = False
    for attempt_no in range(1, max_attempts + 1):
        budget.require_window()
        observer = SupplementAttemptObserver(
            budget=budget,
            batch_id=batch_id,
            logical_call_id=logical_call_id,
            attempt_no=attempt_no,
            estimated_input_tokens=estimated_input,
            output_cap=active_cap,
        )
        options = gateway.options_for(
            "claim_evidence_retrieval",
            temperature=0.0,
            max_output_tokens=active_cap,
            request_timeout_seconds=min(
                budget.policy.attempt_timeout_seconds,
                max(1.0, budget.remaining_seconds() - 0.5),
            ),
        ).model_copy(update={
            "max_attempts": 1,
            "allow_schema_repair": False,
            "allow_text_fallback": False,
        })
        try:
            result = gateway.invoke_structured(
                messages=messages,
                output_schema=output_schema,
                context=context_factory(attempt_no),
                options=options,
                attempt_observer=observer,
            )
            if truncated_output_cap is not None and getattr(result, "finish_reason", None) == "length":
                # A complete-looking JSON can still have been cut at a valid
                # boundary.  Treat it as the same truncation the exception path
                # reports, so the single upgrade rule applies to both shapes.
                raise _truncated_result_error(result, attempt_no)
            return result, attempt_no
        except SupplementBudgetExceeded:
            raise
        except LLMBudgetUnavailable:
            # The upper production/round scope refused this call; the observer
            # has already settled it as not sent.  Retrying would only re-run the
            # same rejected reservation.
            raise
        except LLMGatewayError as exc:
            # Only a provider/transport/structured-output failure is retried.
            # A programming or contract error must surface immediately instead
            # of burning the remaining attempts on the same bug.
            last_error = exc
            if exc.error.code == ErrorCode.LLM_OUTPUT_TRUNCATED and truncated_output_cap is not None:
                if upgraded or truncated_output_cap <= active_cap:
                    break
                active_cap = truncated_output_cap
                upgraded = True
            continue
        except Exception:
            raise
    assert last_error is not None
    raise last_error


__all__ = [
    "SupplementAttemptObserver",
    "SupplementBudget",
    "SupplementBudgetExceeded",
    "SupplementDeadline",
    "SupplementUnavailable",
    "call_with_budget",
    "compute_deadline",
    "estimated_input_tokens",
    "utcnow",
]
