"""Narrow transaction boundary for generation continuation creation."""

from __future__ import annotations

from contextlib import ExitStack
from copy import copy, deepcopy
from typing import Any, Self

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learners.curriculum import (
    MemoryCurriculumRepository,
    SQLCurriculumRepository,
)
from app.db.learners.mastery import MemoryMasteryRepository, SQLMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import (
    MemoryTierProgressRepository,
    SQLTierProgressRepository,
)
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.services.learners.mastery import MasteryService


class ContinuationAtomicityError(RuntimeError):
    """The configured writer repositories cannot share one atomic boundary."""


def _repository_kind(repository: object) -> str | None:
    if type(repository) in (
        MemoryGenerationJobRepository,
        MemoryFeedbackLoopRepository,
        MemoryMasteryRepository,
        MemoryCurriculumRepository,
        MemoryTierProgressRepository,
    ):
        return "memory"
    if type(repository) in (
        SQLGenerationJobRepository,
        SQLFeedbackLoopRepository,
        SQLMasteryRepository,
        SQLCurriculumRepository,
        SQLTierProgressRepository,
    ):
        return "sql"
    return None


def _sessionmaker_for(factory: object) -> sessionmaker | None:
    if isinstance(factory, scoped_session):
        factory = factory.session_factory
    return factory if isinstance(factory, sessionmaker) else None


def _engine_for_factory(factory: object) -> Engine | None:
    maker = _sessionmaker_for(factory)
    if maker is None:
        return None
    bind = maker.kw.get("bind")
    if isinstance(bind, Connection):
        return bind.engine
    return bind if isinstance(bind, Engine) else None


def _clone_with_session_factory(repository: object, session_factory: object) -> object:
    cloned = copy(repository)
    cloned.session_factory = session_factory
    return cloned


def has_standard_core_writers(generation_job_service: object) -> bool:
    """Return whether this is a standard repository graph requiring a UOW.

    Old lightweight test/application stubs with no standard repositories keep
    their established direct call path. Once any standard writer is present,
    unsupported or mixed writers are rejected before the first mutation.
    """
    job_repository = getattr(generation_job_service, "job_repo", None)
    mastery_service = getattr(generation_job_service, "mastery_service", None)
    repositories = [job_repository]
    if mastery_service is not None:
        repositories.extend(
            [
                getattr(mastery_service, "repository", None),
                getattr(mastery_service, "curriculum_repo", None),
                getattr(mastery_service, "tier_progress_repo", None),
            ]
        )
    return any(_repository_kind(repository) is not None for repository in repositories)


def has_standard_writers(
    generation_job_service: object, feedback_repositories: list[object]
) -> bool:
    """Check the complete writer set after lazy feedback providers are resolved."""
    mastery_service = getattr(generation_job_service, "mastery_service", None)
    repositories = [
        getattr(generation_job_service, "job_repo", None),
        *feedback_repositories,
    ]
    if mastery_service is not None:
        repositories.extend(
            [
                getattr(mastery_service, "repository", None),
                getattr(mastery_service, "curriculum_repo", None),
                getattr(mastery_service, "tier_progress_repo", None),
            ]
        )
    return any(_repository_kind(repository) is not None for repository in repositories)


class ContinuationUnitOfWork:
    """Bind a call-local service graph to one SQL connection or Memory snapshot."""

    def __init__(
        self, generation_job_service: object, feedback_repositories: list[object]
    ):
        self.original_service = generation_job_service
        self.feedback_repositories = feedback_repositories
        self.mode: str | None = None
        self.engine: Engine | None = None
        self.connection = None
        self.transaction = None
        self.session_factory = None
        self._exit_stack: ExitStack | None = None
        self._snapshots: list[tuple[object, dict[str, Any]]] = []
        self._bound_feedback_repositories: list[object] = []
        self.generation_job_service = None
        self.schedule_failed = False

        self._validate_participants()

    def _validate_participants(self) -> list[object]:
        job_repository = getattr(self.original_service, "job_repo", None)
        mastery_service = getattr(self.original_service, "mastery_service", None)
        if mastery_service is not None and type(mastery_service) is not MasteryService:
            raise ContinuationAtomicityError(
                "continuation has an unsupported mastery service"
            )

        writer_repositories = [job_repository, *self.feedback_repositories]
        if mastery_service is not None:
            writer_repositories.append(mastery_service.repository)
            writer_repositories.extend(
                repository
                for repository in (
                    mastery_service.curriculum_repo,
                    mastery_service.tier_progress_repo,
                )
                if repository is not None
            )
        kinds = [_repository_kind(repository) for repository in writer_repositories]
        if any(kind is None for kind in kinds):
            raise ContinuationAtomicityError(
                "continuation writer repositories must all use supported SQL or Memory implementations"
            )
        if len(set(kinds)) != 1:
            raise ContinuationAtomicityError(
                "continuation writer repositories mix SQL and Memory implementations"
            )
        self.mode = kinds[0]

        if self.mode == "sql":
            session_factories = [
                repository.session_factory for repository in writer_repositories
            ]
            engines = [_engine_for_factory(factory) for factory in session_factories]
            if (
                any(engine is None for engine in engines)
                or len({id(engine) for engine in engines}) != 1
            ):
                raise ContinuationAtomicityError(
                    "continuation SQL writers must share one SQLAlchemy Engine"
                )
            self.engine = engines[0]
            if mastery_service is not None:
                for read_repository in (
                    mastery_service.resource_repo,
                    getattr(mastery_service.knowledge_service, "catalog", None),
                ):
                    if isinstance(
                        read_repository,
                        (SQLResourceRepository, KnowledgeCatalogRepository),
                    ):
                        read_engine = _engine_for_factory(
                            read_repository.session_factory
                        )
                        if read_engine is not self.engine:
                            raise ContinuationAtomicityError(
                                "continuation SQL reads must use the same Engine as its writers"
                            )
        else:
            if mastery_service is not None:
                learner_repository = getattr(
                    mastery_service.repository, "learner_repository", None
                )
                if type(learner_repository) is not MemoryLearnerRepository:
                    raise ContinuationAtomicityError(
                        "Memory mastery requires its Memory learner repository"
                    )
        return writer_repositories

    def __enter__(self) -> Self:
        if self.mode == "sql":
            self.connection = self.engine.connect()
            self.transaction = self.connection.begin()
            self.session_factory = scoped_session(
                sessionmaker(
                    autocommit=False,
                    autoflush=False,
                    bind=self.connection,
                    join_transaction_mode="rollback_only",
                )
            )
            self._bind_sql_graph()
        else:
            self._acquire_memory_locks_and_snapshot()
            self._bind_memory_graph()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.schedule_failed = bool(
            getattr(self.generation_job_service, "_continuation_schedule_failed", False)
        )
        if self.mode == "memory":
            try:
                if exc_type is not None:
                    self._restore_memory_snapshot()
            finally:
                if self._exit_stack is not None:
                    self._exit_stack.close()
            return False

        try:
            if self.session_factory is not None:
                self.session_factory.remove()
            if self.transaction is not None and self.transaction.is_active:
                if exc_type is None:
                    try:
                        self._commit_outer_transaction()
                    except Exception:
                        if self.transaction.is_active:
                            self.transaction.rollback()
                        raise
                else:
                    self.transaction.rollback()
        finally:
            if self.connection is not None:
                self.connection.close()
        return False

    def _commit_outer_transaction(self) -> None:
        self.transaction.commit()

    def _bind_sql_graph(self) -> None:
        original = self.original_service
        self.generation_job_service = copy(original)
        self.generation_job_service._continuation_atomicity_active = True
        self.generation_job_service._continuation_schedule_failed = False
        self.generation_job_service.job_repo = _clone_with_session_factory(
            original.job_repo,
            self.session_factory,
        )
        self._bind_feedback_repositories()

        mastery_service = original.mastery_service
        if mastery_service is None:
            return
        bound_mastery = copy(mastery_service)
        bound_mastery.repository = _clone_with_session_factory(
            mastery_service.repository,
            self.session_factory,
        )
        if mastery_service.curriculum_repo is not None:
            bound_mastery.curriculum_repo = _clone_with_session_factory(
                mastery_service.curriculum_repo,
                self.session_factory,
            )
        if mastery_service.tier_progress_repo is not None:
            bound_mastery.tier_progress_repo = _clone_with_session_factory(
                mastery_service.tier_progress_repo,
                self.session_factory,
            )
        if isinstance(mastery_service.resource_repo, SQLResourceRepository):
            bound_mastery.resource_repo = _clone_with_session_factory(
                mastery_service.resource_repo,
                self.session_factory,
            )
        knowledge_service = copy(mastery_service.knowledge_service)
        catalog = getattr(mastery_service.knowledge_service, "catalog", None)
        if isinstance(catalog, KnowledgeCatalogRepository):
            knowledge_service.catalog = _clone_with_session_factory(
                catalog, self.session_factory
            )
        bound_mastery.knowledge_service = knowledge_service
        self.generation_job_service.mastery_service = bound_mastery

    def _bind_memory_graph(self) -> None:
        original = self.original_service
        self.generation_job_service = copy(original)
        self.generation_job_service._continuation_atomicity_active = True
        self.generation_job_service._continuation_schedule_failed = False
        self._bind_feedback_repositories()
        if original.mastery_service is not None:
            self.generation_job_service.mastery_service = copy(original.mastery_service)

    def _bind_feedback_repositories(self) -> None:
        if self.mode == "sql":
            self._bound_feedback_repositories = [
                _clone_with_session_factory(repository, self.session_factory)
                for repository in self.feedback_repositories
            ]
        else:
            self._bound_feedback_repositories = list(self.feedback_repositories)

    def feedback_repo_factory(self):
        if not self._bound_feedback_repositories:
            raise ContinuationAtomicityError(
                "continuation requested an unplanned feedback repository"
            )
        return self._bound_feedback_repositories.pop(0)

    def _acquire_memory_locks_and_snapshot(self) -> None:
        self._exit_stack = ExitStack()
        original = self.original_service
        mastery_service = original.mastery_service

        # Match existing nested write order: feedback -> mastery -> learner.
        # The other participant locks have no cross-repository nesting.
        feedback = [
            repo
            for repo in self.feedback_repositories
            if isinstance(repo, MemoryFeedbackLoopRepository)
        ]
        mastery_repo = (
            mastery_service.repository if mastery_service is not None else None
        )
        curriculum_repo = (
            mastery_service.curriculum_repo if mastery_service is not None else None
        )
        tier_repo = (
            mastery_service.tier_progress_repo if mastery_service is not None else None
        )
        job_repo = original.job_repo
        learner_repo = getattr(mastery_repo, "learner_repository", None)
        lock_order = [
            *(repo._lock for repo in feedback),
            *([mastery_repo._lock] if mastery_repo is not None else []),
            *(
                [curriculum_repo._lock]
                if curriculum_repo is not None and hasattr(curriculum_repo, "_lock")
                else []
            ),
            *(
                [tier_repo._lock]
                if tier_repo is not None and hasattr(tier_repo, "_lock")
                else []
            ),
            job_repo._lock,
            *([learner_repo._lock] if learner_repo is not None else []),
        ]
        seen: set[int] = set()
        for lock in lock_order:
            if id(lock) not in seen:
                self._exit_stack.enter_context(lock)
                seen.add(id(lock))

        self._snapshots = [
            (job_repo, {"_store": deepcopy(job_repo._store)}),
            *((repo, {"_followups": deepcopy(repo._followups)}) for repo in feedback),
        ]
        if mastery_repo is not None:
            self._snapshots.append(
                (
                    mastery_repo,
                    {
                        "_states": deepcopy(mastery_repo._states),
                        "_events": deepcopy(mastery_repo._events),
                        "_node_names": deepcopy(mastery_repo._node_names),
                    },
                )
            )
        if curriculum_repo is not None:
            self._snapshots.append(
                (
                    curriculum_repo,
                    {
                        "_rows": deepcopy(curriculum_repo._rows),
                        "_attempts": deepcopy(curriculum_repo._attempts),
                    },
                )
            )
        if tier_repo is not None:
            self._snapshots.append(
                (tier_repo, {"_states": deepcopy(tier_repo._states)})
            )
        if learner_repo is not None:
            self._snapshots.append(
                (
                    learner_repo,
                    {
                        "_store": {
                            key: (profile, deepcopy(profile))
                            for key, profile in learner_repo._store.items()
                        },
                    },
                )
            )

    def _restore_memory_snapshot(self) -> None:
        for repository, fields in self._snapshots:
            if "_store" in fields and isinstance(repository, MemoryLearnerRepository):
                original_profiles = fields["_store"]
                repository._store.clear()
                for key, (profile, snapshot) in original_profiles.items():
                    _restore_model_in_place(profile, snapshot)
                    repository._store[key] = profile
                continue
            for name, snapshot in fields.items():
                setattr(repository, name, deepcopy(snapshot))


def _restore_model_in_place(target: object, snapshot: object) -> None:
    """Restore a Pydantic learner while retaining its public object identity."""
    for name in (
        "__dict__",
        "__pydantic_fields_set__",
        "__pydantic_extra__",
        "__pydantic_private__",
    ):
        if hasattr(snapshot, name):
            object.__setattr__(target, name, deepcopy(getattr(snapshot, name)))


__all__ = [
    "ContinuationAtomicityError",
    "ContinuationUnitOfWork",
    "has_standard_core_writers",
    "has_standard_writers",
]
