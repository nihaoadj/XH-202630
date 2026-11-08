"""Projection boundaries: round history pagination and the report's current primary."""

from app.db.audit.memory import MemoryAuditRepository
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.questionnaire.memory import MemoryQuestionnaireRepository
from app.models.learning_documents.schemas import GenerateRequest
from app.services.learners.history import LearningHistoryService
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService
from tests.integration.services.test_round_generation import create_payload, dual_round, fixture


def history_for(service):
    return LearningHistoryService(
        ProfileService(service.learners), MemoryQuestionnaireRepository(), MemoryDiagnosisRepository(),
        service.feedback.generation_job_service.job_repo, MemoryFeedbackRepository(),
        feedback_loop_repo=service.feedback.feedback_loop_repo, resource_repo=service.feedback.resource_repo,
        audit_repo=MemoryAuditRepository(), knowledge_service=service.feedback.mastery_service.knowledge_service,
        round_service=service,
    )


def legacy_job(service, run_id, batch_id):
    job_repo = service.feedback.generation_job_service.job_repo
    job_repo.create(
        run_id=run_id, batch_id=batch_id, learner_id="learner", topic="legacy",
        knowledge_base_id="kb",
        request_payload=GenerateRequest(learner_id="learner", knowledge_base_id="kb", topic="legacy",
                                        target_skill_nodes=["b"], resource_types=["讲义"]).model_dump(mode="json"),
    )
    # created_at is owned by the repository clock; a distinct batch still keeps
    # the two projections independently addressable.
    return job_repo.get(run_id)


def test_history_pages_rounds_and_legacy_batches_without_duplicates():
    service, profile = fixture()
    created = service.create(profile, create_payload())
    legacy_job(service, "legacy-run", "legacy-batch")

    history = history_for(service)
    page = history.journey("learner", offset=0, limit=20)

    assert [item.round_id for item in page.learning_rounds] == [created.round_id]
    assert [item.round_id for item in page.rounds] == ["legacy-batch"]
    assert page.total_rounds == 2

    first = history.journey("learner", offset=0, limit=1)
    second = history.journey("learner", offset=1, limit=1)
    seen = [item.round_id for item in first.learning_rounds] + [item.round_id for item in first.rounds]
    seen += [item.round_id for item in second.learning_rounds] + [item.round_id for item in second.rounds]
    assert sorted(seen) == sorted(["legacy-batch", created.round_id])
    assert first.next_offset == 1
    assert second.next_offset is None


def test_round_jobs_never_appear_as_a_second_legacy_batch():
    service, profile = fixture()
    created = service.create(profile, create_payload())
    run_id = created.members[0].job_ids[0]

    page = history_for(service).journey("learner", offset=0, limit=20)

    assert page.rounds == []
    assert all(run_id not in item.run_ids for item in page.rounds)
    assert page.learning_rounds[0].round_id == created.round_id


def test_report_current_targets_use_the_latest_round_primary_only():
    service, profile = fixture()
    newest = dual_round(service, profile)
    report = ReportService(
        resource_repo=service.feedback.resource_repo, feedback_repo=MemoryFeedbackRepository(),
        feedback_loop_repo=service.feedback.feedback_loop_repo,
        generation_job_repo=service.feedback.generation_job_service.job_repo,
        round_service=service,
    )

    assert report._latest_active_batch_target_ids(service.learners.get("learner")) == {"b"}
    assert newest.primary_node_id == "b"
    assert [member.role for member in newest.members] == ["primary", "review"]


def test_report_targets_fall_back_only_when_no_round_exists():
    service, profile = fixture()
    report = ReportService(
        resource_repo=service.feedback.resource_repo, feedback_repo=MemoryFeedbackRepository(),
        feedback_loop_repo=service.feedback.feedback_loop_repo,
        generation_job_repo=service.feedback.generation_job_service.job_repo,
        round_service=service,
    )

    # Without any round the legacy projection keeps its own "no active batch"
    # result instead of inventing a primary.
    assert not report._latest_active_batch_target_ids(service.learners.get("learner"))
