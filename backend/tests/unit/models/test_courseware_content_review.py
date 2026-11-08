import pytest
from pydantic import ValidationError
from app.models.courseware.content_review import (
    BatchResultV1, FieldIssueV1, RevisionPatchV1, ContentReviewStateV1,
    MAX_SPEC_BYTES, validate_private_spec,
)
from tests.fakes.courseware_content_review import fixture_settings, ContentReviewGateway
from app.agents.resource_workflows.interactive_courseware.content_review.persistence import freeze_policy
from datetime import datetime, timedelta, timezone


def policy():
    return freeze_policy(fixture_settings(), ContentReviewGateway(), datetime.now(timezone.utc)+timedelta(minutes=10))


@pytest.mark.parametrize("change", [{"schema_version": "2.0"}, {"extra": "forbidden"}, {"batch_id": "x"*97}, {"identity": "x"*64}, {"results": [{}]*129}])
def test_model_output_rejects_unknown_versions_fields_and_bounds(change):
    raw = dict(batch_id="b", identity="a"*64, value_hash="b"*64, results=[])
    with pytest.raises(ValidationError):
        BatchResultV1.model_validate({**raw, **change})


def test_issue_patch_and_private_spec_are_bounded():
    with pytest.raises(ValidationError):
        FieldIssueV1(code="factual_conflict", severity="error", reason="x"*161)
    with pytest.raises(ValidationError):
        RevisionPatchV1(identity="a"*64, changes=[dict(item_id="x", old_value_hash="b"*64, new_value="x"*8193)])
    state = ContentReviewStateV1(policy=policy())
    assert ContentReviewStateV1.model_validate_json(state.model_dump_json()) == state
    with pytest.raises(ValueError, match="size limit"):
        validate_private_spec({"content_review": state.model_dump(mode="json"), "other": "x"*MAX_SPEC_BYTES})


def test_unknown_frozen_policy_is_not_interpreted_as_latest():
    raw = policy().model_dump(mode="json"); raw["ruleset_version"] = "future"
    with pytest.raises(ValidationError):
        type(policy()).model_validate(raw)
