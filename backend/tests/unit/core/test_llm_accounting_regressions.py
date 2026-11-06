"""Independent acceptance counterexamples: accounting must remain observational."""
from types import SimpleNamespace

import pytest

from app.core.llm import accounting as a
from app.models.shared.llm import LLMUsage
from app.models.shared.llm_accounting import (
    AccountingDomain as D, LLMCallObservationV1, summarize_observations, build_task_response,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(a, "_enabled", True)
    monkeypatch.setattr(a, "_publisher", None)


def test_nested_scope_preserves_business_exception():
    original = ValueError("business")
    with pytest.raises(ValueError) as raised:
        with a.segment_scope(D.COURSEWARE, "r"):
            with a.segment_scope(D.COURSEWARE, "r"):
                raise original
    assert raised.value is original


@pytest.mark.parametrize("fault", ["seal", "hash", "logger"])
@pytest.mark.parametrize("business_failure", [False, True])
def test_scope_cleanup_never_changes_business(monkeypatch, fault, business_failure):
    def fail(*args, **kwargs):
        raise RuntimeError("accounting")
    if fault in {"seal", "logger"}:
        monkeypatch.setattr(a._SegmentFrame, "seal", fail)
    if fault == "hash":
        monkeypatch.setattr(a, "canonical_accounting_hash", fail)
    if fault == "logger":
        monkeypatch.setattr(a.logger, "warning", fail)
    original = ValueError("business")
    def execute():
        with a.segment_scope(D.COURSEWARE, "r"):
            if business_failure:
                raise original
            return "ok"
    if business_failure:
        with pytest.raises(ValueError) as raised:
            execute()
        assert raised.value is original
    else:
        assert execute() == "ok"


def test_record_failure_preserves_success(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("accounting")
    monkeypatch.setattr(a._CallFrame, "record_result", fail)
    marker = object()
    original = a.observed_gateway_method(lambda **kwargs: marker)
    with a.segment_scope(D.COURSEWARE, "r"):
        assert original(context=SimpleNamespace(run_id="r")) is marker


def test_known_usage_is_independent_per_field():
    frame = a._CallFrame(a._SegmentFrame(D.COURSEWARE, "r", "stage"), 1)
    usage = LLMUsage(input_tokens=7)
    frame.record_result(SimpleNamespace(usage=usage, attempts=[SimpleNamespace(attempt=1, usage=usage)]))
    observed = frame.finalize()
    assert observed.known_input_tokens == 7
    assert observed.usage_input_tokens == 7
    assert observed.usage_output_tokens is None


def call(index, **kwargs):
    return LLMCallObservationV1(domain="courseware", run_id="r", segment_id="s", observation_id=index, **kwargs)


def test_unknown_call_invalidates_complete_total():
    summary = summarize_observations([
        call(1, usage_complete=True, usage_total_tokens=15), call(2),
    ])
    assert summary.complete_total_tokens is None


def test_shared_partition_is_additive():
    result = build_task_response(domain="courseware", run_id="r", segments=[], availability="partial", coverage_complete=False,
        observations=[call(1, attribution="resource_set", resource_labels=["a", "b"], known_total_tokens=15)])
    assert sum(p.usage.known_total_tokens for p in result.resource_partition_summaries) == 15


def test_readonly_query_does_not_create_database(tmp_path):
    from app.services.runs.llm_accounting import LLMAccountingQueryService
    path = tmp_path / "absent" / "accounting.db"
    response = LLMAccountingQueryService(str(path)).query_task(domain="courseware", run_id="r")
    assert response.availability == "unavailable"
    assert not path.parent.exists()


@pytest.mark.parametrize("with_end", [False, True])
def test_writer_requires_end_and_survives_idle(monkeypatch, with_end):
    import json
    import queue
    from app.services.runs import llm_accounting_runtime as rt
    from app.db.audit.llm_accounting import sql_repository as sr
    from app.models.shared.llm_accounting import AccountingSegmentV1, canonical_accounting_hash
    saved = []
    class Repo:
        def __init__(self, *args): pass
        def save_segment(self, value): saved.append(value)
        def close(self): pass
    segment = AccountingSegmentV1(domain="courseware", run_id="r", segment_id="s", process_nonce="p", sealed=True)
    digest = canonical_accounting_hash(segment.stable_payload())
    payload = json.dumps({"segment": segment.stable_payload(), "payload_hash": digest}).encode()
    frames = [{"kind": "chunk", "domain": "courseware", "run_id": "r", "segment_id": "s", "seq": 1, "total": 1, "payload": payload}]
    if with_end:
        frames.append({"kind": "end", "domain": "courseware", "run_id": "r", "segment_id": "s", "total": 1, "call_count": 0, "payload_hash": digest})
    frames.append({"kind": "stop"})
    class Queue:
        count = 0
        def get(self, **kwargs):
            self.count += 1
            if self.count == 1:
                raise queue.Empty
            return frames.pop(0)
        def put_nowait(self, value): pass
    q = Queue()
    monkeypatch.setattr(sr, "SQLLLMAccountingRepository", Repo)
    monkeypatch.setattr(rt, "CONSUMER_IDLE_TIMEOUT_SECONDS", -1)
    rt._writer_main(q, q, "unused")
    assert q.count >= 3
    assert len(saved) == int(with_end)


@pytest.mark.parametrize("directory", ["vector_store_dir", "knowledge_base_dir"])
def test_accounting_path_rejects_knowledge_storage(monkeypatch, tmp_path, directory):
    from app.services.runs import llm_accounting_runtime as rt
    protected = tmp_path / "protected"
    settings = SimpleNamespace(database_url="sqlite:///business.db", resources_dir=str(tmp_path / "resources"),
        llm_accounting_db_path=str(protected / "chroma.sqlite3"), **{directory: str(protected)})
    monkeypatch.setattr(rt, "get_settings", lambda: settings)
    assert rt.resolve_llm_accounting_db_path() is None


@pytest.mark.parametrize("filename", ["hash#name.db", "percent%name.db", "space name.db"])
def test_readonly_uri_preserves_legal_filename(tmp_path, filename):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository
    path = tmp_path / filename
    writer = SQLLLMAccountingRepository(str(path))
    writer.close()
    reader = SQLLLMAccountingRepository(str(path), readonly=True)
    try:
        assert reader.get_task("courseware", "r").unavailable_reasons == []
    finally:
        reader.close()


def test_corrupt_payload_never_contributes_to_statistics(tmp_path):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository
    from app.db.audit.llm_accounting.schema import llm_call_observations
    from app.models.shared.llm_accounting import AccountingSegmentV1, SegmentSubmissionV1
    repository = SQLLLMAccountingRepository(str(tmp_path / "integrity.db"))
    try:
        original = call(1, known_input_tokens=4)
        segment = AccountingSegmentV1(domain="courseware", run_id="r", segment_id="s", process_nonce="p",
            calls=[original], call_count=1, sealed=True)
        assert repository.save_segment(SegmentSubmissionV1(segment=segment, payload_hash=segment.payload_hash())) == "sealed"
        with repository.engine.begin() as connection:
            connection.execute(llm_call_observations.update().values(
                payload_json=original.model_copy(update={"known_input_tokens": 9}).model_dump_json()))
        records = repository.get_task("courseware", "r")
        assert records.unavailable_reasons
        assert records.calls == []
    finally:
        repository.close()
