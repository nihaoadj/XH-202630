"""Short deterministic checks for the authoritative-source pilot."""
import hashlib
import json
from app.core.retrieval.knowledge_paths import resolve_knowledge_file

import pytest
from langchain.schema import Document

from app.core.retrieval.knowledge_base import chunk_documents, load_documents
from app.core.retrieval.markdown_structure import MAX_ATOMIC_CHARS, structural_chunks
from tests.paths import BACKEND_ROOT, KNOWLEDGE_BASE_ROOT


def test_teaching_revision_preserves_documents_and_chunker_not_old_content_ids():
    baseline = json.loads((BACKEND_ROOT / "tests/fixtures/knowledge_pilot/legacy_chunks.json").read_text())
    from tests.fakes.knowledge_versions import pre_evidence_corpus
    with pre_evidence_corpus() as base:
        docs = [doc for doc in load_documents(str(base)) if doc.metadata["source_path"].startswith("teaching/zh/")]
    chunks = chunk_documents(docs)
    revision = json.loads((BACKEND_ROOT / "tests/fixtures/knowledge_pilot/teaching_v2_m3.json").read_text(encoding="utf-8"))
    assert {d.metadata["document_id"] for d in docs} == set(baseline["chunks"].values())
    expected = {ident: doc_id for doc_id, entry in revision["documents"].items() for ident in entry["chunk_ids"]}
    assert {c.metadata["chunk_id"]: c.metadata["document_id"] for c in chunks} == expected
    assert {c.metadata["chunking_config_hash"] for c in chunks} == {baseline["config_hash"]}
    # Retain the legacy loader projection; only teaching content/version changes.
    assert all("document_type" not in doc.metadata for doc in docs)


def _split(text, mapping=None, size=100):
    doc = Document(page_content=text, metadata={"section_knowledge_points": mapping or {}})
    return structural_chunks(doc, chunk_size=size, chunk_overlap=20)


def test_sections_ignore_code_headings_and_preserve_exact_offsets():
    code = "```python\n# not a heading\n" + "print('x')\n" * 15 + "```"
    text = f"# Guide\n\n## First\n\nIntro.\n\n{code}\n\n## Second\n\nOther text."
    chunks = _split(text, {"Guide / First": ["Chunk 切分"], "Guide / Second": ["Embedding"]})
    atomic = [c for c in chunks if c.metadata["atomic_block"]]
    assert len(atomic) == 1 and atomic[0].page_content == code
    assert atomic[0].metadata["oversized_block"]
    assert atomic[0].metadata["section"] == "Guide / First"
    assert atomic[0].metadata["knowledge_points"] == ["Chunk 切分"]
    assert chunks[-1].metadata["knowledge_points"] == ["Embedding"]
    for chunk in chunks:
        start = chunk.metadata["start_index"]
        assert text[start:start + len(chunk.page_content)] == chunk.page_content
        assert not ("First" in chunk.page_content and "Second" in chunk.page_content)


def test_tables_are_not_split_and_ordinary_paragraphs_are_bounded():
    table = "| name | value |\n| --- | --- |\n" + "| Example | 123 |\n" * 15
    chunks = _split("# Tables\n\n" + table + "\n" + "word " * 100)
    atomic = [c for c in chunks if c.metadata["atomic_block"]]
    assert len(atomic) == 1 and atomic[0].page_content == table.strip()
    assert all(len(c.page_content) <= 100 for c in chunks if not c.metadata["atomic_block"])


@pytest.mark.parametrize("text", ["```python\nunclosed", "```\n" + "x" * MAX_ATOMIC_CHARS + "\n```"])
def test_unsafe_or_unbounded_atomic_blocks_fail_closed(text):
    with pytest.raises(ValueError):
        _split(text)


def test_unmapped_sections_are_not_filled_with_document_tags():
    doc = Document(page_content="# Guide\n\nIntro\n\n## Tagged\n\nContent\n\n## Other\n\nUnknown", metadata={
        "knowledge_points": ["Embedding"],
        "section_knowledge_points": {"Guide / Tagged": ["Chunk 切分"]},
    })
    chunks = structural_chunks(doc, chunk_size=100, chunk_overlap=20)
    assert chunks[0].metadata["knowledge_points"] == []
    assert chunks[-1].metadata["knowledge_points"] == []
    assert chunks[1].metadata["knowledge_points"] == ["Chunk 切分"]


def test_unknown_document_strategy_is_rejected():
    with pytest.raises(ValueError, match="Unsupported"):
        chunk_documents([Document(page_content="text", metadata={"chunking_strategy": "unknown"})])


@pytest.mark.parametrize("tamper", ["original.source", "normalized.md"])
def test_modified_authoritative_files_fail_before_indexing(tmp_path, tamper):
    original = b"# Source\n\nComplete text."
    for name in ("original.source", "normalized.md"):
        (tmp_path / name).write_bytes(original)
    spec = {
        "id": "official", "file": "normalized.md", "document_type": "authoritative_original",
        "source_snapshot": "original.source", "source_hash": hashlib.sha256(original).hexdigest(),
        "normalized_hash": hashlib.sha256(original).hexdigest(),
    }
    (tmp_path / "metadata.json").write_text(json.dumps({"documents": [spec]}))
    (tmp_path / tamper).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_documents(str(tmp_path))


def test_pilot_sources_are_complete_pinned_and_licensed():
    root = KNOWLEDGE_BASE_ROOT / "rag_engineering_training"
    registry = json.loads(resolve_knowledge_file(root, "provenance/import_batches/pilot.json").read_text(encoding="utf-8"))
    # Registry is verified by the preparation CLI as well; the loader validates
    # snapshot/normalized hashes before building any SQL/Chroma projection.
    pilot_ids = {source["id"] for source in registry["sources"]}
    sources = [doc for doc in load_documents(str(root)) if doc.metadata["document_id"] in pilot_ids]
    assert len(sources) == 3
    assert len(registry["sources"]) == 3
    known = {node["name"] for node in json.loads((root / "metadata.json").read_text(encoding="utf-8"))["skill_nodes"]}
    for doc in sources:
        assert hashlib.sha256(resolve_knowledge_file(root, doc.metadata["source_snapshot"]).read_bytes()).hexdigest() == doc.metadata["source_hash"]
        assert resolve_knowledge_file(root, doc.metadata["license"]).is_file()
        assert len(doc.metadata["source_version"]) == 40
        assert all(set(points) <= known for points in doc.metadata["section_knowledge_points"].values())
    chunks = chunk_documents(sources)
    assert chunks and all(c.metadata.get("chunking_strategy") == "markdown_evidence_v2" for c in chunks)
    assert all(doc.metadata["chunking_strategy"] == "markdown_evidence_v2" for doc in sources)
    for chunk in chunks:
        doc = next(d for d in sources if d.metadata["document_id"] == chunk.metadata["document_id"])
        lines = doc.page_content.splitlines()[chunk.metadata["line_start"] - 1:chunk.metadata["line_end"]]
        assert chunk.page_content in "\n".join(lines)
