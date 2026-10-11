"""Structural contracts for the existing courseware source dependencies."""

from collections.abc import Callable
from typing import Any, Protocol

from app.db.courseware.repository import MemoryCoursewareRepository, SQLCoursewareRepository
from app.models.courseware.snapshots import LearnerContextSnapshot
from app.models.learning_documents.schemas import LearningResource


# Both durable and in-memory implementations expose the existing workflow API.
CoursewareRepository = MemoryCoursewareRepository | SQLCoursewareRepository
LearnerContextProvider = Callable[
    [str | None], LearnerContextSnapshot | dict[str, Any] | None
]


class SourceResourcePort(Protocol):
    """Read source resources without depending on the application facade."""

    def get(self, resource_id: str) -> LearningResource | None: ...

    def list_by_learner(self, learner_id: str) -> list[LearningResource]: ...
