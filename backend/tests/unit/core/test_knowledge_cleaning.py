"""Small offline regression for source cleaning and exact-text vector reuse."""
from copy import deepcopy
import json
import sqlite3

import pytest
from langchain.schema import Document

from scripts import prepare_chinese_sources as tool
from scripts.refresh_cleaned_knowledge import ReusingVectorIndex, verify_history, validate_prior_index, KB_ID


def test_badge_anchor_is_removed_but_named_link_and_code_are_preserved():
    parser = tool.OfficialHTML("https://example.org/docs/")
    parser.feed('<h1>图检索</h1><p><a href="demo.ipynb">\n<img src="colab-badge.svg" alt="Colab"/>\n</a></p>'
                '<p><a href="source.py">完整示例代码</a></p>'
                '<table><tr><th>名称</th></tr><tr><td><a href="item">链接</a></td></tr></table>'
                '<pre><code class="language-python">value = "[ ](example)"\n\n\n\n    print(value)</code></pre>')
    text = parser.result()
    assert "demo.ipynb" not in text and "colab-badge" not in text
    assert "[完整示例代码](https://example.org/docs/source.py)" in text
    assert "| [链接](https://example.org/docs/item) |" in text
    assert 'value = "[ ](example)"\n\n\n\n    print(value)' in text
    assert parser.empty_links_removed == 1
    assert parser.blank_lines_removed > 0


@pytest.mark.parametrize("marker", ["```", "~~~~"])
def test_layout_compaction_preserves_fenced_bytes_and_is_idempotent(marker):
    code = f'{marker}python\n  x = 1\n\n\n\n  y = 2\n{marker}\n'
    text = "# Title\n\n\n\nParagraph\n\n\n" + code + "\n\n\nNext\n"
    cleaned, removed = tool.compact_layout_blanks(text)
    assert code in cleaned and removed == 5
    assert tool.compact_layout_blanks(cleaned) == (cleaned, 0)


def test_unclosed_fence_fails_instead_of_rewriting_code():
    with pytest.raises(tool.common.SourceError):
        tool.compact_layout_blanks("```python\n  data\n\n\n")


def _refresh_tree(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    root.mkdir()
    path = "references/zh/milvus/example/content.md"
    raw = "references/zh/milvus/example/original.md"
    assets = {path: b"old body", raw: b"pinned raw", "provenance/registry.json": b"{}"}
    for name, data in assets.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    previous = {"sources": [{"normalized_path": path}],
                "asset_hashes": {name: tool.digest(data) for name, data in assets.items()}}
    registry = {"manifest_documents": [{"id": "source_zh_milvus_example", "file": path, "normalized_hash": tool.digest(b"new body")}]}
    assets[tool.REGISTRY] = tool.canonical(registry)
    registry_file = root / tool.REGISTRY
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_bytes(tool.canonical(previous))
    (root / "metadata.json").write_bytes(tool.canonical({"documents": [{"id": "source_zh_milvus_example", "file": path}]}))
    monkeypatch.setattr(tool, "KB", root)
    monkeypatch.setattr(tool.common, "KB_ROOT", root)
    monkeypatch.setattr(tool, "check_layout", lambda *args: None)
    monkeypatch.setattr(tool, "registry_payload", lambda *args: {"status": "new"})
    assets[path] = b"new body"
    return root, path, raw, assets, previous


def test_explicit_refresh_backs_up_old_body_and_never_changes_original(tmp_path, monkeypatch):
    root, path, raw, assets, previous = _refresh_tree(tmp_path, monkeypatch)
    receipt = tmp_path / "receipt"
    result = tool.refresh_derived_assets(assets, previous, receipt)
    assert result["status"] == "complete"
    assert (root / path).read_bytes() == b"new body"
    assert (receipt / "before" / path).read_bytes() == b"old body"
    assert (root / raw).read_bytes() == b"pinned raw"


@pytest.mark.parametrize("damage", ["edited_body", "upstream_rewrite", "commit_failure"])
def test_refresh_refuses_drift_or_rolls_back_all_outputs(tmp_path, monkeypatch, damage):
    root, path, raw, assets, previous = _refresh_tree(tmp_path, monkeypatch)
    if damage == "edited_body":
        (root / path).write_bytes(b"uncommitted local edit")
    elif damage == "upstream_rewrite":
        assets[raw] = b"different original"
    else:
        monkeypatch.setattr(tool, "registry_payload", lambda *args: (_ for _ in ()).throw(ValueError("synthetic failure")))
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, tool.common.SourceError)):
        tool.refresh_derived_assets(assets, previous, tmp_path / "receipt")
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


class FakeStore:
    def __init__(self):
        self.rows = {}
        self._collection = self
        self.embedded = []
        self.metadata = {}

    def get(self, include):
        return {"ids": list(self.rows), "documents": [row[0] for row in self.rows.values()],
                "metadatas": [row[1] for row in self.rows.values()], "embeddings": [row[2] for row in self.rows.values()]}

    def upsert(self, ids, documents, metadatas, embeddings):
        for ident, text, meta, vector in zip(ids, documents, metadatas, embeddings, strict=True):
            self.rows[ident] = (text, meta, vector)

    def add_documents(self, documents, ids):
        self.embedded.extend(ids)
        self.upsert(ids, [d.page_content for d in documents], [d.metadata for d in documents], [[1.0, 0.0]] * len(ids))

    def delete(self, ids):
        for ident in ids:
            self.rows.pop(ident)


def chunk(ident, text="same", config="fixed"):
    return Document(page_content=text, metadata={"chunk_id": ident, "knowledge_base_id": "rag_engineering_training",
                                                 "chunking_config_hash": config})


def test_same_text_reuses_embedding_with_new_id_but_changed_text_is_embedded():
    store = FakeStore()
    old = chunk("old-version-id")
    store.rows["old-version-id"] = (old.page_content, old.metadata, [0.25, 0.75])
    new = chunk("new-version-id")
    adapter = ReusingVectorIndex(store, profile_fingerprint="fixed-profile", dimensions=2)
    adapter.synchronize([new, chunk("genuine-new", "changed")], knowledge_base_id="rag_engineering_training")
    assert store.rows[new.metadata["chunk_id"]][2] == [0.25, 0.75]
    assert store.embedded == ["genuine-new"]
    assert "old-version-id" not in store.rows
    assert adapter.stats["exact_text_reused"] == adapter.stats["embedded"] == 1


def test_changed_chunking_config_cannot_reuse_old_embedding():
    store = FakeStore()
    store.rows["old"] = ("same", chunk("old").metadata, [0.25, 0.75])
    ReusingVectorIndex(store, profile_fingerprint="fixed", dimensions=2).synchronize(
        [chunk("new", config="different")], knowledge_base_id="rag_engineering_training")
    assert store.embedded == ["new"]


@pytest.mark.parametrize("damage", ["dimension", "nan", "stable_id"])
def test_vector_corruption_fails_before_deleting_old_records(damage):
    store = FakeStore()
    metadata = chunk("old").metadata
    vector = [1.0] if damage == "dimension" else [float("nan"), 0.0] if damage == "nan" else [1.0, 0.0]
    store.rows["old"] = ("same", metadata, vector)
    before = deepcopy(store.rows)
    with pytest.raises(ValueError):
        ReusingVectorIndex(store, profile_fingerprint="fixed", dimensions=2).synchronize(
            [chunk("old", "different") if damage == "stable_id" else chunk("new")], knowledge_base_id="rag_engineering_training")
    assert list(store.rows) == list(before)


def test_history_guard_allows_new_versions_but_not_modified_evidence():
    before = {"knowledge_document_versions": {"old": "hash"}, "retrieval_evidence_snapshots": {"ev": "frozen"}}
    after = deepcopy(before)
    after["knowledge_document_versions"]["new"] = "new hash"
    verify_history(before, after)
    after["retrieval_evidence_snapshots"]["ev"] = "changed"
    with pytest.raises(ValueError):
        verify_history(before, after)


@pytest.mark.parametrize("damage", [None, "not_ready", "identity", "profile"])
def test_prior_index_requires_ready_exact_sql_vector_text_and_persisted_profile(tmp_path, damage):
    store = FakeStore()
    store.rows["one"] = ("same", chunk("one").metadata, [1.0, 0.0])
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE knowledge_index_status (knowledge_base_id,status,active_snapshot_hash,expected_chunk_count,sql_chunk_count,vector_chunk_count)")
    connection.execute("CREATE TABLE knowledge_chunk_versions (knowledge_base_id,chunk_id,content,active)")
    connection.execute("INSERT INTO knowledge_index_status VALUES (?,?,?,?,?,?)", (KB_ID, "failed" if damage == "not_ready" else "ready", "snapshot", 1, 1, 1))
    connection.execute("INSERT INTO knowledge_chunk_versions VALUES (?,?,?,?)", (KB_ID, "different" if damage == "identity" else "one", "same", 1))
    (tmp_path / "knowledge-embedding-profile.json").write_text(json.dumps({"knowledge_base_id": KB_ID,
        "profile_fingerprint": "wrong" if damage == "profile" else "fixed"}), encoding="utf-8")
    try:
        if damage:
            with pytest.raises(ValueError):
                validate_prior_index(connection, store, profile_fingerprint="fixed", model={}, db_path=tmp_path / "db", vector_path=tmp_path)
        else:
            result = validate_prior_index(connection, store, profile_fingerprint="fixed", model={}, db_path=tmp_path / "db", vector_path=tmp_path)
            assert result["sql_vector_identity_and_text_match"]
    finally:
        connection.close()


def test_current_html_sources_have_no_empty_links_or_layout_runs_outside_code():
    catalog, _ = tool.read_catalog()
    registry = json.loads(tool.common.local_path(tool.REGISTRY).read_text(encoding="utf-8"))
    html_ids = {item["id"] for item in catalog["sources"] if item["kind"] == "html_markdown"}
    import re
    for item in registry["sources"]:
        if item["id"] not in html_ids:
            continue
        body = tool.common.local_path(item["normalized_path"]).read_text(encoding="utf-8")
        outside = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*$", "", body)
        assert not re.search(r"\[\s*\]\([^)]*\)", outside), item["id"]
        assert tool.compact_layout_blanks(body)[1] == 0, item["id"]
