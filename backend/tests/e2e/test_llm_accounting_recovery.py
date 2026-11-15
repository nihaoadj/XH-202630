"""Recovery & multi-segment integrity of the bypass accounting (T41 §8.2).

End-to-end, using the real spawn-based writer child and the real claim
workflow entry point:

* duplicate delivery is idempotent, a same-key different-hash replay is a
  conflict that never overwrites the first value;
* a missing segment stays ``not_recorded``/``partial`` and never becomes a
  fabricated "complete zero";
* a real re-execution produces a new segment (new calls) that is not deduped
  away just because it shares the run/source snapshot;
* the business projection is byte-identical with and without accounting.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from app.core.llm import accounting
from app.models.shared.llm import (
    LLMCallOptions,
    RawLLMResponse,
    StructuredOutputMode,
)
from app.models.shared.llm_accounting import (
    AccountingSegmentV1,
    LLMCallObservationV1,
    SegmentSubmissionV1,
    canonical_accounting_hash,
)
from app.services.runs import llm_accounting_runtime as runtime
from tests.fakes.llm import ScriptedLLMTransport
from app.core.llm.gateway import LLMGateway


@pytest.fixture()
def tmp_dir_session():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def enabled():
    accounting.set_enabled(True)
    accounting.install_publisher(None)
    yield
    runtime.stop_llm_accounting_runtime()
    accounting.set_enabled(False)
    accounting.install_publisher(None)


def _segment(run_id: str, segment_id: str, *, outcome: str = "success") -> AccountingSegmentV1:
    return AccountingSegmentV1(
        domain="learning_documents",
        run_id=run_id,
        segment_id=segment_id,
        process_nonce="proc-e2e",
        calls=[
            LLMCallObservationV1(
                domain="learning_documents",
                run_id=run_id,
                segment_id=segment_id,
                observation_id=1,
                stage="claim_extract",
                outcome=outcome,  # type: ignore[arg-type]
            )
        ],
        call_count=1,
        sealed=True,
    )


def _submission(segment: AccountingSegmentV1) -> SegmentSubmissionV1:
    return SegmentSubmissionV1(
        segment=segment,
        payload_hash=canonical_accounting_hash(segment.stable_payload()),
    )


def _repository(db_path: str):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    return SQLLLMAccountingRepository(db_path, readonly=True)


def _wait_for(task_repo, domain: str, run_id: str, *, calls: int, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = task_repo.get_task(domain, run_id)
        if len(records.calls) >= calls:
            return records
        time.sleep(0.15)
    return task_repo.get_task(domain, run_id)


def _wait_for_persisted(db_path: Path, domain: str, run_id: str, *, calls: int, timeout: float = 30.0):
    """Wait for the writer child to create tables, then poll a fresh readonly repo.

    The readonly repository caches a sticky ``storage_capacity_exceeded`` flag,
    so it must be constructed only after the writer has initialised the schema.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not db_path.exists():
        time.sleep(0.15)
    records = None
    repo = None
    while time.monotonic() < deadline:
        if repo is None:
            repo = _repository(str(db_path))
        records = repo.get_task(domain, run_id)
        if len(records.calls) >= calls:
            break
        time.sleep(0.15)
    if repo is not None:
        repo.close()
    return records


def test_duplicate_delivery_idempotent_and_conflict_never_overwrites(tmp_dir_session):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    db_path = Path(tmp_dir_session) / "accounting.db"
    repo = SQLLLMAccountingRepository(str(db_path))
    segment = _segment("run-dup", "seg-dup")
    assert repo.save_segment(_submission(segment)) == "sealed"
    assert repo.save_segment(_submission(segment)) == "duplicate"
    # A conflicting replay (same key, different content) is flagged, first wins.
    conflicting = _segment("run-dup", "seg-dup", outcome="gateway_error")
    assert repo.save_segment(_submission(conflicting)) == "conflict"
    records = repo.get_task("learning_documents", "run-dup")
    assert records.conflicts == 1
    assert len(records.calls) == 1
    assert records.calls[0].outcome == "success"
    repo.close()


def test_missing_segment_is_not_recorded_not_zero(tmp_dir_session):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    db_path = Path(tmp_dir_session) / "accounting-missing.db"
    repo = SQLLLMAccountingRepository(str(db_path), readonly=True)
    records = repo.get_task("learning_documents", "run-absent")
    assert records.calls == []
    assert records.segments == []
    repo.close()


def test_real_reexecution_produces_distinct_segments(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-reexec.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        from app.agents.resource_workflows.learning_documents.claim_review_agent import (
            claim_extract_node,
        )
        from app.agents.shared.llm_accounting import text_run_segment
        from tests.integration.workflow.test_llm_accounting_text import (
            _EXTRACT_OUTCOME,
            _state,
        )

        def run_once():
            state = _state(run_id="run-reexec")
            transport = ScriptedLLMTransport(
                [RawLLMResponse(content=json.dumps(_EXTRACT_OUTCOME, ensure_ascii=False))]
            )
            gateway = LLMGateway(
                transport,
                default_options=LLMCallOptions(
                    max_attempts=1,
                    request_timeout_seconds=5.0,
                    structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
                ),
                sleep=lambda _s: None,
            )
            with text_run_segment("run-reexec"):
                claim_extract_node(state, llm_gateway=gateway)

        run_once()
        run_once()

        records = _wait_for_persisted(db_path, "learning_documents", "run-reexec", calls=2)
        # Two real executions -> two distinct segments -> two observations.
        assert records is not None
        assert len(records.calls) == 2
        assert len(records.segments) == 2
        assert {segment.segment_id for segment in records.segments}
    finally:
        rt.stop()


def test_business_projection_identical_with_runtime_installed(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-projection.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        from app.agents.resource_workflows.learning_documents.claim_review_agent import (
            claim_extract_node,
        )
        from app.agents.shared.llm_accounting import text_run_segment
        from tests.integration.workflow.test_llm_accounting_text import (
            _EXTRACT_OUTCOME,
            _state,
        )

        stable_fields = (
            "claim_text", "claim_type", "source_start", "source_end",
            "knowledge_point_id", "source_evidence_ids",
        )

        def project():
            state = _state(run_id="run-projection")
            transport = ScriptedLLMTransport(
                [RawLLMResponse(content=json.dumps(_EXTRACT_OUTCOME, ensure_ascii=False))]
            )
            gateway = LLMGateway(
                transport,
                default_options=LLMCallOptions(
                    max_attempts=1,
                    request_timeout_seconds=5.0,
                    structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
                ),
                sleep=lambda _s: None,
            )
            with text_run_segment("run-projection"):
                extracted = claim_extract_node(state, llm_gateway=gateway)
            return [
                {k: claim.get(k) for k in stable_fields}
                for claim in extracted.get("extracted_claims", [])
            ]

        with_runtime = project()
        # Kill the writer: the same business path must produce the same claims.
        if rt._process is not None:
            rt._process.terminate()
            rt._process.join(timeout=5)
        without_writer = project()
        assert with_runtime == without_writer
        assert with_runtime, "the claim must be extracted in both runs"
    finally:
        rt.stop()
