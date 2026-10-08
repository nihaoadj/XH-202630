"""Safe projections from internal Evidence DTOs to public resource citations."""

from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import SourceRef


def source_refs_from_evidence(
    evidence: list[EvidenceItem],
    *,
    limit: int = 3,
) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for item in evidence[:limit]:
        locator = item.locator
        refs.append(SourceRef(
            doc_id=item.document_id,
            title=locator.title,
            snippet=item.excerpt,
            score=item.normalized_score,
            provenance_status="verified",
            evidence_id=item.evidence_id,
            knowledge_base_id=item.knowledge_base_id,
            document_version=item.document_version,
            chunk_id=item.chunk_id,
            section=locator.section,
            page=locator.page,
            source_path=locator.source_path,
            source_type=locator.source_type.value,
            line_start=locator.line_start,
            line_end=locator.line_end,
            timestamp_start_ms=locator.timestamp_start_ms,
            timestamp_end_ms=locator.timestamp_end_ms,
            retrieval_query=item.query,
            query_hash=item.query_hash,
            raw_score=item.raw_score,
            score_kind=item.score_kind.value,
            normalized_score=item.normalized_score,
            excerpt_hash=item.excerpt_hash,
            retrieval_config_hash=item.config_hash,
            rank=item.rank,
            metadata={
                "schema_version": item.schema_version,
                "provenance_status": "verified",
            },
        ))
    return refs


def source_refs_are_scoped(
    source_refs: list[SourceRef],
    evidence: list[EvidenceItem],
) -> bool:
    if not source_refs or not evidence:
        return False
    allowed = {
        (item.evidence_id, item.knowledge_base_id, item.chunk_id)
        for item in evidence
    }
    return all(
        ref.provenance_status == "verified"
        and (ref.evidence_id, ref.knowledge_base_id, ref.chunk_id) in allowed
        for ref in source_refs
    )
