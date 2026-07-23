"""SQLAlchemy 实现的学习反馈仓库"""
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.db.feedback.base import BaseFeedbackRepository
from app.db.models import FeedbackRecordORM
from app.models.schemas import FeedbackAnswer, FeedbackRecord, KnowledgeState


def _orm_to_pydantic(orm: FeedbackRecordORM) -> FeedbackRecord:
    """将 ORM 对象转换为 Pydantic 模型"""
    return FeedbackRecord(
        feedback_id=orm.feedback_id,
        learner_id=orm.learner_id,
        resource_id=orm.resource_id,
        correct_rate=orm.correct_rate,
        decision=orm.decision,
        answers=[FeedbackAnswer(**item) for item in (orm.answers or [])],
        feedback_type=orm.feedback_type,
        time_spent_seconds=orm.time_spent_seconds,
        completed=orm.completed,
        self_rating=orm.self_rating,
        practice_result=orm.practice_result or {},
        decision_reason=orm.decision_reason,
        next_action=orm.next_action,
        recommended_topics=orm.recommended_topics or [],
        updated_knowledge_states={
            key: KnowledgeState(**value)
            for key, value in (orm.updated_knowledge_states or {}).items()
        },
        regenerate_suggestion=orm.regenerate_suggestion or {},
        created_at=orm.created_at,
    )


def _pydantic_to_orm(record: FeedbackRecord) -> FeedbackRecordORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return FeedbackRecordORM(
        feedback_id=record.feedback_id,
        learner_id=record.learner_id,
        resource_id=record.resource_id,
        correct_rate=record.correct_rate,
        decision=record.decision,
        answers=[answer.model_dump() for answer in record.answers],
        feedback_type=record.feedback_type,
        time_spent_seconds=record.time_spent_seconds,
        completed=record.completed,
        self_rating=record.self_rating,
        practice_result=record.practice_result,
        decision_reason=record.decision_reason,
        next_action=record.next_action,
        recommended_topics=record.recommended_topics,
        updated_knowledge_states={
            key: value.model_dump()
            for key, value in record.updated_knowledge_states.items()
        },
        regenerate_suggestion=record.regenerate_suggestion,
    )


class SQLFeedbackRepository(BaseFeedbackRepository):
    """基于 SQLAlchemy 的学习反馈仓库"""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, feedback_id: str) -> Optional[FeedbackRecord]:
        with self.session_factory() as db:
            orm = db.query(FeedbackRecordORM).filter_by(feedback_id=feedback_id).first()
        return _orm_to_pydantic(orm) if orm else None

    def save(self, record: FeedbackRecord) -> None:
        with self.session_factory() as db:
            orm = db.query(FeedbackRecordORM).filter_by(feedback_id=record.feedback_id).first()
            if orm:
                orm.learner_id = record.learner_id
                orm.resource_id = record.resource_id
                orm.correct_rate = record.correct_rate
                orm.decision = record.decision
                orm.answers = [answer.model_dump() for answer in record.answers]
                orm.feedback_type = record.feedback_type
                orm.time_spent_seconds = record.time_spent_seconds
                orm.completed = record.completed
                orm.self_rating = record.self_rating
                orm.practice_result = record.practice_result
                orm.decision_reason = record.decision_reason
                orm.next_action = record.next_action
                orm.recommended_topics = record.recommended_topics
                orm.updated_knowledge_states = {
                    key: value.model_dump()
                    for key, value in record.updated_knowledge_states.items()
                }
                orm.regenerate_suggestion = record.regenerate_suggestion
            else:
                orm = _pydantic_to_orm(record)
                db.add(orm)
            db.commit()

    def list_by_learner(self, learner_id: str) -> List[FeedbackRecord]:
        with self.session_factory() as db:
            orms = (
                db.query(FeedbackRecordORM)
                .filter_by(learner_id=learner_id)
                .order_by(FeedbackRecordORM.created_at.desc())
                .all()
            )
        return [_orm_to_pydantic(orm) for orm in orms]
