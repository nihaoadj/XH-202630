"""SQLAlchemy 诊断记录仓库。"""
from __future__ import annotations

import hashlib
from typing import Callable, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.models import DiagnosticAnswerORM, KnowledgeStateORM
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
