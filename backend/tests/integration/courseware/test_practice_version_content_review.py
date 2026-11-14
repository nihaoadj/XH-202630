"""New practice formats pass the real content-review registry and release gates."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.resource_workflows.interactive_courseware.content_review.lifecycle import verify_run_content
from app.db.courseware.models import Base
from app.db.courseware.repository import MemoryCoursewareRepository, SQLCoursewareRepository
from app.db.shared.models import LearnerProfileORM
from app.models.courseware.contracts import CoursewareJobCreateRequest
from app.models.courseware.content_review import ContentReviewBlocked
from tests.fakes.courseware_content_review import (
    ContentReviewGateway, fixture_environment, fixture_settings, make_workflow, resource,
)


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield MemoryCoursewareRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'practice.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(learner_id="content-learner", learner_type="test", education="test",
                                major="test", learning_goal="test", skill_level="初级"))
        db.commit()
    yield SQLCoursewareRepository(factory)
    engine.dispose()


def versioned_workflow(tmp_path, repository, version, **gateway_options):
    gateway = ContentReviewGateway("practice_code", **gateway_options)
    wf, source = make_workflow(tmp_path, "practice_code", repo=repository, gateway=gateway)
    versioned = resource("practice_code", practice_version=version)
    source.practice_guide_payload = versioned.practice_guide_payload
    source.practice_guide_payload_hash = versioned.practice_guide_payload_hash
    return wf, source


@pytest.mark.parametrize("version", ["3.0", "4.0", "5.0", "6.0"])
def test_content_review_enabled_practice_versions_publish_and_reverify(tmp_path, repository, version):
    with fixture_environment(tmp_path):
        wf, source = versioned_workflow(tmp_path, repository, version)
        job = wf.create_job(CoursewareJobCreateRequest(
            learner_id=source.learner_id, source_resource_ids=[source.resource_id],
        ))
        result = wf.run(job.run_id)
        assert result.status == "published", result.model_dump()
        stored = repository.get_job(job.run_id)
        assert stored["source_snapshots"][0]["practice_guide_payload"]["schema_version"] == version
        assert verify_run_content(repository, job.run_id)
        published = repository.get_resource_by_run(job.run_id)
        release = published["released_release_id"]
        assert release
        if version == "5.0":
            assert "输入记录" in wf.artifact(published["resource_id"])[1].decode("utf-8")
        # SQL re-reads via a fresh repository, not the original object/session.
        if isinstance(repository, SQLCoursewareRepository):
            assert verify_run_content(SQLCoursewareRepository(repository.session_factory), job.run_id)
        calls = len(wf.llm_gateway.calls)
        assert any(call["output_schema"].__name__ == "BatchResultV1" for call in wf.llm_gateway.calls)
        assert wf.run(job.run_id).status == "published"
        assert wf.publish(job.run_id).status == "published"
        assert len(wf.llm_gateway.calls) == calls
        assert repository.get_resource_by_run(job.run_id)["released_release_id"] == release


@pytest.mark.parametrize("strict", [False, True])
def test_v6_unavailable_content_review_is_explicitly_degraded_or_blocked(tmp_path, repository, strict):
    def incomplete(raw, _payload):
        raw["results"].pop()
        return raw

    settings = fixture_settings(courseware_release_policy="strict" if strict else "resilient")
    with fixture_environment(tmp_path, settings):
        wf, source = versioned_workflow(tmp_path, repository, "6.0", fault=incomplete)
        job = wf.create_job(CoursewareJobCreateRequest(
            learner_id=source.learner_id, source_resource_ids=[source.resource_id],
        ))
        result = wf.run(job.run_id)
        state = wf.content_review.state(job.run_id)
        assert state.record.status == ("blocked" if strict else "degraded")
        if strict:
            assert result.status == "quarantined"
        else:
            assert result.status == "published_with_warnings"
            assert state.record.approved_values == {} and state.record.reason
            assert verify_run_content(repository, job.run_id)
        assert result.status != "published"


def test_v6_source_code_tampering_blocks_reverified_release(tmp_path, repository):
    with fixture_environment(tmp_path):
        wf, source = versioned_workflow(tmp_path, repository, "6.0")
        job = wf.create_job(CoursewareJobCreateRequest(
            learner_id=source.learner_id, source_resource_ids=[source.resource_id],
        ))
        assert wf.run(job.run_id).status == "published"
        stored = repository.get_job(job.run_id)
        snapshots = stored["source_snapshots"]
        snapshots[0]["practice_guide_payload"]["practice"]["steps"][0]["code_blocks"][0]["code"] = "other = 2"
        repository.update_job(job.run_id, source_snapshots=snapshots)
        with pytest.raises(ContentReviewBlocked):
            verify_run_content(repository, job.run_id)
