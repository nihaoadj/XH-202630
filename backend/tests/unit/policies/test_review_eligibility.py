"""Review eligibility: published material plus a formal learning assessment."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.learners.review_eligibility import eligible_review_ids


def profile(knowledge_base_id="kb"):
    return LearnerProfile(learner_id="learner", learner_type="test", education="test", major="test",
                          knowledge_base_id=knowledge_base_id, learning_goal="test")


def environment():
    jobs = MemoryGenerationJobRepository()
    resources = MemoryResourceRepository()
    return jobs, resources


def add_run(jobs, run_id, learner_id="learner", knowledge_base_id="kb", nodes=("a",)):
    jobs.create(run_id=run_id, batch_id=run_id, learner_id=learner_id, topic="topic",
                knowledge_base_id=knowledge_base_id, request_payload=GenerateRequest(
                    learner_id=learner_id, knowledge_base_id=knowledge_base_id, topic="topic",
                    target_skill_nodes=list(nodes), resource_types=["讲义"]).model_dump(mode="json"))


def add_resource(resources, run_id, resource_type="讲义", status="published", node="a", learner_id="learner"):
    resource = LearningResource(resource_id=f"resource-{run_id}-{resource_type}", learner_id=learner_id, topic="topic",
                                resource_type=resource_type, difficulty="初级", content_text="fixture",
                                knowledge_points=[node], source_refs=[], learning_path_node=node,
                                publication_status=status, run_id=run_id, batch_id=run_id)
    resources.save(resource, learner_id=learner_id, topic="topic")
    return resource


def attempt(run_id, node="a", kind="learning_check", total=1, learner_id="learner"):
    return SimpleNamespace(
        learner_id=learner_id, source_run_id=run_id, submitted_at=datetime.now(timezone.utc),
        metadata={"assessment_kind": kind},
        knowledge_point_results=[SimpleNamespace(knowledge_point_id=node, total_count=total, score=0.5)],
    )


def eligible(jobs, resources, attempts, learner=None):
    return eligible_review_ids(learner or profile(), resources,
                               SimpleNamespace(list_attempts=lambda learner_id, limit: attempts), jobs)


def test_published_resource_and_formal_assessment_are_both_required():
    jobs, resources = environment()
    add_run(jobs, "run-a")
    add_resource(resources, "run-a")

    assert eligible(jobs, resources, []) == set()
    assert eligible(jobs, resources, [attempt("run-a")]) == {"a"}

    other = environment()
    add_run(other[0], "run-a")
    add_resource(other[1], "run-a", status="unpublished")
    assert eligible(*other, [attempt("run-a")]) == set()


def test_initial_diagnosis_self_assessment_and_other_direction_do_not_qualify():
    jobs, resources = environment()
    add_run(jobs, "run-a")
    add_resource(resources, "run-a")

    assert eligible(jobs, resources, [attempt("run-a", kind="initial_diagnosis")]) == set()
    assert eligible(jobs, resources, [attempt("run-a", kind="self_assessment")]) == set()

    foreign = environment()
    add_run(foreign[0], "run-a", knowledge_base_id="other")
    add_resource(foreign[1], "run-a")
    assert eligible(*foreign, [attempt("run-a")]) == set()


def test_assessment_without_any_scored_question_does_not_qualify_a_node():
    jobs, resources = environment()
    add_run(jobs, "run-a")
    add_resource(resources, "run-a")

    assert eligible(jobs, resources, [attempt("run-a", total=0)]) == set()


def test_reassessment_of_a_review_node_keeps_it_qualified():
    jobs, resources = environment()
    add_run(jobs, "run-a", nodes=("a", "b"))
    add_resource(resources, "run-a", node="b")
    add_resource(resources, "run-a", resource_type="复习清单", node="b")

    assert eligible(jobs, resources, [attempt("run-a", node="b", kind="reassessment")]) == {"b"}
