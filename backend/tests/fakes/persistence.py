from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.memory import MemoryAuditRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.shared.models import Base
from app.models.shared.persistence import CreateRunCommand, canonical_hash


def create_command(run_id: str = "run-001", knowledge_base_id: str | None = "kb-001"):
    snapshot = {
        "learner_id": "learner-001",
        "topic": "RAG",
        "knowledge_base_id": knowledge_base_id,
        "resource_types": ["讲义"],
    }
    return CreateRunCommand(
        run_id=run_id,
        learner_id="learner-001",
        knowledge_base_id=knowledge_base_id,
        topic="RAG",
        request_snapshot=snapshot,
        request_hash=canonical_hash(snapshot),
        occurred_at=datetime.now(timezone.utc),
    )


def memory_repository() -> MemoryAuditRepository:
    return MemoryAuditRepository()


def sqlite_repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p0_04.db'}")
    Base.metadata.create_all(engine)
    return SQLAuditRepository(sessionmaker(bind=engine)), engine
