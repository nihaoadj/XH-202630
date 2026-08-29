import pytest

from app.agents.shared.retrieval import retrieve_node
from app.config import Settings
from app.core.security import errors as errors_module
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.common import ErrorInfo
from app.models.knowledge.knowledge import EvidenceBatch, RetrievalStatus
from tests.fakes.evidence import (
    ScriptedEvidenceRetriever,
    make_available_batch,
    make_evidence,
)


def _settings(**overrides):
    values = {
        "_env_file": None,
        "app_mode": "demo",
        "allow_degraded_generation": True,
    }
    values.update(overrides)
    if values["app_mode"] == "production":
        values["llm_api_key"] = "test-production-key"
    return Settings(**values)


def _state(**overrides):
    state = {
        "schema_version": "1.0",
        "run_id": "run-retrieval-policy",
        "topic": "Evidence",
        "knowledge_base_id": "kb-fixture",
        "generation_mode": "standard",
        "constraints": {},
        "trace": [],
        "errors": [],
    }
    state.update(overrides)
    return state


def _failed_batch(status=RetrievalStatus.RETRIEVAL_ERROR):
    code = (
        ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE
        if status == RetrievalStatus.RETRIEVAL_ERROR
        else ErrorCode.EVIDENCE_INSUFFICIENT
    )
    return EvidenceBatch(
        status=status,
        knowledge_base_id="kb-fixture",
        query_hashes=["1" * 64],
        query_count=1,
        candidate_count=0 if status == RetrievalStatus.RETRIEVAL_ERROR else 1,
        dropped_candidate_count=0 if status == RetrievalStatus.RETRIEVAL_ERROR else 1,
        config_hash="2" * 64,
        error=ErrorInfo(
            code=code.value,
            category="retrieval",
            message="sanitized",
            retryable=status == RetrievalStatus.RETRIEVAL_ERROR,
            source="evidence_retriever",
        ),
    )


def test_retrieval_error_can_degrade_only_when_runtime_policy_allows(monkeypatch):
    monkeypatch.setattr(errors_module, "get_settings", lambda: _settings())
    result = retrieve_node(
        _state(),
        evidence_retriever=ScriptedEvidenceRetriever([_failed_batch()], _settings()),
    )

    assert result["retrieval_status"] == "retrieval_error"
    assert result["retrieved_evidence"] == []
    assert result["trace"][0]["status"] == "degraded"
    assert result["errors"][0]["code"] == "RETRIEVAL_UPSTREAM_UNAVAILABLE"


def test_production_retrieval_error_fails_closed(monkeypatch):
    production = _settings(app_mode="production", allow_degraded_generation=False)
    monkeypatch.setattr(errors_module, "get_settings", lambda: production)

    with pytest.raises(ApplicationError) as exc:
        retrieve_node(
            _state(),
            evidence_retriever=ScriptedEvidenceRetriever([_failed_batch()], production),
        )

    assert exc.value.code == ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE


def test_no_hit_is_business_result_even_when_degraded_mode_is_forbidden(monkeypatch):
    production = _settings(app_mode="production", allow_degraded_generation=False)
    monkeypatch.setattr(errors_module, "get_settings", lambda: production)
    batch = EvidenceBatch(
        status=RetrievalStatus.NO_HIT,
        knowledge_base_id="kb-fixture",
        query_hashes=["1" * 64],
        query_count=1,
        candidate_count=0,
        dropped_candidate_count=0,
        config_hash="2" * 64,
    )

    result = retrieve_node(
        _state(),
        evidence_retriever=ScriptedEvidenceRetriever([batch], production),
    )

    assert result["retrieval_status"] == "no_hit"
    assert result["errors"] == []


def test_partial_provider_failure_is_visible_on_available_batch(monkeypatch):
    demo = _settings()
    monkeypatch.setattr(errors_module, "get_settings", lambda: demo)
    evidence = make_evidence()
    batch = make_available_batch([evidence])
    batch = batch.model_copy(update={"partial_failure_count": 1})

    result = retrieve_node(
        _state(),
        evidence_retriever=ScriptedEvidenceRetriever([batch], demo),
    )

    assert result["retrieval_status"] == "available"
    assert result["retrieved_evidence"] == [evidence]
    assert result["trace"][0]["status"] == "degraded"
    assert result["trace"][0]["retrieval_partial_failure_count"] == 1


def test_target_node_uses_scoped_retrieval_when_mapped_evidence_is_sufficient(monkeypatch):
    demo = _settings()
    monkeypatch.setattr(errors_module, "get_settings", lambda: demo)
    evidence = make_evidence(chunk_id="mapped-chunk")
    retriever = ScriptedEvidenceRetriever(
        [make_available_batch([evidence]).model_copy(update={"retrieval_scope": "node_scoped"})],
        demo,
        mapped_chunk_ids=["mapped-chunk"],
    )

    result = retrieve_node(
        _state(target_skill_nodes=["node-a"]),
        evidence_retriever=retriever,
    )

    assert len(retriever.calls) == 1
    assert retriever.calls[0].retrieval_scope == "node_scoped"
    assert retriever.calls[0].allowed_chunk_ids == ["mapped-chunk"]
    assert result["retrieval_profile"]["final_retrieval_source"] == "node_scoped"


def test_insufficient_node_scope_reuses_existing_global_retrieval(monkeypatch):
    demo = _settings()
    monkeypatch.setattr(errors_module, "get_settings", lambda: demo)
    insufficient = _failed_batch(RetrievalStatus.EVIDENCE_INSUFFICIENT)
    global_evidence = make_evidence(chunk_id="global-chunk")
    retriever = ScriptedEvidenceRetriever(
        [insufficient, make_available_batch([global_evidence])],
        demo,
        mapped_chunk_ids=["mapped-chunk"],
    )

    result = retrieve_node(
        _state(target_skill_nodes=["node-a"]),
        evidence_retriever=retriever,
    )

    assert [item.retrieval_scope for item in retriever.calls] == ["node_scoped", "global"]
    assert retriever.calls[1].allowed_chunk_ids is None
    assert result["retrieved_evidence"] == [global_evidence]
    assert result["retrieval_profile"]["final_retrieval_source"] == "global_fallback"
    assert result["retrieval_profile"]["node_scope_fallback_reason"] == "evidence_insufficient"


def test_final_evidence_insufficiency_is_recorded_after_global_fallback(monkeypatch):
    demo = _settings()
    monkeypatch.setattr(errors_module, "get_settings", lambda: demo)
    retriever = ScriptedEvidenceRetriever(
        [
            _failed_batch(RetrievalStatus.EVIDENCE_INSUFFICIENT),
            _failed_batch(RetrievalStatus.EVIDENCE_INSUFFICIENT),
        ],
        demo,
        mapped_chunk_ids=["mapped-chunk"],
    )

    result = retrieve_node(
        _state(target_skill_nodes=["node-a"]),
        evidence_retriever=retriever,
    )

    assert [item.retrieval_scope for item in retriever.calls] == ["node_scoped", "global"]
    assert result["retrieval_status"] == "evidence_insufficient"
    assert result["retrieval_profile"]["final_retrieval_source"] == "evidence_insufficient"


def test_node_scope_error_keeps_existing_error_semantics_without_global_retry(monkeypatch):
    demo = _settings()
    monkeypatch.setattr(errors_module, "get_settings", lambda: demo)
    retriever = ScriptedEvidenceRetriever(
        [_failed_batch()],
        demo,
        mapped_chunk_ids=["mapped-chunk"],
    )

    result = retrieve_node(
        _state(target_skill_nodes=["node-a"]),
        evidence_retriever=retriever,
    )

    assert len(retriever.calls) == 1
    assert retriever.calls[0].retrieval_scope == "node_scoped"
    assert result["retrieval_status"] == "retrieval_error"
