"""Tests for resource-scoped interactive-courseware job creation."""

import pytest
from pydantic import ValidationError

from app.models.courseware import CoursewareBatchCreateRequest, CoursewareJobCreateRequest, CoursewareJobResponse
from app.services.courseware.service import CoursewareService
from app.agents.resource_workflows.interactive_courseware.workflow import (
    InteractiveCoursewareWorkflow,
    source_resource_type_from_projection,
)
from app.db.courseware.repository import MemoryCoursewareRepository


class _Workflow:
    def __init__(self):
        self.requests = []

    def create_job(self, request):
        self.requests.append(request)
        return CoursewareJobResponse(
            run_id=f"cw-{len(self.requests)}", learner_id=request.learner_id,
            status="queued", request_options={},
        )


class _ResourceService:
    def get(self, _resource_id):
        return None


def test_courseware_library_recovers_source_text_type_from_persisted_projection():
    assert source_resource_type_from_projection({
        "source_summary": [{"resource_id": "text-1", "resource_type": "讲义"}],
    }) == "讲义"
    assert source_resource_type_from_projection({}, [{
        "source_snapshot": '{"resource_type": "分阶测试题"}',
    }]) == "分阶测试题"


def test_single_job_contract_refuses_multiple_sources():
    with pytest.raises(ValidationError):
        CoursewareJobCreateRequest(learner_id="learner-1", source_resource_ids=["guide-1", "quiz-1"])


def test_batch_selection_fans_out_to_independent_single_source_jobs():
    workflow = _Workflow()
    service = CoursewareService(repo=object(), resource_service=object(), audit_repo=object(), workflow=workflow)

    result = service.create_jobs_for_resources(CoursewareBatchCreateRequest(
        learner_id="learner-1", resource_ids=["guide-1", "quiz-1"],
        interaction_intensity="high", idempotency_key="selection-42",
    ))

    assert [job.run_id for job in result.jobs] == ["cw-1", "cw-2"]
    assert [request.source_resource_ids for request in workflow.requests] == [["guide-1"], ["quiz-1"]]
    assert [request.idempotency_key for request in workflow.requests] == ["selection-42:0", "selection-42:1"]


def test_same_resource_can_create_multiple_new_courseware_versions_without_a_key():
    workflow = InteractiveCoursewareWorkflow(MemoryCoursewareRepository(), _ResourceService(), object())
    request = CoursewareJobCreateRequest(learner_id="learner-1", source_resource_ids=["guide-1"])

    first = workflow.create_job(request)
    second = workflow.create_job(request)

    assert first.run_id != second.run_id


def test_explicit_idempotency_key_still_reuses_the_same_submission():
    workflow = InteractiveCoursewareWorkflow(MemoryCoursewareRepository(), _ResourceService(), object())
    request = CoursewareJobCreateRequest(
        learner_id="learner-1", source_resource_ids=["guide-1"], idempotency_key="retry-request-1",
    )

    first = workflow.create_job(request)
    second = workflow.create_job(request)

    assert first.run_id == second.run_id
