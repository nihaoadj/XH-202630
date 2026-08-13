from datetime import datetime, timezone

import pytest

from app.agents.generator import generate_node
from app.agents.policies import decide_review, may_publish
from app.agents.validators import revision_instructions_are_valid
from app.core.evidence import source_refs_from_evidence
from app.db.audit.base import PersistenceConflict
from app.db.audit.memory import MemoryAuditRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.persistence import CreateRunCommand, canonical_hash
from app.models.schemas import LearnerProfile, LearningResource
from app.models.workflow import ReviewDecision
from app.services.run_query_service import RunQueryService
from app.services.workflow_artifact_recorder import WorkflowArtifactRecorder
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def _resource(resource_id: str, resource_type: str, **updates) -> LearningResource:
    values = {
        "resource_id": resource_id,
        "learner_id": "p0-05-learner",
        "topic": "RAG",
        "resource_type": resource_type,
        "difficulty": "初级",
        "content_text": f"{resource_type} v1",
        "knowledge_points": ["检索"],
        "source_refs": [],
    }
    values.update(updates)
    return LearningResource(**values)


def test_review_policy_fails_closed_and_requires_executable_revision():
    approve = {
        "decision": "approve",
        "hallucination_score": 0.0,
        "difficulty_match": True,
        "coverage_rate": 1.0,
        "issues": [],
        "revision_instructions": [],
    }
    assert decide_review(
        approve,
        valid_source_refs=True,
        valid_revision_instructions=False,
    ) == ReviewDecision.APPROVE
    assert decide_review(
        {**approve, "issues": [{"severity": "critical"}]},
        valid_source_refs=True,
        valid_revision_instructions=False,
    ) == ReviewDecision.HUMAN_REVIEW
    assert decide_review(
        {**approve, "decision": "revise"},
        valid_source_refs=True,
        valid_revision_instructions=False,
    ) == ReviewDecision.HUMAN_REVIEW
    assert may_publish(decision="approve", review_status="approved")
    assert not may_publish(decision="human_review", review_status="approved")


def test_revision_instruction_validator_rejects_unknown_targets():
    instruction = {
        "issue_codes": ["coverage_gap"],
        "target_resource_type": "讲义",
        "action": "补充失败边界",
        "priority": 1,
    }
    assert revision_instructions_are_valid([instruction], ["讲义", "练习"])
    assert not revision_instructions_are_valid(
        [{**instruction, "target_resource_type": "视频"}],
        ["讲义", "练习"],
    )


def test_generator_revision_only_creates_targeted_resource_version():
    evidence = make_evidence(knowledge_base_id="kb-p0-05")
    previous_tutorial = _resource(
        "tutorial-v1",
        "讲义",
        source_refs=source_refs_from_evidence([evidence]),
    )
    previous_exercise = _resource(
        "exercise-v1",
        "练习",
        source_refs=source_refs_from_evidence([evidence]),
    )
    gateway = ScriptedLLMGateway([{
        "resources": [{
            "resource_type": "讲义",
            "difficulty": "初级",
            "content_text": "讲义 v2，已补充边界",
            "knowledge_points": ["检索"],
        }],
    }])
    result = generate_node(
        {
            "schema_version": "1.0",
            "run_id": "run-targeted-revision",
            "learner_id": "p0-05-learner",
            "learner": LearnerProfile(
                learner_id="p0-05-learner",
                learner_type="学生",
                education="本科",
                major="计算机",
                skill_level="初级",
                learning_goal="学习 RAG",
            ),
            "topic": "RAG",
            "resource_types": ["讲义", "练习"],
            "retrieved_evidence": [evidence],
            "generated_resources": [previous_tutorial, previous_exercise],
            "review_result": {
                "revision_instructions": [{
                    "issue_codes": ["coverage_gap"],
                    "target_resource_type": "讲义",
                    "action": "补充失败边界",
                    "priority": 1,
                }],
            },
            "include_review": True,
            "generation_attempt": 2,
            "revision_count": 1,
            "trace": [],
        },
        llm_gateway=gateway,
    )
    by_type = {resource.resource_type: resource for resource in result["generated_resources"]}
    assert by_type["讲义"].version == 2
    assert by_type["讲义"].parent_resource_id == "tutorial-v1"
    assert by_type["练习"].resource_id == "exercise-v1"
    assert result["trace"][0]["resource_ids"] == [by_type["讲义"].resource_id]


def test_resource_repository_enforces_immutability_and_publication_filter():
    repository = MemoryResourceRepository()
    draft = _resource("draft", "讲义")
    repository.save(draft, "p0-05-learner", "RAG", run_id="run-resource")
    assert repository.list_by_learner("p0-05-learner") == []
    published = draft.model_copy(
        update={
            "review_status": "approved",
            "publication_status": "published",
            "published_at": datetime.now(timezone.utc),
        }
    )
    repository.save(published, "p0-05-learner", "RAG", run_id="run-resource")
    assert [item.resource_id for item in repository.list_by_learner("p0-05-learner")] == ["draft"]
    with pytest.raises(PersistenceConflict):
        repository.save(
            published.model_copy(update={"content_text": "mutated"}),
            "p0-05-learner",
            "RAG",
            run_id="run-resource",
        )
    with pytest.raises(PersistenceConflict):
        repository.save(
            _resource("duplicate-v1", "讲义"),
            "p0-05-learner",
            "RAG",
            run_id="run-resource",
        )


def test_artifact_recorder_persists_versions_reviews_and_timeline():
    audit = MemoryAuditRepository()
    resources = MemoryResourceRepository()
    request = {"learner_id": "p0-05-learner", "topic": "RAG"}
    command = CreateRunCommand(
        run_id="run-artifacts",
        learner_id="p0-05-learner",
        topic="RAG",
        request_snapshot=request,
        request_hash=canonical_hash(request),
    )
    audit.create_run(command)
    audit.start_run(command.run_id, occurred_at=command.occurred_at)
    recorder = WorkflowArtifactRecorder(resources, audit)
    resource = _resource("artifact-v1", "讲义")
    state = {
        "run_id": command.run_id,
        "learner_id": "p0-05-learner",
        "topic": "RAG",
        "current_node": "generator",
        "generated_resources": [resource],
    }
    recorder.record(
        state,
        {
            "step_id": "step-generator",
            "sequence": 1,
            "node_name": "generate",
            "agent_name": "generator",
            "resource_ids": [resource.resource_id],
        },
    )
    review = {
        "decision": "revise",
        "status": "revise",
        "review_ids": {resource.resource_id: "review-v1"},
        "revision_count": 0,
        "hallucination_score": 0.3,
        "difficulty_match": True,
        "issues": [{"code": "coverage_gap", "severity": "medium"}],
        "revision_instructions": [{
            "issue_codes": ["coverage_gap"],
            "target_resource_type": "讲义",
            "action": "补充边界",
            "priority": 1,
        }],
    }
    recorder.record(
        {**state, "current_node": "reviewer", "review_result": review},
        {
            "step_id": "step-reviewer",
            "sequence": 2,
            "node_name": "review",
            "agent_name": "reviewer",
            "review_ids": ["review-v1"],
        },
    )
    assert resources.list_by_run(command.run_id)[0].review_status == "revision_requested"
    assert audit.list_reviews_by_run(command.run_id)[0]["revision_instructions"][0]["action"] == "补充边界"
    timeline = RunQueryService(audit, resources).get_timeline(command.run_id)
    assert timeline.resource_versions[0]["resource_id"] == resource.resource_id
    assert timeline.reviews[0]["review_id"] == "review-v1"
