"""LangGraph node wrapper that persists Step lifecycle around side effects."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.core.errors import ApplicationError, ErrorCode
from app.config import get_settings
from app.db.audit.base import BaseAuditRepository, PersistenceConflict, PersistenceError
from app.models.agent_contracts import (
    bind_recorded_step_context,
    reset_recorded_step_context,
    workflow_budget_metadata,
)
from app.models.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    PersistedEvidenceSnapshot,
)


NODE_METADATA: dict[str, tuple[str, str]] = {
    "diagnose": ("diagnosis", "学情诊断"),
    "retrieve": ("retriever", "知识证据检索"),
    "evidence_gate": ("evidence_gate", "事实生成证据门禁"),
    "plan": ("planner", "学习路径规划"),
    "generate": ("generator", "个性化资源生成"),
    "review": ("reviewer", "审核纠偏"),
    "prepare_revision": ("supervisor", "准备返工"),
    "finalize_draft": ("supervisor", "草稿终结"),
    "claim_extract": ("claim_extractor", "独立 Claim 抽取"),
    "claim_judge": ("claim_judge", "冻结证据 Claim 判定"),
    "claim_decide": ("claim_supervisor", "Claim 确定性决策"),
    "finalize": ("supervisor", "协同决策"),
    "finalize_evidence_insufficient": ("supervisor", "证据不足终结"),
}


def _persistence_failure(exc: Exception) -> ApplicationError:
    code = (
        ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
        if isinstance(exc, PersistenceConflict)
        else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
    )
    return ApplicationError(code, status_code=409 if isinstance(exc, PersistenceConflict) else 503)


class RecordedNode:
    def __init__(
        self,
        node_name: str,
        node: Callable[[dict[str, Any]], dict[str, Any]],
        repository: BaseAuditRepository,
    ):
        self.node_name = node_name
        self.node = node
        self.repository = repository

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        run_id = str(state["run_id"])
        step_id = str(uuid.uuid4())
        sequence = len(state.get("trace", [])) + 1
        attempt = int(state.get("generation_attempt", 1))
        if self.node_name == "prepare_revision":
            attempt += 1
        started_at = datetime.now(timezone.utc)
        agent_name, action = NODE_METADATA.get(
            self.node_name,
            (self.node_name, self.node_name),
        )
        context = {
            "step_id": step_id,
            "sequence": sequence,
            "attempt": attempt,
            "started_at": started_at,
            "node_name": self.node_name,
        }
        try:
            self.repository.begin_step(
                BeginStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    step_sequence=sequence,
                    node_name=self.node_name,
                    agent_name=agent_name,
                    action=action,
                    generation_attempt=attempt,
                    started_at=started_at,
                    lease_expires_at=started_at + timedelta(
                        seconds=get_settings().workflow_run_lease_seconds
                    ),
                )
            )
        except Exception as exc:
            raise _persistence_failure(exc) from exc

        token = bind_recorded_step_context(context)
        try:
            output = self.node(state)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            error_code = (
                exc.code.value if isinstance(exc, ApplicationError) else ErrorCode.INTERNAL_ERROR.value
            )
            failed_trace = {
                "schema_version": state.get("schema_version", "1.0"),
                "run_id": run_id,
                "step_id": step_id,
                "sequence": sequence,
                "attempt": attempt,
                "agent_name": agent_name,
                "node_name": self.node_name,
                "action": action,
                "status": "failed",
                "input_summary": "节点输入已通过契约校验",
                "output_summary": "节点执行失败",
                "decision_reason": "节点异常终止；原始异常未持久化。",
                "error_code": error_code,
                "error_message": "工作流步骤执行失败",
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                **workflow_budget_metadata(state, started_at),
            }
            try:
                self.repository.complete_step(
                    CompleteStepCommand(
                        run_id=run_id,
                        step_id=step_id,
                        trace=failed_trace,
                        ended_at=ended_at,
                    )
                )
            except Exception as persistence_exc:
                raise _persistence_failure(persistence_exc) from persistence_exc
            raise
        finally:
            reset_recorded_step_context(token)

        trace_items = output.get("trace", []) if isinstance(output, dict) else []
        trace = next(
            (
                dict(item)
                for item in reversed(trace_items)
                if isinstance(item, dict) and item.get("step_id") == step_id
            ),
            None,
        )
        if trace is None:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=500)
        evidence = [
            PersistedEvidenceSnapshot.from_evidence(
                item,
                run_id=run_id,
                retrieval_step_id=step_id,
            )
            for item in output.get("retrieved_evidence", [])
        ]
        try:
            self.repository.complete_step(
                CompleteStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    trace=trace,
                    evidence=evidence,
                    ended_at=datetime.now(timezone.utc),
                )
            )
        except Exception as exc:
            raise _persistence_failure(exc) from exc
        return output


def recorded_node(
    node_name: str,
    node: Callable[[dict[str, Any]], dict[str, Any]],
    repository: BaseAuditRepository | None,
):
    return RecordedNode(node_name, node, repository) if repository is not None else node
