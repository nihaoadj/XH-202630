"""Offline maintenance: reconcile cleaned sources, reusing exact-text embeddings.

Stop this project's Web and Workers first. Never changes model configuration,
deletes SQL history, or edits frozen Evidence. Backups contain private local data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.config import get_settings, resolve_backend_path  # noqa: E402
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest, load_documents, chunk_documents  # noqa: E402
from app.core.retrieval.vector_store import get_vector_store, _to_chroma_document  # noqa: E402
from app.db.knowledge import KnowledgeCatalogRepository  # noqa: E402
from app.db.shared.database import get_session_factory  # noqa: E402
from app.services.knowledge.ingestion import ChromaKnowledgeVectorIndex, IngestionService  # noqa: E402
from scripts.knowledge_layout import encoded, write_atomic  # noqa: E402
from scripts.rebuild_multilingual_index import verify_model_receipt  # noqa: E402
from langchain.schema import Document  # noqa: E402

KB_ID = "rag_engineering_training"


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def history_baseline(connection):
    """All immutable historical rows, not just the latest enabled version."""
    result = {}
    for table, key in (("retrieval_evidence_snapshots", "evidence_id"),
                       ("knowledge_document_versions", "document_version"),
                       ("knowledge_chunk_versions", "chunk_id")):
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                   if row[1] not in {"enabled", "is_current", "active"}]
        if not columns or key not in columns:
            raise ValueError("historical schema missing")
        rows = connection.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
        index = columns.index(key)
        result[table] = {str(row[index]): digest(list(row)) for row in rows}
    return result


def verify_history(before, after):
    for table, rows in before.items():
        if any(after[table].get(key) != value for key, value in rows.items()):
            raise ValueError(f"historical immutable rows changed: {table}")
        if table == "retrieval_evidence_snapshots" and after[table] != rows:
            raise ValueError("frozen evidence changed during maintenance")


def validate_prior_index(connection, store, *, profile_fingerprint, model, db_path, vector_path):
    """Bind legacy unlabelled vectors to their verified build receipt before reuse."""
    state = connection.execute(
        "SELECT status,active_snapshot_hash,expected_chunk_count,sql_chunk_count,vector_chunk_count "
        "FROM knowledge_index_status WHERE knowledge_base_id = ?", (KB_ID,),
    ).fetchone()
    active = connection.execute(
        "SELECT chunk_id,content FROM knowledge_chunk_versions WHERE knowledge_base_id = ? AND active = 1", (KB_ID,),
    ).fetchall()
    old = store.get(include=["documents"])
    if (state is None or state[0] != "ready" or not active
            or set(state[2:]) != {len(active)} or len(old["ids"]) != len(active)
            or dict(zip(old["ids"], old["documents"], strict=True)) != dict(active)):
        raise ValueError("prior index not ready or SQL/vector identities/text differ")
    marker = (store._collection.metadata or {}).get("embedding_profile_fingerprint")
    sidecar = vector_path / "knowledge-embedding-profile.json"
    if sidecar.is_file():
        stored_profile = json.loads(sidecar.read_text(encoding="utf-8"))
        if stored_profile.get("knowledge_base_id") != KB_ID or stored_profile.get("profile_fingerprint") != profile_fingerprint:
            raise ValueError("persisted vector profile receipt differs")
        marker = stored_profile["profile_fingerprint"]
    if marker is not None:
        if marker != profile_fingerprint:
            raise ValueError("persisted vector embedding profile differs")
        proof = "persisted_vector_profile"
    else:
        build = json.loads((ROOT / "output/test-runs/kb-m3/build.json").read_text(encoding="utf-8"))
        audit = json.loads((ROOT / "output/test-runs/kb-m3/audit.json").read_text(encoding="utf-8"))
        if (build["status"] != "ready" or build["active_snapshot_hash"] != state[1]
                or build["model_id"] != model["model_id"] or build["model_revision"] != model["model_revision"]
                or Path(build["target_database"]).resolve() != db_path.resolve()
                or Path(build["target_vectors"]).resolve() != vector_path.resolve()
                or build["vector_chunk_count"] != len(active) or audit["status"] != "passed"
                or audit["exact_sql_vector_text_metadata"] != "passed"):
            raise ValueError("cannot establish legacy vector profile from verified build history")
        proof = "verified_pinned_build_and_audit_receipts"
    return {"status": "ready", "active_snapshot_hash": state[1], "chunk_count": len(active),
            "profile_proof": proof, "profile_fingerprint": profile_fingerprint,
            "sql_vector_identity_and_text_match": True}


class ReusingVectorIndex(ChromaKnowledgeVectorIndex):
    """Only for stopped-service maintenance under one verified model profile."""

    def __init__(self, store, *, profile_fingerprint, dimensions):
        super().__init__()
        self.store = store
        self.profile_fingerprint = profile_fingerprint
        self.dimensions = dimensions
        self.stats = {}

    def synchronize(self, documents, *, knowledge_base_id):
        documents = list(documents)
        if knowledge_base_id != KB_ID or not documents or not self.profile_fingerprint:
            raise ValueError("invalid maintenance scope")
        expected = [str(item.metadata["chunk_id"]) for item in documents]
        if len(expected) != len(set(expected)) or any(
            item.metadata.get("knowledge_base_id") != knowledge_base_id for item in documents
        ):
            raise ValueError("duplicate or cross-KB chunk")
        previous = self.store.get(include=["documents", "metadatas", "embeddings"])
        old_ids = set(previous["ids"])
        old_by_id, reusable = {}, {}
        for ident, text, metadata, embedding in zip(previous["ids"], previous["documents"],
                                                   previous["metadatas"], previous["embeddings"], strict=True):
            if (len(embedding) != self.dimensions or metadata.get("knowledge_base_id") != knowledge_base_id
                    or not all(float("-inf") < float(value) < float("inf") for value in embedding)):
                raise ValueError("old vector profile/scope/values invalid")
            old_by_id[ident] = (text, metadata)
            key = (hashlib.sha256(text.encode()).hexdigest(), metadata.get("chunking_config_hash"))
            reusable.setdefault(key, []).append((text, embedding))
        reused_ids, copied, embedded = 0, 0, 0
        for offset in range(0, len(documents), 32):
            fresh, ids, texts, metadatas, embeddings = [], [], [], [], []
            for source in documents[offset:offset + 32]:
                document = _to_chroma_document(source)
                ident, text = str(document.metadata["chunk_id"]), document.page_content
                if ident in old_by_id:
                    if old_by_id[ident] != (text, document.metadata):
                        raise ValueError("stable chunk ID has different text/metadata")
                    reused_ids += 1
                    continue
                key = (hashlib.sha256(text.encode()).hexdigest(), document.metadata.get("chunking_config_hash"))
                matching = next((embedding for prior, embedding in reusable.get(key, []) if prior == text), None)
                if matching is None:
                    fresh.append(document)
                else:
                    ids.append(ident)
                    texts.append(text)
                    metadatas.append(document.metadata)
                    embeddings.append(list(map(float, matching)))
            if ids:
                self.store._collection.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
                copied += len(ids)
            if fresh:
                self.store.add_documents(fresh, ids=[item.metadata["chunk_id"] for item in fresh])
                embedded += len(fresh)
            print(f"vectors {min(offset + 32, len(documents))}/{len(documents)}: "
                  f"stable={reused_ids} copied={copied} embedded={embedded}", flush=True)
        obsolete = sorted(old_ids - set(expected))
        for offset in range(0, len(obsolete), 256):
            self.store.delete(ids=obsolete[offset:offset + 256])
        actual = self.store.get(include=[])["ids"]
        if set(actual) != set(expected) or len(actual) != len(expected):
            raise ValueError("active vector identities differ from source snapshot")
        self.stats = {"before": len(old_ids), "after": len(expected), "stable_reused": reused_ids,
                      "exact_text_reused": copied, "embedded": embedded, "obsolete_removed": len(obsolete),
                      "profile_fingerprint": self.profile_fingerprint, "dimensions": self.dimensions}
        return expected

    def count(self, knowledge_base_id):
        return self.store._collection.count()


def validate_partial_vectors(data, prior, expected, *, dimensions):
    """Accept only exact old/new identities under the already verified profile."""
    allowed = dict(prior)
    for ident, value in expected.items():
        if ident in allowed and allowed[ident] != value:
            raise ValueError("old/new stable identity metadata conflict")
        allowed[ident] = value
    ids = data["ids"]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("empty or duplicate interrupted vector identities")
    for ident, text, metadata, embedding in zip(
        ids, data["documents"], data["metadatas"], data["embeddings"], strict=True,
    ):
        if ident not in allowed or (text, metadata) != allowed[ident]:
            raise ValueError("interrupted vector text/full metadata outside verified snapshots")
        if len(embedding) != dimensions or not all(math.isfinite(float(v)) for v in embedding):
            raise ValueError("interrupted vector shape/values invalid")
    return {"validated_vectors": len(ids), "stable_candidates": len(set(ids) & set(expected)),
            "expected_candidates": len(expected)}


def verify_vector_backup(path, *, expected, dimensions, collection_name):
    """Validate a private copy, leaving the original recovery files untouched."""
    import chromadb
    from scripts.knowledge_corpus_cleaning import file_hashes
    before = file_hashes(path)
    with tempfile.TemporaryDirectory(prefix="vector-backup-check-", dir=path.parent) as scratch:
        copied = Path(scratch) / "vectors"
        shutil.copytree(path, copied)
        if file_hashes(copied) != before:
            raise ValueError("vector backup copy incomplete")
        client = chromadb.PersistentClient(path=str(copied), settings=chromadb.Settings(anonymized_telemetry=False))
        try:
            collection = client.get_collection(collection_name, embedding_function=None)
            data = collection.get(include=["documents", "metadatas", "embeddings"])
            if set(data["ids"]) != set(expected):
                raise ValueError("vector backup does not contain the complete prior snapshot")
            validate_partial_vectors(data, expected, {}, dimensions=dimensions)
        finally:
            client._system.stop()
    if file_hashes(path) != before:
        raise ValueError("original vector backup changed during validation")
    return before


def resume_preflight(receipt_dir, *, db_path, vector_path, profile, store):
    from scripts.evidence_corpus_promotion import verify_active
    record = json.loads((receipt_dir / "receipt.json").read_text(encoding="utf-8"))
    prior_index = record.get("prior_index") or {}
    if (record.get("status") != "backed_up" or Path(record["database"]).resolve() != db_path.resolve()
            or Path(record["vectors"]).resolve() != vector_path.resolve()
            or record.get("profile") != profile or record.get("profile_fingerprint") != digest(profile)
            or prior_index.get("status") != "ready" or prior_index.get("profile_fingerprint") != digest(profile)):
        raise ValueError("resume requires the same interrupted receipt and embedding profile")
    sidecar = json.loads((vector_path / "knowledge-embedding-profile.json").read_text(encoding="utf-8"))
    backup_vectors = receipt_dir / "vectors-before"
    if (sidecar.get("knowledge_base_id") != KB_ID or sidecar.get("profile") != profile
            or sidecar.get("profile_fingerprint") != digest(profile) or not backup_vectors.is_dir()
            or not (backup_vectors / "chroma.sqlite3").is_file()):
        raise ValueError("resume vector profile or original backup missing")
    with sqlite3.connect((receipt_dir / "database-before.db").as_uri() + "?mode=ro", uri=True) as backup:
        if history_baseline(backup) != record["history_before"]:
            raise ValueError("original backup history hash differs")
        state = backup.execute(
            "SELECT status,active_snapshot_hash,expected_chunk_count,sql_chunk_count,vector_chunk_count "
            "FROM knowledge_index_status WHERE knowledge_base_id=?", (KB_ID,),
        ).fetchone()
        if (state is None or state[0] != "ready" or state[1] != prior_index["active_snapshot_hash"]
                or set(state[2:]) != {prior_index["chunk_count"]}):
            raise ValueError("original backup not bound to prior ready snapshot")
        old = {}
        for ident, text, metadata in backup.execute(
            "SELECT chunk_id,content,metadata FROM knowledge_chunk_versions WHERE knowledge_base_id=? AND active=1", (KB_ID,),
        ):
            item = _to_chroma_document(Document(page_content=text, metadata=json.loads(metadata)))
            old[ident] = (text, item.metadata)
        if len(old) != prior_index["chunk_count"]:
            raise ValueError("original backup chunk count differs")
    backup_hashes = verify_vector_backup(backup_vectors, expected=old,
        dimensions=profile["embedding_index"]["dimensions"], collection_name=store._collection.name)
    if record.get("verified_vector_backup_hashes", backup_hashes) != backup_hashes:
        raise ValueError("verified vector backup file inventory/hash differs")
    record["verified_vector_backup_hashes"] = backup_hashes
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as current:
        verify_history(record["history_before"], history_baseline(current))
    snapshot = verify_active(verify_upstream=True)
    chunks = chunk_documents(load_documents(), chunk_size=900, chunk_overlap=100)
    expected = {}
    for chunk in chunks:
        item = _to_chroma_document(chunk)
        expected[item.metadata["chunk_id"]] = (item.page_content, item.metadata)
    record["resume_preflight"] = {**validate_partial_vectors(
        store.get(include=["documents", "metadatas", "embeddings"]), old, expected,
        dimensions=profile["embedding_index"]["dimensions"],
    ), "source_snapshot": snapshot["chunk_snapshot_hash"]}
    return record


def maintenance(receipt_dir, *, resume=False):
    for port in (8000, 8081, 8082):
        with socket.socket() as connection:
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError("stop project Web/Workers before maintenance")
    settings = get_settings()
    if settings.db_type != "sqlite" or not settings.embedding_local_files_only:
        raise ValueError("maintenance requires SQLite and the pinned local model")
    manifest = load_knowledge_base_manifest()
    receipt = verify_model_receipt()
    model = manifest["raw_metadata"]["embedding_index"]
    if (manifest["knowledge_base_id"] != KB_ID or model["model_id"] != receipt["model_id"]
            or model["model_revision"] != receipt["revision"] or model["dimensions"] != receipt["dimension"]
            or Path(settings.embedding_model).resolve() != Path(receipt["directory"]).resolve()):
        raise ValueError("model/index receipt mismatch; do not mix embedding profiles")
    profile = {"embedding_index": model, "model_files": receipt["files"],
               "model_path": str(Path(settings.embedding_model).resolve()),
               "metric": settings.vector_distance_metric, "normalize_embeddings": True}
    db_path = resolve_backend_path(settings.database_url.removeprefix("sqlite:///"))
    vector_path = resolve_backend_path(settings.vector_store_dir)
    receipt_dir = Path(receipt_dir).resolve()
    if resume and not receipt_dir.is_relative_to(ROOT / "backend/data/knowledge_backups"):
        raise ValueError("resume receipt must remain in private knowledge backup directory")
    if (not db_path.is_file() or not vector_path.is_dir()
            or receipt_dir == vector_path or vector_path in receipt_dir.parents
            or ROOT not in receipt_dir.parents or receipt_dir == ROOT):
        raise ValueError("invalid backup or active data path")
    if not resume:
        receipt_dir.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(db_path) as source:
        stored = source.execute("SELECT metadata FROM knowledge_bases WHERE knowledge_base_id = ?", (KB_ID,)).fetchone()
        if stored is None or json.loads(stored[0]).get("embedding_index") != model:
            raise ValueError("active SQL index has a different embedding profile")
        before = history_baseline(source)
        active = source.execute("SELECT count(*) FROM generation_jobs WHERE status IN ('queued','running')").fetchone()[0]
        active += source.execute("SELECT count(*) FROM agent_runs WHERE status IN ('running','finalizing')").fetchone()[0]
        active += source.execute("SELECT count(*) FROM courseware_generation_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if active:
            raise ValueError("active generation exists; do not interrupt it")
        if not resume:
            with sqlite3.connect(receipt_dir / "database-before.db") as backup:
                source.backup(backup)
    if resume:
        store = get_vector_store(KB_ID)
        record = resume_preflight(receipt_dir, db_path=db_path, vector_path=vector_path, profile=profile, store=store)
        before = record["history_before"]
        print(json.dumps({"resume_preflight": record["resume_preflight"]}), flush=True)
    else:
        shutil.copytree(vector_path, receipt_dir / "vectors-before")
        record = {"status": "backed_up", "database": str(db_path), "vectors": str(vector_path),
                  "profile": profile, "profile_fingerprint": digest(profile), "history_before": before}
        write_atomic(receipt_dir / "receipt.json", encoded(record))
        store = get_vector_store(KB_ID)
        with sqlite3.connect(db_path) as source:
            record["prior_index"] = validate_prior_index(
                source, store, profile_fingerprint=digest(profile), model=model, db_path=db_path, vector_path=vector_path)
    write_atomic(receipt_dir / "receipt.json", encoded(record))
    # Chroma forbids modify(metadata=...) when it contains even the unchanged
    # hnsw:space. Keep its metric metadata intact and persist our profile beside
    # the index, covered by the same stopped-service backup/restore boundary.
    write_atomic(vector_path / "knowledge-embedding-profile.json", encoded({
        "knowledge_base_id": KB_ID, "profile_fingerprint": digest(profile), "profile": profile,
    }))
    adapter = ReusingVectorIndex(store, profile_fingerprint=digest(profile), dimensions=model["dimensions"])
    report = IngestionService(catalog=KnowledgeCatalogRepository(get_session_factory()), vector_index=adapter).ingest()
    record.update(status=report.status, report=report.model_dump(mode="json"), vectors_reuse=adapter.stats)
    with sqlite3.connect(db_path) as source:
        after = history_baseline(source)
    try:
        verify_history(before, after)
        if report.status != "ready":
            raise ValueError("ingestion failed; keep services stopped, restore the recorded backup")
        record["history_verified"] = True
        record["history_counts_after"] = {key: len(rows) for key, rows in after.items()}
    except Exception:
        record["status"] = "failed"
        write_atomic(receipt_dir / "receipt.json", encoded(record))
        raise
    write_atomic(receipt_dir / "receipt.json", encoded(record))
    print(json.dumps({"status": record["status"], "report": record["report"],
                      "vectors_reuse": adapter.stats, "history_verified": True}, ensure_ascii=False, indent=2))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--receipt", type=Path, required=True, help="new private local backup directory")
    parser.add_argument("--resume", action="store_true", help="verify and resume an interrupted evidence-v2 receipt; never overwrite backups")
    args = parser.parse_args()
    maintenance(args.receipt, resume=args.resume)


if __name__ == "__main__":
    main()
