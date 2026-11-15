"""Stopped-service file promotion/replay; no business DB or models."""
import json
from pathlib import Path

import pytest

from scripts import knowledge_corpus_cleaning as cleaner
from scripts import knowledge_corpus_promotion as promotion
from backend.tests.unit.core.test_knowledge_corpus_cleaning import _source


def setup_candidate(tmp_path, monkeypatch):
    source, output = _source(tmp_path, monkeypatch)
    monkeypatch.setattr(promotion, "ROOT", tmp_path)
    cleaner.build(output, apply=True)
    receipt = tmp_path / "backend/data/knowledge_backups/test/source"
    return source, output, receipt


def test_promote_retains_portable_base_and_replays_original_candidate(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    before = cleaner.file_hashes(source)
    result = promotion.promote(output, receipt)
    assert result["status"] == "files_promoted" and result["ingested"] is False
    assert cleaner.file_hashes(receipt / "source-before") == before
    assert (receipt / ".gitignore").read_text() == "*\n"
    with promotion.reconstructed_base(source) as base:
        assert cleaner.file_hashes(base) == before
    assert promotion.verify_active()["documents"] == 62
    assert cleaner.verify(output)["documents"] == 62


def test_rollback_restores_all_bytes_and_removes_only_added_files(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    before = cleaner.file_hashes(source)
    promotion.promote(output, receipt)
    promotion.rollback(receipt)
    assert cleaner.file_hashes(source) == before
    assert not (source / promotion.DESCRIPTOR).is_file()
    assert cleaner.verify(output)["documents"] == 62


def test_rebuilding_candidate_after_promotion_replays_base_without_touching_active_files(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    promotion.promote(output, receipt)
    before = cleaner.file_hashes(source)
    rebuilt = output.parent / "rebuilt"
    cleaner.build(rebuilt, apply=True)
    assert cleaner.file_hashes(source) == before
    assert json.loads((rebuilt / "candidate-snapshot.json").read_text()) == json.loads((output / "candidate-snapshot.json").read_text())


def test_partial_failure_rolls_back_before_propagating_error(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    before = cleaner.file_hashes(source)
    monkeypatch.setattr(promotion, "verify_active", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic check failure")))
    with pytest.raises(ValueError, match="synthetic"):
        promotion.promote(output, receipt)
    assert cleaner.file_hashes(source) == before
    assert json.loads((receipt / "receipt.json").read_text())["status"] == "source_rolled_back"


@pytest.mark.parametrize("damage", ["source", "candidate", "existing_receipt"])
def test_preflight_refuses_drift_or_overwriting_backup(tmp_path, monkeypatch, damage):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    if damage == "source":
        (source / "README.md").write_text("concurrent edit", encoding="utf-8")
    elif damage == "candidate":
        (output / "corpus/synthetic/teaching/zh/00.md").write_text("damaged", encoding="utf-8")
    else:
        receipt.mkdir(parents=True)
        (receipt / "keep").write_text("keep")
    before = cleaner.file_hashes(source)
    with pytest.raises((ValueError, FileExistsError)):
        promotion.promote(output, receipt)
    assert cleaner.file_hashes(source) == before


def test_rollback_rejects_concurrent_edit_instead_of_overwriting_user_work(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    promotion.promote(output, receipt)
    path = source / "teaching/zh/00.md"
    path.write_text("user changed this", encoding="utf-8")
    with pytest.raises(ValueError, match="concurrent"):
        promotion.rollback(receipt)
    assert path.read_text() == "user changed this"


def test_final_registry_write_never_overwrites_concurrent_external_edit(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    original = promotion.registry_payload

    def concurrently_edit_registry(root):
        payload = original(root)
        (source / "provenance/registry.json").write_text("external edit", encoding="utf-8")
        return payload

    monkeypatch.setattr(promotion, "registry_payload", concurrently_edit_registry)
    with pytest.raises(ValueError, match="concurrent"):
        promotion.promote(output, receipt)
    assert (source / "provenance/registry.json").read_text() == "external edit"
    assert json.loads((receipt / "receipt.json").read_text())["status"] == "recovery_blocked"


@pytest.mark.parametrize("path", ["../outside", "backend/data", "backend/data/knowledge_backups"])
def test_receipt_scope_rejects_broad_or_external_paths(tmp_path, monkeypatch, path):
    monkeypatch.setattr(promotion, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        promotion.private_receipt(tmp_path / path)


def test_baseline_blob_drift_is_rejected(tmp_path, monkeypatch):
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    promotion.promote(output, receipt)
    blob = next((source / promotion.BASE / "blobs").glob("*.source"))
    blob.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="baseline drift"):
        with promotion.reconstructed_base(source):
            pass


def test_active_manifest_cannot_silently_change_node_mapping(tmp_path, monkeypatch):
    from scripts.knowledge_layout import encoded, registry_payload, write_atomic
    source, output, receipt = setup_candidate(tmp_path, monkeypatch)
    promotion.promote(output, receipt)
    path = source / "metadata.json"
    manifest = json.loads(path.read_text())
    manifest["documents"][0]["knowledge_points"] = ["invented"]
    write_atomic(path, encoded(manifest))
    write_atomic(source / "provenance/registry.json", encoded(registry_payload(source)))
    with pytest.raises(ValueError, match="deterministic replay"):
        promotion.verify_active()


def test_promoter_has_no_database_model_network_or_process_imports():
    import ast
    tree = ast.parse(Path(promotion.__file__).read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    forbidden = ("sqlite3", "sqlalchemy", "chromadb", "app.db", "app.services", "httpx", "requests", "socket", "subprocess")
    assert not any(name == prefix or name.startswith(prefix + ".") for name in imports for prefix in forbidden)
