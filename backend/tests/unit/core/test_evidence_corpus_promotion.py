"""Small file-only evidence epoch activation/recovery checks."""
from copy import deepcopy
import json

import pytest

from app.core.retrieval.knowledge_base import load_documents, chunk_documents
from scripts import evidence_corpus_promotion as promoter
from scripts.knowledge_layout import encoded, registry_payload, write_atomic, LAYOUT


def fixture(tmp_path, monkeypatch):
    source = tmp_path / "source"
    output = tmp_path / "output/knowledge-cleaning/test"
    candidate = output / "corpus/synthetic"
    source.mkdir()
    (source / "README.md").write_text("old source", encoding="utf-8")
    spec = {"id": "module_test", "title": "Topic", "file": "teaching/zh/test.md", "knowledge_points": ["node"]}
    text = "# Topic\n\n[Demo](https://example.org/demo)\n\nComplete technical explanation.\n"
    write_atomic(source / spec["file"], text.encode())
    manifest = {"knowledge_base_id": "synthetic", "version": "1", "document_identity_revision": "epoch",
        "storage_layout": LAYOUT, "documents": [spec]}
    write_atomic(source / "metadata.json", encoded(manifest))
    for batch in ("pilot", "bulk", "chinese"):
        write_atomic(source / f"provenance/import_batches/{batch}.json", encoded({"sources": []}))
    write_atomic(source / "provenance/registry.json", encoded(registry_payload(source)))
    before = promoter.file_hashes(source)
    import shutil
    shutil.copytree(source, candidate)
    transformed, _, links, _ = promoter.builder.transform(spec, text)
    new = deepcopy(manifest)
    new["document_identity_revision"] += "-evidence-v2"
    new["chunking"] = {"strategy": "recursive_v1", "chunk_size": 900, "chunk_overlap": 100}
    new["documents"][0]["chunking_strategy"] = "markdown_evidence_v2"
    new["staged_evidence_chunking"] = {"profile": promoter.builder.PROFILE, "strategy": "markdown_evidence_v2",
        "target_chars": 900, "soft_max_chars": 1200, "overlap_chars": 100, "ingested": False,
        "parent_context_runtime_enabled": False}
    write_atomic(candidate / spec["file"], transformed.encode())
    write_atomic(candidate / "metadata.json", encoded(new))
    write_atomic(candidate / "provenance/auxiliary_links.json", encoded({"profile": promoter.builder.PROFILE,
        "documents": {spec["id"]: links}}))
    write_atomic(candidate / "provenance/registry.json", encoded(registry_payload(candidate)))
    chunks = chunk_documents(load_documents(str(candidate)), chunk_size=900, chunk_overlap=100)
    audit = {"source_hashes": before, "candidate_snapshot_hash": promoter.builder.digest_chunks(chunks),
        "new": {"count": len(chunks)}, "documents": [spec]}
    write_atomic(output / "audit.json", encoded(audit))
    monkeypatch.setattr(promoter, "KB", source)
    monkeypatch.setattr(promoter.previous, "ROOT", tmp_path)
    monkeypatch.setattr(promoter.builder, "ROOT", tmp_path)
    monkeypatch.setattr(promoter.builder, "verify", lambda *a, **kw: None)
    return source, output, tmp_path / "backend/data/knowledge_backups/case/source", before


def test_promote_replays_old_source_and_verifies_new_v2_identity(tmp_path, monkeypatch):
    source, output, receipt, before = fixture(tmp_path, monkeypatch)
    result = promoter.promote(output, receipt)
    assert result["status"] == "files_promoted" and result["ingested"] is False
    with promoter.reconstructed_previous(source) as base:
        assert promoter.file_hashes(base) == before
    assert promoter.verify_active()["chunks"] == 1
    assert "https://example.org/demo" not in (source / "teaching/zh/test.md").read_text()
    assert (receipt / ".gitignore").read_text() == "*\n"


def test_explicit_rollback_preserves_all_before_bytes(tmp_path, monkeypatch):
    source, output, receipt, before = fixture(tmp_path, monkeypatch)
    promoter.promote(output, receipt)
    promoter.previous.rollback(receipt, active=source)
    assert promoter.file_hashes(source) == before


def test_failed_verification_restores_source_without_touching_database(tmp_path, monkeypatch):
    source, output, receipt, before = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(promoter, "verify_active", lambda *a, **kw: (_ for _ in ()).throw(ValueError("synthetic failure")))
    with pytest.raises(ValueError, match="synthetic failure"):
        promoter.promote(output, receipt)
    assert promoter.file_hashes(source) == before


def test_rollback_does_not_overwrite_concurrent_source_deletion(tmp_path, monkeypatch):
    source, output, receipt, _ = fixture(tmp_path, monkeypatch)
    promoter.promote(output, receipt)
    deleted = source / "teaching/zh/test.md"
    deleted.unlink()
    remaining = promoter.file_hashes(source)
    with pytest.raises(ValueError, match="concurrent source deletion"):
        promoter.previous.rollback(receipt, active=source)
    assert not deleted.exists() and promoter.file_hashes(source) == remaining


@pytest.mark.parametrize("damage", ["source", "existing_backup", "candidate_missing"])
def test_refuses_drift_or_missing_asset_or_backup_overwrite(tmp_path, monkeypatch, damage):
    source, output, receipt, _ = fixture(tmp_path, monkeypatch)
    if damage == "source":
        (source / "README.md").write_text("external change")
    elif damage == "existing_backup":
        receipt.mkdir(parents=True)
    else:
        (output / "corpus/synthetic/README.md").unlink()
    before = promoter.file_hashes(source)
    with pytest.raises((ValueError, FileExistsError)):
        promoter.promote(output, receipt)
    assert promoter.file_hashes(source) == before


def test_final_registry_concurrent_edit_is_not_overwritten(tmp_path, monkeypatch):
    source, output, receipt, _ = fixture(tmp_path, monkeypatch)
    original = promoter.registry_payload

    def concurrent(root):
        value = original(root)
        (source / "provenance/registry.json").write_text("external edit")
        return value

    monkeypatch.setattr(promoter, "registry_payload", concurrent)
    with pytest.raises(ValueError):
        promoter.promote(output, receipt)
    assert (source / "provenance/registry.json").read_text() == "external edit"
    assert json.loads((receipt / "receipt.json").read_text())["status"] == "recovery_blocked"


def test_wrong_replay_node_mapping_fails_even_with_valid_registry(tmp_path, monkeypatch):
    source, output, receipt, _ = fixture(tmp_path, monkeypatch)
    promoter.promote(output, receipt)
    path = source / "metadata.json"
    manifest = json.loads(path.read_text())
    manifest["documents"][0]["knowledge_points"] = ["invented"]
    write_atomic(path, encoded(manifest))
    write_atomic(source / "provenance/registry.json", encoded(registry_payload(source)))
    with pytest.raises(ValueError, match="metadata"):
        promoter.verify_active()
