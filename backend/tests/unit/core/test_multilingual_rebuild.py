import json

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.retrieval.knowledge_base import chunk_documents, load_documents, load_knowledge_base_manifest
from app.core.retrieval.knowledge_ids import document_version_id, sha256_hex
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.migrations.p0_34_knowledge_identity_revision import (
    MIGRATION_ID,
    apply_p0_34_knowledge_identity_revision_migration,
)
from app.db.migrations.p0_33_chunk_skill_node_mappings import MIGRATION_ID as P0_33_MIGRATION_ID
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import (
    Base,
    KnowledgeChunkVersionORM,
    KnowledgeDocumentORM,
    KnowledgeDocumentVersionORM,
)


def test_shadow_targets_refuse_existing_or_source_paths_without_writes(tmp_path):
    from scripts.rebuild_multilingual_index import reject_existing_targets
    source = tmp_path / 'source.db'
    source.write_bytes(b'untouched-source')
    config = tmp_path / '.env'
    config.write_text('secret-not-logged', encoding='utf-8')
    with pytest.raises(ValueError, match='SHADOW_TARGET_MUST_BE_NEW'):
        reject_existing_targets(source, source, tmp_path / 'vectors')
    with pytest.raises(ValueError, match='SHADOW_TARGET_OUTSIDE_DATA'):
        reject_existing_targets(source, tmp_path / 'shadow.db', tmp_path / 'vectors')
    assert source.read_bytes() == b'untouched-source'
    assert config.read_text(encoding='utf-8') == 'secret-not-logged'
    assert not (tmp_path / 'shadow.db').exists()


def test_build_failure_before_backup_cannot_activate_or_mutate_source(tmp_path, monkeypatch):
    from scripts import rebuild_multilingual_index as module
    config = tmp_path / '.env'
    config.write_bytes(b'original-config')
    source = tmp_path / 'source.db'
    source.write_bytes(b'original-data')
    def fail():
        raise ValueError('MODEL_NOT_READY')
    monkeypatch.setattr(module, 'verify_model_receipt', fail)
    with pytest.raises(ValueError, match='MODEL_NOT_READY'):
        module.build()
    assert config.read_bytes() == b'original-config'
    assert source.read_bytes() == b'original-data'
    # This module deliberately has no activation command/config-writing API.
    assert not hasattr(module, 'activate')


def _write_kb(kb_dir, source_path, *, identity_revision=None):
    source = kb_dir / source_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Stable source\n\nBody remains exactly the same.", encoding="utf-8")
    manifest = {
        "knowledge_base_id": "kb-identity-history",
        "knowledge_base_name": "Identity history fixture",
        "version": "1.0.0",
        "documents": [{
            "id": "doc-stable",
            "title": "Stable source",
            "file": source_path,
            "source_type": "markdown",
            "version": "source-v1",
        }],
    }
    if identity_revision is not None:
        manifest["document_identity_revision"] = identity_revision
    (kb_dir / "metadata.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def test_document_version_identity_revision_keeps_legacy_id_and_is_stable():
    content_hash = sha256_hex("")

    assert document_version_id("kb", "doc", content_hash) == "dv_e50fb285d274b7425a6f1008"
    assert document_version_id(
        "kb", "doc", content_hash, identity_revision=None,
    ) == "dv_e50fb285d274b7425a6f1008"

    first = document_version_id(
        "kb", "doc", content_hash, identity_revision="layout-v2",
    )
    second = document_version_id(
        "kb", "doc", content_hash, identity_revision="layout-v2",
    )
    assert first == second
    assert first != "dv_e50fb285d274b7425a6f1008"
    with pytest.raises(ValueError, match="identity_revision"):
        document_version_id("kb", "doc", content_hash, identity_revision="")


def test_manifest_projects_valid_document_identity_revision_only_when_present(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    _write_kb(kb_dir, "old/source.md")

    legacy_manifest = load_knowledge_base_manifest(str(kb_dir))
    legacy_document = load_documents(str(kb_dir))[0]
    assert legacy_manifest["document_identity_revision"] is None
    assert "document_identity_revision" not in legacy_document.metadata

    (kb_dir / "old" / "source.md").unlink()
    _write_kb(kb_dir, "new/source.md", identity_revision="layout-v1-teaching-v2-m3-20261027")
    revised_manifest = load_knowledge_base_manifest(str(kb_dir))
    revised_document = load_documents(str(kb_dir))[0]
    assert revised_manifest["document_identity_revision"] == "layout-v1-teaching-v2-m3-20261027"
    assert revised_document.metadata["document_identity_revision"] == "layout-v1-teaching-v2-m3-20261027"
    assert revised_document.metadata["document_id"] == "doc-stable"
    assert revised_document.metadata["source_path"] == "new/source.md"
    assert revised_document.metadata["document_version"] != legacy_document.metadata["document_version"]

    for invalid in ("", "contains whitespace", "x" * 129, 17, ["revision"]):
        manifest = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
        manifest["document_identity_revision"] = invalid
        (kb_dir / "metadata.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError, match="document_identity_revision"):
            load_knowledge_base_manifest(str(kb_dir))


def test_same_document_and_body_can_move_path_without_losing_old_sql_history(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    _write_kb(kb_dir, "old/source.md")
    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    catalog = KnowledgeCatalogRepository(factory)

    legacy_manifest = load_knowledge_base_manifest(str(kb_dir))
    catalog.upsert_knowledge_base(legacy_manifest)
    legacy_documents = load_documents(str(kb_dir))
    legacy_chunks = chunk_documents(legacy_documents)
    catalog.sync_documents(
        legacy_documents,
        legacy_chunks,
        knowledge_base_id="kb-identity-history",
    )
    legacy_document_version = legacy_documents[0].metadata["document_version"]
    legacy_chunk_id = legacy_chunks[0].metadata["chunk_id"]

    (kb_dir / "old" / "source.md").unlink()
    _write_kb(
        kb_dir,
        "new/source.md",
        identity_revision="layout-v2",
    )
    revised_manifest = load_knowledge_base_manifest(str(kb_dir))
    catalog.upsert_knowledge_base(revised_manifest)
    revised_documents = load_documents(str(kb_dir))
    revised_chunks = chunk_documents(revised_documents)
    catalog.sync_documents(
        revised_documents,
        revised_chunks,
        knowledge_base_id="kb-identity-history",
    )

    revised_document_version = revised_documents[0].metadata["document_version"]
    revised_chunk_id = revised_chunks[0].metadata["chunk_id"]
    assert revised_documents[0].metadata["document_id"] == "doc-stable"
    assert revised_document_version != legacy_document_version
    assert revised_chunk_id != legacy_chunk_id
    assert catalog.get_document_version(legacy_document_version).source_path == "old/source.md"
    assert catalog.resolve_chunk_locator(
        "kb-identity-history",
        legacy_document_version,
        legacy_chunk_id,
    ).source_path == "old/source.md"
    assert catalog.get_document_version(revised_document_version).source_path == "new/source.md"

    with factory() as db:
        old_version = db.get(KnowledgeDocumentVersionORM, legacy_document_version)
        new_version = db.get(KnowledgeDocumentVersionORM, revised_document_version)
        current_document = db.get(KnowledgeDocumentORM, "doc-stable")
        assert old_version.identity_revision == ""
        assert old_version.is_current is False
        assert new_version.identity_revision == "layout-v2"
        assert new_version.is_current is True
        assert current_document.knowledge_base_id == "kb-identity-history"
        assert current_document.source_path == "new/source.md"
        assert db.get(KnowledgeChunkVersionORM, legacy_chunk_id).active is False
        assert db.get(KnowledgeChunkVersionORM, revised_chunk_id).active is True


def _create_legacy_identity_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE knowledge_bases (knowledge_base_id VARCHAR(128) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"
        )
        connection.exec_driver_sql("""
            CREATE TABLE knowledge_document_versions (
                document_version VARCHAR(128) PRIMARY KEY,
                document_id VARCHAR(128) NOT NULL,
                knowledge_base_id VARCHAR(128) NOT NULL,
                title VARCHAR(512) NOT NULL,
                source_path VARCHAR(1024) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                source_version VARCHAR(64),
                content_hash VARCHAR(64) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                is_current BOOLEAN NOT NULL DEFAULT 1,
                metadata JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_kb_document_content_version
                    UNIQUE (knowledge_base_id, document_id, content_hash),
                FOREIGN KEY (knowledge_base_id)
                    REFERENCES knowledge_bases(knowledge_base_id)
            )
        """)
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_versions_document_id "
            "ON knowledge_document_versions (document_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_versions_knowledge_base_id "
            "ON knowledge_document_versions (knowledge_base_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_versions_content_hash "
            "ON knowledge_document_versions (content_hash)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_document_versions_is_current "
            "ON knowledge_document_versions (is_current)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_legacy_document_source_path "
            "ON knowledge_document_versions (source_path)"
        )
        connection.exec_driver_sql("""
            CREATE TABLE knowledge_chunk_versions (
                chunk_id VARCHAR(128) PRIMARY KEY,
                knowledge_base_id VARCHAR(128) NOT NULL,
                document_version VARCHAR(128) NOT NULL,
                FOREIGN KEY (knowledge_base_id)
                    REFERENCES knowledge_bases(knowledge_base_id),
                FOREIGN KEY (document_version)
                    REFERENCES knowledge_document_versions(document_version)
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE knowledge_chunk_skill_node_mappings (
                mapping_id VARCHAR(128) PRIMARY KEY,
                chunk_id VARCHAR(128) NOT NULL,
                FOREIGN KEY (chunk_id)
                    REFERENCES knowledge_chunk_versions(chunk_id)
            )
        """)
        connection.execute(
            text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"),
            {"id": P0_33_MIGRATION_ID},
        )
        connection.execute(
            text("INSERT INTO knowledge_bases (knowledge_base_id) VALUES (:id)"),
            {"id": "kb-legacy"},
        )
        connection.exec_driver_sql("""
            INSERT INTO knowledge_document_versions (
                document_version, document_id, knowledge_base_id, title,
                source_path, source_type, source_version, content_hash,
                enabled, is_current, metadata, created_at
            ) VALUES (
                'dv-legacy', 'doc-stable', 'kb-legacy', 'Legacy title',
                'old/source.md', 'markdown', 'source-v1', 'body-hash',
                1, 1, '{"legacy": true}', '2026-01-02 03:04:05'
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO knowledge_chunk_versions (chunk_id, knowledge_base_id, document_version)
            VALUES ('chunk-legacy', 'kb-legacy', 'dv-legacy')
        """)


def test_p034_migrates_real_legacy_table_preserving_rows_indexes_foreign_keys_and_idempotence(tmp_path):
    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    )
    _create_legacy_identity_schema(engine)

    apply_p0_34_knowledge_identity_revision_migration(engine)
    apply_p0_34_knowledge_identity_revision_migration(engine)

    inspector = inspect(engine)
    columns = {item["name"]: item for item in inspector.get_columns("knowledge_document_versions")}
    assert "identity_revision" in columns
    assert columns["identity_revision"]["nullable"] is False
    assert columns["identity_revision"]["default"] == "''"
    assert columns['enabled']['default'] == '1'
    assert columns['is_current']['default'] == '1'
    assert {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("knowledge_document_versions")
    } == {("knowledge_base_id", "document_id", "content_hash", "identity_revision")}
    assert {item["name"] for item in inspector.get_indexes("knowledge_document_versions")} >= {
        "ix_knowledge_document_versions_content_hash",
        "ix_legacy_document_source_path",
    }
    with engine.connect() as connection:
        legacy = connection.execute(text("""
            SELECT document_version, document_id, knowledge_base_id, title,
                   source_path, source_type, source_version, content_hash,
                   enabled, is_current, metadata, created_at, identity_revision
            FROM knowledge_document_versions WHERE document_version='dv-legacy'
        """)).mappings().one()
        assert legacy["source_path"] == "old/source.md"
        assert legacy["title"] == "Legacy title"
        assert legacy["metadata"] == '{"legacy": true}'
        assert legacy["created_at"] == "2026-01-02 03:04:05"
        assert legacy["is_current"] == 1
        assert legacy["identity_revision"] == ""
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        child_fks = connection.exec_driver_sql(
            "PRAGMA foreign_key_list(knowledge_chunk_versions)"
        ).fetchall()
        assert any(row[2] == "knowledge_document_versions" for row in child_fks)
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"),
            {"id": MIGRATION_ID},
        ).scalar_one() == 1

    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO knowledge_document_versions (
                document_version, document_id, knowledge_base_id, title,
                source_path, source_type, content_hash, identity_revision
            ) VALUES (
                'dv-revised', 'doc-stable', 'kb-legacy', 'Revised title',
                'new/source.md', 'markdown', 'body-hash', 'layout-v2'
            )
        """))
        connection.execute(text("""
            INSERT INTO knowledge_document_versions (
                document_version, document_id, knowledge_base_id, title,
                source_path, source_type, content_hash
            ) VALUES (
                'dv-raw-default', 'doc-other', 'kb-legacy', 'Default revision',
                'other/source.md', 'markdown', 'other-body-hash'
            )
        """))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO knowledge_document_versions (
                    document_version, document_id, knowledge_base_id, title,
                    source_path, source_type, content_hash, identity_revision
                ) VALUES (
                    'dv-revised-duplicate', 'doc-stable', 'kb-legacy', 'Duplicate',
                    'another/source.md', 'markdown', 'body-hash', 'layout-v2'
                )
            """))

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM knowledge_document_versions")
        ).scalar_one() == 3
        assert connection.execute(text(
            "SELECT identity_revision FROM knowledge_document_versions "
            "WHERE document_version='dv-raw-default'"
        )).scalar_one() == ""
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_p034_explicitly_rejects_non_sqlite_engine():
    class NonSqliteEngine:
        class URL:
            @staticmethod
            def get_backend_name():
                return "postgresql"

        url = URL()

    with pytest.raises(RuntimeError, match="P0_34_SQLITE_ONLY"):
        apply_p0_34_knowledge_identity_revision_migration(NonSqliteEngine())
