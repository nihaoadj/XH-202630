from app.db.generation.memory import MemoryGenerationJobRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.services.generation.jobs import GenerationJobService


class _RecordingGenerationService:
    def __init__(self):
        self.calls = []

    def generate_with_run_id(self, learner, request, *, run_id, batch_id):
        self.calls.append((learner.learner_id, request.topic, run_id, batch_id))

        class _Response:
            resources = []

        return _Response()


def test_retry_can_create_a_new_run_in_the_existing_resource_batch():
    learner = LearnerProfile(
        learner_id="batch_learner",
        learner_type="test",
        education="本科",
        major="软件工程",
        knowledge_base_id="rag_engineering_training",
        learning_goal="掌握 RAG",
    )
    request = GenerateRequest(
        learner_id=learner.learner_id,
        topic="RAG 工程链路",
        knowledge_base_id=learner.knowledge_base_id,
        resource_types=["讲义"],
    )
    repository = MemoryGenerationJobRepository()
    generator = _RecordingGenerationService()
    service = GenerationJobService(repository, generator)

    first = service.create_job(learner, request, run_id="run_first")
    retry = service.create_job(learner, request, run_id="run_retry", batch_id=first.batch_id)
    service.run_job(learner, request, retry.run_id, retry.batch_id)

    assert first.batch_id == "run_first"
    assert retry.run_id == "run_retry"
    assert retry.batch_id == first.batch_id
    assert generator.calls == [(learner.learner_id, request.topic, "run_retry", "run_first")]
