from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.tutor.base import TutorIdempotencyConflict
from app.db.tutor.memory import MemoryTutorRepository
from app.db.tutor.sql_repository import SQLTutorRepository
from app.models.tutor import TutorEvidenceRef, TutorSession, TutorTurn


def _session() -> TutorSession:
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    return TutorSession(
        session_id="tus_repo_1",
        learner_id="learner-1",
        source_type="batch",
        source_resource_id="resource-1",
        source_run_id="run-1",
        source_batch_id="batch-1",
        knowledge_base_id="kb-1",
        context_type="question_help",
        question_id="question-1",
        knowledge_point="rerank",
        created_at=now,
        updated_at=now,
    )


def _turn(*, request_hash: str = "1" * 64) -> TutorTurn:
    return TutorTurn(
        turn_id="tut_repo_1",
        session_id="tus_repo_1",
        sequence=1,
        client_message_id="client-message-1",
        request_hash=request_hash,
        user_message="为什么需要 rerank？",
        assistant_message="先想一想召回候选很多时会发生什么。",
        pedagogy_action="hint",
        hint_level=1,
        follow_up_question="候选很多时，Prompt 能全部容纳吗？",
        target_knowledge_points=["rerank"],
        grounding_status="grounded",
        grounding_source="frozen_evidence",
        evidence_refs=[
            TutorEvidenceRef(
                evidence_id="ev-1",
                title="RAG",
                snippet="Rerank 对候选结果重新排序。",
                grounding_source="frozen_evidence",
                score=0.9,
            )
        ],
        created_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )


@pytest.fixture(params=["memory", "sql"])
def repository(request):
    if request.param == "memory":
        return MemoryTutorRepository()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return SQLTutorRepository(sessionmaker(bind=engine))


def test_repository_persists_session_turn_and_progression(repository):
    repository.create_session(_session())
    stored = repository.append_turn(_turn())
    assert stored.turn_id == "tut_repo_1"
    assert repository.get_session("tus_repo_1").turn_count == 1
    assert repository.get_session("tus_repo_1").current_hint_level == 1
    assert repository.list_turns("tus_repo_1")[0].assistant_message.startswith("先想")
    assert repository.count_turns(
        "learner-1",
        source_batch_id="batch-1",
        context_type="question_help",
        question_id="question-1",
    ) == 1
    assert repository.count_turns(
        "learner-1",
        source_run_id="run-1",
        context_type="question_help",
        question_id="question-1",
    ) == 1
    assert repository.count_turns(
        "learner-1",
        source_run_id="run-1",
        context_type="question_help",
        created_before=datetime(2026, 8, 18, tzinfo=timezone.utc),
    ) == 0


def test_repository_idempotent_replay_and_conflict(repository):
    repository.create_session(_session())
    first = repository.append_turn(_turn())
    replay = repository.append_turn(_turn())
    assert replay.turn_id == first.turn_id
    assert repository.get_session("tus_repo_1").turn_count == 1

    with pytest.raises(TutorIdempotencyConflict):
        repository.append_turn(_turn(request_hash="2" * 64))


def test_repository_lists_and_closes_sessions(repository):
    repository.create_session(_session())
    assert repository.list_sessions(
        "learner-1",
        status="active",
        source_batch_id="batch-1",
    )[0].session_id == "tus_repo_1"
    closed_at = datetime(2026, 8, 19, 1, tzinfo=timezone.utc)
    closed = repository.update_session_state(
        "tus_repo_1",
        status="closed",
        closed_at=closed_at,
    )
    assert closed.status == "closed"
    assert closed.closed_at == closed_at
