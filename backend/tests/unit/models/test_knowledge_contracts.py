from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.evidence import source_refs_are_scoped, source_refs_from_evidence
from app.core.knowledge_ids import (
    chunk_id,
    chunking_config_hash,
    document_id,
    document_version_id,
    evidence_id,
    normalize_source_path,
    normalize_text,
    query_hash,
    retrieval_config_hash,
    sha256_hex,
)
from app.models.common import ErrorInfo
from app.models.knowledge import (
    EvidenceBatch,
    EvidenceItem,
    KnowledgeChunk,
    RetrievalStatus,
    ScoreKind,
    SourceLocator,
    SourceType,
)


def _chunk() -> KnowledgeChunk:
    text = "# 标题\n稳定证据内容。"
    text_hash = sha256_hex(normalize_text(text))
    config_hash = chunking_config_hash({"strategy": "recursive-v1", "size": 500})
    version = document_version_id("kb-one", "doc-one", sha256_hex(normalize_text(text)))
    stable_chunk_id = chunk_id(
        knowledge_base_id="kb-one",
        logical_document_id="doc-one",
        document_version=version,
        chunking_hash=config_hash,
        ordinal=0,
        text_hash=text_hash,
    )
    locator = SourceLocator(
        knowledge_base_id="kb-one",
        document_id="doc-one",
        document_version=version,
        chunk_id=stable_chunk_id,
        source_type=SourceType.MARKDOWN,
        source_path="references/one.md",
        title="标题",
        section="标题",
        line_start=1,
        line_end=2,
    )
    return KnowledgeChunk(
        knowledge_base_id="kb-one",
        document_id="doc-one",
        document_version=version,
        chunk_id=stable_chunk_id,
        ordinal=0,
        text=text,
        text_hash=text_hash,
        chunking_config_hash=config_hash,
        locator=locator,
    )


def _evidence() -> EvidenceItem:
    chunk = _chunk()
    config_hash = retrieval_config_hash({"metric": "cosine", "top_k": 3})
    hashed_query = query_hash("稳定查询")
    return EvidenceItem(
        evidence_id=evidence_id(
            run_id="run-one",
            step_id="step-one",
            knowledge_base_id=chunk.knowledge_base_id,
            retrieval_query_hash=hashed_query,
            knowledge_chunk_id=chunk.chunk_id,
            config_hash=config_hash,
        ),
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        chunk_id=chunk.chunk_id,
        query="稳定查询",
        query_hash=hashed_query,
        query_rank=1,
        rank=1,
        raw_score=0.2,
        score_kind=ScoreKind.DISTANCE,
        normalized_score=0.9,
        excerpt=chunk.text,
        excerpt_hash=sha256_hex(normalize_text(chunk.text)),
        locator=chunk.locator,
        config_hash=config_hash,
        retrieved_at=datetime.now(timezone.utc),
    )


def test_document_and_chunk_ids_are_stable_and_content_addressed():
    first_document = document_id("kb-one", "references\\one.md")
    second_document = document_id("kb-one", "references/one.md")
    first_hash = sha256_hex(normalize_text("same\r\ncontent "))
    second_hash = sha256_hex(normalize_text("same\ncontent"))

    assert first_document == second_document
    assert first_hash == second_hash
    assert document_version_id("kb-one", first_document, first_hash) == document_version_id(
        "kb-one", second_document, second_hash
    )
    assert document_version_id("kb-one", first_document, first_hash) != document_version_id(
        "kb-one", first_document, sha256_hex("changed")
    )
    assert _chunk().chunk_id == _chunk().chunk_id


@pytest.mark.parametrize(
    "path",
    ["../secret.md", "/absolute.md", "C:\\secret.md", "", "."],
)
def test_source_path_must_stay_inside_knowledge_base(path):
    with pytest.raises(ValueError):
        normalize_source_path(path)


def test_text_source_requires_resolvable_locator():
    chunk = _chunk()
    payload = chunk.locator.model_dump()
    payload.update({"section": None, "line_start": None, "line_end": None})

    with pytest.raises(ValidationError):
        SourceLocator.model_validate(payload)


def test_chunk_rejects_locator_identity_mismatch():
    chunk = _chunk()
    payload = chunk.model_dump()
    payload["locator"]["knowledge_base_id"] = "other-kb"

    with pytest.raises(ValidationError):
        KnowledgeChunk.model_validate(payload)


def test_evidence_batch_enforces_status_invariants():
    item = _evidence()
    available = EvidenceBatch(
        status=RetrievalStatus.AVAILABLE,
        knowledge_base_id="kb-one",
        evidence=[item],
        query_hashes=[item.query_hash],
        query_count=1,
        candidate_count=1,
        dropped_candidate_count=0,
        config_hash=item.config_hash,
    )
    assert available.evidence[0].evidence_id.startswith("ev_")

    with pytest.raises(ValidationError):
        EvidenceBatch(
            status=RetrievalStatus.NO_HIT,
            knowledge_base_id="kb-one",
            evidence=[item],
            query_hashes=[item.query_hash],
            query_count=1,
            candidate_count=1,
            dropped_candidate_count=0,
            config_hash=item.config_hash,
        )

    error = ErrorInfo(
        code="EVIDENCE_INSUFFICIENT",
        category="evidence",
        message="证据不足",
        source="evidence_retriever",
    )
    insufficient = EvidenceBatch(
        status=RetrievalStatus.EVIDENCE_INSUFFICIENT,
        knowledge_base_id="kb-one",
        evidence=[],
        query_hashes=[item.query_hash],
        query_count=1,
        candidate_count=1,
        dropped_candidate_count=1,
        config_hash=item.config_hash,
        error=error,
    )
    assert insufficient.error.code == "EVIDENCE_INSUFFICIENT"


def test_source_refs_are_verified_system_projections_not_legacy_guesses():
    item = _evidence()
    refs = source_refs_from_evidence([item])

    assert refs[0].provenance_status == "verified"
    assert refs[0].snippet == item.excerpt
    assert refs[0].score == item.normalized_score
    assert source_refs_are_scoped(refs, [item]) is True
    assert source_refs_are_scoped([], [item]) is False
    assert source_refs_are_scoped(
        [refs[0].model_copy(update={"chunk_id": "forged"})],
        [item],
    ) is False
