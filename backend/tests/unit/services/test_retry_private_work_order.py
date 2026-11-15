"""Manual retries must preserve the private finding, not a public summary."""
from types import SimpleNamespace
import pytest
from app.services.generation.resource_retry import _frozen_review_work_order, _retry_revision_input
from tests.unit.agents.test_resource_issue_engine import _resource, _run, _approve_outcome
from tests.unit.agents.test_resource_issue_closure_regressions import _issue


def fixture_review(monkeypatch):
    resource = _resource(content="正文第一段\n\n正文第二段")
    def failed(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_issue(location={"kind":"paragraph", "paragraph_id":"p000001"}).model_dump(mode="json")]
        return out
    result, _, _ = _run(resource=resource, outcomes=[failed])
    assert result.ledger is not None and result.ledger.issues
    record = SimpleNamespace(resource_ledgers=[result.ledger])
    monkeypatch.setattr("app.models.reviews.review_audit.review_audit_envelope", lambda *a, **k: {"audit_hash":"verified"})
    audit = SimpleNamespace(get_step_review_audit=lambda *a: record)
    projection = {"review_audit_refs":[{"schema_version":"4.0", "step_id":"review", "audit_hash":"verified"}]}
    spec = SimpleNamespace(resource_spec_id="spec-1", knowledge_points=["目标一"])
    return resource, audit, projection, spec


def test_private_work_order_retains_requirement_and_acceptance(monkeypatch):
    parent, audit, projection, spec = fixture_review(monkeypatch)
    order = _frozen_review_work_order(audit, projection, run_id="run-1", resource=parent, spec=spec)
    result = _retry_revision_input(generation=SimpleNamespace(), run_id="run-1", resource=parent,
        spec_id="spec-1", spec=spec, feedback={"issues":[{"code":"structure_quality"}]}, evidence=[], work_order=order)
    issue = result["input"]["issues"][0]
    assert issue["requirement"] and issue["acceptance"] and issue["location"]["paragraph_id"] == "p000001"
    assert result["input"]["revision_source"] != "compat"


def test_private_work_order_rejects_audit_hash_or_changed_parent(monkeypatch):
    parent, audit, projection, spec = fixture_review(monkeypatch)
    projection["review_audit_refs"][0]["audit_hash"] = "tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        _frozen_review_work_order(audit, projection, run_id="run-1", resource=parent, spec=spec)
    projection["review_audit_refs"][0]["audit_hash"] = "verified"
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        _frozen_review_work_order(audit, projection, run_id="run-1", resource=parent.model_copy(update={"content_text":"changed"}), spec=spec)
