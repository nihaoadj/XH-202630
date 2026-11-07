"""Fixed learning-round storage identities and transactional repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any

from app.db.feedback.round_models import ROUND_MODELS

Record = dict[str, Any]
MODELS = {model.__tablename__: model for model in ROUND_MODELS}


class RoundConflict(ValueError):
    """A unique identity or row version no longer matches the caller."""


class BaseRoundRepository(ABC):
    """Storage access only; services own authorization and business decisions.

    Table identifiers are restricted to MODELS, filters are equality-only and
    all returned rows are detached copies. Writes require transaction().
    """

    @abstractmethod
    def transaction(self) -> AbstractContextManager[BaseRoundRepository]: ...

    @abstractmethod
    def find(self, table: str, **filters: Any) -> list[Record]: ...

    @abstractmethod
    def insert(self, table: str, values: Record) -> Record: ...

    @abstractmethod
    def compare_and_set(self, table: str, identity: str, version: int, changes: Record) -> Record: ...

    @abstractmethod
    def delete_learner(self, learner_id: str) -> None: ...

    def one(self, table: str, **filters: Any) -> Record | None:
        rows = self.find(table, **filters)
        if len(rows) > 1:
            raise RoundConflict("ROUND_IDENTITY_NOT_UNIQUE")
        return rows[0] if rows else None

    @abstractmethod
    def list_rounds(self, learner_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Record], int]: ...


def validate_relation(repository: BaseRoundRepository, table: str, row: Record) -> None:
    """Cross-table identities not expressible with the existing single FKs."""
    validate_record(table, row)
    if table == "learning_rounds" and row.get("parent_round_id"):
        parent = repository.one(table, round_id=row["parent_round_id"])
        if not parent or (parent["learner_id"], parent["knowledge_base_id"]) != (row["learner_id"], row["knowledge_base_id"]):
            raise RoundConflict("ROUND_PARENT_OWNER_MISMATCH")
    elif table == "learning_round_nodes":
        parent = repository.one("learning_rounds", round_id=row["round_id"])
        if parent is None or ((parent["protocol_version"] == "legacy-correction/v1") != (row["role"] == "legacy")):
            raise RoundConflict("ROUND_ROLE_PROTOCOL_MISMATCH")
        if len(repository.find(table, round_id=row["round_id"])) >= 2:
            raise RoundConflict("ROUND_MEMBER_LIMIT")
    elif table == "learning_round_stage_nodes":
        stage = repository.one("learning_round_stages", stage_id=row["stage_id"])
        member = repository.one("learning_round_nodes", round_node_id=row["round_node_id"])
        if not stage or not member or stage["round_id"] != member["round_id"]:
            raise RoundConflict("ROUND_STAGE_MEMBER_MISMATCH")
        parent = repository.one("learning_rounds", round_id=member["round_id"])
        if row.get("batch_id") is None and not (
            parent["protocol_version"] == "legacy-correction/v1" and stage["kind"] == "initial"
        ):
            raise RoundConflict("ROUND_BATCH_REQUIRED")


def validate_update(table: str, changes: Record) -> None:
    immutable = {primary_key(table), "row_version", "round_id", "round_node_id", "stage_id",
                 "stage_node_id", "learner_id", "knowledge_base_id", "skill_node_id", "role",
                 "protocol_version", "source_attempt_id", "parent_round_id", "batch_id"}
    if set(changes) & immutable or set(changes) - set(MODELS[table].__table__.columns.keys()):
        raise ValueError("round identities are immutable")


def validate_record(table: str, row: Record) -> None:
    """Shared SQL/Memory checks; SQL also retains physical CHECK constraints."""
    choices = {
        "learning_rounds": {"protocol_version": {"learning-round/v1", "legacy-correction/v1"}},
        "learning_round_nodes": {"role": {"primary", "review", "legacy"}},
        "learning_round_stages": {"kind": {"initial", "correction"}, "state": {"producing", "awaiting_assessment", "completed"}},
        "learning_round_job_bindings": {"relation_kind": {"production", "append", "retry"}},
        "learning_round_evaluation_sessions": {"grading_state": {"idle", "grading", "submitted"}},
        "learner_remediation_needs": {"status": {"remediate", "practice", "resolved"}},
        "learning_round_budget_reservations": {"state": {"reserved", "settled", "unknown"}},
    }
    for key, allowed in choices.get(table, {}).items():
        value = row.get(key, "idle" if key == "grading_state" else None)
        if value not in allowed:
            raise RoundConflict("ROUND_INVALID_STATE")
    if table == "learning_round_stages":
        if (row["kind"] == "initial" and row["ordinal"] != 0) or (row["kind"] == "correction" and row["ordinal"] <= 0):
            raise RoundConflict("ROUND_INVALID_ORDINAL")
    if table == "learning_round_evaluation_sessions":
        if (row.get("grading_state", "idle") == "submitted") != (row.get("attempt_id") is not None):
            raise RoundConflict("ROUND_INVALID_SUBMISSION_STATE")
    for key in ("score", "last_score"):
        if key in row and not (0 <= row[key] <= 1):
            raise RoundConflict("ROUND_INVALID_SCORE")
    for key in ("wait_rounds", "reserved_tokens", "known_tokens", "recovery_count"):
        if row.get(key) is not None and row[key] < 0:
            raise RoundConflict("ROUND_NEGATIVE_COUNTER")
    if table == "learning_round_budget_reservations":
        if (row.get("stage_node_id") is None) == (row.get("session_id") is None) or row["gateway_attempt"] <= 0:
            raise RoundConflict("ROUND_INVALID_BUDGET_SCOPE")


def validate_page(offset: int, limit: int) -> None:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid round pagination")


def validate_complete_rounds(repository: BaseRoundRepository, identities: set[str]) -> None:
    for identity in identities:
        parent = repository.one("learning_rounds", round_id=identity)
        if parent is None:
            continue
        members = repository.find("learning_round_nodes", round_id=identity)
        roles = [member["role"] for member in members]
        if not 1 <= len(roles) <= 2 or (
            parent["protocol_version"] == "learning-round/v1" and roles.count("primary") != 1
        ):
            raise RoundConflict("ROUND_INCOMPLETE_MEMBERS")


def primary_key(table: str) -> str:
    return next(iter(MODELS[table].__table__.primary_key.columns)).name
