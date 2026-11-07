"""SQL round repository with explicit transaction and optimistic writes."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Callable, Iterator

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.feedback.round_base import BaseRoundRepository, MODELS, Record, RoundConflict, primary_key, validate_relation, validate_update, validate_record, validate_page, validate_complete_rounds


class SQLRoundRepository(BaseRoundRepository):
    def __init__(self, session_factory: Callable[[], Session], session: Session | None = None):
        self.session_factory = session_factory
        self._session = session
        self._touched_rounds: set[str] = set()

    @contextmanager
    def transaction(self) -> Iterator[SQLRoundRepository]:
        if self._session is not None:
            yield self
            return
        with self.session_factory() as db:
            try:
                if db.get_bind().dialect.name == "sqlite":
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                bound = SQLRoundRepository(self.session_factory, db)
                yield bound
                validate_complete_rounds(bound, bound._touched_rounds)
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise RoundConflict("ROUND_UNIQUENESS_CONFLICT") from error
            except BaseException:
                db.rollback()
                raise

    def find(self, table: str, **filters: Any) -> list[Record]:
        model = MODELS[table]
        unknown = set(filters) - set(model.__table__.columns.keys())
        if unknown:
            raise ValueError("unknown round filter")
        if self._session is None:
            with self.session_factory() as db:
                return self._read(db, model, filters)
        return self._read(self._session, model, filters)

    @staticmethod
    def _read(db: Session, model: Any, filters: Record) -> list[Record]:
        key = next(iter(model.__table__.primary_key.columns))
        return [deepcopy({column.name: getattr(row, column.name) for column in model.__table__.columns})
                for row in db.query(model).filter_by(**filters).order_by(key).all()]

    def list_rounds(self, learner_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Record], int]:
        validate_page(offset, limit)
        if self._session is None:
            with self.session_factory() as db:
                return SQLRoundRepository(self.session_factory, db).list_rounds(learner_id, offset, limit)
        model = MODELS["learning_rounds"]
        query = self._session.query(model).filter_by(learner_id=learner_id)
        total = query.count()
        rows = query.order_by(model.created_at.desc(), model.round_id.desc()).offset(offset).limit(limit).all()
        return [deepcopy({c.name: getattr(row, c.name) for c in model.__table__.columns}) for row in rows], total

    def insert(self, table: str, values: Record) -> Record:
        if self._session is None:
            raise RuntimeError("round writes require a transaction")
        validate_relation(self, table, values)
        if table in {"learning_rounds", "learning_round_nodes"}:
            self._touched_rounds.add(values["round_id"])
        model = MODELS[table]
        row = model(**deepcopy(values))
        self._session.add(row)
        self._session.flush()
        return self.one(table, **{primary_key(table): values[primary_key(table)]})

    def compare_and_set(self, table: str, identity: str, version: int, changes: Record) -> Record:
        if self._session is None:
            raise RuntimeError("round writes require a transaction")
        model = MODELS[table]
        validate_update(table, changes)
        current = self.one(table, **{primary_key(table): identity})
        if current is not None:
            validate_record(table, {**current, **changes})
        count = self._session.query(model).filter_by(**{
            primary_key(table): identity, "row_version": version,
        }).update({**deepcopy(changes), "row_version": version + 1}, synchronize_session=False)
        if count != 1:
            raise RoundConflict("ROUND_ROW_VERSION_CONFLICT")
        self._session.flush()
        self._session.expire_all()
        return self.one(table, **{primary_key(table): identity})

    def delete_learner(self, learner_id: str) -> None:
        if self._session is None:
            raise RuntimeError("round writes require a transaction")
        delete_round_facts(self._session, learner_id)


def delete_round_facts(db: Session, learner_id: str) -> None:
    """Join the caller's learner-deletion transaction; never commit here."""
    if not inspect(db.connection()).has_table("learning_rounds"):
        return
    rounds = db.query(MODELS["learning_rounds"].round_id).filter_by(learner_id=learner_id)
    members = db.query(MODELS["learning_round_nodes"].round_node_id).filter(MODELS["learning_round_nodes"].round_id.in_(rounds))
    stages = db.query(MODELS["learning_round_stages"].stage_id).filter(MODELS["learning_round_stages"].round_id.in_(rounds))
    stage_nodes = db.query(MODELS["learning_round_stage_nodes"].stage_node_id).filter(MODELS["learning_round_stage_nodes"].stage_id.in_(stages))
    selectors = {
        "learning_round_budget_reservations": ("stage_id", stages),
        "feedback_node_decisions": ("round_node_id", members),
        "learning_round_job_bindings": ("stage_node_id", stage_nodes),
        "learning_round_evaluation_sessions": ("stage_id", stages),
        "learning_round_stage_nodes": ("stage_id", stages),
        "learning_round_stages": ("round_id", rounds),
        "learning_round_nodes": ("round_id", rounds),
    }
    for table, (field, values) in selectors.items():
        model = MODELS[table]
        db.query(model).filter(getattr(model, field).in_(values)).delete(synchronize_session=False)
    db.query(MODELS["learner_remediation_needs"]).filter_by(learner_id=learner_id).delete(synchronize_session=False)
    # Self references must be cleared before deleting a learner's whole chain.
    db.query(MODELS["learning_rounds"]).filter_by(learner_id=learner_id).update({"parent_round_id": None}, synchronize_session=False)
    db.query(MODELS["learning_rounds"]).filter_by(learner_id=learner_id).delete(synchronize_session=False)
