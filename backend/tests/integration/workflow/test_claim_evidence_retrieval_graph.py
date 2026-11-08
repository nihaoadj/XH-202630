"""Compiled-graph proof of the open supplement branch (H05).

The real ``build_workflow`` graph runs with its real review, claim-extraction,
judge, supplement and decision nodes on file-SQLite persistence; only the LLM
gateway, the KB retriever and the resource agent are scripted.  The chain
proves on the compiled graph (not node-direct calls): first supported+missing
judgement → batch query → scripted KB recall → rejudge of the missing claim
only → still-missing targeted claim revision → child re-review and Claim
recheck → publication.

Two lost-fixture lessons are baked in (the original handoff file was deleted
before H05 closed):
1. the frozen resource-review execution identity binds the reviewer model, so
   the scripted gateway must report the frozen ``settings.llm_model`` — a
   mismatched gateway fails the review closed (by design, not a bug);
2. a claim-only revision delivers the typed ``context.claim_review_revision``
   input, not ``constraints["resource_revision"]`` — keying the fake agent on
   the wrong field made the "revised" content identical, the gap stayed open
   and the run correctly ended in ``human_review``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.resource_workflows.learning_documents import generator_agent as resource_generator_module
from app.agents.resource_workflows.learning_documents import workflow as workflow_module
from app.agents.resource_agents.base import GeneratedArtifact, ResourceArtifactMetadata
from app.config import get_settings
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.claim.supplement import SQLClaimSupplementRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, KnowledgeBaseORM, LearnerProfileORM
from app.models.knowledge.knowledge import RetrievalStatus
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.reviews.claim_evidence_retrieval import ClaimEvidenceRetrievalStatus
from app.services.generation import generation as generation_module
from app.services.generation.generation import GenerationService
from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder
from tests.fakes.evidence import ScriptedEvidenceRetriever, make_available_batch, make_evidence
from app.core.llm.gateway import LLMGateway
from app.models.reviews.claim_extraction import OfflineClaimGateway
from app.models.shared.llm import RawLLMResponse, LLMUsage
from tests.fakes.claim_extraction import NeutralScriptedTransport

BASE_EVIDENCE_ID = "ev-base-rag"
SUPPLEMENT_EVIDENCE_ID = "ev-supplement-patrol"

INITIAL_CONTENT = "RAG 系统通过向量检索召回文档片段。RAG 系统的召回率必须达到 99%。"
REVISED_CONTENT = "RAG 系统通过向量检索召回文档片段。企业向量库需要每周巡检一次。"

BASE_EXCERPT = "RAG 系统通过向量检索从企业知识库召回相关文档片段。"
SUPPLEMENT_EXCERPT = "企业向量库需要每周巡检一次，并记录巡检结果。"


def _learner() -> LearnerProfile:
    return LearnerProfile(
        learner_id="learner-graph", learner_type="测试", education="本科",
        major="测试", learning_goal="验证补检全链路", knowledge_base_id="kb-fixture",
    )


def _request() -> GenerateRequest:
    return GenerateRequest(
        learner_id="learner-graph", topic="RAG 评估", knowledge_base_id="kb-fixture",
        resource_types=["讲义"], include_review=True, include_claim_check=True,
        include_claim_evidence_retrieval=True, target_skill_nodes=["skill-rag"],
        profile_focus_mode="off", max_iterations=1, claim_max_iterations=1,
    )


def _supplement_batch():
    evidence = make_evidence(
        knowledge_base_id="kb-fixture", document_id="doc-new",
        document_version="docv-new", chunk_id="chunk-new",
        evidence_id=SUPPLEMENT_EVIDENCE_ID, excerpt=SUPPLEMENT_EXCERPT,
        query="企业向量库 巡检", rank=1,
    )
    return make_available_batch([evidence])


def _scripted_extraction(call):
    """Neutral-v2 extraction: copy the scripted sentences verbatim."""

    payload = json.loads(call["messages"][1].content)
    units = []
    for unit in payload["target_units"]:
        text = unit["text"]
        claims = []
        for marker in ("向量检索召回文档片段", "召回率必须达到", "每周巡检"):
            start = text.find(marker)
            if start < 0:
                continue
            end = text.find("。", start)
            if end < 0:
                continue
            sentence = text[start:end + 1]
            claims.append({
                "claim_text": sentence, "claim_type": "factual",
                "source_text": sentence, "knowledge_point_id": "skill-rag",
            })
        units.append({
            "unit_id": unit["unit_id"],
            "status": "claims" if claims else "structure",
            "reason": "scripted" if claims else "no factual unit",
            "claims": claims,
        })
    return {
        "schema_version": "2.0",
        "resource_id": payload["resource_id"],
        "resource_version": payload["resource_version"],
        "content_hash": payload["content_hash"],
        "batch_id": payload["batch_id"],
        "units": units,
    }


def _scripted_judge(call):
    """Round 0: the 99% claim is missing; round 2: the revised claims hold."""

    payload = json.loads(call["messages"][1].content)
    judgements = []
    for claim in payload["claims"]:
        if claim["resource_version"] == 1 and "召回率必须达到" in claim["claim_text"]:
            judgements.append({
                "claim_id": claim["claim_id"], "verdict": "not_in_evidence",
                "evidence_ids": [], "reason": "初始证据不含召回率阈值条款",
                "confidence": 0.9,
            })
        elif "每周巡检" in claim["claim_text"]:
            judgements.append({
                "claim_id": claim["claim_id"], "verdict": "supported",
                "evidence_ids": [SUPPLEMENT_EVIDENCE_ID],
                "reason": "补证摘录包含巡检要求", "confidence": 0.9,
            })
        else:
            judgements.append({
                "claim_id": claim["claim_id"], "verdict": "supported",
                "evidence_ids": [BASE_EVIDENCE_ID],
                "reason": "冻结证据支持", "confidence": 0.9,
            })
    return {"judgements": judgements}


def _scripted_query(call):
    payload = json.loads(call["messages"][1].content)
    return {
        "batch_id": payload["batch_id"], "input_hash": payload["input_hash"],
        "items": [
            {
                "claim_id": item["claim_id"],
                "queries": [{"text": "企业向量库 巡检"}],
            }
            for item in payload["claims"]
        ],
    }


def _scripted_rejudge(call):
    payload = json.loads(call["messages"][1].content)
    judgements = []
    for claim in payload["claims"]:
        if "召回率必须达到" in claim["claim_text"]:
            judgements.append({
                "claim_id": claim["claim_id"], "verdict": "not_in_evidence",
                "evidence_ids": [], "reason": "补证摘录仍不含召回率阈值条款",
                "confidence": 0.9,
            })
    return {"judgements": judgements}


def _scripted_review(_call):
    return {
        "decision": "approve", "hallucination_score": 0.0, "issues": [],
        "difficulty_match": True, "coverage_rate": 1.0, "suggestion": "离线固定通过",
        "revision_instructions": [],
    }


def _scripted_resource_review(call):
    """resource_issue_v1 engine response: echo the frozen binding, approve."""

    payload = json.loads(call["messages"][1].content)
    return {
        "binding": payload["binding"],
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass",
                       "self_contained": "pass"},
        "targets": [
            {"target": name, "status": "covered", "reason": "脚本化通过",
             "location": {"kind": "root"}}
            for name in payload["targets"]
        ],
        "hallucination_score": 0.0,
        "issues": [], "resolutions": [], "reopen": [],
        "omitted_blocking_issues": False, "findings": [],
    }


def _scripted_diagnosis(_call):
    return {"ability_tags": [], "weak_points": [], "recommended_difficulty": "初级", "suggestion": "ok"}


def _scripted_plan(_call):
    return {
        "learning_path": [{"order": 1, "topic": "skill-rag", "reason": "ok"}],
        "skip_points": [], "remedial_points": [], "challenge_points": [],
        "resource_requirements": {}, "decision_reason": "ok",
    }


def _router():
    """Dispatch scripted outcomes by the frozen schema name of each call."""

    def plan(schema_name, call):
        if schema_name == "DiagnosisLLMOutput":
            return _scripted_diagnosis(call)
        if schema_name == "PlannerLLMOutput":
            return _scripted_plan(call)
        if schema_name == "ReviewLLMOutput":
            return _scripted_review(call)
        if schema_name in {"ResourceReviewInitialV1", "ResourceReviewRecheckV1"}:
            return _scripted_resource_review(call)
        if schema_name == "BatchOutputV2":
            return _scripted_extraction(call)
        if schema_name == "ClaimJudgementLLMOutput":
            return _scripted_judge(call)
        if schema_name == "ClaimQueryBatchOutputV1":
            return _scripted_query(call)
        if schema_name == "ClaimSupplementJudgementLLMOutput":
            return _scripted_rejudge(call)
        raise AssertionError(f"unexpected scripted schema {schema_name}")

    seen = []

    def route(call):
        seen.append(call["context"].schema_name)
        return plan(call["context"].schema_name, call)

    return route, seen


@pytest.fixture()
def stores(tmp_path):
    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{tmp_path / 'h05-graph.db'}"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    resources = SQLResourceRepository(factory)
    claims = SQLClaimRepository(factory)
    supplement = SQLClaimSupplementRepository(
        claim_repository=claims, audit_repository=audit, session_factory=factory)
    return audit, resources, claims, supplement, factory


def _service(monkeypatch, *, gateway, retriever, audit, resources, claims, supplement):
    monkeypatch.setattr(
        generation_module, "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )
    seen_generation = []

    def agent_generate(spec, context, **kwargs):
        revision = context.claim_review_revision is not None or (
            (context.constraints or {}).get("resource_revision") is not None
        )
        seen_generation.append({
            "evidence": [item.evidence_id for item in context.evidence],
            "supplement": list(context.supplement_evidence_ids),
            "revision": revision,
        })
        cited = list(spec.evidence_ids)
        if revision and context.supplement_evidence_ids:
            cited = list(dict.fromkeys([*cited, *context.supplement_evidence_ids]))
        return GeneratedArtifact(
            metadata=ResourceArtifactMetadata(
                resource_spec_id=spec.resource_spec_id,
                resource_family_id=spec.resource_family_id,
                resource_type="讲义", representation="text", agent_name="frozen",
                prompt_version="1", artifact_format="markdown",
                source_evidence_ids=cited),
            difficulty="初级", mime_type="text/markdown",
            content_text=REVISED_CONTENT if revision else INITIAL_CONTENT,
            knowledge_points=spec.knowledge_points,
        )

    monkeypatch.setattr(
        resource_generator_module, "get_resource_agent",
        lambda _: SimpleNamespace(agent_name="frozen", prompt_version="1",
                                  artifact_format="markdown", generate=agent_generate),
    )
    graph = workflow_module.build_workflow(
        llm_gateway=gateway, evidence_retriever=retriever,
        lifecycle_repository=audit,
        resource_progress_recorder=WorkflowArtifactRecorder(resources, audit, claims),
        claim_repository=claims, supplement_repository=supplement,
    )
    service = GenerationService(
        resources, graph, audit, claim_repo=claims, supplement_repository=supplement,
    )
    return service, seen_generation


def test_compiled_graph_runs_supplement_revision_and_child_review(
    monkeypatch, stores, tmp_path,
):
    audit, resources, claims, supplement, factory = stores
    route, seen_schemas = _router()
    # The frozen resource-review execution identity binds the reviewer model:
    # the scripted gateway must report the same model the service froze at
    # submission time, otherwise the review engine fails closed (by design).
    class GraphGateway(OfflineClaimGateway, LLMGateway):
        pass

    def transport_route(call):
        name = call["output_schema"].__name__
        if "binding" in call["output_schema"].model_fields and "targets" in call["output_schema"].model_fields:
            name = "ResourceReviewInitialV1"
        result = route({**call, "context": SimpleNamespace(schema_name=name)})
        return RawLLMResponse(content=json.dumps(result, ensure_ascii=False),
                              usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                              finish_reason="stop")

    gateway = GraphGateway(NeutralScriptedTransport([transport_route] * 40, model_name=get_settings().llm_model))
    base_evidence = make_evidence(
        knowledge_base_id="kb-fixture", evidence_id=BASE_EVIDENCE_ID,
        excerpt=BASE_EXCERPT, query="RAG 检索", rank=1,
    )
    retriever = ScriptedEvidenceRetriever([
        make_available_batch([base_evidence]),
        _supplement_batch(),
    ])
    service, seen_generation = _service(
        monkeypatch, gateway=gateway, retriever=retriever, audit=audit,
        resources=resources, claims=claims, supplement=supplement,
    )

    learner = _learner()
    request = _request()
    with factory() as db:
        db.add(KnowledgeBaseORM(knowledge_base_id="kb-fixture", name="synthetic"))
        db.add(LearnerProfileORM(
            learner_id="learner-graph", learner_type="测试", education="本科",
            major="测试", learning_goal="验证补检全链路"))
        db.commit()

    response = service.generate_with_run_id(learner, request, run_id="run-graph")

    # The whole chain ran on the compiled graph: query and rejudge are real
    # node calls, not helper-assembled state.
    assert response.workflow_status == "completed", response.error_codes
    assert "ClaimQueryBatchOutputV1" in seen_schemas
    assert "ClaimSupplementJudgementLLMOutput" in seen_schemas

    # The supplement evidence reached the revision generator input, and the
    # revised artifact actually cites it.
    assert len(seen_generation) == 2
    assert seen_generation[0]["revision"] is False
    assert SUPPLEMENT_EVIDENCE_ID not in seen_generation[0]["evidence"]
    assert seen_generation[1]["revision"] is True
    assert SUPPLEMENT_EVIDENCE_ID in seen_generation[1]["supplement"]
    assert SUPPLEMENT_EVIDENCE_ID in seen_generation[1]["evidence"]

    # The published resource is the revised child version citing both the base
    # and the supplement evidence.
    published = [item for item in response.resources if item.publication_status == "published"]
    assert len(published) == 1
    child = published[0]
    assert child.version == 2 and child.parent_resource_id
    cited_ids = {ref.evidence_id for ref in child.source_refs}
    assert SUPPLEMENT_EVIDENCE_ID in cited_ids
    assert BASE_EVIDENCE_ID in cited_ids
    assert child.content_text == REVISED_CONTENT
    assert child.claim_metric_status == "complete"
    assert child.claim_factual_pass_rate == 1.0

    # The original version keeps its content and was never published by the
    # new round: only the child version is public.
    saved = {item.resource_id: item for item in resources.list_by_run("run-graph")}
    parent = saved[child.parent_resource_id]
    assert parent.version == 1 and parent.content_text == INITIAL_CONTENT
    assert parent.publication_status == "unpublished"
    assert BASE_EVIDENCE_ID in {ref.evidence_id for ref in parent.source_refs}
    assert SUPPLEMENT_EVIDENCE_ID not in {
        ref.evidence_id for ref in parent.source_refs
    }

    # Exactly one session for the one missing factual claim; the supported
    # sibling was never rejudged.
    sessions = supplement.list_sessions(["run-graph"])
    assert len(sessions) == 1
    session = sessions[0]
    assert session.status is ClaimEvidenceRetrievalStatus.COMPLETED
    assert session.active is True and session.hard_block is False
    assert len(session.target_claim_ids) == 1
    target_claim_id = session.target_claim_ids[0]
    supplements = [
        item for item in supplement.list_supplements(["run-graph"])
        if item.session_id == session.session_id
    ]
    assert [item.claim_id for item in supplements] == [target_claim_id]
    assert supplements[0].verdict.value == "not_in_evidence"

    # The activated audit scope keeps the parent chain to the retrieval scope.
    scopes = supplement.list_evidence_sets(["run-graph"])
    purposes = {item.purpose: item for item in scopes}
    assert purposes["audit"].parent_scope_id is None
    generation_scope = purposes["generation"]
    assert generation_scope.parent_scope_id == purposes["audit"].scope_id
    assert SUPPLEMENT_EVIDENCE_ID in generation_scope.added_evidence_ids

    # Frozen budget accounting: one query call + one rejudge call, one attempt
    # each, and the scripted query count landed on the ledger.
    ledger = supplement.get_run("run-graph")
    assert ledger is not None
    assert ledger.logical_calls == 2
    assert ledger.attempts == 2
    assert ledger.query_count == 1

    # Round-0 supported claim text was re-extracted on the child version, and
    # the effective child metric covers both factual claims without dropping
    # the denominator.
    child_claims = [
        item for item in claims.list_claims_by_run("run-graph")
        if item.resource_version == 2
    ]
    assert len(child_claims) == 2


def test_failed_graph_retries_twice_through_real_jobs_with_frozen_supplements(monkeypatch, stores):
    from app.db.generation.memory import MemoryGenerationJobRepository
    from app.services.generation.jobs import GenerationJobService
    from app.models.learning_documents.schemas import GenerateRequest

    audit, resources, claims, supplement, factory = stores
    route, schemas = _router()
    def send(call):
        schema = call["output_schema"]
        name = schema.__name__
        if "binding" in schema.model_fields and "targets" in schema.model_fields:
            name = "ResourceReviewInitialV1"
        if name == "ClaimJudgementLLMOutput":
            data = json.loads(call["messages"][1].content)
            records = []
            for claim in data["claims"]:
                patrol = "每周巡检" in claim["claim_text"]
                absent = "召回率必须达到" in claim["claim_text"]
                excerpt = "每周巡检" if patrol else "向量检索"
                refs = [item["evidence_id"] for item in data["allowed_evidence"] if excerpt in item["excerpt"]]
                records.append({"claim_id": claim["claim_id"],
                                "verdict": "not_in_evidence" if absent else "contradicted" if patrol else "supported",
                                "evidence_ids": [] if absent else refs[:1],
                                "reason": "离线固定持续失败情形" if patrol else "离线冻结依据", "confidence": 0.9})
            output = {"judgements": records}
        else:
            output = route({**call, "context": SimpleNamespace(schema_name=name)})
        return RawLLMResponse(content=json.dumps(output, ensure_ascii=False), finish_reason="stop",
                              usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15))
    class GraphGateway(OfflineClaimGateway, LLMGateway):
        pass
    gateway = GraphGateway(NeutralScriptedTransport([send] * 100, model_name=get_settings().llm_model))
    base = make_evidence(knowledge_base_id="kb-fixture", evidence_id=BASE_EVIDENCE_ID,
                         excerpt=BASE_EXCERPT, query="RAG 检索", rank=1)
    retriever = ScriptedEvidenceRetriever([make_available_batch([base]), _supplement_batch()])
    service, generated = _service(monkeypatch, gateway=gateway, retriever=retriever, audit=audit,
                                  resources=resources, claims=claims, supplement=supplement)
    learner, request = _learner(), _request()
    with factory() as db:
        db.add(KnowledgeBaseORM(knowledge_base_id="kb-fixture", name="synthetic"))
        db.add(LearnerProfileORM(learner_id=learner.learner_id, learner_type="测试", education="本科",
                                 major="测试", learning_goal=learner.learning_goal))
        db.commit()
    job_repo = MemoryGenerationJobRepository()
    jobs = GenerationJobService(job_repo, service)
    source = "run-failure-chain"
    jobs.create_job(learner, request, run_id=source)
    assert job_repo.get_dispatch(source)["dispatch_snapshot"]["claim_evidence_retrieval_policy_hash"]
    snapshots = []
    for index in range(3):
        jobs.run_job(learner, request, source)
        job = job_repo.get(source)
        assert job.job_status == "completed", job.error_message
        current = resources.list_by_run(source)
        assert current and all(item.publication_status == "unpublished" for item in current)
        latest = max(current, key=lambda item: item.version)
        evidence = audit.list_evidence(source)
        assert any("每周巡检" in item.excerpt for item in evidence)
        allowed = {item.evidence_id for item in evidence}
        assert all(set(item.evidence_ids) <= allowed for item in claims.list_judgements_by_run(source))
        snapshots.append((source, [item.model_dump(mode="json") for item in evidence], latest))
        if index == 2:
            break
        new_job, request = jobs.create_resource_retry(learner, source, latest.resource_spec_id, "text")
        assert new_job.run_id != source
        dispatch = job_repo.get_dispatch(new_job.run_id)["dispatch_snapshot"]
        assert dispatch["claim_evidence_retrieval_policy_hash"]
        assert dispatch["resource_retry_context"]["source_run_id"] == source
        if index == 0:
            assert dispatch["resource_retry_context"]["supplement_context"]["evidence"]
        assert GenerateRequest.model_validate(job_repo.get(new_job.run_id).request_payload) == request
        source = new_job.run_id
    assert len({run for run, _, _ in snapshots}) == 3
    assert len(retriever.calls) == 2  # both retries skip upstream retrieve and do not invent missing claims
    for run, frozen, _ in snapshots:
        assert [item.model_dump(mode="json") for item in audit.list_evidence(run)] == frozen
    assert all(not resources.get(item.resource_id).published_at for _, _, item in snapshots)
