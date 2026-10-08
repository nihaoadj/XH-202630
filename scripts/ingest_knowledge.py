"""Reconcile one knowledge base into immutable SQL history and its KB vector index."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.shared.database import get_session_factory, init_database
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.services.knowledge.ingestion import ChromaKnowledgeVectorIndex, IngestionService


def main(
    kb_dir: str | None = None,
    knowledge_base_id: str | None = None,
) -> int:
    init_database()
    service = IngestionService(
        catalog=KnowledgeCatalogRepository(get_session_factory()),
        vector_index=ChromaKnowledgeVectorIndex(),
    )
    report = (
        service.reconcile(knowledge_base_id)
        if knowledge_base_id
        else service.ingest(kb_dir)
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.status == "ready" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="对账知识库的不可变 SQL 目录与 KB 专属 Chroma 索引"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--kb-dir", help="知识库目录；默认读取 KNOWLEDGE_BASE_DIR")
    source.add_argument(
        "--knowledge-base-id",
        help="按项目内 knowledge_base_id 显式重新入库并对账",
    )
    args = parser.parse_args()
    raise SystemExit(main(
        kb_dir=args.kb_dir,
        knowledge_base_id=args.knowledge_base_id,
    ))
