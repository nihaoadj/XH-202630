"""Persist deterministic module-level Chunk-to-skill-node mappings."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260829_p0_33_chunk_skill_node_mappings"
MAPPING_SOURCE = "module_knowledge_points_v1"


def _mapping_id(knowledge_base_id: str, chunk_id: str, skill_node_id: str) -> str:
    value = "|".join((knowledge_base_id, chunk_id, skill_node_id))
    return f"chunk_skill_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


def apply_p0_33_chunk_skill_node_mappings_migration(engine: Engine) -> None:
    """Create the mapping table and backfill active Chunk versions idempotently."""

    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        tables = set(inspect(engine).get_table_names())
        if not {"knowledge_chunk_versions", "rag_skill_nodes"}.issubset(tables):
            return
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS knowledge_chunk_skill_node_mappings (
                mapping_id VARCHAR(128) PRIMARY KEY,
                knowledge_base_id VARCHAR(128) NOT NULL,
                document_id VARCHAR(128) NOT NULL,
                document_version VARCHAR(128) NOT NULL,
                chunk_id VARCHAR(128) NOT NULL,
                skill_node_id VARCHAR(128) NOT NULL,
                mapping_source VARCHAR(64) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chunk_id, skill_node_id),
                FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(knowledge_base_id),
                FOREIGN KEY(chunk_id) REFERENCES knowledge_chunk_versions(chunk_id),
                FOREIGN KEY(skill_node_id) REFERENCES rag_skill_nodes(node_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_chunk_skill_node_mapping_kb_node
            ON knowledge_chunk_skill_node_mappings(knowledge_base_id, skill_node_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_chunk_skill_node_mapping_chunk
            ON knowledge_chunk_skill_node_mappings(chunk_id)
        """))

        node_ids_by_kb_and_name = {
            (str(row["knowledge_base_id"]), str(row["name"]).strip()): str(row["node_id"])
            for row in conn.execute(text("""
                SELECT knowledge_base_id, node_id, name FROM rag_skill_nodes
            """)).mappings()
            if str(row["name"]).strip()
        }
        chunks = conn.execute(text("""
            SELECT knowledge_base_id, document_id, document_version, chunk_id, knowledge_points
            FROM knowledge_chunk_versions
            WHERE active = 1
        """)).mappings()
        for chunk in chunks:
            try:
                knowledge_points = json.loads(chunk["knowledge_points"] or "[]")
            except (TypeError, json.JSONDecodeError):
                knowledge_points = []
            for point in {str(value).strip() for value in knowledge_points if str(value).strip()}:
                skill_node_id = node_ids_by_kb_and_name.get((chunk["knowledge_base_id"], point))
                if skill_node_id is None:
                    continue
                conn.execute(text("""
                    INSERT OR IGNORE INTO knowledge_chunk_skill_node_mappings (
                        mapping_id, knowledge_base_id, document_id, document_version,
                        chunk_id, skill_node_id, mapping_source
                    ) VALUES (
                        :mapping_id, :knowledge_base_id, :document_id, :document_version,
                        :chunk_id, :skill_node_id, :mapping_source
                    )
                """), {
                    "mapping_id": _mapping_id(chunk["knowledge_base_id"], chunk["chunk_id"], skill_node_id),
                    "knowledge_base_id": chunk["knowledge_base_id"],
                    "document_id": chunk["document_id"],
                    "document_version": chunk["document_version"],
                    "chunk_id": chunk["chunk_id"],
                    "skill_node_id": skill_node_id,
                    "mapping_source": MAPPING_SOURCE,
                })
        if "schema_migrations" in tables and not conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"),
            {"id": MIGRATION_ID},
        ).first():
            conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["MIGRATION_ID", "apply_p0_33_chunk_skill_node_mappings_migration"]
