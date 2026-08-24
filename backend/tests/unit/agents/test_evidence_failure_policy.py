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
