import json

from sqlalchemy import create_engine, text

from app.db.migrations.p0_33_chunk_skill_node_mappings import (
    MIGRATION_ID,
    apply_p0_33_chunk_skill_node_mappings_migration,
)


def test_chunk_skill_mapping_migration_backfills_only_active_chunks_idempotently():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE knowledge_bases (knowledge_base_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("""
            CREATE TABLE rag_skill_nodes (
                node_id VARCHAR(128) PRIMARY KEY,
                knowledge_base_id VARCHAR(128) NOT NULL,
                name VARCHAR(256) NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE knowledge_chunk_versions (
                chunk_id VARCHAR(128) PRIMARY KEY,
                knowledge_base_id VARCHAR(128) NOT NULL,
                document_id VARCHAR(128) NOT NULL,
                document_version VARCHAR(128) NOT NULL,
                knowledge_points TEXT,
                active BOOLEAN NOT NULL
            )
        """))
        conn.execute(text("INSERT INTO knowledge_bases VALUES ('kb')"))
        conn.execute(text("""
            INSERT INTO rag_skill_nodes VALUES
            ('node-a', 'kb', '节点 A'), ('node-b', 'kb', '节点 B'), ('other', 'other-kb', '节点 A')
        """))
        conn.execute(text("""
            INSERT INTO knowledge_chunk_versions VALUES
            ('active', 'kb', 'doc', 'v1', :points, 1),
            ('inactive', 'kb', 'doc', 'v0', :points, 0)
        """), {"points": json.dumps(["节点 A", "节点 B", "不存在"], ensure_ascii=False)})

    apply_p0_33_chunk_skill_node_mappings_migration(engine)
    apply_p0_33_chunk_skill_node_mappings_migration(engine)

    with engine.begin() as conn:
        mappings = conn.execute(text("""
            SELECT chunk_id, skill_node_id
            FROM knowledge_chunk_skill_node_mappings
            ORDER BY skill_node_id
        """)).all()
        assert mappings == [("active", "node-a"), ("active", "node-b")]
        assert conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"),
            {"id": MIGRATION_ID},
        ).scalar_one() == 1
