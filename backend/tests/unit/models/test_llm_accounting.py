"""Unit tests for the V1 accounting contracts and pure aggregation."""

from app.models.shared.llm_accounting import (
    LLM_ACCOUNTING_SCHEMA_VERSION,
    LLMAttemptEvidenceV1,
    LLMCallObservationV1,
    AccountingSegmentV1,
    TaskLLMAccountingResponseV1,
    build_task_response,
    canonical_accounting_hash,
    deduplicate_observations,
    summarize_observations,
)
from app.services.runs.llm_accounting import LLMAccountingQueryService


def _observation(**overrides) -> LLMCallObservationV1:
    base = dict(
        domain="learning_documents",
        run_id="run-1",
        segment_id="seg-1",
        observation_id=1,
        stage="generate",
        attempts=[
            LLMAttemptEvidenceV1(
                ordinal=1,
                gateway_status="success",
                usage_input_tokens=10,
                usage_output_tokens=5,
                usage_total_tokens=15,
                usage_source="summary",
            )
        ],
        usage_input_tokens=10,
        usage_output_tokens=5,
        usage_total_tokens=15,
        known_input_tokens=10,
        known_output_tokens=5,
        known_total_tokens=15,
        usage_complete=True,
    )
    base.update(overrides)
    return LLMCallObservationV1(**base)


def test_same_primary_key_same_hash_is_idempotent_no_op():
    first = _observation()
    second = _observation()
    deduped, conflicts = deduplicate_observations([first, second])
    assert len(deduped) == 1
    assert conflicts == 0


def test_same_primary_key_different_hash_is_conflict_first_value_wins():
    first = _observation()
    second = _observation(usage_complete=False, known_input_tokens=11)
    deduped, conflicts = deduplicate_observations([first, second])
    assert len(deduped) == 1
    assert deduped[0].known_input_tokens == 10
    assert conflicts == 1


def test_same_call_id_reused_is_two_logical_calls():
    first = _observation(source_call_id="same-call", observation_id=1)
    second = _observation(source_call_id="same-call", observation_id=2)
    deduped, conflicts = deduplicate_observations([first, second])
    assert len(deduped) == 2
    assert conflicts == 0


def test_usage_fieldwise_unknown_and_conflict():
    unknown = _observation(
        attempts=[LLMAttemptEvidenceV1(ordinal=1, gateway_status="success")],
        usage_input_tokens=None,
        usage_complete=False,
        known_input_tokens=0,
    )
    conflict = _observation(
        attempts=[
            LLMAttemptEvidenceV1(
                ordinal=1,
                usage_input_tokens=10,
                usage_output_tokens=5,
                usage_total_tokens=15,
                usage_source="summary",
                helper_observed=True,
                helper_raw_success=True,
                helper_usage_input_tokens=10,
                helper_usage_output_tokens=5,
                helper_usage_total_tokens=15,
            )
        ],
    )
    assert unknown.usage_input_tokens is None
    evidence = conflict.attempts[0]
    merged_input, merged_output, merged_total, mismatch = evidence.merged_usage()
    assert (merged_input, merged_output, merged_total) == (10, 5, 15)
    assert mismatch is False
    conflicting = LLMAttemptEvidenceV1(
        ordinal=1,
        usage_input_tokens=10,
        helper_usage_input_tokens=99,
    )
    _, _, _, mismatch = conflicting.merged_usage()
    assert mismatch is True


def test_shared_resource_labels_form_additive_partition():
    exclusive = _observation(attribution="resource", resource_labels=["r-1"])
    shared = _observation(
        observation_id=2,
        attribution="resource_set",
        resource_labels=["r-1", "r-2"],
    )
    response = _respond([exclusive, shared])
    partitions = {(item.partition, item.label) for item in response.resource_partition_summaries}
    assert ("exclusive", "r-1") in partitions
    assert ("shared", 'shared:["r-1", "r-2"]') in partitions
    assert sum(p.usage.observed_calls for p in response.resource_partition_summaries) == 2
    # Each call contributes to exactly one additive partition.
    assert response.task_summary.observed_calls == 2


def test_top_level_usage_not_double_counted_in_summary():
    call = _observation()
    summary = summarize_observations([call])
    assert summary.known_input_tokens == 10
    assert summary.complete_input_tokens == 10
    assert summary.usage_complete_calls == 1
    assert summary.observed_calls == 1


def test_canonical_hash_stable_and_excludes_recorded_at():
    first = _observation()
    second = _observation(recorded_at="2999-01-01T00:00:00+00:00")
    assert canonical_accounting_hash(first.stable_payload()) == canonical_accounting_hash(
        second.stable_payload()
    )


def test_task_response_shape_and_stage_filter():
    calls = [
        _observation(stage="generate"),
        _observation(observation_id=2, stage="review"),
    ]
    response = _respond(calls, stage_filter="review", include_calls=True)
    assert isinstance(response, TaskLLMAccountingResponseV1)
    assert response.task_summary.observed_calls == 2
    assert response.filtered_summary is not None
    assert response.filtered_summary.observed_calls == 1
    assert all(call.stage == "review" for call in response.calls)
    assert response.schema_version == LLM_ACCOUNTING_SCHEMA_VERSION


def test_capacity_limits_are_frozen():
    from app.models.shared import llm_accounting as m

    assert m.MAX_CALLS_PER_SEGMENT == 8192
    assert m.MAX_ATTEMPTS_PER_CALL == 3
    assert m.MAX_BATCH_SEGMENTS == 128
    assert m.MAX_BATCH_JSON_BYTES == 8 * 1024 * 1024


def test_query_service_pending_vs_not_recorded_vs_partial():
    import tempfile
    from pathlib import Path

    import shutil
    import tempfile
    from pathlib import Path

    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / "accounting.db"
        # Initialize the independent accounting schema (writer-side path).
        from app.db.audit.llm_accounting.sql_repository import (
            SQLLLMAccountingRepository,
        )

        SQLLLMAccountingRepository(str(db_path)).close()
        service = LLMAccountingQueryService(str(db_path))
        running = service.query_task(domain="learning_documents", run_id="run-x", task_terminal=False)
        assert running.availability == "pending"
        terminal = service.query_task(domain="learning_documents", run_id="run-x", task_terminal=True)
        assert terminal.availability == "not_recorded"
        assert terminal.task_summary.observed_calls == 0
        assert terminal.usage_complete is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _respond(calls, **kwargs) -> TaskLLMAccountingResponseV1:
    from app.models.shared.llm_accounting import SegmentInfoV1

    return build_task_response(
        domain="learning_documents",
        run_id="run-1",
        observations=calls,
        segments=[
            SegmentInfoV1(
                segment_id="seg-1",
                recorded_at="2026-11-05T00:00:00+00:00",
                call_count=len(calls),
                sealed=True,
            )
        ],
        availability="available",
        coverage_complete=False,
        **kwargs,
    )


def test_segment_payload_hash_round_trip():
    segment = AccountingSegmentV1(
        domain="courseware",
        run_id="run-1",
        segment_id="seg-1",
        process_nonce="proc-1",
        calls=[_observation(domain="courseware")],
        sealed=True,
    )
    payload = segment.stable_payload()
    rebuilt = AccountingSegmentV1.model_validate(payload)
    assert canonical_accounting_hash(rebuilt.stable_payload()) == canonical_accounting_hash(
        payload
    )
