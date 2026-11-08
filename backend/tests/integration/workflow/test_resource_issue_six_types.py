"""Generic six-type generation, revision, recheck, Claim and HTTP reading regression."""

import json
import copy
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone
from app.core.execution import ExecutionFence, execution_fence
from app.agents.shared.recorded_node import RecordedNode
from app.db.audit.memory import MemoryAuditRepository
from app.models.shared.persistence import (
    CreateRunCommand,
    canonical_hash,
    build_checkpoint_projection,
)
from app.models.reviews.resource_review_policy import (
    ResourceReviewPolicyV1,
    policy_hash,
    execution_identity_fields,
)
from app.agents.resource_workflows.learning_documents.workflow import (
    prepare_revision_node,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.assessment import (
    assessment_questions,
)
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.resource_agents.checklist import ReviewChecklistAgent
from app.agents.resource_workflows.learning_documents import generator_agent
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node,
    claim_judge_node,
    claim_decide_node,
)
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.api.learning_documents import documents
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.shared.agent_contracts import (
    GeneratedArtifact,
    ResourceArtifactMetadata,
)
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for, case
from tests.unit.agents.test_resource_type_agents import (
    _inputs,
    CHECKLIST_PAYLOAD,
    CASE_STUDY_MARKDOWN,
)
from app.core.retrieval.evidence import source_refs_from_evidence


@pytest.mark.parametrize(
    "kind",
    ["讲义", "实操指南", "分阶测试题", "案例分析", "复习清单", "个性化纠错训练包"],
)
def test_generic_six_types_revision_claim_publication_markdown(kind, monkeypatch):
    sample = case("assessment.clean.01") if kind == "分阶测试题" else case()
    state = state_for(sample)
    source = state["generated_resources"][0]
    if kind == "分阶测试题":
        from app.agents.resource_agents.assessment import render_assessment_markdown

        source = source.model_copy(
            update={
                "content_text": render_assessment_markdown(source.assessment_payload)
            }
        )
    if kind in {"讲义", "案例分析", "个性化纠错训练包"}:
        source = source.model_copy(
            update={
                "resource_type": kind,
                "practice_guide_payload": None,
                "practice_guide_payload_hash": None,
                "content_text": "# 讲义\n\n冻结证据支持这个教学示例。"
                if kind == "讲义"
                else CASE_STUDY_MARKDOWN
                if kind == "案例分析"
                else "# 纠错练习\n\n可信的补救概念与练习。",
            }
        )
    elif kind == "复习清单":
        spec, context, evidence = _inputs("复习清单")
        artifact = ReviewChecklistAgent().generate(
            spec, context, llm_gateway=ScriptedLLMGateway([CHECKLIST_PAYLOAD])
        )
        state["retrieved_evidence"] = [evidence]
        source = LearningResource(
            resource_id="checklist",
            resource_type=kind,
            difficulty="初级",
            content_text=artifact.content_text,
            knowledge_points=["skill-search"],
            review_practice_payload=artifact.artifact_data["review_practice_package"],
            source_refs=source_refs_from_evidence([evidence]),
        )
    learner = LearnerProfile(
        learner_id="five-types",
        learner_type="测试",
        education="本科",
        major="测试",
        learning_goal="冻结流程验收",
    )
    state.update(
        learner=learner,
        topic="合成教学",
        resource_types=[kind],
        target_skill_nodes=source.knowledge_points,
        generated_resources=[],
        include_review=True,
        include_claim_check=True,
        max_iterations=2,
        claim_max_iterations=1,
    )
    if kind == "个性化纠错训练包":
        state["learning_plan"] = {
            "correction_focus_snapshot": {
                "ordered_target_nodes": [
                    {"skill_node_id": node} for node in source.knowledge_points
                ]
            }
        }

    generation_count = 0

    def generate(spec, context, **kwargs):
        nonlocal generation_count
        generation_count += 1
        artifact_source = source
        if kind == "分阶测试题" and generation_count > 1:
            # Change the actual generated package, so only the parent index can
            # resolve the old question identifier in a false-positive closure.
            package = copy.deepcopy(source.assessment_payload)
            package["node_blocks"][0]["single_choice_questions"][0]["question_id"] += (
                "-v2"
            )
            artifact_source = source.model_copy(
                update={
                    "assessment_payload": package,
                    "content_text": render_assessment_markdown(package),
                }
            )
        return GeneratedArtifact(
            metadata=ResourceArtifactMetadata(
                resource_spec_id=spec.resource_spec_id,
                resource_family_id=spec.resource_family_id,
                resource_type=kind,
                representation="text",
                agent_name="frozen",
                prompt_version="1",
                artifact_format="markdown",
                source_evidence_ids=spec.evidence_ids,
            ),
            difficulty="初级",
            mime_type="text/markdown",
            content_text=artifact_source.content_text,
            knowledge_points=source.knowledge_points,
            artifact_data={
                key: value
                for key, value in {
                    "practice_guide_package": artifact_source.practice_guide_payload,
                    "assessment_package": artifact_source.assessment_payload,
                    "review_practice_package": artifact_source.review_practice_payload,
                }.items()
                if value
            },
        )

    agent = SimpleNamespace(
        agent_name="frozen",
        prompt_version="1",
        artifact_format="markdown",
        generate=generate,
    )
    monkeypatch.setattr(generator_agent, "get_resource_agent", lambda _: agent)
    policy = ResourceReviewPolicyV1(
        context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2
    ).model_dump(mode="json")
    state.update(
        **execution_identity_fields("fake-model"),
        resource_review_contract_version="1.1",
        resource_review_policy=policy,
        resource_review_policy_hash=policy_hash(policy),
        resource_ledgers={},
        resource_revision={},
    )
    state.update(
        generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([]))
    )
    generated = state["generated_resources"][0]
    assert (
        generated.resource_type == kind and generated.review_status == "pending_review"
    )
    audit = MemoryAuditRepository()
    now = datetime.now(timezone.utc)
    frozen = {
        key: state[key]
        for key in (
            "resource_review_contract_version",
            "resource_review_policy",
            "resource_review_policy_hash",
            "resource_review_identity",
            "resource_review_identity_hash",
            "review_policy",
        )
    }
    audit.create_run(
        CreateRunCommand(
            run_id=state["run_id"],
            request_snapshot=frozen,
            request_hash=canonical_hash(frozen),
            owner_instance_id="six-owner",
            lease_expires_at=now + timedelta(hours=1),
        )
    )
    audit.start_run(
        state["run_id"], occurred_at=now, lease_expires_at=now + timedelta(hours=1)
    )

    def answer(call, blocking=False):
        payload = json.loads(call["messages"][1].content)
        output = {
            "binding": payload["binding"],
            "dimensions": {
                "factual_evidence": "pass",
                "difficulty": "pass",
                "self_contained": "fail" if blocking else "pass",
            },
            "targets": [
                {
                    "target": t,
                    "status": "covered",
                    "reason": "完整材料",
                    "location": {"kind": "root"},
                }
                for t in payload["targets"]
            ],
            "hallucination_score": 0.0,
            "issues": [],
            "omitted_blocking_issues": False,
        }
        if kind == "分阶测试题":
            output["findings"] = [
                {
                    "question_id": q["question_id"],
                    "scope_decision": "in_scope",
                    "supported_evidence_ids": q["evidence_ids"][:1],
                    "answer_check": "pass",
                    "clarity_check": "pass",
                    "rubric_check": "not_applicable"
                    if q["question_type"] in {"single_choice", "multiple_choice"}
                    else "pass",
                    "reason": "完整检查",
                }
                for q in assessment_questions(payload["structured_payload"])
            ]
        if blocking:
            output["issues"] = [
                {
                    "issue_id": "temporary",
                    "code": "structure_quality",
                    "severity": "high",
                    "blocking": True,
                    "blocking_rule": "self_contained",
                    "dimension": "self_contained",
                    "location": {"kind": "root"},
                    "impact": "材料需核对",
                    "requirement": "核对材料",
                    "acceptance": "材料已提供",
                    "criteria_version": 1,
                    "path": "reorganize_existing",
                    "teaching_rule_id": "self_contained",
                    "executability": "executable",
                    "rationale": "材料核对",
                }
            ]
        else:
            if kind == "分阶测试题":
                assert (
                    payload["previous_structured_payload"] == source.assessment_payload
                )
                old_question = assessment_questions(source.assessment_payload)[0][
                    "question_id"
                ]
                assert old_question in payload["previous_location_index"]["unit_ids"]
                assert old_question not in payload["location_index"]["unit_ids"]
                assert (
                    payload["previous_binding"]["artifact_exact_hash"]
                    == state["resource_ledgers"][spec_id]["binding"][
                        "artifact_exact_hash"
                    ]
                )
            output["resolutions"] = [
                {
                    "issue_id": old_id,
                    "result": "false_positive",
                    "reason": "父版已有完整材料",
                    "previous_location": {"kind": "structured", "unit_id": old_question}
                    if kind == "分阶测试题"
                    else {"kind": "root"},
                }
            ]
        return output

    review_traces = []

    def review(blocking):
        state["trace"] = list(review_traces)
        gateway = ScriptedLLMGateway([lambda call: answer(call, blocking)])
        with execution_fence(ExecutionFence(state["run_id"], "six-owner")):
            update = RecordedNode(
                "review",
                lambda current: review_node(
                    current, llm_gateway=gateway, review_repository=audit
                ),
                audit,
            )(state)
        previous_trace = state.get("trace", [])
        state.update(update)
        state["trace"] = [*previous_trace, *update["trace"]]
        review_traces[:] = state["trace"]
        trace = state["trace"][-1]
        projection = build_checkpoint_projection(state)
        audit.save_checkpoint(
            run_id=state["run_id"],
            step_id=trace["step_id"],
            step_sequence=trace["sequence"],
            node_name="review",
            state_projection=projection,
            state_hash=canonical_hash(projection),
            occurred_at=datetime.now(timezone.utc),
        )
        assert len(gateway.calls) == 1, (
            state.get("resource_stop_reasons"),
            state.get("review_result"),
            state.get("errors"),
            [
                row["issue"]["requirement"]
                for ledger in state.get("resource_ledgers", {}).values()
                for row in ledger["issues"]
            ],
        )

    review(True)
    assert state["review_result"]["decision"] == "revise"
    spec_id = state["generated_resources"][0].resource_spec_id
    old_id = state["resource_ledgers"][spec_id]["issues"][0]["issue"]["issue_id"]
    state.update(prepare_revision_node(state))
    state.update(
        generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([]))
    )
    assert state["generated_resources"][0].version == generated.version + 1
    if kind == "分阶测试题":
        invalid = copy.deepcopy(state)
        invalid["resource_revision"][spec_id]["previous_structured_payload"][
            "node_blocks"
        ][0]["single_choice_questions"][0]["stem"] += "篡改"
        unused_gateway = ScriptedLLMGateway([])
        with execution_fence(ExecutionFence(state["run_id"], "six-owner")):
            rejected = review_node(
                invalid, llm_gateway=unused_gateway, review_repository=audit
            )
        assert not unused_gateway.calls
        assert rejected["review_result"]["decision"] != "approve"
        assert rejected["errors"]
    review(False)
    assert state["resource_ledgers"][spec_id]["issues"][0]["status"] == "closed", (
        state.get("resource_stop_reasons"),
        state.get("review_result"),
        state.get("errors"),
    )
    assert len(state["resource_ledgers"][spec_id]["observations"]) == 2
    assert (
        audit.get_step_review_audit(
            state["run_id"], state["trace"][-1]["step_id"]
        ).schema_version
        == "4.0"
    )

    assert state["review_result"]["decision"] == "approve"

    def extract(call):
        payload = json.loads(call["messages"][1].content)
        resource = payload["resources"][0]
        content = state["generated_resources"][0].content_text
        text = next(
            (
                line.strip()
                for line in content.splitlines()
                if len(line.strip()) > 10 and not line.lstrip().startswith("#")
            ),
            content,
        )[:80]
        start = content.index(text)
        return {
            "resources": [
                {
                    "resource_id": resource["resource_id"],
                    "claims": [
                        {
                            "claim_text": text,
                            "claim_type": "factual",
                            "source_text": text,
                            "source_start": start,
                            "source_end": start + len(text),
                            "knowledge_point_id": source.knowledge_points[0],
                            "source_evidence_ids": [
                                payload["allowed_evidence"][0]["evidence_id"]
                            ],
                        }
                    ],
                }
            ]
        }

    state.update(claim_extract_node(state, llm_gateway=ScriptedLLMGateway([extract])))

    def judge(call):
        payload = json.loads(call["messages"][1].content)
        return {
            "judgements": [
                {
                    "claim_id": claim["claim_id"],
                    "verdict": "supported",
                    "evidence_ids": [payload["allowed_evidence"][0]["evidence_id"]],
                    "reason": "冻结证据支持",
                    "confidence": 0.99,
                }
                for claim in payload["claims"]
            ]
        }

    state.update(claim_judge_node(state, llm_gateway=ScriptedLLMGateway([judge])))
    state.update(claim_decide_node(state))
    state.update(decide_node(state))
    resource = state["generated_resources"][0]
    assert resource.publication_status == "published"
    assert resource.claim_metric_status == (
        "not_applicable" if kind == "分阶测试题" else "complete"
    )
    repo = MemoryResourceRepository()
    repo.save(resource, learner.learner_id, "合成教学")
    profiles = MemoryLearnerRepository()
    profiles.save(learner)
    app = FastAPI()
    app.container = SimpleNamespace(
        resource_service=lambda: ResourceService(repo),
        profile_service=lambda: ProfileService(profiles),
    )
    app.include_router(documents.router, prefix="/api/resources")
    response = TestClient(app).get("/api/resources/items/" + resource.resource_id)
    assert response.status_code == 200
    assert response.json()["resource"]["content_text"] == resource.content_text
    if kind != "分阶测试题":
        assert (
            resource.content_text
            == generated.content_text
            == source.content_text.strip()
        )
    else:
        assert "q-001-v2" in resource.content_text
    assert response.json()["resource"]["mime_type"] == "text/markdown"
