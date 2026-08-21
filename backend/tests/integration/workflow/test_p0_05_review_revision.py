from datetime import datetime, timezone

import pytest

from app.agents.generator import generate_node
from app.agents.reviewer import review_node
from app.agents.resource_spec_builder import build_resource_specs
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
    specs = build_resource_specs(
        run_id="run-targeted-revision",
        resource_types=["讲义", "分阶测试题"],
        topic="RAG",
        difficulty="初级",
        learning_plan={},
        evidence=[evidence],
        target_skill_nodes=["检索"],
    )
    previous_tutorial = _resource(
        "tutorial-v1",
        "讲义",
        source_refs=source_refs_from_evidence([evidence]),
        resource_spec_id=specs[0].resource_spec_id,
        resource_family_id=specs[0].resource_family_id,
    )
    previous_assessment = _resource(
        "assessment-v1",
        "分阶测试题",
        source_refs=source_refs_from_evidence([evidence]),
        resource_spec_id=specs[1].resource_spec_id,
        resource_family_id=specs[1].resource_family_id,
    )
    gateway = ScriptedLLMGateway([
        "# RAG 讲义\n\n## 学习目标\n\n讲义 v2，已补充边界"
    ])
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
            "resource_types": ["讲义", "分阶测试题"],
            "target_skill_nodes": ["检索"],
            "resource_specs": [item.model_dump(mode="json") for item in specs],
            "retrieved_evidence": [evidence],
            "generated_resources": [previous_tutorial, previous_assessment],
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
    assert by_type["分阶测试题"].resource_id == "assessment-v1"
    assert result["trace"][0]["resource_ids"] == [by_type["讲义"].resource_id]


def test_revision_review_only_rechecks_the_new_target_version():
    """An assessment revision must not create replacement reviews for siblings."""

    evidence = make_evidence(knowledge_base_id="kb-p0-05")
    approved_lecture = _resource(
        "lecture-v1",
        "讲义",
        source_refs=source_refs_from_evidence([evidence]),
        review_status="approved",
        review_id="lecture-review-v1",
        publication_status="published",
    )
    revised_assessment = _resource(
        "assessment-v2",
        "分阶测试题",
        source_refs=source_refs_from_evidence([evidence]),
        review_status="pending_review",
        parent_resource_id="assessment-v1",
        version=2,
    )
    gateway = ScriptedLLMGateway([{
        "decision": "approve",
        "hallucination_score": 0.0,
        "issues": [],
        "difficulty_match": True,
        "coverage_rate": 1.0,
        "suggestion": "修订版符合要求。",
        "revision_instructions": [],
    }])

    result = review_node(
        {
            "schema_version": "1.0",
            "run_id": "run-assessment-revision-review",
            "learner_id": "p0-05-learner",
            "learner": LearnerProfile(
                learner_id="p0-05-learner", learner_type="学生", education="本科",
                major="计算机", skill_level="初级", learning_goal="学习 RAG",
            ),
            "topic": "RAG",
            "retrieved_evidence": [evidence],
            "generated_resources": [approved_lecture, revised_assessment],
            "resource_executions": [
                {"resource_id": approved_lecture.resource_id, "resource_type": "讲义",
                 "representation": "text", "resource_execution_state": "approved"},
                {"resource_id": revised_assessment.resource_id, "resource_type": "分阶测试题",
                 "representation": "text", "resource_execution_state": "generated"},
            ],
            "generation_attempt": 2,
            "revision_count": 1,
            "include_claim_check": False,
            "trace": [],
        },
        llm_gateway=gateway,
    )

    assert len(gateway.calls) == 1
    reviewed = {item.resource_id: item for item in result["generated_resources"]}
    assert reviewed["lecture-v1"].review_id == "lecture-review-v1"
    assert reviewed["lecture-v1"].review_status == "approved"
    assert reviewed["assessment-v2"].review_status == "approved"
    assert set(result["review_result"]["review_ids"]) == {"assessment-v2"}


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
