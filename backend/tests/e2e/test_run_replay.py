from datetime import datetime, timezone

from app.core.retrieval.knowledge_ids import normalize_text, query_hash, sha256_hex
from app.models.knowledge.knowledge import EvidenceItem, ScoreKind, SourceLocator, SourceType
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    PersistedEvidenceSnapshot,
    canonical_hash,
)
from app.services.runs.queries import RunQueryService
from backend.tests.fakes.persistence import create_command, sqlite_repository


def test_cross_process_replay_uses_database_snapshots_only(tmp_path):
    repository, engine = sqlite_repository(tmp_path)
    command = create_command("run-replay")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    repository.begin_step(
        BeginStepCommand(
            run_id=command.run_id,
            step_id="step-retrieve",
            step_sequence=1,
            node_name="retrieve",
            agent_name="retriever",
            action="知识证据检索",
            started_at=command.occurred_at,
        )
    )
    excerpt = "RAG 在生成前检索可信证据。"
    evidence = EvidenceItem(
        evidence_id="evidence-replay",
        knowledge_base_id="kb-001",
        document_id="doc-001",
        document_version="v1",
        chunk_id="chunk-001",
        query="什么是 RAG",
        query_hash=query_hash("什么是 RAG"),
        query_rank=1,
        rank=1,
        raw_score=0.1,
        score_kind=ScoreKind.DISTANCE,
        normalized_score=0.9,
        excerpt=excerpt,
        excerpt_hash=sha256_hex(normalize_text(excerpt)),
        locator=SourceLocator(
            knowledge_base_id="kb-001",
            document_id="doc-001",
            document_version="v1",
            chunk_id="chunk-001",
            source_type=SourceType.MARKDOWN,
            source_path="docs/rag.md",
            title="RAG",
            section="定义",
        ),
        config_hash="1" * 64,
        retrieved_at=datetime.now(timezone.utc),
    )
    snapshot = PersistedEvidenceSnapshot.from_evidence(
        evidence,
        run_id=command.run_id,
        retrieval_step_id="step-retrieve",
    )
    repository.complete_step(
        CompleteStepCommand(
            run_id=command.run_id,
            step_id="step-retrieve",
            trace={
                "run_id": command.run_id,
                "step_id": "step-retrieve",
                "sequence": 1,
                "attempt": 1,
                "agent_name": "retriever",
                "status": "success",
                "evidence_refs": [evidence.evidence_id],
            },
            evidence=[snapshot],
        )
    )
    projection = {"run_id": command.run_id, "evidence_ids": [evidence.evidence_id]}
    repository.save_checkpoint(
        run_id=command.run_id,
        step_id="step-retrieve",
        step_sequence=1,
        node_name="retriever",
        state_projection=projection,
        state_hash=canonical_hash(projection),
        occurred_at=datetime.now(timezone.utc),
    )

    from app.db.audit.sql_repository import SQLAuditRepository
    from sqlalchemy.orm import sessionmaker

    fresh_service = RunQueryService(SQLAuditRepository(sessionmaker(bind=engine)))
    timeline = fresh_service.get_timeline(command.run_id)
    assert timeline.evidence[0].excerpt == excerpt
    assert "query" not in timeline.evidence[0].model_dump()
    assert timeline.checkpoints[0].state_hash == canonical_hash(projection)
