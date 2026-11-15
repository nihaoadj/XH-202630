"""Round storage constraints and rollback against real SQLite and memory."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.feedback.round_base import RoundConflict
from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, LearnerProfileORM

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def round_values(identity="r", protocol="learning-round/v1", learner="learner"):
    return dict(round_id=identity, learner_id=learner, knowledge_base_id="kb",
                protocol_version=protocol, selection_key=f"selection-{identity}",
                selection_hash="a" * 64, budget_snapshot={"L": 2}, created_at=NOW)


def add_member(repository, identity, role, parent="r"):
    return repository.insert("learning_round_nodes", dict(
        round_node_id=identity, round_id=parent, skill_node_id=identity, role=role, name=identity,
    ))


def add_stage(repository, identity="s", parent="r"):
    return repository.insert("learning_round_stages", dict(
        stage_id=identity, round_id=parent, kind="initial", ordinal=0, selection_key=identity,
        selection_hash="b" * 64, state="producing", budget_snapshot={}, created_at=NOW,
    ))


def add_stage_member(repository, identity, member, stage="s", batch=None):
    return repository.insert("learning_round_stage_nodes", dict(
        stage_node_id=identity, stage_id=stage, round_node_id=member, batch_id=batch,
        request_snapshot={}, resource_types=["分阶测试题"], difficulty="初级", config_hash="c" * 64,
    ))


@pytest.fixture(params=["memory", "sqlite"])
def repository(request):
    if request.param == "memory":
        yield MemoryRoundRepository()
        return
    engine = configure_sqlite_foreign_keys(create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    ))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([LearnerProfileORM(learner_id=value, learner_type="test", education="本科", major="test", learning_goal="test")
                    for value in ("learner", "other")])
        db.commit()
    yield SQLRoundRepository(factory)
    engine.dispose()


def test_atomic_rollback_does_not_leave_a_partial_round(repository):
    with pytest.raises(RuntimeError, match="injected"):
        with repository.transaction() as tx:
            tx.insert("learning_rounds", round_values())
            add_member(tx, "a", "primary")
            raise RuntimeError("injected")
    assert repository.find("learning_rounds") == []
    assert repository.find("learning_round_nodes") == []


def test_role_uniqueness_and_two_member_limit(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
    with pytest.raises((RoundConflict, ValueError)):
        with repository.transaction() as tx:
            add_member(tx, "b", "primary")
    with repository.transaction() as tx:
        add_member(tx, "b", "review")
    with pytest.raises(RoundConflict, match="LIMIT"):
        with repository.transaction() as tx:
            add_member(tx, "c", "review")
    assert len(repository.find("learning_round_nodes")) == 2


def test_legacy_import_uses_two_null_batches_without_invented_roles(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values(protocol="legacy-correction/v1"))
        add_member(tx, "a", "legacy")
        add_member(tx, "b", "legacy")
        add_stage(tx)
        add_stage_member(tx, "sa", "a")
        add_stage_member(tx, "sb", "b")
    assert [row["batch_id"] for row in repository.find("learning_round_stage_nodes")] == [None, None]


def test_normal_stage_requires_a_real_batch(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
        add_stage(tx)
    with pytest.raises(RoundConflict, match="BATCH_REQUIRED"):
        with repository.transaction() as tx:
            add_stage_member(tx, "sa", "a")


def test_stage_cannot_attach_a_member_from_another_round(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        tx.insert("learning_rounds", round_values("other-round"))
        add_member(tx, "home-primary", "primary")
        add_member(tx, "a", "primary", "other-round")
        add_stage(tx)
    with pytest.raises(RoundConflict, match="MEMBER_MISMATCH"):
        with repository.transaction() as tx:
            add_stage_member(tx, "sa", "a", batch="batch")


def test_compare_and_set_and_detached_reads(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "home-primary", "primary")
        add_stage(tx)
    row = repository.one("learning_round_stages", stage_id="s")
    row["budget_snapshot"]["L"] = 999
    assert repository.one("learning_round_stages", stage_id="s")["budget_snapshot"] == {}
    with repository.transaction() as tx:
        assert tx.compare_and_set("learning_round_stages", "s", 1, {"state": "awaiting_assessment"})["row_version"] == 2
    with pytest.raises(RoundConflict):
        with repository.transaction() as tx:
            tx.compare_and_set("learning_round_stages", "s", 1, {"state": "completed"})
    with pytest.raises(ValueError):
        with repository.transaction() as tx:
            tx.compare_and_set("learning_round_stages", "s", 2, {"round_id": "another"})


def test_delete_one_learner_keeps_other_facts(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        tx.insert("learning_rounds", round_values("keep", learner="other"))
        add_member(tx, "keep-primary", "primary", "keep")
        add_member(tx, "a", "primary")
        add_stage(tx)
        add_stage_member(tx, "sa", "a", batch="batch")
        tx.insert("learning_round_evaluation_sessions", dict(
            session_id="session", stage_id="s", manifest_hash="d" * 64, manifest={}, created_at=NOW,
        ))
    with repository.transaction() as tx:
        tx.delete_learner("learner")
    assert [row["round_id"] for row in repository.find("learning_rounds")] == ["keep"]
    assert repository.find("learning_round_evaluation_sessions") == []


def test_round_page_has_stable_ties_and_a_bounded_window(repository):
    with repository.transaction() as tx:
        for key in ("a", "c", "b"):
            tx.insert("learning_rounds", round_values(key))
            add_member(tx, f"member-{key}", "primary", key)
    page, total = repository.list_rounds("learner", 1, 1)
    assert total == 3
    assert [row["round_id"] for row in page] == ["b"]
    with pytest.raises(ValueError):
        repository.list_rounds("learner", 0, 1000)


def test_parent_round_cannot_belong_to_another_learner(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values("other-round", learner="other"))
        add_member(tx, "other-primary", "primary", "other-round")
    with pytest.raises(RoundConflict, match="OWNER_MISMATCH"):
        with repository.transaction() as tx:
            tx.insert("learning_rounds", {**round_values(), "parent_round_id": "other-round"})


def test_invalid_stage_and_submission_states_are_rejected(repository):
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "home-primary", "primary")
        add_stage(tx)
    with pytest.raises(RoundConflict, match="INVALID_STATE"):
        with repository.transaction() as tx:
            tx.compare_and_set("learning_round_stages", "s", 1, {"state": "invented"})
    with pytest.raises(RoundConflict, match="SUBMISSION_STATE"):
        with repository.transaction() as tx:
            tx.insert("learning_round_evaluation_sessions", dict(
                session_id="session", stage_id="s", manifest_hash="d" * 64, manifest={},
                created_at=NOW, grading_state="submitted",
            ))


def test_memory_profile_delete_uses_the_shared_round_store():
    from app.db.learners.memory import MemoryLearnerRepository
    from app.models.learning_documents.schemas import LearnerProfile

    rounds = MemoryRoundRepository()
    learners = MemoryLearnerRepository(rounds)
    learners.save(LearnerProfile(learner_id="learner", learner_type="test", education="test",
                                 major="test", learning_goal="test"))
    with rounds.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "home-primary", "primary")
    assert learners.delete("learner")
    assert rounds.find("learning_rounds") == []


def test_sql_profile_delete_cleans_round_references_before_old_facts(repository):
    if not isinstance(repository, SQLRoundRepository):
        pytest.skip("SQL deletion integration only")
    from app.db.learners.sql_repository import SQLLearnerRepository

    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
        add_stage(tx)
        add_stage_member(tx, "sa", "a", batch="batch")
    assert SQLLearnerRepository(repository.session_factory).delete("learner")
    assert repository.find("learning_rounds") == []


@pytest.mark.parametrize("role", [None, "review"])
def test_incomplete_normal_round_is_rolled_back(repository, role):
    with pytest.raises(RoundConflict, match="INCOMPLETE_MEMBERS"):
        with repository.transaction() as tx:
            tx.insert("learning_rounds", round_values())
            if role:
                add_member(tx, "only-review", role)
    assert repository.find("learning_rounds") == []


def test_nested_creation_cannot_hide_an_incomplete_round(repository):
    with pytest.raises(RoundConflict, match="INCOMPLETE_MEMBERS"):
        with repository.transaction() as outer:
            with outer.transaction() as inner:
                inner.insert("learning_rounds", round_values())
    assert repository.find("learning_rounds") == []


def test_nested_complete_round_and_parent_chain_deletion(repository):
    with repository.transaction() as outer:
        with outer.transaction() as inner:
            inner.insert("learning_rounds", round_values())
            add_member(inner, "a", "primary")
        outer.insert("learning_rounds", {**round_values("child"), "parent_round_id": "r"})
        add_member(outer, "child-node", "primary", "child")
    with repository.transaction() as tx:
        tx.delete_learner("learner")
    assert repository.find("learning_rounds") == []
    if isinstance(repository, SQLRoundRepository):
        from sqlalchemy import text

        with repository.session_factory() as db:
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
