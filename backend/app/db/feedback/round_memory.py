"""In-memory round facts with serialized transactions and snapshot rollback."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from typing import Any, Iterator

from app.db.feedback.round_base import BaseRoundRepository, MODELS, Record, RoundConflict, primary_key, validate_relation, validate_update, validate_record, validate_page, validate_complete_rounds


class MemoryRoundRepository(BaseRoundRepository):
    def __init__(self):
        self._rows: dict[str, dict[str, Record]] = {table: {} for table in MODELS}
        self._lock = RLock()
        self._depth = 0
        self._touched_rounds: set[str] = set()

    @contextmanager
    def transaction(self) -> Iterator[MemoryRoundRepository]:
        with self._lock:
            snapshot = deepcopy(self._rows)
            touched = self._touched_rounds.copy()
            self._depth += 1
            try:
                yield self
                if self._depth == 1:
                    validate_complete_rounds(self, self._touched_rounds)
            except BaseException:
                self._rows = snapshot
                self._touched_rounds = touched
                raise
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._touched_rounds = touched

    def find(self, table: str, **filters: Any) -> list[Record]:
        model = MODELS[table]
        if set(filters) - set(model.__table__.columns.keys()):
            raise ValueError("unknown round filter")
        with self._lock:
            return [deepcopy(row) for _, row in sorted(self._rows[table].items())
                    if all(row.get(key) == value for key, value in filters.items())]

    def list_rounds(self, learner_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Record], int]:
        validate_page(offset, limit)
        rows = sorted(self.find("learning_rounds", learner_id=learner_id),
                      key=lambda row: (row["created_at"].timestamp(), row["round_id"]), reverse=True)
        return rows[offset:offset + limit], len(rows)

    def _validate(self, table: str, row: Record, replacing: str | None = None) -> None:
        """Match SQL uniqueness, nullable indexes and domain FKs owned here."""
        validate_record(table, row)
        columns = MODELS[table].__table__.columns
        if set(row) - set(columns.keys()):
            raise ValueError("unknown round field")
        for column in columns:
            if not column.nullable and row.get(column.name) is None:
                raise RoundConflict("ROUND_REQUIRED_FIELD")
            for fk in column.foreign_keys:
                parent_table, parent_key = fk.target_fullname.split(".")
                if parent_table in MODELS and row.get(column.name) is not None:
                    if self.one(parent_table, **{parent_key: row[column.name]}) is None:
                        raise RoundConflict("ROUND_FOREIGN_KEY")
        unique = {
            "learning_rounds": [("learner_id", "selection_key"), ("learner_id", "protocol_version", "source_attempt_id")],
            "learning_round_nodes": [("round_id", "skill_node_id")],
            "learning_round_stages": [("round_id", "ordinal"), ("round_id", "selection_key")],
            "learning_round_stage_nodes": [("stage_id", "round_node_id"), ("batch_id",), ("round_node_id", "source_attempt_id")],
            "learning_round_evaluation_sessions": [("stage_id",), ("attempt_id",)],
            "feedback_node_decisions": [("attempt_id", "round_node_id")],
            "learner_remediation_needs": [("learner_id", "knowledge_base_id", "skill_node_id")],
            "learning_round_budget_reservations": [("scope_id", "call_id", "gateway_attempt")],
        }.get(table, [])
        if table == "learning_rounds" and row["protocol_version"] == "learning-round/v1":
            unique = [*unique, ("parent_round_id",)]
        if table == "learning_round_nodes" and row["role"] in {"primary", "review"}:
            unique = [*unique, ("round_id", "role")]
        for identity, other in self._rows[table].items():
            if identity == replacing:
                continue
            for fields in unique:
                if all(row.get(key) is not None for key in fields) and all(row[key] == other.get(key) for key in fields):
                    raise RoundConflict("ROUND_UNIQUENESS_CONFLICT")

    def insert(self, table: str, values: Record) -> Record:
        with self._lock:
            if not self._depth:
                raise RuntimeError("round writes require a transaction")
            row = deepcopy(values)
            for column in MODELS[table].__table__.columns:
                if column.name not in row:
                    if column.default is not None:
                        row[column.name] = column.default.arg(None) if column.default.is_callable else deepcopy(column.default.arg)
                    elif column.nullable:
                        row[column.name] = None
            key = row[primary_key(table)]
            if key in self._rows[table]:
                raise RoundConflict("ROUND_UNIQUENESS_CONFLICT")
            validate_relation(self, table, row)
            if table in {"learning_rounds", "learning_round_nodes"}:
                self._touched_rounds.add(row["round_id"])
            self._validate(table, row)
            self._rows[table][key] = row
            return deepcopy(row)

    def compare_and_set(self, table: str, identity: str, version: int, changes: Record) -> Record:
        with self._lock:
            if not self._depth:
                raise RuntimeError("round writes require a transaction")
            validate_update(table, changes)
            row = self._rows[table].get(identity)
            if row is None or row.get("row_version") != version:
                raise RoundConflict("ROUND_ROW_VERSION_CONFLICT")
            updated = {**row, **deepcopy(changes), "row_version": version + 1}
            self._validate(table, updated, replacing=identity)
            self._rows[table][identity] = updated
            return deepcopy(updated)

    def delete_learner(self, learner_id: str) -> None:
        with self._lock:
            if not self._depth:
                raise RuntimeError("round writes require a transaction")
            rounds = {row["round_id"] for row in self.find("learning_rounds", learner_id=learner_id)}
            members = {row["round_node_id"] for row in self.find("learning_round_nodes") if row["round_id"] in rounds}
            stages = {row["stage_id"] for row in self.find("learning_round_stages") if row["round_id"] in rounds}
            stage_nodes = {row["stage_node_id"] for row in self.find("learning_round_stage_nodes") if row["stage_id"] in stages}
            for table, rows in self._rows.items():
                for key, row in list(rows.items()):
                    if (row.get("learner_id") == learner_id or row.get("round_id") in rounds
                            or row.get("stage_id") in stages or row.get("round_node_id") in members
                            or row.get("stage_node_id") in stage_nodes):
                        del rows[key]
