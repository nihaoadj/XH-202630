"""Real shared-connection commit/rollback, memory rollback and unsupported graph rejection."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository
from app.db.shared.models import Base, LearnerProfileORM
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.shared.unit_of_work import SharedTransaction, SharedTransactionError
from tests.integration.persistence.test_learning_round_repository import round_values, add_member


def test_rejects_mixed_or_unknown_writers_before_entering():
    with pytest.raises(SharedTransactionError):
        SharedTransaction([MemoryRoundRepository(), object()])


def test_memory_external_transaction_checks_members_and_rolls_back():
    rounds = MemoryRoundRepository()
    with pytest.raises(RuntimeError, match="injected"):
        with SharedTransaction([rounds]) as uow:
            writer = uow.bind(rounds)
            writer.insert("learning_rounds", round_values())
            add_member(writer, "node", "primary")
            raise RuntimeError("injected")
    assert rounds.find("learning_rounds") == []
    assert rounds._depth == 0


def test_memory_rollback_restores_the_existing_profile_object():
    from app.db.learners.memory import MemoryLearnerRepository
    from app.models.learning_documents.schemas import LearnerProfile

    learners = MemoryLearnerRepository()
    profile = LearnerProfile(learner_id="learner", learner_type="test", education="test",
                             major="test", learning_goal="before")
    learners.save(profile)
    with pytest.raises(RuntimeError):
        with SharedTransaction([learners]):
            profile.learning_goal = "after"
            raise RuntimeError("injected")
    assert learners.get("learner") is profile
    assert profile.learning_goal == "before"


@pytest.mark.parametrize("fail", [False, True])
def test_sql_child_commit_cannot_escape_the_outer_transaction(fail):
    engine = configure_sqlite_foreign_keys(create_engine("sqlite://", poolclass=StaticPool))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    learners = SQLLearnerRepository(factory)
    rounds = SQLRoundRepository(factory)
    with factory() as db:
        db.add(LearnerProfileORM(learner_id="learner", learner_type="test", education="test", major="test", learning_goal="before"))
        db.commit()
    try:
        with SharedTransaction([rounds, learners]) as uow:
            writer = uow.bind(rounds)
            writer.insert("learning_rounds", round_values())
            add_member(writer, "node", "primary")
            # Existing repositories commit their own Session; the external
            # connection must retain ownership of the actual transaction.
            uow.bind(learners).update_partial("learner", {"learning_goal": "after"})
            if fail:
                raise RuntimeError("injected")
    except RuntimeError:
        if not fail:
            raise
    assert bool(rounds.find("learning_rounds")) is not fail
    assert learners.get("learner").learning_goal == ("before" if fail else "after")
    engine.dispose()
