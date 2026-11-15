"""F04: child evidence context, retry boundary and recovery resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.security.errors import ApplicationError
from app.services.generation.resource_retry import (
    _has_supplement_scope,
    prepare_resource_retry,
)
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner


def _scope(*, purpose: str = "generation", version: int = 1, resource_id: str = "res-1"):
    return SimpleNamespace(
        purpose=purpose, resource_version=version, resource_id=resource_id,
        added_evidence_ids=["ev-new"],
    )


class _Supplement:
    def __init__(self, scopes):
        self.scopes = list(scopes)

    def list_evidence_sets(self, run_ids):
        return list(self.scopes)


class _Resources:
    def __init__(self, *, parent=None, spec=None):
        self.parent = parent
        self.spec = spec

    def get_spec(self, spec_id):
        return self.spec

    def get_execution(self, run_id, spec_id, representation):
        return SimpleNamespace(state="failed", resource_id="res-1")

    def get(self, resource_id):
        return self.parent


class _Jobs:
    def __init__(self, learner_id: str = "learner-1"):
        self.learner_id = learner_id

    def get(self, run_id):
        return SimpleNamespace(learner_id=self.learner_id, job_status="completed")

    def get_dispatch(self, run_id):
        return {}


def _service(*, parent, spec, scopes):
    generation = SimpleNamespace(
        resource_repo=_Resources(parent=parent, spec=spec),
        audit_repo=SimpleNamespace(),
        supplement_repository=_Supplement(scopes),
    )
    return SimpleNamespace(job_repo=_Jobs(), generation_service=generation)


def _learner():
    return SimpleNamespace(learner_id="learner-1", user_id="user-1")


def test_retry_still_refuses_missing_frozen_source_context():
    """A scope does not exempt retry from its frozen dispatch checks."""

    parent = SimpleNamespace(
        resource_id="res-1", version=2, publication_status="unpublished",
    )
    service = _service(
        parent=parent, spec=SimpleNamespace(run_id="run-1"),
        scopes=[_scope(version=2)],
    )

    with pytest.raises(ApplicationError) as caught:
        prepare_resource_retry(service, _learner(), "run-1", "spec-1", "text")

    assert caught.value.status_code == 409
    assert "冻结上下文" in (caught.value.public_message or "")


def test_retry_keeps_the_original_behaviour_without_a_generation_scope():
    parent = SimpleNamespace(
        resource_id="res-1", version=1, publication_status="unpublished",
    )
    service = _service(
        parent=parent, spec=SimpleNamespace(run_id="run-1"),
        scopes=[_scope(purpose="audit", version=1)],
    )

    with pytest.raises(ApplicationError) as caught:
        prepare_resource_retry(service, _learner(), "run-1", "spec-1", "text")

    # It still fails on the frozen-context checks, but not because of a
    # supplement scope: legacy retry behaviour is unchanged.
    assert caught.value.status_code == 409
    assert "补检新增证据" not in (caught.value.public_message or "")


def test_supplement_scope_detection_is_bound_to_the_parent_version():
    parent = SimpleNamespace(resource_id="res-1", version=2)
    generation = SimpleNamespace(
        supplement_repository=_Supplement([_scope(version=1, resource_id="res-1")]),
    )
    assert _has_supplement_scope(generation, "run-1", parent) is False

    generation.supplement_repository = _Supplement([_scope(version=2)])
    assert _has_supplement_scope(generation, "run-1", parent) is True

    generation.supplement_repository = _Supplement([_scope(purpose="audit", version=2)])
    assert _has_supplement_scope(generation, "run-1", parent) is False


def test_recovery_resolves_the_child_generation_scope_only_for_the_same_spec():
    """The recovery path recomputes the same bounded evidence pool."""

    parent = SimpleNamespace(resource_id="res-1", resource_spec_id="spec-1", run_id="run-1",
                             resource_family_id="family-1", version=1, parent_resource_id=None)
    child = SimpleNamespace(resource_id="res-2", resource_spec_id="spec-1", run_id="run-1",
                            resource_family_id="family-1", version=2, parent_resource_id="res-1")
    child_spec = SimpleNamespace(resource_spec_id="spec-1", evidence_ids=["ev-base"])
    other_spec = SimpleNamespace(resource_spec_id="spec-2", evidence_ids=["ev-base"])

    class _ArtifactRecorder:
        resource_repository = SimpleNamespace(get={"res-1": parent, "res-2": child}.get)

    supplement = _Supplement([
        _scope(version=1, resource_id="res-1"),
        _scope(version=1, resource_id="res-9"),
    ])
    runner = DurableWorkflowRunner(
        workflow=None, repository=SimpleNamespace(), artifact_recorder=_ArtifactRecorder(),
        supplement_repository=supplement,
    )

    assert runner._evidence_ids_for(
        "run-1", child_spec, version=2, resource_id="res-2", available={"ev-base", "ev-new"},
    ) == ["ev-base", "ev-new"]
    # A different spec never inherits the scope, and an unavailable snapshot is
    # never invented.
    with pytest.raises(ValueError):
        runner._evidence_ids_for(
            "run-1", other_spec, version=2, resource_id="res-2", available={"ev-base", "ev-new"},
        )
    with pytest.raises(ValueError):
        runner._evidence_ids_for(
            "run-1", child_spec, version=2, resource_id="res-2", available={"ev-base"},
        )
    # A legacy run without scopes keeps exactly the frozen spec boundary.
    legacy = DurableWorkflowRunner(
        workflow=None, repository=SimpleNamespace(), artifact_recorder=_ArtifactRecorder(),
    )
    assert legacy._evidence_ids_for(
        "run-1", child_spec, version=2, resource_id="res-2", available={"ev-base", "ev-new"},
    ) == ["ev-base"]


def test_retry_and_recovery_follow_the_real_ancestry_for_v3():
    resources = {}
    for version in (1, 2, 3):
        resources[f"res-{version}"] = SimpleNamespace(
            resource_id=f"res-{version}", run_id="run-1", resource_spec_id="spec-1",
            resource_family_id="family-1", version=version,
            parent_resource_id=f"res-{version - 1}" if version > 1 else None,
        )
    repo = SimpleNamespace(get=resources.get)
    generation = SimpleNamespace(resource_repo=repo, supplement_repository=_Supplement([_scope()]))
    assert _has_supplement_scope(generation, "run-1", resources["res-2"])
    assert _has_supplement_scope(generation, "run-1", resources["res-3"])
    runner = DurableWorkflowRunner(None, None, SimpleNamespace(resource_repository=repo),
                                   generation.supplement_repository)
    spec = SimpleNamespace(resource_spec_id="spec-1", evidence_ids=["ev-base"])
    assert runner._evidence_ids_for("run-1", spec, version=3, resource_id="res-3",
                                    available={"ev-base", "ev-new"}) == ["ev-base", "ev-new"]
    resources["res-1"].resource_family_id = "foreign"
    with pytest.raises(ApplicationError) as caught:
        _has_supplement_scope(generation, "run-1", resources["res-3"])
    assert caught.value.status_code == 409
    with pytest.raises(ValueError):
        runner._evidence_ids_for("run-1", spec, version=3, resource_id="res-3",
                                 available={"ev-base", "ev-new"})


def test_retry_scope_read_failure_is_not_treated_as_no_supplement():
    def broken(_):
        raise RuntimeError("repository unavailable")
    generation = SimpleNamespace(supplement_repository=SimpleNamespace(list_evidence_sets=broken))
    with pytest.raises(ApplicationError) as caught:
        _has_supplement_scope(generation, "run-1", SimpleNamespace(resource_id="res-1", version=1))
    assert caught.value.status_code == 409


def test_no_supplements_do_not_reject_cross_run_business_parent():
    parent = SimpleNamespace(resource_id="retry-child", run_id="retry-run", version=2,
                             parent_resource_id="old-parent")
    generation = SimpleNamespace(supplement_repository=_Supplement([]))
    assert not _has_supplement_scope(generation, "retry-run", parent)
