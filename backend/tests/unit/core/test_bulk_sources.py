"""Offline PDF provenance, complete-source and pre-bulk identity checks."""
import hashlib
import importlib.util
import json
from app.core.retrieval.knowledge_paths import resolve_knowledge_file

import pytest
from langchain.schema import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.core.retrieval.evidence import source_refs_from_evidence
from app.core.retrieval.knowledge_base import chunk_documents, load_documents
from app.core.retrieval.knowledge_ids import canonical_json, document_version_id, sha256_hex
from app.core.retrieval.markdown_structure import structural_chunks
from app.core.retrieval.retriever import EvidenceRetriever
from app.core.retrieval.vector_store import _to_chroma_document
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.shared.models import Base
from app.models.knowledge.knowledge import RetrievalRequest
from tests.fakes.evidence import ScriptedVectorSearchBackend, make_vector_candidate
from tests.paths import BACKEND_ROOT, KNOWLEDGE_BASE_ROOT, PROJECT_ROOT
from tests.fakes.knowledge_versions import without_identity_revision, source_baseline


def _paper():
    text = "## PDF page 1\n\nFirst-page definition.\n# literal PDF heading\n\n## PDF page 2\n\nSecond-page experiment."
    return Document(page_content=text, metadata={
        "knowledge_base_id": "paper-test", "document_id": "paper", "title": "PDF fixture",
        "document_version": document_version_id("paper-test", "paper", sha256_hex(text)),
        "document_content_hash": sha256_hex(text), "source_type": "pdf",
        "source_path": "paper.md", "chunking_strategy": "markdown_structure_v1",
        "knowledge_points": [], "learner_levels": [],
        "page_spans": [
            {"page": 1, "line_start": 1, "line_end": 5},
            {"page": 2, "line_start": 6, "line_end": 8},
        ],
        "section_knowledge_points": {"PDF page 1": ["Embedding"], "PDF page 2": ["RAG 评测"]},
    })


def test_pdf_spans_keep_physical_page_and_ignore_literal_headings():
    chunks = chunk_documents([_paper()])
    assert {chunk.metadata["page"] for chunk in chunks} == {1, 2}
    assert [chunk.metadata["section"] for chunk in chunks] == ["PDF page 1", "PDF page 2"]
    assert all("First-page" not in chunk.page_content or "Second-page" not in chunk.page_content for chunk in chunks)
    assert chunks[0].metadata["knowledge_points"] == ["Embedding"]


@pytest.mark.parametrize("change", ["gap", "overlap", "wrong_page", "incomplete", "wrong_marker", "boolean"])
def test_invalid_pdf_page_ranges_fail_closed(change):
    doc = _paper()
    spans = doc.metadata["page_spans"]
    if change == "gap":
        spans[1]["line_start"] += 1
    elif change == "overlap":
        spans[1]["line_start"] -= 1
    elif change == "wrong_page":
        spans[1]["page"] = 3
    elif change == "incomplete":
        spans.pop()
    elif change == "wrong_marker":
        doc.page_content = doc.page_content.replace("## PDF page 2", "## PDF page 9")
    else:
        spans[0]["page"] = True
    with pytest.raises(ValueError, match="page_spans"):
        structural_chunks(doc, chunk_size=500, chunk_overlap=100)


def test_pdf_page_survives_sql_chroma_evidence_and_public_reference():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repo = KnowledgeCatalogRepository(sessionmaker(bind=engine))
    doc = _paper()
    chunks = chunk_documents([doc])
    repo.upsert_knowledge_base({"knowledge_base_id": "paper-test", "name": "Paper test", "version": "1"})
    repo.sync_documents([doc], chunks, knowledge_base_id="paper-test")
    restored = repo.get_chunk(chunks[-1].metadata["chunk_id"], knowledge_base_id="paper-test")
    assert restored.locator.page == 2
    assert _to_chroma_document(chunks[-1]).metadata["page"] == 2
    backend = ScriptedVectorSearchBackend({"experiment": [make_vector_candidate(restored, query="experiment")]})
    batch = EvidenceRetriever(backend=backend, chunk_repository=repo, settings=Settings(_env_file=None)).retrieve(
        RetrievalRequest(run_id="run-pdf", step_id="retrieve", knowledge_base_id="paper-test", queries=["experiment"]),
    )
    assert batch.evidence[0].locator.page == 2
    assert source_refs_from_evidence(batch.evidence)[0].page == 2
    engine.dispose()


def test_original_95_official_chunk_metadata_and_identities_remain_frozen():
    baseline = json.loads((BACKEND_ROOT / "tests/fixtures/knowledge_pilot/pre_bulk_chunks.json").read_text())
    # Teaching content is now a new legitimate revision; the original 95 pilot
    # source chunks remain immutable, while teaching has its own v2 fixture.
    baseline = {ident: item for ident, item in baseline.items() if item["document_id"].startswith("source_")}
    assert len(baseline) == 95
    old_docs = {entry["document_id"] for entry in baseline.values()}
    with source_baseline() as base:
        chunks = chunk_documents(without_identity_revision([doc for doc in load_documents(str(base)) if doc.metadata["document_id"] in old_docs]))
    current = {chunk.metadata["chunk_id"]: {
        "document_id": chunk.metadata["document_id"],
        "metadata_hash": hashlib.sha256(canonical_json(chunk.metadata).encode()).hexdigest(),
    } for chunk in chunks}
    assert current == baseline


def test_bulk_originals_are_complete_pinned_and_page_locatable():
    root = KNOWLEDGE_BASE_ROOT / "rag_engineering_training"
    catalog = json.loads(resolve_knowledge_file(root, "provenance/catalogs/bulk.json").read_text(encoding="utf-8"))
    registry = json.loads(resolve_knowledge_file(root, "provenance/import_batches/bulk.json").read_text(encoding="utf-8"))
    records = {entry["id"]: entry for entry in registry["sources"]}
    assert len(records) == len(catalog["sources"]) == 18
    docs = {doc.metadata["document_id"]: doc for doc in load_documents() if doc.metadata["document_id"] in records}
    assert set(docs) == set(records)
    pdfs = [doc for doc in docs.values() if doc.metadata["source_type"] == "pdf"]
    assert len(pdfs) == 6
    assert sum(len(doc.metadata["page_spans"]) for doc in pdfs) == 100
    assert sum(len(doc.page_content) for doc in docs.values()) > 400000
    for source in catalog["sources"]:
        doc = docs[source["id"]]
        assert hashlib.sha256(resolve_knowledge_file(root, doc.metadata["source_snapshot"]).read_bytes()).hexdigest() == source["sha256"]
        assert hashlib.sha256(resolve_knowledge_file(root, doc.metadata["source_path"]).read_bytes()).hexdigest() == doc.metadata["normalized_hash"]
        assert resolve_knowledge_file(root, doc.metadata["license"]).is_file()
        for chunk in chunk_documents([doc]):
            start, end = chunk.metadata["line_start"], chunk.metadata["line_end"]
            assert chunk.page_content in "\n".join(doc.page_content.splitlines()[start - 1:end])
            if doc.metadata["source_type"] == "pdf":
                span = doc.metadata["page_spans"][chunk.metadata["page"] - 1]
                assert span["line_start"] <= start <= end <= span["line_end"]


def _preparer():
    spec = importlib.util.spec_from_file_location("bulk_preparer_test", PROJECT_ROOT / "scripts/expand_authoritative_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_heading_maps_use_real_lines_and_heading_depth():
    preparer = _preparer()
    text = "# Root\n\nIntroduction\n\n### Embeddings\n\nBody\n\n```text\n## Fake\n```\n\n## BM25\n\nSearch"
    mapping, warnings = preparer.build_section_map(text, ["RAG 基础概念"])
    assert not warnings
    assert "Embedding" in mapping["Root / Embeddings"]
    assert "混合检索" in mapping["Root / BM25"]
    assert all("Fake" not in key for key in mapping)


def test_source_preparation_rejects_outside_paths():
    preparer = _preparer()
    with pytest.raises(preparer.SourceError):
        preparer.local_path("../../outside")
    with pytest.raises(preparer.SourceError):
        preparer.local_path("C:/outside")


def test_large_rst_documentation_splits_only_at_original_tabs():
    preparer = _preparer()
    introduction = "Architecture introduction.\n\n"
    examples = [".. tab:: Model " + str(index) + "\n\n    " + "print('example')\n    " * 150 for index in range(5)]
    text = "```{eval-rst}\n" + introduction + "\n\n".join(examples) + "\n```"
    normalized, warnings = preparer.split_rst_tabs(text)
    assert warnings and normalized.count("```{eval-rst}") == 6
    assert introduction in normalized and all(example in normalized for example in examples)
    chunks = structural_chunks(Document(page_content=normalized), chunk_size=500, chunk_overlap=100)
    assert chunks and all(len(chunk.page_content) <= 12000 for chunk in chunks)
