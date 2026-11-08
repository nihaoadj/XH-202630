"""Strategy freezing, dispatch resolution and authority-chain validation (T44 P3)."""

from types import SimpleNamespace

import pytest

from app.models.shared.persistence import canonical_hash
from app.models.generation.dispatch import TEXT_WORKFLOW_VERSION
from app.services.generation.resource_review_policy import (
    freeze_resource_review_policy,
    resolve_resource_review_dispatch,
    resource_review_fields,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_authority import (
    RESOURCE_WORKFLOW_VERSION,
    validate_resource_authority,
)


def _request(include_review=True, resource_types=("讲义", "实操指南")):
    return SimpleNamespace(include_review=include_review, resource_types=list(resource_types))


def _settings(strategy="compat", context_tokens=None):
    return SimpleNamespace(
        resource_review_strategy=strategy,
        resource_review_context_tokens=context_tokens,
        llm_max_output_tokens=16384,
        llm_max_attempts=2,
        llm_model="fake-model",
    )


def test_compat_freezes_nothing():
    frozen = freeze_resource_review_policy(_request(), _settings("compat"))
    assert frozen == {}


def test_resource_issue_v1_freezes_contract_and_hash():
    frozen = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    assert frozen["resource_review_contract_version"] == "1.1"
    assert frozen["resource_review_policy"]["strategy"] == "resource_issue_v1"
    assert frozen["resource_review_policy_hash"] == canonical_hash(frozen["resource_review_policy"])


def test_resource_issue_v1_ignored_without_review_or_types():
    assert freeze_resource_review_policy(_request(include_review=False), _settings("resource_issue_v1", 262144)) == {}
    assert freeze_resource_review_policy(_request(resource_types=("互动课件",)), _settings("resource_issue_v1", 262144)) == {}


def test_dispatch_roundtrip_and_hash_tamper_rejected():
    frozen = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    snapshot = {"workflow_version": RESOURCE_WORKFLOW_VERSION, "base_workflow_version": TEXT_WORKFLOW_VERSION,
                **frozen}
    snapshot["resource_dispatch_hash"] = canonical_hash({k: v for k, v in snapshot.items()
                                                         if k != "resource_dispatch_hash"})
    version, fields = resolve_resource_review_dispatch(snapshot)
    assert version == TEXT_WORKFLOW_VERSION
    assert fields["resource_review_contract_version"] == "1.1"
    # Tampering any frozen field invalidates the dispatch hash.
    tampered = dict(snapshot)
    tampered["resource_review_contract_version"] = "9.9"
    with pytest.raises(ValueError):
        resolve_resource_review_dispatch(tampered)


def test_legacy_dispatch_rejects_resource_fields():
    frozen = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    legacy = {"workflow_version": "learning_documents.text.v1", **frozen}
    with pytest.raises(ValueError):
        resolve_resource_review_dispatch(legacy)


def test_validate_resource_authority_rejects_mixed_checkpoint():
    frozen = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    snapshot = {**frozen, "learner": {}}
    request_hash = canonical_hash(snapshot)
    # A checkpoint carrying the resource fields must agree with the run snapshot.
    with pytest.raises(ValueError):
        validate_resource_authority(
            request_snapshot=snapshot, request_hash=request_hash,
            created_event_request_hash=request_hash, checkpoint={"resource_review_contract_version": "9.9"})


def test_resource_review_fields_rejects_incomplete_contract():
    with pytest.raises(ValueError):
        resource_review_fields({"resource_review_contract_version": "1.0"})


def test_execution_identity_is_frozen_and_changed_model_cannot_send():
    from app.models.reviews.resource_review_policy import validate_execution_identity
    frozen = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    validate_execution_identity(frozen, SimpleNamespace(transport=SimpleNamespace(model_name="fake-model")))
    with pytest.raises(ValueError, match="model differs"):
        validate_execution_identity(frozen, SimpleNamespace(transport=SimpleNamespace(model_name="changed-model")))
    for field in ("resource_review_identity", "resource_review_identity_hash"):
        bad = dict(frozen)
        del bad[field]
        with pytest.raises(ValueError):
            resource_review_fields(bad)


def test_historical_resource_policy_keeps_hash_and_read_access_but_is_not_sendable():
    from app.models.reviews.resource_review_policy import validate_execution_identity
    modern = freeze_resource_review_policy(_request(), _settings("resource_issue_v1", 262144))
    historical = {key: value for key, value in modern.items() if not key.startswith("resource_review_identity")}
    historical["resource_review_contract_version"] = "1.0"
    assert resource_review_fields(historical) == historical
    assert historical["resource_review_policy_hash"] == modern["resource_review_policy_hash"]
    with pytest.raises(ValueError, match="read-only"):
        validate_execution_identity(historical, SimpleNamespace(transport=SimpleNamespace(model_name="fake-model")))
