"""Bounded retrieval: a stalled backend must not hold a run until lease expiry."""

import time

from app.config import Settings
from app.core.retrieval.retriever import EvidenceRetriever
from app.core.security.errors import ErrorCode
from app.db.knowledge.memory import MemoryKnowledgeChunkRepository
from app.models.knowledge.knowledge import RetrievalPolicy, RetrievalRequest, RetrievalStatus


def _retriever() -> EvidenceRetriever:
    return EvidenceRetriever(
        backend=object(),
        chunk_repository=MemoryKnowledgeChunkRepository([]),
        settings=Settings(_env_file=None, embedding_model="fake-embedding"),
    )


def _request() -> RetrievalRequest:
    return RetrievalRequest(
        run_id="run-retrieval-deadline",
        step_id="step-retrieval-deadline",
        knowledge_base_id="kb-retrieval-deadline",
        queries=["query-one"],
        policy=RetrievalPolicy(),
    )


def test_stalled_retrieval_returns_bounded_failure_batch():
    retriever = _retriever()

    def _stall(request):
        time.sleep(5)

    retriever.retrieve = _stall

    started = time.perf_counter()
    batch = retriever.retrieve_with_deadline(_request(), timeout_seconds=0.2)
    elapsed = time.perf_counter() - started

    assert elapsed < 3
    assert batch.status == RetrievalStatus.RETRIEVAL_ERROR
    assert batch.evidence == []
    assert batch.retrieval_profile["deadline_exceeded"] is True
    assert batch.error is not None
    assert batch.error.code == ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE.value
    assert batch.error.retryable is True


def test_a_successful_retrieval_passes_through_unchanged():
    retriever = _retriever()
    retriever.retrieve = lambda request: "sentinel-batch"

    assert retriever.retrieve_with_deadline(_request(), timeout_seconds=5) == "sentinel-batch"


def test_disabled_deadline_falls_back_to_direct_retrieval():
    retriever = _retriever()
    retriever.retrieve = lambda request: "sentinel-batch"

    assert retriever.retrieve_with_deadline(_request(), timeout_seconds=0) == "sentinel-batch"
