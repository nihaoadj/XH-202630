"""SQLAlchemy 实现的学习者画像仓库"""
from typing import Dict, Optional, Callable

from sqlalchemy.orm import Session

from app.db.learner.base import BaseLearnerRepository
from app.db.models import LearnerProfileORM
from app.models.schemas import LearnerProfile


def _orm_to_pydantic(orm: LearnerProfileORM) -> LearnerProfile:
    """将 ORM 对象转换为 Pydantic 模型"""
    return LearnerProfile(
        learner_id=orm.learner_id,
        education=orm.education,
        major=orm.major,
        theory_scores=orm.theory_scores or {},
        skill_level=orm.skill_level,
        weak_points=orm.weak_points or [],
        strong_points=orm.strong_points or [],
        learning_goal=orm.learning_goal,
    )


def _pydantic_to_orm(profile: LearnerProfile) -> LearnerProfileORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return LearnerProfileORM(
        learner_id=profile.learner_id,
        education=profile.education,
        major=profile.major,
        theory_scores=profile.theory_scores,
        skill_level=profile.skill_level,
        weak_points=profile.weak_points,
        strong_points=profile.strong_points,
        learning_goal=profile.learning_goal,
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
                orm.education = profile.education
                orm.major = profile.major
                orm.theory_scores = profile.theory_scores
                orm.skill_level = profile.skill_level
                orm.weak_points = profile.weak_points
                orm.strong_points = profile.strong_points
                orm.learning_goal = profile.learning_goal
            else:
                orm = _pydantic_to_orm(profile)
                db.add(orm)
            db.commit()

    def delete(self, learner_id: str) -> bool:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=learner_id).first()
            if orm:
                db.delete(orm)
                db.commit()
                return True
            return False

    def list_all(self) -> Dict[str, LearnerProfile]:
        with self.session_factory() as db:
            orms = db.query(LearnerProfileORM).all()
        return {orm.learner_id: _orm_to_pydantic(orm) for orm in orms}
