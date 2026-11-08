"""One connection or memory snapshot for explicitly supported local writers."""

from __future__ import annotations

from contextlib import ExitStack
from copy import copy, deepcopy

from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker

from app.db.feedback.round_base import validate_complete_rounds
from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository


class SharedTransactionError(RuntimeError):
    pass


def begin_sql_scope(engine: Engine):
    """Common external transaction binding for round and legacy continuation."""
    connection = engine.connect()
    try:
        transaction = connection.begin()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        factory = scoped_session(sessionmaker(
            autocommit=False, autoflush=False, bind=connection, join_transaction_mode="rollback_only",
        ))
        return connection, transaction, factory
    except BaseException:
        connection.close()
        raise


class SharedTransaction:
    """Bind a fixed repository set; unsupported writers fail before mutation.

    No SQL/model calls belong in this class. Callers explicitly list every
    writer. Nested repository commits join the outer connection and cannot
    commit the business transaction on their own.
    """

    def __init__(self, repositories):
        from app.db.audit.memory import MemoryAuditRepository
        from app.db.audit.sql_repository import SQLAuditRepository
        from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
        from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
        from app.db.generation.memory import MemoryGenerationJobRepository
        from app.db.generation.sql_repository import SQLGenerationJobRepository
        from app.db.learners.curriculum import MemoryCurriculumRepository, SQLCurriculumRepository
        from app.db.learners.mastery import MemoryMasteryRepository, SQLMasteryRepository
        from app.db.learners.memory import MemoryLearnerRepository
        from app.db.learners.sql_repository import SQLLearnerRepository
        from app.db.learners.tier_progress import MemoryTierProgressRepository, SQLTierProgressRepository

        self._sql_types = (SQLRoundRepository, SQLAuditRepository, SQLFeedbackLoopRepository,
                           SQLGenerationJobRepository, SQLCurriculumRepository, SQLMasteryRepository,
                           SQLTierProgressRepository, SQLLearnerRepository)
        self._memory_types = (MemoryAuditRepository, MemoryRoundRepository, MemoryFeedbackLoopRepository, MemoryGenerationJobRepository,
                              MemoryCurriculumRepository, MemoryMasteryRepository, MemoryTierProgressRepository,
                              MemoryLearnerRepository)
        self.repositories = list({id(repo): repo for repo in repositories if repo is not None}.values())
        if not self.repositories:
            raise SharedTransactionError("empty writer graph")
        if all(type(repo) in self._sql_types for repo in self.repositories):
            self.mode = "sql"
            engines = []
            for repo in self.repositories:
                factory = repo.session_factory
                factory = factory.session_factory if isinstance(factory, scoped_session) else factory
                if not isinstance(factory, sessionmaker) or not isinstance(factory.kw.get("bind"), Engine):
                    raise SharedTransactionError("unsupported SQL session factory")
                engines.append(factory.kw["bind"])
            if len({id(engine) for engine in engines}) != 1:
                raise SharedTransactionError("writers use different engines")
            self.engine = engines[0]
        elif all(type(repo) in self._memory_types for repo in self.repositories):
            self.mode = "memory"
        else:
            raise SharedTransactionError("unsupported or mixed writers")
        self._bound = {}
        self._stack = ExitStack()
        self._snapshots = []
        self._profile_references = {}

    def __enter__(self):
        try:
            if self.mode == "sql":
                self.connection, self.transaction, self.factory = begin_sql_scope(self.engine)
                self._stack.callback(self.connection.close)
                self._stack.callback(self.factory.remove)
                for repo in self.repositories:
                    bound = copy(repo)
                    bound.session_factory = self.factory
                    if type(repo) is SQLRoundRepository:
                        bound._session = self.factory()
                        bound._touched_rounds = set()
                    self._bound[id(repo)] = bound
            else:
                # Feedback -> mastery -> learner follows existing write order.
                priority = {"MemoryAuditRepository": -1, "MemoryFeedbackLoopRepository": 0, "MemoryMasteryRepository": 1,
                            "MemoryCurriculumRepository": 2, "MemoryTierProgressRepository": 3,
                            "MemoryGenerationJobRepository": 4, "MemoryLearnerRepository": 5,
                            "MemoryRoundRepository": 6}
                for repo in sorted(self.repositories, key=lambda r: (priority[type(r).__name__], id(r))):
                    self._stack.enter_context(repo._lock)
                    snapshot = {key: deepcopy(value) for key, value in vars(repo).items()
                                if isinstance(value, (dict, set, list))}
                    self._snapshots.append((repo, snapshot))
                    if type(repo).__name__ == "MemoryLearnerRepository":
                        self._profile_references[id(repo)] = dict(repo._store)
                    self._bound[id(repo)] = repo
                    if type(repo) is MemoryRoundRepository:
                        repo._depth += 1
            return self
        except BaseException:
            self._stack.close()
            raise

    def bind(self, repository):
        if id(repository) not in self._bound:
            raise SharedTransactionError("unplanned repository requested")
        return self._bound[id(repository)]

    def bind_reader(self, repository):
        """Known SQL reads join the same snapshot; do not silently cross DBs."""
        if repository is None or not hasattr(repository, "session_factory"):
            return repository
        if self.mode != "sql":
            raise SharedTransactionError("memory transaction has a SQL reader")
        factory = repository.session_factory
        factory = factory.session_factory if isinstance(factory, scoped_session) else factory
        if not isinstance(factory, sessionmaker) or factory.kw.get("bind") is not self.engine:
            raise SharedTransactionError("reader uses a different engine")
        reader = copy(repository)
        reader.session_factory = self.factory
        return reader

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                for repo in self._bound.values():
                    if type(repo) in (SQLRoundRepository, MemoryRoundRepository):
                        validate_complete_rounds(repo, repo._touched_rounds)
                if self.mode == "sql":
                    self.factory().flush()
                    self.transaction.commit()
            elif self.mode == "sql":
                self.transaction.rollback()
            else:
                self._restore()
        except BaseException:
            if self.mode == "sql" and self.transaction.is_active:
                self.transaction.rollback()
            elif self.mode == "memory":
                self._restore()
            raise
        finally:
            if self.mode == "memory":
                for repo in self.repositories:
                    if type(repo) is MemoryRoundRepository:
                        repo._depth -= 1
                        if repo._depth == 0:
                            repo._touched_rounds = set()
            self._stack.close()
        return False

    def _restore(self):
        for repo, fields in self._snapshots:
            for key, value in fields.items():
                if key == "_store" and id(repo) in self._profile_references:
                    originals = self._profile_references[id(repo)]
                    for identity, saved in value.items():
                        original = originals[identity]
                        original.__dict__.clear()
                        original.__dict__.update(deepcopy(saved.__dict__))
                    repo._store = originals
                else:
                    setattr(repo, key, value)
