"""诊断仓储的 SQLAlchemy 实现。"""
from __future__ import annotations

import hashlib
from typing import Callable, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.extended_models import DiagnosticRunORM
from app.db.models import DiagnosticAnswerORM, KnowledgeStateORM
from app.models.history_schemas import DiagnosticRunRecord
from app.models.schemas import DiagnosticAnswerRecord, KnowledgeState


def _stable_id(prefix: str, *parts: object) -> str:
    text = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]}"


class SQLDiagnosisRepository(BaseDiagnosisRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
    ) -> None:
        with self.session_factory() as db:
            for answer in answers:
                previous_attempt = (
                    db.query(func.max(DiagnosticAnswerORM.attempt_no))
                    .filter_by(learner_id=learner_id, question_id=answer.question_id)
                    .scalar()
                    or 0
                )
                attempt_no = previous_attempt + 1
                db.add(
                    DiagnosticAnswerORM(
                        answer_id=_stable_id("diag_answer", learner_id, answer.question_id, attempt_no),
                        learner_id=learner_id,
                        question_id=answer.question_id,
                        knowledge_base_id=knowledge_base_id,
                        attempt_no=attempt_no,
                        answer=answer.answer,
                        is_correct=answer.correct,
                        score=answer.score,
                    )
                )

            for skill_node_id, state in knowledge_states.items():
                row = (
                    db.query(KnowledgeStateORM)
                    .filter_by(
                        learner_id=learner_id,
                        knowledge_base_id=knowledge_base_id,
                        skill_node_id=skill_node_id,
                    )
                    .first()
                )
                values = {
                    "mastery_score": state.score,
                    "status": state.status,
                    "evidence": state.evidence,
                }
                if row is None:
                    db.add(
                        KnowledgeStateORM(
                            state_id=_stable_id("knowledge_state", learner_id, knowledge_base_id, skill_node_id),
                            learner_id=learner_id,
                            knowledge_base_id=knowledge_base_id,
                            skill_node_id=skill_node_id,
                            **values,
                        )
                    )
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            db.commit()

    def save_run(self, run: DiagnosticRunRecord) -> None:
        with self.session_factory() as db:
            db.add(
                DiagnosticRunORM(
                    diagnostic_result_id=run.diagnostic_result_id,
                    learner_id=run.learner_id,
                    knowledge_base_id=run.knowledge_base_id,
                    ability_level=run.ability_level,
                    weak_points=run.weak_points,
                    strong_points=run.strong_points,
                    knowledge_states_snapshot=run.knowledge_states_snapshot,
                    recommended_path=run.recommended_path,
                    raw_result=run.raw_result,
                )
            )
            db.commit()

    def list_runs_by_learner(self, learner_id: str) -> list[DiagnosticRunRecord]:
        with self.session_factory() as db:
            rows = (
                db.query(DiagnosticRunORM)
                .filter_by(learner_id=learner_id)
                .order_by(DiagnosticRunORM.created_at.desc())
                .all()
            )
        return [
            DiagnosticRunRecord(
                diagnostic_result_id=row.diagnostic_result_id,
                learner_id=row.learner_id,
                knowledge_base_id=row.knowledge_base_id,
                ability_level=row.ability_level,
                weak_points=row.weak_points or [],
                strong_points=row.strong_points or [],
                knowledge_states_snapshot=row.knowledge_states_snapshot or {},
                recommended_path=row.recommended_path or [],
                raw_result=row.raw_result or {},
                created_at=row.created_at,
            )
            for row in rows
        ]
