"""Direct layout: physical paths and manifest-only indexing, not legacy aliases."""
import hashlib
import json
from pathlib import Path
import pytest
from app.core.retrieval.knowledge_base import load_documents, chunk_documents
from scripts.knowledge_layout import KB, LAYOUT, check_layout

def test_current_tree_has_62_docs_and_no_legacy_directories():
    registry=check_layout()
    assert registry["document_count"]==62
    assert not (KB/"modules").exists() and not (KB/"sources").exists()
    assert not (KB/"provenance/path_aliases.json").exists()
    docs=load_documents()
    chunks=chunk_documents(docs)
    fixture=json.loads((KB.parents[1]/"backend/tests/fixtures/knowledge_pilot/teaching_v2_m3.json").read_text(encoding="utf-8"))
    expected_teaching=sum(len(item["chunk_ids"]) for item in fixture["documents"].values())
    metadata=json.loads((KB/"metadata.json").read_text(encoding="utf-8"))
    if metadata.get("active_evidence_chunking"):
        active=json.loads((KB.parents[1]/"backend/tests/fixtures/knowledge_pilot/evidence_units_v2.json").read_text(encoding="utf-8"))
        chunks=chunk_documents(docs,chunk_size=active["chunk_size"],chunk_overlap=active["chunk_overlap"])
        assert metadata["active_evidence_chunking"]["profile"]==active["profile"]=="evidence-units-v2"
        assert len(docs)==active["document_count"]==62 and len(chunks)==active["chunk_count"]==1121
    elif metadata.get("active_corpus_cleaning"):
        active=json.loads((KB.parents[1]/"backend/tests/fixtures/knowledge_pilot/corpus_clean_v1.json").read_text(encoding="utf-8"))
        assert metadata["active_corpus_cleaning"]["profile"]==active["profile"]=="corpus-clean-v1"
        assert len(docs)==active["document_count"]==62 and len(chunks)==active["chunk_count"]==3177
    else:
        # T24: English 1626 + Chinese 1462 + teaching 126.
        assert len(docs)==62 and len(chunks)==3088+expected_teaching
    assert all(d.metadata["source_version"]==fixture["revision"] for d in docs if d.metadata["document_id"].startswith("module_"))
    assert all((KB/d.metadata["source_path"]).is_file() for d in docs)
    assert len(list((KB/"references").rglob("content.md")))==56
    assert len(list((KB/"teaching/zh").glob("*.md")))==6
    assert len(list((KB/"references").rglob("original.*")))==56

def test_complete_upstream_and_normalized_bytes_are_preserved():
    metadata=json.loads((KB/"metadata.json").read_text(encoding="utf-8"))
    for doc in metadata["documents"]:
        if doc.get("source_snapshot"):
            assert hashlib.sha256((KB/doc["source_snapshot"]).read_bytes()).hexdigest()==doc["source_hash"]
            assert hashlib.sha256((KB/doc["file"]).read_bytes()).hexdigest()==doc["normalized_hash"]

def _kb(tmp_path):
    (tmp_path/"body.md").write_text("# Lesson\n\nBody",encoding="utf-8")
    (tmp_path/"original.md").write_text("# Unindexed original",encoding="utf-8")
    (tmp_path/"README.md").write_text("# Navigation",encoding="utf-8")
    data={"knowledge_base_id":"unit","version":"1","storage_layout":LAYOUT,"documents":[{"id":"lesson","file":"body.md"}]}
    (tmp_path/"metadata.json").write_text(json.dumps(data),encoding="utf-8")
    return data

def test_original_and_readme_are_not_implicitly_indexed(tmp_path):
    _kb(tmp_path)
    docs=load_documents(str(tmp_path))
    assert len(docs)==1 and docs[0].metadata["document_id"]=="lesson"

@pytest.mark.parametrize("change",["duplicate","missing","empty"])
def test_invalid_declared_bodies_are_rejected(tmp_path,change):
    data=_kb(tmp_path)
    if change=="duplicate":
        data["documents"].append({"id":"other","file":"body.md"})
    elif change=="missing":
        data["documents"][0]["file"]="missing.md"
    else:
        (tmp_path/"body.md").write_text("",encoding="utf-8")
    (tmp_path/"metadata.json").write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises((ValueError,FileNotFoundError)):
        load_documents(str(tmp_path))
