from collections.abc import Callable
from functools import lru_cache

from app.config import get_settings
from app.db.shared.database import get_session_factory
from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.learners.base import BaseLearnerRepository
from app.db.learners.repository import get_learner_repository
from app.db.learners.mastery import BaseMasteryRepository, MemoryMasteryRepository


def create_feedback_loop_repository(
    db_type: str,
    session_factory: Callable | None = None,
    learner_repository: BaseLearnerRepository | None = None,
    mastery_repository: BaseMasteryRepository | None = None,
) -> BaseFeedbackLoopRepository:
    if db_type == "memory":
        return MemoryFeedbackLoopRepository(
            learner_repository or get_learner_repository(),
            mastery_repository if isinstance(mastery_repository, MemoryMasteryRepository) else None,
        )
    if db_type not in {"sqlite", "postgresql"}:
        raise ValueError(f"Unsupported DB_TYPE for feedback loop repository: {db_type}")
    return SQLFeedbackLoopRepository(session_factory or get_session_factory())


@lru_cache()
def get_feedback_loop_repository() -> BaseFeedbackLoopRepository:
    return create_feedback_loop_repository(get_settings().db_type)
