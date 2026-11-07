"""The publication summary is a pure read model over existing repositories."""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.models import Base
from app.models.generation.progress import PublishCompleteness
from app.models.learning_documents.schemas import LearningResource
from app.services.learning_documents.publication_summary import load_publication_summary

RUN_ID = "run-t47"
PARENT_RUN_ID = "run-parent"
REQUEST = {"resource_types": ["讲义", "实操指南", "分阶测试题"]}


class RecordingRepository:
    """Delegate to a real repository and count read calls."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name):
        attribute = getattr(self._inner, name)
        if name in {"get", "list_specs_by_run", "list_executions_by_run", "list_by_run"}:
            def counted(*args, **kwargs):
                self.calls[name] += 1
                return attribute(*args, **kwargs)

            return counted
        return attribute

    @property
    def collection_reads(self) -> int:
        return sum(
            self.calls[name]
            for name in ("list_specs_by_run", "list_executions_by_run", "list_by_run")
        )


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield MemoryResourceRepository(), None
        return
    engine = create_engine(f"sqlite:///{tmp_path / 't47_publication.db'}")
    Base.metadata.create_all(engine)
    try:
        yield SQLResourceRepository(sessionmaker(bind=engine)), engine
    finally:
        engine.dispose()


def _seed(repository) -> None:
    for order, (spec_id, resource_type) in enumerate(
        (("spec-video", "讲义"), ("spec-practice", "实操指南"), ("spec-assessment", "分阶测试题"))
    ):
        repository.save_spec(ResourceSpecRecord(
            resource_spec_id=spec_id,
            run_id=RUN_ID,
            resource_type=resource_type,
            learning_objective=f"覆盖 {resource_type}",
            difficulty="初级",
            representations=[{"representation": "text"}],
            display_order=order,
        ))
    repository.save_spec(ResourceSpecRecord(
        resource_spec_id="spec-parent",
        run_id=PARENT_RUN_ID,
        resource_type="讲义",
        learning_objective="父 run 讲义",
        difficulty="初级",
        representations=[{"representation": "text"}],
    ))
    repository.upsert_execution(ResourceExecutionRecord(
        run_id=RUN_ID, resource_spec_id="spec-video", resource_type="讲义",
        state="approved", resource_id="res-video-v2", attempt=1,
        agent_name="TextResourceAgent", prompt_version="v1", artifact_format="markdown",
    ))
    repository.upsert_execution(ResourceExecutionRecord(
        run_id=RUN_ID, resource_spec_id="spec-practice", resource_type="实操指南",
        state="approved", resource_id="res-practice", attempt=1,
        agent_name="PracticeAgent", prompt_version="v1", artifact_format="markdown",
    ))
    repository.upsert_execution(ResourceExecutionRecord(
        run_id=RUN_ID, resource_spec_id="spec-assessment", resource_type="分阶测试题",
        state="failed", error_code="GENERATION_FAILED", attempt=1,
        agent_name="AssessmentAgent", prompt_version="v1", artifact_format="json",
    ))
    repository.save(
        LearningResource(
            resource_id="res-video-v1", resource_type="讲义", difficulty="初级",
            knowledge_points=["kp-1"], source_refs=[], run_id=RUN_ID,
            resource_spec_id="spec-video", representation="text", version=1,
            publication_status="published",
        ),
        learner_id="learner-1", topic="T47",
    )
    repository.save(
        LearningResource(
            resource_id="res-video-v2", resource_type="讲义", difficulty="初级",
            knowledge_points=["kp-1"], source_refs=[], run_id=RUN_ID,
            resource_spec_id="spec-video", representation="text", version=2,
            publication_status="unpublished", claim_publish_decision_pending=True,
        ),
        learner_id="learner-1", topic="T47",
    )
    repository.save(
        LearningResource(
            resource_id="res-practice", resource_type="实操指南", difficulty="初级",
            knowledge_points=["kp-1"], source_refs=[], run_id=RUN_ID,
            resource_spec_id="spec-practice", representation="text", version=1,
            publication_status="published",
        ),
        learner_id="learner-1", topic="T47",
    )
    repository.save(
        LearningResource(
            resource_id="res-parent", resource_type="讲义", difficulty="初级",
            knowledge_points=["kp-1"], source_refs=[], run_id=PARENT_RUN_ID,
            resource_spec_id="spec-parent", representation="text", version=1,
            publication_status="published",
        ),
        learner_id="learner-1", topic="T47",
    )


def _snapshot(repository) -> dict:
    return {
        "specs": [item.model_dump(mode="json") for item in repository.list_specs_by_run(RUN_ID)],
        "executions": [
            item.model_dump(mode="json") for item in repository.list_executions_by_run(RUN_ID)
        ],
        "resources": [item.model_dump(mode="json") for item in repository.list_by_run(RUN_ID)],
        "parent_resources": [
            item.model_dump(mode="json") for item in repository.list_by_run(PARENT_RUN_ID)
        ],
    }


def test_sql_and_memory_return_the_same_summary_and_write_nothing(repository):
    resource_repository, engine = repository
    _seed(resource_repository)
    before = _snapshot(resource_repository)

    statements: list[str] = []
    if engine is not None:
        def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            statements.append(statement.strip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", capture)
    try:
        summary = load_publication_summary(
            run_id=RUN_ID, request_payload=REQUEST, resource_repository=resource_repository
        )
    finally:
        if engine is not None:
            event.remove(engine, "before_cursor_execute", capture)

    if engine is not None:
        assert statements, "the load must actually query the database"
        assert not ({"INSERT", "UPDATE", "DELETE"} & set(statements)), statements

    assert _snapshot(resource_repository) == before
    assert summary.total == 3
    assert summary.published == 2
    assert summary.unpublished == 1
    assert summary.pending_review == 0
    assert summary.completeness is PublishCompleteness.COMPLETE
    assert summary.incomplete_reasons == []


def test_load_reads_each_collection_at_most_once_per_run(repository):
    resource_repository, _ = repository
    _seed(resource_repository)

    spy = RecordingRepository(resource_repository)
    load_publication_summary(run_id=RUN_ID, request_payload=REQUEST, resource_repository=spy)
    assert spy.calls["get"] == 0
    assert spy.calls["list_specs_by_run"] == 1
    assert spy.calls["list_executions_by_run"] == 1
    assert spy.calls["list_by_run"] == 1

    supplied = RecordingRepository(resource_repository)
    load_publication_summary(
        run_id=RUN_ID,
        request_payload=REQUEST,
        resource_repository=supplied,
        executions=resource_repository.list_executions_by_run(RUN_ID),
    )
    assert supplied.calls["get"] == 0
    assert supplied.collection_reads == 2

    paged = RecordingRepository(resource_repository)
    for _ in range(3):
        load_publication_summary(run_id=RUN_ID, request_payload=REQUEST, resource_repository=paged)
    assert paged.collection_reads <= 3 * 3
    assert paged.calls["get"] == 0


def test_missing_repository_is_unavailable_not_zero(repository):
    resource_repository, _ = repository
    _seed(resource_repository)
    summary = load_publication_summary(
        run_id=RUN_ID, request_payload=REQUEST, resource_repository=None
    )
    assert summary.total is None
    assert summary.published is None
    assert summary.pending_review is None
    assert summary.completeness is PublishCompleteness.UNAVAILABLE
    assert [reason.value for reason in summary.incomplete_reasons] == ["repository_unavailable"]


def test_repository_failure_propagates(repository):
    class BrokenRepository:
        def list_specs_by_run(self, run_id):
            raise RuntimeError("storage offline")

    with pytest.raises(RuntimeError, match="storage offline"):
        load_publication_summary(
            run_id=RUN_ID, request_payload=REQUEST, resource_repository=BrokenRepository()
        )


def test_wrong_slot_reference_does_not_duplicate_pending_or_write(repository):
    resource_repository, _ = repository
    _seed(resource_repository)
    current = resource_repository.get_execution(RUN_ID, "spec-practice", "text")
    assert current is not None
    wrong = current.model_copy(update={"resource_id": "res-video-v2"})
    resource_repository.upsert_execution(wrong)
    before = _snapshot(resource_repository)
    summary = load_publication_summary(
        run_id=RUN_ID, request_payload=REQUEST, resource_repository=resource_repository,
    )
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert "lineage_conflict" in [reason.value for reason in summary.incomplete_reasons]
    assert summary.pending_review is None
    assert summary.published == 2
    assert _snapshot(resource_repository) == before
