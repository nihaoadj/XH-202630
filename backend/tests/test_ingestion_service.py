import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.models import (
    Base,
    KnowledgeChunkVersionORM,
    KnowledgeDocumentVersionORM,
)
from app.models.knowledge import ScoreKind, VectorCandidate
from app.services.ingestion_service import IngestionService


class MemoryVectorIndex:
    def __init__(self, *, count_offset=0, return_hits=True, fail_sync=False):
        self.records = {}
        self.count_offset = count_offset
        self.return_hits = return_hits
        self.fail_sync = fail_sync

    def synchronize(self, documents, *, knowledge_base_id):
        if self.fail_sync:
            raise RuntimeError("provider detail must be sanitized")
        self.records[knowledge_base_id] = {
            item.metadata["chunk_id"]: item for item in documents
        }
        return list(self.records[knowledge_base_id])

    def count(self, knowledge_base_id):
        return len(self.records.get(knowledge_base_id, {})) + self.count_offset

    def search(self, *, query, top_k, knowledge_base_id):
        if not self.return_hits:
            return []
        documents = list(self.records.get(knowledge_base_id, {}).values())[:top_k]
        return [
            VectorCandidate(
                chunk_id=item.metadata["chunk_id"],
                text=item.page_content,
                metadata={
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": item.metadata["document_id"],
                    "document_version": item.metadata["document_version"],
                    "chunk_id": item.metadata["chunk_id"],
                    "text_hash": item.metadata["text_hash"],
                },
                raw_score=0.1,
                score_kind=ScoreKind.DISTANCE,
                metric="cosine",
                query=query,
                query_rank=rank,
            )
            for rank, item in enumerate(documents, start=1)
        ]


def _kb(tmp_path):
    kb_dir = tmp_path / "kb_fixture"
    kb_dir.mkdir()
    (kb_dir / "active.md").write_text(
        "# Evidence\n\nfixed smoke query and trusted content",
        encoding="utf-8",
    )
    (kb_dir / "disabled.md").write_text(
        "# Disabled\n\nthis content must not enter the active index",
        encoding="utf-8",
    )
    (kb_dir / "metadata.json").write_text(json.dumps({
        "knowledge_base_id": "kb-ingestion",
        "index_schema_version": "1.0",
        "chunking": {
            "strategy": "recursive_v1",
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
        "documents": [
            {
                "id": "doc-active",
                "title": "Active",
                "file": "active.md",
                "source_type": "markdown",
                "enabled": True,
            },
            {
                "id": "doc-disabled",
                "title": "Disabled",
                "file": "disabled.md",
                "source_type": "markdown",
                "enabled": False,
            },
        ],
        "smoke_queries": [{
            "query": "fixed smoke query",
            "expected_document_ids": ["doc-active"],
        }],
    }), encoding="utf-8")
    return kb_dir


def _catalog(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingestion.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return KnowledgeCatalogRepository(factory), factory


def test_ingestion_reconciles_counts_smoke_and_is_idempotent(tmp_path):
    kb_dir = _kb(tmp_path)
    catalog, factory = _catalog(tmp_path)
    vector_index = MemoryVectorIndex()
    service = IngestionService(catalog=catalog, vector_index=vector_index)

    first = service.ingest(str(kb_dir))
    second = service.ingest(str(kb_dir))

    assert first.status == second.status == "ready"
    assert first.smoke_status == "passed"
    assert first.expected_active_chunk_count == first.sql_active_chunk_count
    assert first.sql_active_chunk_count == first.vector_chunk_count == 1
    assert first.active_snapshot_hash == second.active_snapshot_hash
    status = catalog.get_index_status("kb-ingestion")
    assert status["status"] == "ready"
    assert status["expected_chunk_count"] == status["sql_chunk_count"] == status["vector_chunk_count"]
    current_document = catalog.get_document(
        "doc-active",
        knowledge_base_id="kb-ingestion",
    )
    assert catalog.get_document_version(current_document.document_version) == current_document
    active_chunk_id = next(iter(vector_index.records["kb-ingestion"]))
    assert catalog.resolve_chunk_locator(
        "kb-ingestion",
        current_document.document_version,
        active_chunk_id,
    ).source_path == "active.md"
    with factory() as db:
        assert db.query(KnowledgeDocumentVersionORM).count() == 1
        assert db.query(KnowledgeChunkVersionORM).count() == 1


def test_ingestion_retains_old_version_but_only_new_chunks_are_active(tmp_path):
    kb_dir = _kb(tmp_path)
    catalog, factory = _catalog(tmp_path)
    service = IngestionService(catalog=catalog, vector_index=MemoryVectorIndex())
    first = service.ingest(str(kb_dir))
    (kb_dir / "active.md").write_text(
        "# Evidence\n\nfixed smoke query and updated trusted content",
        encoding="utf-8",
    )
    second = service.ingest(str(kb_dir))

    assert first.status == second.status == "ready"
    assert first.active_snapshot_hash != second.active_snapshot_hash
    with factory() as db:
        versions = db.query(KnowledgeDocumentVersionORM).all()
        chunks = db.query(KnowledgeChunkVersionORM).all()
        assert len(versions) == 2
        assert sum(item.is_current for item in versions) == 1
        assert len(chunks) == 2
        assert sum(item.active for item in chunks) == 1


def test_count_mismatch_is_not_ready_and_does_not_activate_sql_snapshot(tmp_path):
    kb_dir = _kb(tmp_path)
    catalog, _ = _catalog(tmp_path)
    service = IngestionService(
        catalog=catalog,
        vector_index=MemoryVectorIndex(count_offset=1),
    )

    report = service.ingest(str(kb_dir))

    assert report.status == "not_ready"
    assert report.error.code == "VECTOR_INDEX_OUT_OF_SYNC"
    assert catalog.active_chunk_count("kb-ingestion") == 0


def test_failed_smoke_is_not_ready_and_does_not_activate_sql_snapshot(tmp_path):
    kb_dir = _kb(tmp_path)
    catalog, _ = _catalog(tmp_path)
    service = IngestionService(
        catalog=catalog,
        vector_index=MemoryVectorIndex(return_hits=False),
    )

    report = service.ingest(str(kb_dir))

    assert report.status == "not_ready"
    assert report.smoke_status == "failed"
    assert report.error.code == "KNOWLEDGE_INGESTION_SMOKE_FAILED"
    assert catalog.active_chunk_count("kb-ingestion") == 0


def test_vector_provider_failure_is_sanitized_and_retryable(tmp_path):
    kb_dir = _kb(tmp_path)
    catalog, _ = _catalog(tmp_path)
    service = IngestionService(
        catalog=catalog,
        vector_index=MemoryVectorIndex(fail_sync=True),
    )

    report = service.ingest(str(kb_dir))

    assert report.status == "not_ready"
    assert report.error.code == "KNOWLEDGE_INGESTION_FAILED"
    assert report.error.safe_detail == "operation:failed"
    assert "provider detail" not in report.model_dump_json()
