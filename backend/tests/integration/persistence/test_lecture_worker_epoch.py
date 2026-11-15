from datetime import datetime, timedelta, timezone

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
    LectureStepGuardError, assert_review_entry_allowed,
)
from app.core.execution import ExecutionFence, execution_fence
from app.db.shared.models import GenerationJobORM
from app.models.shared.persistence import BeginStepCommand, CreateRunCommand, canonical_hash
from tests.fakes.persistence import sqlite_repository


def test_dispatch_epoch_is_independent_of_run_write_version(tmp_path):
    repo, engine = sqlite_repository(tmp_path)
    now = datetime.now(timezone.utc)
    lease = now + timedelta(hours=1)
    try:
        repo.create_run(CreateRunCommand(run_id="epoch-test", request_snapshot={},
            request_hash=canonical_hash({}), owner_instance_id="worker", lease_expires_at=lease))
        repo.start_run("epoch-test", occurred_at=now, lease_expires_at=lease)
        repo.begin_step(BeginStepCommand(run_id="epoch-test", step_id="review", step_sequence=1,
            node_name="reviewer", agent_name="reviewer", action="review", lease_expires_at=lease))
        with repo.session_factory() as db:
            db.add(GenerationJobORM(run_id="epoch-test", batch_id="batch", learner_id="test",
                topic="test", status="running", claim_owner="worker", claim_epoch=1,
                lease_expires_at=lease))
            db.commit()
        assert repo.get_run("epoch-test").row_version > 1
        def check(epoch):
            with execution_fence(ExecutionFence("epoch-test", "worker", epoch)):
                assert_review_entry_allowed(repository=repo, run_id="epoch-test",
                    step_id="review", generation_attempt=1)
        check(1)
        with repo.session_factory() as db:
            db.get(GenerationJobORM, "epoch-test").claim_epoch = 2
            db.commit()
        with pytest.raises(LectureStepGuardError, match="epoch"):
            check(1)
        check(2)
        with repo.session_factory() as db:
            db.get(GenerationJobORM, "epoch-test").lease_expires_at = now - timedelta(seconds=1)
            db.commit()
        with pytest.raises(LectureStepGuardError, match="epoch"):
            check(2)
    finally:
        engine.dispose()
