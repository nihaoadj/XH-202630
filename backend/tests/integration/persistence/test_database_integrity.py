from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.db.database import configure_sqlite_foreign_keys
from app.db.integrity import inspect_database_integrity
from app.db.models import (
    AgentStepORM,
    Base,
    ClaimJudgementORM,
    LearningAttemptORM,
    LearningPathMutationORM,
    ResourceReviewORM,
)


def _integrity_engine(tmp_path, name="integrity.db"):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        poolclass=NullPool,
    )
    configure_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    return engine


def test_sqlite_foreign_keys_are_enabled_for_every_connection(tmp_path):
    engine = _integrity_engine(tmp_path)

    for _ in range(2):
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.parametrize(
    "row",
    [
        AgentStepORM(
            step_id="invalid-step",
            run_id="missing-run",
            step_no=1,
            agent_name="test",
            action="invalid reference",
        ),
        ResourceReviewORM(
            review_id="invalid-review",
            resource_id="missing-resource",
            status="approved",
        ),
        LearningAttemptORM(
            attempt_id="invalid-attempt",
            learner_id="missing-learner",
            source_resource_id="missing-resource",
            source_resource_version=1,
            idempotency_key="invalid-attempt-key",
            request_hash="invalid-attempt-hash",
            expected_profile_version=1,
            overall_score=0.0,
            submitted_at=datetime.now(timezone.utc),
        ),
        LearningPathMutationORM(
            mutation_id="invalid-mutation",
            learner_id="missing-learner",
            path_id="missing-path",
            attempt_id="missing-attempt",
            decision_id="missing-decision",
            mutation_type="insert",
            path_version_before=1,
            path_version_after=2,
            created_at=datetime.now(timezone.utc),
        ),
        ClaimJudgementORM(
            judgement_id="invalid-judgement",
            claim_id="missing-claim",
            run_id="missing-run",
            resource_id="missing-resource",
            resource_version=1,
            review_id="missing-review",
            status="completed",
            reason="invalid references",
            judge_type="rule",
            judge_prompt_version="v1",
            created_at=datetime.now(timezone.utc),
        ),
    ],
)
def test_invalid_foreign_key_references_fail(tmp_path, row):
    engine = _integrity_engine(tmp_path, f"{row.__tablename__}.db")
    factory = sessionmaker(bind=engine)

    with factory() as db:
        db.add(row)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    report = inspect_database_integrity(engine)
    assert report["foreign_keys_enabled"] is True
    assert report["foreign_key_violations"] == []
