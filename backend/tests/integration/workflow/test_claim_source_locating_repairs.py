"""T42 repair regressions: frozen limits, contracts and durable diagnostics."""
from datetime import datetime, timezone

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction import contracts
from app.core.execution import execution_session
from app.models.reviews.claim_extraction import (
    EstimateLedger, ExtractionResult, LocationDiagnostic, validate_transition,
)
from tests.unit.agents.test_claim_source_locating import RULES, make_policy, run
from tests.integration.workflow.test_claim_source_locating import v2_state, _extract


TEXT = "系统记录课程内容并保存学习进度，教师确认材料后安排练习，学生阅读正文并完成对应任务。"


def test_frozen_edit_ratio_rejects_two_edits_above_four_percent():
    ref = TEXT.replace("系统", "系系统").replace("教师", "教教师")
    assert 2 / len(ref) > 0.04
    assert not run(TEXT, ref).accepted


def test_legacy_locator_keeps_its_frozen_result():
    from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import locate
    from types import SimpleNamespace

    ref = TEXT.replace("系统", "系系统").replace("教师", "教教师")
    legacy = make_policy(locator_algorithm_version="locator-v1")
    result = locate(TEXT, SimpleNamespace(start=0, end=len(TEXT), kind="paragraph"),
                    ref, legacy, RULES)
    assert result.accepted
    assert (result.start, result.end) == (0, len(TEXT))


def test_duplicate_recovery_preserves_original_boundary():
    text = "陶艺学员把湿润的泥坯放在木板上，接着用海绵擦去边缘水迹并轻轻修整底座，完成后将作品移到通风架上晾干。"
    result = run(text, text[0] + text)
    assert result.accepted
    assert text[result.start:result.end] == text


def test_four_percent_boundary_is_accepted():
    text = (TEXT + "请继续检查材料。")[:48]
    assert len(text) == 48
    ref = text.replace("系统", "系系统").replace("教师", "教教师")
    result = run(text, ref)
    assert result.accepted and result.edits == 2 and result.score == 0.96


@pytest.mark.parametrize("limit", ["min_effective_chars", "max_dp_cells_per_ref"])
def test_locating_uses_frozen_limits_not_live_rule_defaults(limit):
    from types import SimpleNamespace
    from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import locate

    policy = make_policy(**{limit: 100 if limit == "min_effective_chars" else 1})
    result = locate(TEXT, SimpleNamespace(start=0, end=len(TEXT), kind="paragraph"),
                    TEXT.replace("教师", "教教师"), policy, RULES)
    assert not result.accepted


def test_legacy_saved_diagnostics_replay_without_policy_upgrade(monkeypatch):
    from app.agents.resource_workflows.learning_documents.claim_extraction import budget, executor
    from tests.fakes.claim_extraction import extract_every_unit_v2

    freeze = budget.freeze_policy

    def old_freeze(*args, **kwargs):
        p = freeze(*args, **kwargs)
        return p.model_copy(update={"source_locating": p.source_locating.model_copy(
            update={"locator_algorithm_version": "locator-v1"})})

    monkeypatch.setattr(budget, "freeze_policy", old_freeze)
    state, _, repo, gateway, counter = v2_state(TEXT)

    def output(call):
        data = extract_every_unit_v2(call)
        data["units"][0]["claims"][0]["source_text"] = (
            TEXT.replace("系统", "系系统").replace("教师", "教教师"))
        return data

    gateway.outcomes = [output]
    original = executor.materialize_result
    monkeypatch.setattr(executor, "materialize_result",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("interrupted")))
    args = dict(review_id="review", evidence=state["retrieved_evidence"],
                llm_gateway=gateway, repository=repo, counter=counter, step_id="step")
    with execution_session(state["run_id"], "owner"):
        with pytest.raises(RuntimeError, match="interrupted"):
            executor.execute_extraction(state, state["generated_resources"][0], **args)
        before = repo.get(state["run_id"])
        saved = next(iter(before.state.results.values()))
        assert saved.status == "running" and saved.location_diagnostics
        monkeypatch.setattr(executor, "materialize_result", original)
        claims, _, _ = executor.execute_extraction(state, state["generated_resources"][0], **args)
        assert len(gateway.calls) == 1
    after = repo.get(state["run_id"])
    assert after.policy == before.policy
    assert after.policy.source_locating.locator_algorithm_version == "locator-v1"
    assert next(iter(after.state.results.values())).location_diagnostics == saved.location_diagnostics
    assert claims[0].source_text == TEXT


def test_correct_original_recovered_despite_subject_copy_error():
    text = "他负责整理课程材料并保存学习进度，教师确认材料后安排练习，学生阅读正文并完成对应任务。"
    result = run(text, text.replace("他", "她"))
    assert result.accepted
    assert text[result.start:result.end] == text


@pytest.mark.parametrize("asset", ["prompt", "schema"])
def test_contract_drift_rejected_before_any_request(monkeypatch, asset):
    p = make_policy()
    p.prompt_version = contracts.PROMPT_VERSION_V2
    if asset == "prompt":
        monkeypatch.setattr(contracts, "PROMPT_V2", contracts.PROMPT_V2 + "\nchanged")
    else:
        monkeypatch.setattr(contracts.BatchOutputV2, "model_json_schema",
                            classmethod(lambda cls, **kw: {"changed": True}))
    with pytest.raises(ValueError, match="drift"):
        contracts.select_contract(p)


@pytest.mark.parametrize("asset", ["prompt", "schema"])
def test_completed_result_reuses_saved_claims_despite_current_asset_drift(monkeypatch, asset):
    from app.agents.resource_workflows.learning_documents.claim_extraction.executor import execute_extraction
    from tests.fakes.claim_extraction import extract_every_unit_v2

    state, _, repo, gateway, counter = v2_state(TEXT)
    gateway.outcomes = [extract_every_unit_v2]
    args = dict(review_id="review", evidence=state["retrieved_evidence"],
                llm_gateway=gateway, repository=repo, counter=counter, step_id="step")
    with execution_session(state["run_id"], "owner"):
        before, _, _ = execute_extraction(state, state["generated_resources"][0], **args)
        if asset == "prompt":
            monkeypatch.setattr(contracts, "PROMPT_V2", contracts.PROMPT_V2 + "\nchanged")
        else:
            monkeypatch.setattr(contracts.BatchOutputV2, "model_json_schema",
                                classmethod(lambda cls, **kw: {"changed": True}))
        after, _, _ = execute_extraction(state, state["generated_resources"][0], **args)
    assert before == after and len(gateway.calls) == 1


def test_invalid_locating_retains_private_rejection_and_settled_usage():
    state, _, repo, gateway, counter = v2_state(TEXT)

    def invalid(call):
        import json
        payload = json.loads(call["messages"][-1].content)
        return {k: payload[k] for k in (
            "resource_id", "resource_version", "content_hash", "batch_id"
        )} | {"units": [
            dict(unit_id=u["unit_id"], status="claims", reason="synthetic",
                 claims=[dict(claim_text="synthetic", claim_type="factual",
                              source_text="not present anywhere", knowledge_point_id=None)])
            for u in payload["target_units"]
        ]}

    gateway.outcomes = [invalid] * 64
    with execution_session(state["run_id"], "owner"):
        state.update(_extract(state, repo, gateway, counter))
    saved = repo.get(state["run_id"]).state
    result = next(iter(saved.results.values()))
    assert result.status == "failed"
    assert result.location_failures
    for call_id, diagnostics in result.location_failures.items():
        assert saved.logical_calls[call_id].status == "invalid"
        assert 0 < len(diagnostics) <= 8
        assert all(not d.accepted for d in diagnostics)
    assert saved.tokens > 0 and all(t.settled for t in saved.tickets.values())


def test_audit_capacity_failure_keeps_usage_and_never_publishes_partial_success(monkeypatch):
    import app.db.claim.extraction as repository_module
    from tests.fakes.claim_extraction import extract_every_unit_v2

    original = repository_module.check_ledger_size

    def limited(policy, ledger):
        if any(r.outputs for r in ledger.results.values()):
            raise ValueError("extraction ledger byte budget exceeded")
        return original(policy, ledger)

    monkeypatch.setattr(repository_module, "check_ledger_size", limited)
    state, _, repo, gateway, counter = v2_state(TEXT)
    gateway.outcomes = [extract_every_unit_v2]
    with execution_session(state["run_id"], "owner"):
        state.update(_extract(state, repo, gateway, counter))
    saved = repo.get(state["run_id"]).state
    result = next(iter(saved.results.values()))
    assert result.status == "failed" and not result.outputs and not result.final_claims
    assert all(c.status == "failed" for c in saved.logical_calls.values())
    assert saved.tokens > 0 and all(t.settled for t in saved.tickets.values())
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("field", ["location_diagnostics", "location_failures"])
def test_existing_diagnostics_cannot_be_deleted_or_changed(field):
    diagnostic = LocationDiagnostic(
        unit_id="u", candidate_index=0, ref_hash="a" * 64,
        level="exact", accepted=False, code="no_candidate",
    )
    result = ExtractionResult(
        resource_id="r", resource_version=1, review_id="review",
        content_hash="b" * 64, evidence_hash="c" * 64,
        generation_attempt=1, created_at=datetime.now(timezone.utc),
        **{field: {"b": [diagnostic]}},
    )
    before = EstimateLedger(results={"key": result})
    for edited in (None, {}, {"b": [diagnostic.model_copy(update={"code": "changed"})]}):
        after = before.model_copy(update={"results": {
            "key": result.model_copy(update={field: edited}),
        }})
        with pytest.raises(ValueError, match="diagnostic"):
            validate_transition(before, after)
