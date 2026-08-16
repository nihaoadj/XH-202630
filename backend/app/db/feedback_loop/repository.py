from collections.abc import Callable
from functools import lru_cache

from app.config import get_settings
from app.db.database import get_session_factory
from app.db.feedback_loop.base import BaseFeedbackLoopRepository
from app.db.feedback_loop.memory import MemoryFeedbackLoopRepository
from app.db.feedback_loop.sql_repository import SQLFeedbackLoopRepository
from app.db.learner.base import BaseLearnerRepository
from app.db.learner.repository import get_learner_repository


def create_feedback_loop_repository(
    db_type: str,
    session_factory: Callable | None = None,
    learner_repository: BaseLearnerRepository | None = None,
) -> BaseFeedbackLoopRepository:
    if db_type == "memory":
        return MemoryFeedbackLoopRepository(learner_repository or get_learner_repository())
    if db_type not in {"sqlite", "postgresql"}:
        raise ValueError(f"Unsupported DB_TYPE for feedback loop repository: {db_type}")
    return SQLFeedbackLoopRepository(session_factory or get_session_factory())


@lru_cache()
def get_feedback_loop_repository() -> BaseFeedbackLoopRepository:
    return create_feedback_loop_repository(get_settings().db_type)
