"""Contract tests for the bounded, normal-path live workflow smoke."""

from app.core.courseware.live_workflow_smoke import (
    LIVE_COMBINATIONS,
    _outcome_counts,
    redact_workflow_record,
)


def test_live_workflow_smoke_has_four_fixed_combinations_and_redacts_payloads():
    assert len(LIVE_COMBINATIONS) == 4
    assert [item["id"] for item in LIVE_COMBINATIONS] == [
        "lecture_only",
        "lecture_practice_assessment",
        "five_resource_types",
        "repair_revision_candidate",
    ]
    record = redact_workflow_record({
        "run_id": "cw_secret-run-id",
        "warnings": [{"message": "raw prompt should not survive"}],
        "artifact_sha256": "a" * 64,
        "usage": {"input_tokens": 1, "output_tokens": 2},
    })
    assert "raw prompt" not in str(record)
    assert "cw_secret-run-id" not in str(record)
    assert record["artifact_sha256"] == "a" * 64


def test_live_outcomes_do_not_count_warning_publication_twice():
    assert _outcome_counts(["published", "published_with_warnings", "quarantined", "rejected_admission"]) == {
        "published": 1, "warning": 1, "quarantined": 1, "rejected": 1,
    }
