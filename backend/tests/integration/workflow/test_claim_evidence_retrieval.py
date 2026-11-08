"""Workflow-level proof of the optional Claim evidence retrieval feature."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.nodes import (
    claim_evidence_rejudge_node,
    claim_evidence_retrieve_node,
)
from app.agents.resource_workflows.learning_documents.workflow import (
    claim_decide_node,
    route_after_claim_evidence_retrieve,
    route_after_initial_claim_judge,
)
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.supplement import (
    MemoryClaimSupplementRepository,
    SupplementBudgetExceeded,
)
from app.core.retrieval.knowledge_ids import evidence_id, query_hash, sha256_hex
from app.models.knowledge.knowledge import EvidenceBatch, EvidenceItem, RetrievalStatus, ScoreKind, SourceLocator, SourceType
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalStatus,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimJudgeType,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.shared.agent_contracts import bind_recorded_step_context, reset_recorded_step_context
from app.models.shared.llm import LLMCallOptions, LLMCallResult, LLMUsage, StructuredOutputMode
from app.models.shared.persistence import BeginStepCommand, CreateRunCommand, canonical_hash
from app.core.llm.structured_output import parse_structured_output
from tests.fakes.evidence import ScriptedEvidenceRetriever

NOW = datetime.now(timezone.utc)
STEP_ID = "step-supplement"


def policy() -> ClaimEvidenceRetrievalPolicyV1:
    return ClaimEvidenceRetrievalPolicyV1(
        query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
        rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
    )


class ObserverGateway:
    """Scripted gateway that honours the AttemptObserver contract."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.model_name = "fake-model"
        self.transport = SimpleNamespace(
            model_name="fake-model",
            settings=SimpleNamespace(llm_base_url="offline", llm_thinking_mode="disabled"),
        )

    def options_for(self, node_name, *, temperature=0.0, max_output_tokens=None, request_timeout_seconds=None):
        return LLMCallOptions(
            max_attempts=1, temperature=temperature,
            max_output_tokens=max_output_tokens or 4096,
            request_timeout_seconds=request_timeout_seconds or 30.0,
            structured_output_mode=StructuredOutputMode.TEXT,
        )

    def invoke_structured(self, **kwargs):
        self.calls.append(kwargs)
        observer = kwargs.get("attempt_observer")
        context = kwargs["context"]
        ticket = observer.before_attempt(
            context, 1, kwargs["messages"], kwargs["output_schema"],
            StructuredOutputMode.TEXT, kwargs["options"].max_output_tokens,
            kwargs["options"].request_timeout_seconds,
        ) if observer is not None else None
        if observer is not None and hasattr(observer, "on_dispatch"):
            observer.on_dispatch(ticket)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            if observer is not None:
                observer.on_attempt_error(ticket, outcome, 1)
            raise outcome
        if callable(outcome):
            outcome = outcome(kwargs)
        output = parse_structured_output(outcome, kwargs["output_schema"])
        usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        result = LLMCallResult(
            output=output, call_id=context.call_id, model_name=self.model_name,
            provider_request_id="fake", structured_output_mode=StructuredOutputMode.TEXT,
            attempt_count=1, retry_count=0, latency_ms=2, finish_reason="stop",
            usage=usage, attempts=[],
        )
        if observer is not None:
            observer.after_attempt(ticket, result, 2)
        return result


def _locator(
    chunk_id: str, *, document_id: str = "doc-new", document_version: str = "v2",
) -> SourceLocator:
    return SourceLocator(
        knowledge_base_id="kb-fixture", document_id=document_id,
        document_version=document_version,
        chunk_id=chunk_id, source_type=SourceType.MARKDOWN, source_path="docs/new.md",
        title="new.md", section="2",
    )


def _new_evidence(
    chunk_id: str, excerpt: str, query: str, rank: int = 1, *,
    document_id: str = "doc-new", document_version: str = "v2",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id(
            run_id="run-claim", step_id=STEP_ID, knowledge_base_id="kb-fixture",
            retrieval_query_hash=query_hash(query), knowledge_chunk_id=chunk_id,
            config_hash="9" * 64, excerpt_identity=sha256_hex(f"{rank}:{excerpt}"),
        ),
        knowledge_base_id="kb-fixture", document_id=document_id,
        document_version=document_version,
        chunk_id=chunk_id, query=query, query_hash=query_hash(query),
        query_rank=1, rank=rank, raw_score=0.1, score_kind=ScoreKind.DISTANCE,
        normalized_score=0.9, excerpt=excerpt, excerpt_hash=sha256_hex(excerpt),
        locator=_locator(
            chunk_id, document_id=document_id, document_version=document_version,
        ),
        config_hash="9" * 64, retrieved_at=NOW,
    )


def _claim(index: int, text: str, content: str, start: int) -> ClaimRecord:
    return ClaimRecord(
        claim_id="clm_" + f"{index:032x}",
        run_id="run-claim", resource_id="res-claim", resource_version=1,
        review_id="review-claim", claim_index=index,
        claim_text=text, claim_type=ClaimType.FACTUAL,
        source_text=text, source_start=start, source_end=start + len(text),
        source_text_hash=sha256_hex(text), extractor_prompt_version="p0-06-extract-v3",
        claim_hash="b" * 64, created_at=NOW,
    )


def _judgement(claim: ClaimRecord, verdict: ClaimVerdict) -> ClaimJudgement:
    return ClaimJudgement(
        judgement_id="jdg_" + claim.claim_id[4:],
        claim_id=claim.claim_id, run_id=claim.run_id, resource_id=claim.resource_id,
        resource_version=1, review_id=claim.review_id,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-base"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} else [],
        reason="round0", judge_type=ClaimJudgeType.LLM,
        judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
    )


def _state(*, with_policy: bool = True) -> dict:
    content = "Python 使用缩进定义代码块。RAG 召回率不应低于 95%。"
    first = _claim(1, "Python 使用缩进定义代码块", content, 0)
    second = _claim(2, "RAG 召回率不应低于 95%", content, content.index("RAG"))
    resource = LearningResource(
        resource_id="res-claim", resource_type="讲义", difficulty="初级",
        content_text=content, knowledge_points=["skill-python"], source_refs=[],
        run_id="run-claim", version=1, review_id="review-claim",
    )
    base = EvidenceItem(
        evidence_id="ev-base", knowledge_base_id="kb-fixture",
        document_id="doc-fixture", document_version="docv-fixture", chunk_id="chunk-fixture",
        query="base", query_hash=query_hash("base"), query_rank=1, rank=1,
        raw_score=0.2, score_kind=ScoreKind.DISTANCE, normalized_score=0.9,
        excerpt="可信知识片段", excerpt_hash=sha256_hex("可信知识片段"),
        locator=SourceLocator(
            knowledge_base_id="kb-fixture", document_id="doc-fixture",
            document_version="docv-fixture", chunk_id="chunk-fixture",
            source_type=SourceType.MARKDOWN, source_path="source.md",
            title="Fixture", section="Fixture",
        ),
        config_hash="2" * 64, retrieved_at=NOW,
    )
    state = {
        "schema_version": "1.0",
        "run_id": "run-claim",
        "generation_attempt": 1,
        "workflow_deadline_at": NOW + timedelta(seconds=900),
        "knowledge_base_id": "kb-fixture",
        "target_skill_nodes": ["skill-python"],
        "retrieved_evidence": [base],
        "resource_specs": [],
        "generated_resources": [resource],
        "extracted_claims": [first.model_dump(mode="json"), second.model_dump(mode="json")],
        "claim_judgements": [
            _judgement(first, ClaimVerdict.SUPPORTED).model_dump(mode="json"),
            _judgement(second, ClaimVerdict.NOT_IN_EVIDENCE).model_dump(mode="json"),
        ],
        "claim_metrics": {},
        "claim_check_status": "completed",
        "claim_failed_resource_ids": [],
        "claim_eligible_resource_ids": ["res-claim"],
        "review_result": {
            "decision": "approve", "status": "approve",
            "review_ids": {"res-claim": "review-claim"},
            "issues": [], "revision_instructions": [], "hallucination_score": 0.1,
        },
        "include_review": True,
        "include_claim_check": True,
        "trace": [],
        "errors": [],
    }
    if with_policy:
        state["include_claim_evidence_retrieval"] = True
        state["claim_evidence_retrieval_policy"] = policy().model_dump(mode="json")
        state["claim_evidence_retrieval_policy_hash"] = policy().policy_hash
    return state


@pytest.fixture()
def storage():
    audit = MemoryAuditRepository()
    claim_repo = MemoryClaimRepository()
    audit.create_run(CreateRunCommand(
        run_id="run-claim", learner_id="learner-1", knowledge_base_id="kb-fixture",
        topic="RAG", request_snapshot={"topic": "RAG", "include_claim_check": True},
        request_hash=canonical_hash({"topic": "RAG", "include_claim_check": True}),
        occurred_at=NOW,
    ))
    audit.start_run("run-claim", occurred_at=NOW)
    audit.begin_step(BeginStepCommand(
        run_id="run-claim", step_id=STEP_ID, step_sequence=1,
        node_name="claim_evidence_retrieve", agent_name="claim_evidence_retrieval",
        action="Claim 缺证补检", generation_attempt=1, started_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=600),
    ))
    supplement = MemoryClaimSupplementRepository(
        claim_repository=claim_repo, audit_repository=audit,
    )
    return audit, claim_repo, supplement


def _call_retrieve(state, storage, gateway, retriever):
    audit, claim_repo, supplement = storage
    token = bind_recorded_step_context({
        "step_id": STEP_ID, "sequence": 1, "attempt": 1,
        "started_at": NOW, "node_name": "claim_evidence_retrieve",
    })
    try:
        return claim_evidence_retrieve_node(
            state, llm_gateway=gateway, evidence_retriever=retriever,
            supplement_repository=supplement, claim_repository=claim_repo,
            audit_repository=audit,
        )
    finally:
        reset_recorded_step_context(token)


def _call_rejudge(state, storage, gateway):
    audit, claim_repo, supplement = storage
    token = bind_recorded_step_context({
        "step_id": STEP_ID, "sequence": 1, "attempt": 1,
        "started_at": NOW, "node_name": "claim_evidence_retrieve",
    })
    try:
        return claim_evidence_rejudge_node(
            state, llm_gateway=gateway, supplement_repository=supplement,
            claim_repository=claim_repo, audit_repository=audit,
        )
    finally:
        reset_recorded_step_context(token)


def test_router_only_enters_supplements_for_enabled_complete_rounds():
    state = _state()
    assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"

    closed = _state(with_policy=False)
    assert route_after_initial_claim_judge(closed) == "claim_decide"

    failed = {**_state(), "claim_failed_resource_ids": ["res-claim"]}
    assert route_after_initial_claim_judge(failed) == "claim_decide"

    incomplete = {**_state(), "claim_check_status": "failed"}
    assert route_after_initial_claim_judge(incomplete) == "claim_decide"


def test_supported_round_one_activates_and_keeps_other_claims(storage):
    state = _state()
    claim_id = state["extracted_claims"][1]["claim_id"]
    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}],
        }

    gateway = ObserverGateway([query_outcome])

    new_item = _new_evidence("chunk-new", "RAG 召回率不得低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])

    retrieved = _call_retrieve(state, storage, gateway, retriever)
    state.update(retrieved)
    assert route_after_claim_evidence_retrieve(state) == "claim_evidence_rejudge"
    audit, claim_repo, supplement = storage
    session = supplement.list_sessions(["run-claim"])[0]
    assert session.status is ClaimEvidenceRetrievalStatus.REJUDGING

    # Replace the rejudge outcome with the real evidence id now that it exists.
    gateway.outcomes = [{"judgements": [{
        "claim_id": claim_id, "verdict": "supported",
        "evidence_ids": [new_item.evidence_id],
        "reason": "补充证据支持", "confidence": 0.9,
    }]}]
    rejudged = _call_rejudge(state, storage, gateway)
    state.update(rejudged)

    session = supplement.list_sessions(["run-claim"])[0]
    assert session.status is ClaimEvidenceRetrievalStatus.COMPLETED
    assert session.active is True
    verdicts = {item["claim_id"]: item["verdict"] for item in state["claim_judgements"]}
    assert verdicts[claim_id] == "supported"
    # The originally supported Claim was never rejudged or rewritten.
    original_id = state["extracted_claims"][0]["claim_id"]
    assert verdicts[original_id] == "supported"
    assert len(supplement.list_supplements(["run-claim"])) == 1
    assert supplement.list_evidence_sets(["run-claim"])[0].purpose == "audit"
    metric = state["claim_metrics"]["res-claim"]
    assert metric["factual_claim_total"] == 2
    assert metric["supported_claim_total"] == 2
    assert state["claim_evidence_hard_block_resource_ids"] == []
    # Text and round-0 rows are untouched.
    assert state["generated_resources"][0].content_text == "Python 使用缩进定义代码块。RAG 召回率不应低于 95%。"
    assert [item["verdict"] for item in state["claim_judgements"] if item["claim_id"] == original_id] == ["supported"]

    decided = claim_decide_node(state)
    assert decided["review_result"]["decision"] == "approve"


def test_counter_evidence_blocks_the_version_and_forces_revision(storage):
    state = _state()
    claim_id = state["extracted_claims"][1]["claim_id"]
    gateway = ObserverGateway([])

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}],
        }

    gateway.outcomes = [query_outcome]
    new_item = _new_evidence("chunk-new", "RAG 召回率可以低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])
    state.update(_call_retrieve(state, storage, gateway, retriever))

    gateway.outcomes = [{"judgements": [{
        "claim_id": claim_id, "verdict": "contradicted",
        "evidence_ids": [new_item.evidence_id],
        "reason": "新增证据给出相反结论", "confidence": 0.9,
    }]}]
    state.update(_call_rejudge(state, storage, gateway))

    _, _, supplement = storage
    session = supplement.list_sessions(["run-claim"])[0]
    assert session.hard_block is True
    assert session.status is ClaimEvidenceRetrievalStatus.BLOCKED
    assert state["claim_evidence_hard_block_resource_ids"] == ["res-claim"]

    decided = claim_decide_node(state)
    assert decided["review_result"]["decision"] == "revise"
    assert any(
        issue.get("code") == "factual_risk"
        for issue in decided["review_result"]["issues"]
        if issue.get("resource_id") == "res-claim"
    )


def test_no_new_evidence_skips_rejudgment(storage):
    state = _state()
    claim_id = state["extracted_claims"][1]["claim_id"]
    gateway = ObserverGateway([])

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "base"}]}],
        }

    gateway.outcomes = [query_outcome]
    # The retriever returns the same content identity as the frozen base pool.
    same = _new_evidence(
        "chunk-fixture", "可信知识片段", "base",
        document_id="doc-fixture", document_version="docv-fixture",
    )
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[same], query_hashes=[query_hash("base")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])

    state.update(_call_retrieve(state, storage, gateway, retriever))
    _, _, supplement = storage
    session = supplement.list_sessions(["run-claim"])[0]
    assert session.status is ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE
    assert route_after_claim_evidence_retrieve(state) == "claim_decide"
    # Still only the query call; no rejudge was attempted.
    assert len(gateway.calls) == 1

    decided = claim_decide_node(state)
    assert decided["review_result"]["decision"] == "revise"
    assert state["claim_evidence_hard_block_resource_ids"] == []


def test_activation_persists_the_effective_metric_and_survives_round_zero_replay(storage):
    """F02: the activated summary must describe the merged round-1 set.

    The first round supports one Claim and lacks evidence for another; after a
    supplement the version supports two.  The persisted review row, the workflow
    state and the supplement counter must all agree, and replaying the original
    round-0 review must not revert the activated metric.
    """

    state = _state()
    audit, claim_repo, supplement = storage
    review_id = audit.save_review(
        "res-claim",
        {
            "resource_id": "res-claim",
            "run_id": "run-claim",
            "review_id": "review-claim",
            "review_ids": {"res-claim": "review-claim"},
            "status": "approve",
            "claim_total": 2,
            "claim_supported": 1,
            "claim_unsupported": 1,
            "claim_hallucination_rate": 0.5,
            "claim_metric_status": "complete",
        },
        "run-claim",
    )
    claim_id = state["extracted_claims"][1]["claim_id"]

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}],
        }

    gateway = ObserverGateway([query_outcome])
    new_item = _new_evidence("chunk-new", "RAG 召回率不得低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])
    state.update(_call_retrieve(state, storage, gateway, retriever))
    gateway.outcomes = [{"judgements": [{
        "claim_id": claim_id, "verdict": "supported",
        "evidence_ids": [new_item.evidence_id],
        "reason": "补充证据支持", "confidence": 0.9,
    }]}]
    state.update(_call_rejudge(state, storage, gateway))

    persisted = audit.get_review_by_resource("res-claim")
    assert persisted.review_id == review_id
    assert persisted.claim_total == 2
    assert persisted.claim_supported == 2
    assert persisted.claim_unsupported == 0
    assert persisted.claim_hallucination_rate == 0.0
    assert persisted.claim_metric_status == "complete"
    metric = state["claim_metrics"]["res-claim"]
    assert metric["supported_claim_total"] == persisted.claim_supported
    assert metric["not_in_evidence_claim_total"] == 0

    # Replaying the original round-0 review record is idempotent and must not
    # write the stale metric back over the activated round.
    audit.save_review(
        "res-claim",
        {
            "resource_id": "res-claim",
            "run_id": "run-claim",
            "review_id": "review-claim",
            "review_ids": {"res-claim": "review-claim"},
            "status": "approve",
            "claim_total": 2,
            "claim_supported": 1,
            "claim_unsupported": 1,
            "claim_hallucination_rate": 0.5,
            "claim_metric_status": "complete",
        },
        "run-claim",
    )
    assert audit.get_review_by_resource("res-claim").claim_supported == 2


def _a23_state() -> tuple[dict, list[str]]:
    """100 supported Claims plus two missing ones, exactly as A23 describes."""

    state = _state()
    content = "Python 使用缩进定义代码块。"
    claims: list[dict] = []
    judgements: list[dict] = []
    for index in range(1, 103):
        claim = {
            "claim_id": "clm_" + f"{index:032x}",
            "run_id": "run-claim", "resource_id": "res-claim", "resource_version": 1,
            "review_id": "review-claim", "claim_index": index,
            "claim_text": content, "claim_type": "factual",
            "source_text": content, "source_start": 0, "source_end": len(content),
            "source_text_hash": sha256_hex(content),
            "extractor_prompt_version": "p0-06-extract-v3",
            "claim_hash": "b" * 64, "created_at": NOW,
        }
        claims.append(claim)
        verdict = "supported" if index <= 100 else "not_in_evidence"
        judgements.append({
            "judgement_id": "jdg_" + f"{index:032x}",
            "claim_id": claim["claim_id"], "run_id": "run-claim",
            "resource_id": "res-claim", "resource_version": 1,
            "review_id": "review-claim", "status": "completed", "verdict": verdict,
            "evidence_ids": ["ev-base"] if verdict == "supported" else [],
            "reason": "round0", "judge_type": "llm",
            "judge_prompt_version": "p0-06-judge-v1",
            "confidence": 0.8, "created_at": NOW,
        })
    state["extracted_claims"] = claims
    state["claim_judgements"] = judgements
    return state, [item["claim_id"] for item in claims if item["claim_index"] > 100]


def _a23_retrieve(state, storage, gap_ids):
    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        sent = [item["claim_id"] for item in data["claims"]]
        assert sent == gap_ids
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [
                {"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}
                for claim_id in sent
            ],
        }

    gateway = ObserverGateway([query_outcome])
    new_item = _new_evidence("chunk-new", "RAG 召回率不得低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])
    state.update(_call_retrieve(state, storage, gateway, retriever))
    return gateway


def test_a23_hundred_supported_and_two_absent_only_rejudge_the_gaps(storage):
    """A23: the round-1 target set is exactly the two missing Claims."""

    state, gap_ids = _a23_state()
    gateway = _a23_retrieve(state, storage, gap_ids)
    _, _, supplement = storage
    session = supplement.list_sessions(["run-claim"])[0]
    assert session.target_claim_ids == gap_ids

    # One gap is supported by the new excerpt, the other stays missing.
    def rejudge_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        sent = [item["claim_id"] for item in data["claims"]]
        assert set(sent) == set(gap_ids)
        allowed = data["allowed_evidence"][-1]["evidence_id"]
        return {"judgements": [
            {
                "claim_id": sent[0], "verdict": "supported",
                "evidence_ids": [allowed],
                "reason": "补充证据支持", "confidence": 0.9,
            },
            {
                "claim_id": sent[1], "verdict": "not_in_evidence",
                "evidence_ids": [], "reason": "仍无直接证据", "confidence": 0.6,
            },
        ]}

    gateway.outcomes = [rejudge_outcome]
    state.update(_call_rejudge(state, storage, gateway))

    metric = state["claim_metrics"]["res-claim"]
    assert metric["factual_claim_total"] == 102
    assert metric["supported_claim_total"] == 101
    assert metric["not_in_evidence_claim_total"] == 1
    assert metric["contradicted_claim_total"] == 0
    # Every originally supported Claim keeps its round-0 judgement.
    effective = {item["claim_id"]: item["verdict"] for item in state["claim_judgements"]}
    assert len(effective) == 102
    for claim_id in [item for item in effective if item not in gap_ids]:
        assert effective[claim_id] == "supported"
    assert [item.claim_id for item in supplement.list_supplements(["run-claim"])] == gap_ids
    assert supplement.list_sessions(["run-claim"])[0].active is True


def test_a23_a_forged_supported_claim_is_rejected_and_stays_inactive(storage):
    """A returned non-target Claim must not enter the round-1 set."""

    state, gap_ids = _a23_state()
    supported_id = "clm_" + f"{1:032x}"
    gateway = _a23_retrieve(state, storage, gap_ids)
    _, _, supplement = storage

    def forged_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        allowed = data["allowed_evidence"][-1]["evidence_id"]
        return {"judgements": [
            {
                "claim_id": gap_ids[0], "verdict": "supported",
                "evidence_ids": [allowed], "reason": "补充证据支持", "confidence": 0.9,
            },
            {
                "claim_id": gap_ids[1], "verdict": "not_in_evidence",
                "evidence_ids": [], "reason": "仍无直接证据", "confidence": 0.6,
            },
            {
                "claim_id": supported_id, "verdict": "contradicted",
                "evidence_ids": [allowed], "reason": "伪造的非目标判定", "confidence": 0.9,
            },
        ]}

    gateway.outcomes = [forged_outcome]
    state.update(_call_rejudge(state, storage, gateway))

    session = supplement.list_sessions(["run-claim"])[0]
    assert session.active is False
    assert session.hard_block is False
    assert [item.claim_id for item in supplement.list_supplements(["run-claim"])] == []
    assert state["claim_evidence_hard_block_resource_ids"] == []
    metric = state["claim_metrics"]["res-claim"]
    assert metric["supported_claim_total"] == 100
    assert metric["not_in_evidence_claim_total"] == 2
    effective = {item["claim_id"]: item["verdict"] for item in state["claim_judgements"]}
    assert effective[supported_id] == "supported"


@pytest.fixture()
def sqlite_storage(tmp_path):
    """Real SQL repositories for the node-level activation path (F01/F02)."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.audit.sql_repository import SQLAuditRepository
    from app.db.claim.sql_repository import SQLClaimRepository
    from app.db.claim.supplement import SQLClaimSupplementRepository
    from app.db.shared.models import (
        AgentRunORM,
        AgentStepORM,
        Base,
        GeneratedResourceORM,
        ResourceClaimORM,
        ResourceReviewORM,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 't50_workflow.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    audit = SQLAuditRepository(factory)
    state = _state()
    with factory() as db:
        db.add(AgentRunORM(
            run_id="run-claim", learner_id="learner-1", knowledge_base_id="kb-fixture",
            topic="RAG", status="running",
        ))
        db.add(AgentStepORM(
            step_id=STEP_ID, run_id="run-claim", step_no=1,
            agent_name="claim_evidence_retrieval", node_name="claim_evidence_retrieve",
            action="Claim 缺证补检", status="running",
        ))
        db.add(GeneratedResourceORM(
            resource_id="res-claim", run_id="run-claim", learner_id="learner-1",
            topic="RAG", resource_type="讲义", difficulty="初级", storage_type="text",
            version=1, review_id="review-claim",
        ))
        db.add(ResourceReviewORM(
            review_id="review-claim", resource_id="res-claim", run_id="run-claim",
            status="approve", claim_total=2, claim_supported=1, claim_unsupported=1,
            claim_hallucination_rate=0.5, claim_metric_status="complete",
        ))
        for item in state["extracted_claims"]:
            db.add(ResourceClaimORM(
                claim_id=item["claim_id"], review_id="review-claim",
                resource_id="res-claim", claim_text=item["claim_text"],
                supported=item["claim_id"] == state["extracted_claims"][0]["claim_id"],
            ))
        db.commit()
    claim_repo = SQLClaimRepository(factory)
    supplement = SQLClaimSupplementRepository(
        claim_repository=claim_repo, audit_repository=audit, session_factory=factory,
    )
    try:
        yield audit, claim_repo, supplement
    finally:
        engine.dispose()


def test_sql_node_path_saves_scope_then_activates_with_the_effective_metric(sqlite_storage):
    """F01/F02 on the real SQL node sequence: save scope, then activate.

    The node persists the audit scope before activation; the earlier
    implementation inserted the same scope twice and failed the composite unique
    constraint, so no SQL run could ever activate.  The persisted review must
    also carry the merged round-1 metric instead of the first-round one.
    """

    state = _state()
    claim_id = state["extracted_claims"][1]["claim_id"]

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}],
        }

    gateway = ObserverGateway([query_outcome])
    new_item = _new_evidence("chunk-new", "RAG 召回率不得低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])
    state.update(_call_retrieve(state, sqlite_storage, gateway, retriever))
    audit, _claim_repo, supplement = sqlite_storage
    assert supplement.list_sessions(["run-claim"])[0].status is (
        ClaimEvidenceRetrievalStatus.REJUDGING
    )

    gateway.outcomes = [{"judgements": [{
        "claim_id": claim_id, "verdict": "supported",
        "evidence_ids": [new_item.evidence_id],
        "reason": "补充证据支持", "confidence": 0.9,
    }]}]
    result = _call_rejudge(state, sqlite_storage, gateway)

    session = supplement.list_sessions(["run-claim"])[0]
    assert session.active is True
    assert session.status is ClaimEvidenceRetrievalStatus.COMPLETED
    assert result["errors"] == []
    # scope was saved once by the node and reused by the activation
    scopes = supplement.list_evidence_sets(["run-claim"])
    assert scopes[0].purpose == "audit"
    assert len([item for item in scopes if item.purpose == "audit"]) == 1
    review = audit.get_review_by_resource("res-claim")
    assert review.claim_total == 2
    assert review.claim_supported == 2
    assert review.claim_unsupported == 0
    assert review.claim_hallucination_rate == 0.0
    assert result["claim_metrics"]["res-claim"]["supported_claim_total"] == 2

    # Repeating the activation transaction is idempotent, not a second insert.
    from app.models.reviews.claim_evidence_retrieval import round_one_identity

    again = supplement.activate_session(
        session_id=session.session_id,
        scope=scopes[0],
        round_one_hash=round_one_identity(supplement.list_supplements(["run-claim"])),
        supported=2, contradicted=0, absent=0, factual=2, claim_total=2, now=NOW,
    )
    assert again.active is True
    assert len([item for item in supplement.list_evidence_sets(["run-claim"]) if item.purpose == "audit"]) == 1


def test_supplement_evidence_reaches_the_revision_child_version(storage):
    """F04: the authorised excerpt is usable by the child, not by siblings.

    It must reach the revision constraint channel, the child generation pool,
    the resource worker scope and the child's ordinary/Claim review context —
    the frozen spec, allocation and parent ledger are left untouched.
    """

    from app.agents.resource_agents.registry import get_resource_agent
    from app.agents.resource_workflows.learning_documents.workflow import _prepare_revision_node
    from app.agents.shared.evidence_scope import (
        resolve_generation_evidence_context,
        resolve_review_evidence_context,
    )
    from app.models.shared.agent_contracts import ResourceGenerationContext, ResourceSpec

    state = _state()
    claim_id = state["extracted_claims"][1]["claim_id"]

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "RAG 召回率 95%"}]}],
        }

    gateway = ObserverGateway([query_outcome])
    new_item = _new_evidence("chunk-new", "RAG 召回率可以低于 95%。", "RAG 召回率 95%")
    retriever = ScriptedEvidenceRetriever([EvidenceBatch(
        status=RetrievalStatus.AVAILABLE, knowledge_base_id="kb-fixture",
        evidence=[new_item], query_hashes=[query_hash("RAG 召回率 95%")],
        query_count=1, candidate_count=1, dropped_candidate_count=0,
        config_hash="9" * 64,
    )])
    state.update(_call_retrieve(state, storage, gateway, retriever))
    gateway.outcomes = [{"judgements": [{
        "claim_id": claim_id, "verdict": "contradicted",
        "evidence_ids": [new_item.evidence_id],
        "reason": "新增证据给出相反结论", "confidence": 0.9,
    }]}]
    state.update(_call_rejudge(state, storage, gateway))
    scopes = state["claim_evidence_scopes"]["res-claim"]
    # A blocked round never activates, but it still grants the child revision
    # exactly the excerpts discovered for it.
    assert [item["purpose"] for item in scopes] == ["generation"]

    spec = ResourceSpec(
        resource_spec_id="11111111-1111-1111-1111-111111111111",
        resource_family_id="22222222-2222-2222-2222-222222222222",
        resource_type="讲义", learning_objective="解释 RAG 召回率",
        knowledge_points=["skill-python"], evidence_ids=["ev-base"],
        difficulty="初级", representations=[{"representation": "text", "max_output_tokens": 2048}],
        display_order=1,
    )
    state["resource_specs"] = [spec.model_dump(mode="json")]
    parent = state["generated_resources"][0].model_copy(
        update={"resource_spec_id": spec.resource_spec_id},
    )
    state["generated_resources"] = [parent]
    state["claim_evidence_lineage"] = {parent.resource_id: {
        key: getattr(parent, key) for key in ("resource_id", "run_id", "resource_spec_id",
                                             "resource_family_id", "version", "parent_resource_id")
    }}
    child = parent.model_copy(update={
        "resource_id": "res-child", "version": parent.version + 1,
        "parent_resource_id": parent.resource_id,
    })
    sibling = parent.model_copy(update={"resource_id": "res-sibling", "version": 1})

    # 1. The revision constraint channel carries the authorised excerpt.
    state["review_result"]["revision_instructions"] = [{
        "target_resource_type": "讲义", "target_claim_ids": [claim_id],
    }]
    prepared = _prepare_revision_node(state, claim_only=True)
    excerpts = prepared["constraints"]["claim_revision_supplement_evidence"]
    assert [item["evidence_id"] for item in excerpts] == [new_item.evidence_id]
    assert excerpts[0]["excerpt"] == new_item.excerpt
    # The frozen spec and its evidence ids are not rewritten.
    assert prepared["constraints"].get("claim_revision_supplement_evidence")
    assert spec.evidence_ids == ["ev-base"]

    # 2. The child generation pool is base + authorised supplement.
    generation_evidence, supplement_ids = resolve_generation_evidence_context(
        state, spec, parent,
    )
    assert [item.evidence_id for item in generation_evidence] == [
        "ev-base", new_item.evidence_id,
    ]
    assert supplement_ids == [new_item.evidence_id]

    # 3. The resource worker sees the same scope and cites the new excerpt.
    context = ResourceGenerationContext(
        run_id="run-claim", batch_id="run-claim", step_id="worker-step",
        topic="RAG", evidence=generation_evidence,
        supplement_evidence_ids=supplement_ids, constraints={},
    )
    agent = get_resource_agent("讲义")
    scoped = agent._scoped_evidence(spec, context)
    assert [item.evidence_id for item in scoped] == ["ev-base", new_item.evidence_id]
    with pytest.raises(Exception):
        agent._scoped_evidence(
            spec, context.model_copy(update={"supplement_evidence_ids": ["ev-forged"]}),
        )

    # 4. The child's ordinary and Claim review context inherits it; a sibling
    #    resource of the same parent version does not.
    child_ids = [item.evidence_id for item in resolve_review_evidence_context(state, child)]
    assert child_ids == ["ev-base", new_item.evidence_id]
    state["claim_evidence_lineage"][child.resource_id] = {
        key: getattr(child, key) for key in ("resource_id", "run_id", "resource_spec_id",
                                            "resource_family_id", "version", "parent_resource_id")
    }
    grandchild = child.model_copy(update={
        "resource_id": "res-grandchild", "version": 3, "parent_resource_id": child.resource_id,
    })
    assert [item.evidence_id for item in resolve_review_evidence_context(state, grandchild)] == child_ids
    assert [item.evidence_id for item in resolve_generation_evidence_context(state, spec, child)[0]] == child_ids
    invalid = grandchild.model_copy(update={"resource_family_id": "foreign-family"})
    with pytest.raises(Exception):
        resolve_review_evidence_context(state, invalid)
    from app.services.runs.durable_workflow_runner import DurableWorkflowRunner

    persisted = {item.resource_id: item for item in (parent, child, grandchild)}
    audit, _, supplement = storage
    runner = DurableWorkflowRunner(
        None, audit, SimpleNamespace(resource_repository=SimpleNamespace(get=persisted.get)), supplement,
    )
    restored = {**state, "generated_resources": [grandchild], "claim_evidence_scopes": {},
                "supplement_retrieved_evidence": [], "claim_evidence_lineage": {}}
    runner._restore_evidence_context(restored)
    assert [item.evidence_id for item in resolve_review_evidence_context(restored, grandchild)] == child_ids
    restored["supplement_retrieved_evidence"] = []
    with pytest.raises(Exception):
        resolve_review_evidence_context(restored, grandchild)
    sibling_ids = [
        item.evidence_id for item in resolve_review_evidence_context(state, sibling)
    ]
    assert sibling_ids == ["ev-base"]
    # 5. The parent version keeps its own audit-only scope.
    parent_ids = [
        item.evidence_id for item in resolve_review_evidence_context(state, parent)
    ]
    assert parent_ids == ["ev-base", new_item.evidence_id]
    later = {**state, "generated_resources": [grandchild]}
    later.update(_call_rejudge(later, storage, ObserverGateway([])))
    assert [item.evidence_id for item in resolve_review_evidence_context(later, grandchild)] == child_ids

    # A16: a scoped binding that drifts is a hard contract error, never a
    # silent fallback to the base pool. The persisted originals stay untouched.
    import copy
    from app.core.security.errors import ApplicationError
    for damage in ("run", "resource", "version", "knowledge_base", "excerpt"):
        damaged = {**state, "claim_evidence_scopes": copy.deepcopy(state["claim_evidence_scopes"]),
                   "supplement_retrieved_evidence": list(state["supplement_retrieved_evidence"])}
        scope = damaged["claim_evidence_scopes"][parent.resource_id][0]
        if damage == "run":
            scope["run_id"] = "foreign-run"
        elif damage == "resource":
            scope["resource_id"] = sibling.resource_id
        elif damage == "version":
            scope["resource_version"] = 99
        else:
            key, value = (("knowledge_base_id", "foreign-kb") if damage == "knowledge_base"
                          else ("excerpt", "altered excerpt"))
            damaged["supplement_retrieved_evidence"] = [
                item.model_copy(update={key: value}) for item in damaged["supplement_retrieved_evidence"]]
        with pytest.raises(ApplicationError):
            resolve_review_evidence_context(damaged, grandchild)
        with pytest.raises(ApplicationError):
            resolve_generation_evidence_context(damaged, spec, parent)


def test_child_without_supplements_keeps_the_frozen_spec_boundary(storage):
    from app.agents.shared.evidence_scope import resolve_review_evidence_context

    state = _state()
    parent = state["generated_resources"][0]
    child = parent.model_copy(update={
        "resource_id": "res-child", "version": 2,
        "parent_resource_id": parent.resource_id,
    })

    assert [
        item.evidence_id for item in resolve_review_evidence_context(state, child)
    ] == ["ev-base"]


def test_budget_exhaustion_is_recorded_without_dropping_round_zero(storage):
    state = _state()
    policy_value = policy()
    state["claim_evidence_retrieval_policy"] = policy_value.model_copy(
        update={"max_logical_calls": 1, "queries_per_claim": 2}
    ).model_dump(mode="json")
    state["claim_evidence_retrieval_policy_hash"] = policy_value.model_copy(
        update={"max_logical_calls": 1, "queries_per_claim": 2}
    ).policy_hash
    claim_id = state["extracted_claims"][1]["claim_id"]
    gateway = ObserverGateway([])

    def query_outcome(kwargs):
        import json

        data = json.loads(kwargs["messages"][-1].content)
        return {
            "batch_id": data["batch_id"], "input_hash": data["input_hash"],
            "items": [{"claim_id": claim_id, "queries": [{"text": "x"}]}],
        }

    gateway.outcomes = [query_outcome]
    retriever = ScriptedEvidenceRetriever([])
    # The single allowed logical call is spent by the query batch; a second
    # session attempt must stop at the ledger boundary.
    state.update(_call_retrieve(state, storage, gateway, retriever))

    _, _, supplement = storage
    ledger = supplement.get_run("run-claim")
    assert ledger.logical_calls == 1
    assert all(
        item.status in {
            ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
            ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
            ClaimEvidenceRetrievalStatus.UNAVAILABLE,
        }
        for item in supplement.list_sessions(["run-claim"])
    )


@pytest.mark.parametrize("kind", ["lecture", "resource"])
@pytest.mark.parametrize("changed", [False, True])
def test_reviewer_keeps_the_predecessor_for_an_evidence_epoch(monkeypatch, kind, changed):
    """A changed evidence context must reach the engine as a predecessor ledger.

    Popping it in the reviewer would silently reset every unresolved defect, so
    the reviewer passes the predecessor through and the engine records the
    epoch transition itself.
    """
    from app.agents.resource_workflows.learning_documents import reviewer_agent
    from app.agents.resource_workflows.learning_documents.reviewing import lecture_engine_v2
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues import engine
    from app.models.reviews.review_audit import ReviewPolicySnapshotV1

    state = _state()
    resource = state["generated_resources"][0].model_copy(update={"resource_spec_id": "spec-1"})
    state["generated_resources"] = [resource]
    state["review_policy"] = ReviewPolicySnapshotV1().model_dump(mode="json")
    state[f"{kind}_review_policy"] = {"test": True}
    state[f"{kind}_review_contract_version"] = "2.0" if kind == "lecture" else "1.1"
    evidence = state["retrieved_evidence"]
    frozen = [{"evidence_id": item.evidence_id, "excerpt_hash": sha256_hex(item.excerpt),
               **({"excerpt": item.excerpt} if kind == "lecture" else {})} for item in evidence]
    ledger = {"binding": {"evidence_snapshot_hash": "0" * 64 if changed else canonical_hash({"evidence": frozen})},
              "open_issues": ["still-open"], "closed_issues": ["closed"], "unchanged_count": 2}
    state[f"{kind}_ledgers"] = {"spec-1": ledger}
    monkeypatch.setattr(reviewer_agent, "resolve_review_evidence_context", lambda *args: evidence)
    monkeypatch.setattr(reviewer_agent, "check_resource_structure", lambda **kwargs: None)
    monkeypatch.setattr(reviewer_agent, "source_refs_are_scoped", lambda *args: True)
    monkeypatch.setattr(reviewer_agent, "node_tier_difficulty_review", lambda *args: None)

    class ReachedEngine(BaseException):
        pass

    def inspect_entry(**kwargs):
        passed = kwargs["state"][f"{kind}_ledgers"]
        assert passed["spec-1"] == ledger
        raise ReachedEngine()

    monkeypatch.setattr(lecture_engine_v2 if kind == "lecture" else engine,
                        "review_lecture_v2" if kind == "lecture" else "review_resource_v1", inspect_entry)
    with pytest.raises(ReachedEngine):
        reviewer_agent.review_node(state, llm_gateway=ObserverGateway([]))


def test_three_query_schema_failures_charge_attempts_then_fallback_keeps_round_zero(storage):
    from app.core.llm.gateway import LLMGateway
    from app.models.shared.llm import RawLLMResponse
    from tests.fakes.llm import ScriptedLLMTransport

    state = _state()
    before = list(state["claim_judgements"])
    responses = [RawLLMResponse(content="[]", finish_reason="stop",
                               usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)) for _ in range(3)]
    transport = ScriptedLLMTransport(responses)
    gateway = LLMGateway(transport)
    nohit = EvidenceBatch(status=RetrievalStatus.NO_HIT, knowledge_base_id="kb-fixture", evidence=[],
                         query_hashes=[], query_count=1, candidate_count=0, dropped_candidate_count=0,
                         config_hash="9" * 64)
    retriever = ScriptedEvidenceRetriever([nohit] * 5)
    state.update(_call_retrieve(state, storage, gateway, retriever))
    repository = storage[2]
    ledger = repository.get_run("run-claim")
    assert len(transport.calls) == 3
    assert ledger.logical_calls == 1 and ledger.attempts == 3
    assert ledger.known_tokens == 45 and ledger.reserved_tokens == 0
    assert retriever.calls  # deterministic fallback really searched, not an empty success
    assert state["claim_judgements"] == before
    assert repository.list_sessions(["run-claim"])[0].status is ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE
    assert route_after_claim_evidence_retrieve(state) == "claim_decide"


def test_partial_supported_rejudge_then_failure_never_activates_the_round(storage):
    state, gap_ids = _a23_state()
    configured = policy().model_copy(update={"rejudge_batch_claims": 1})
    state["claim_evidence_retrieval_policy"] = configured.model_dump(mode="json")
    state["claim_evidence_retrieval_policy_hash"] = configured.policy_hash
    before = [ClaimJudgement.model_validate(item).model_dump(mode="json") for item in state["claim_judgements"]]
    gateway = _a23_retrieve(state, storage, gap_ids)
    def success(kwargs):
        import json
        data = json.loads(kwargs["messages"][-1].content)
        assert len(data["claims"]) == 1
        return {"judgements": [{"claim_id": data["claims"][0]["claim_id"], "verdict": "supported",
                                "evidence_ids": [data["allowed_evidence"][-1]["evidence_id"]],
                                "reason": "partial", "confidence": 0.9}]}
    gateway.outcomes = [success, RuntimeError("offline fault after first batch")]
    state.update(_call_rejudge(state, storage, gateway))
    session = storage[2].list_sessions(["run-claim"])[0]
    assert not session.active and not session.hard_block
    assert session.status is ClaimEvidenceRetrievalStatus.UNAVAILABLE
    assert len(storage[2].list_supplements(["run-claim"])) == 1
    assert state["claim_judgements"] == before
    assert state["claim_metrics"]["res-claim"]["factual_claim_total"] == 102
    assert state["claim_metrics"]["res-claim"]["supported_claim_total"] == 100
