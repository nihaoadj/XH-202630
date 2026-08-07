"""SQLAlchemy 实现的学习者画像仓库"""
from typing import Dict, Optional, Callable

from sqlalchemy.orm import Session

from app.db.learner.base import BaseLearnerRepository
from app.db.models import AgentRunORM, DiagnosticAnswerORM, KnowledgeStateORM, LearnerProfileORM
from app.models.schemas import KnowledgeState, LearnerProfile, LearningPreferences


def _orm_to_pydantic(orm: LearnerProfileORM) -> LearnerProfile:
    """将 ORM 对象转换为 Pydantic 模型"""
    return LearnerProfile(
        learner_id=orm.learner_id,
        user_id=orm.user_id,
        learner_type=orm.learner_type,
        education=orm.education,
        major=orm.major,
        target_domain=orm.target_domain,
        knowledge_base_id=orm.knowledge_base_id,
        theory_scores=orm.theory_scores or {},
        knowledge_states={
            key: KnowledgeState(**value)
            for key, value in (orm.knowledge_states or {}).items()
        },
        skill_level=orm.skill_level,
        weak_points=orm.weak_points or [],
        strong_points=orm.strong_points or [],
        learning_goal=orm.learning_goal,
        learning_preferences=LearningPreferences(**orm.learning_preferences)
        if orm.learning_preferences
        else None,
        last_feedback_summary=orm.last_feedback_summary or {},
    )


def _pydantic_to_orm(profile: LearnerProfile) -> LearnerProfileORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return LearnerProfileORM(
        learner_id=profile.learner_id,
        user_id=profile.user_id,
        learner_type=profile.learner_type,
        education=profile.education,
        major=profile.major,
        target_domain=profile.target_domain,
        knowledge_base_id=profile.knowledge_base_id,
        theory_scores=profile.theory_scores,
        knowledge_states={
            key: value.model_dump()
            for key, value in profile.knowledge_states.items()
        },
        skill_level=profile.skill_level,
        weak_points=profile.weak_points,
        strong_points=profile.strong_points,
        learning_goal=profile.learning_goal,
        learning_preferences=profile.learning_preferences.model_dump()
        if profile.learning_preferences
        else {},
        last_feedback_summary=profile.last_feedback_summary,
    )


class SQLLearnerRepository(BaseLearnerRepository):
    """基于 SQLAlchemy 的学习者画像仓库"""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=learner_id).first()
        return _orm_to_pydantic(orm) if orm else None

    def save(self, profile: LearnerProfile) -> None:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=profile.learner_id).first()
            if orm:
                orm.user_id = profile.user_id
                orm.learner_type = profile.learner_type
                orm.education = profile.education
                orm.major = profile.major
                orm.target_domain = profile.target_domain
                orm.knowledge_base_id = profile.knowledge_base_id
                orm.theory_scores = profile.theory_scores
                orm.knowledge_states = {
                    key: value.model_dump()
                    for key, value in profile.knowledge_states.items()
                }
                orm.skill_level = profile.skill_level
                orm.weak_points = profile.weak_points
                orm.strong_points = profile.strong_points
                orm.learning_goal = profile.learning_goal
                orm.learning_preferences = (
                    profile.learning_preferences.model_dump()
                    if profile.learning_preferences
                    else {}
                )
                orm.last_feedback_summary = profile.last_feedback_summary
            else:
                orm = _pydantic_to_orm(profile)
                db.add(orm)
            db.commit()

    def delete(self, learner_id: str) -> bool:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=learner_id).first()
            if orm:
                # 诊断记录与知识状态直接依赖画像；Agent 运行轨迹则匿名保留，以免丢失审计证据。
                db.query(DiagnosticAnswerORM).filter_by(learner_id=learner_id).delete(synchronize_session=False)
                db.query(KnowledgeStateORM).filter_by(learner_id=learner_id).delete(synchronize_session=False)
                db.query(AgentRunORM).filter_by(learner_id=learner_id).update({"learner_id": None}, synchronize_session=False)
                db.delete(orm)
                db.commit()
                return True
            return False

    def list_all(self) -> Dict[str, LearnerProfile]:
        with self.session_factory() as db:
            orms = db.query(LearnerProfileORM).all()
        return {orm.learner_id: _orm_to_pydantic(orm) for orm in orms}

    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        profile = self.get(learner_id)
        if profile is None:
            return None
        updated = profile.model_copy(update=updates)
        self.save(updated)
        return updated

    def list_with_pagination(
        self,
        page: int,
        page_size: int,
        skill_level: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        with self.session_factory() as db:
            query = db.query(LearnerProfileORM)
            if user_id:
                query = query.filter_by(user_id=user_id)
            if skill_level:
                query = query.filter_by(skill_level=skill_level)
            total = query.count()
            rows = query.order_by(LearnerProfileORM.learner_id).offset((page - 1) * page_size).limit(page_size).all()
        return {"total": total, "page": page, "page_size": page_size, "items": [_orm_to_pydantic(row) for row in rows]}
