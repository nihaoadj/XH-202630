"""T44 generic resource-review contract: typed locations, two origins, replay.

These are golden tests for the pure contract.  They assert the illegal sets,
versions, locations, coverage links, the two observation origins and the legal
state transitions without any model call.
"""

import hashlib

import pytest

from app.models.reviews.resource_review import (
    ResourceGateKeyV1,
    ResourceIssueHistoryV1,
    ResourceIssueV1,
    ResourceLedgerV1,
    ResourceLocationV1,
    ResourceObservationV1,
    ResourceProgramGateResultV1,
    ResourceReviewBindingV1,
    ResourceReviewInitialV1,
    ResourceReviewOutputV1,
    ResourceReopenV1,
    ResourceResolutionV1,
    derived_coverage_rate,
    model_issue_id,
    output_hash,
    program_issue_id,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def binding(version: int = 1, *, text: str = "text", payload: str | None = None,
            comparison: str = "cmp") -> ResourceReviewBindingV1:
    payload_hash = h(payload) if payload is not None else None
    return ResourceReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="lineage-1",
        resource_id=f"res-{version}", resource_type="讲义", version=version,
        text_exact_hash=h(text), structured_payload_hash=payload_hash,
        artifact_exact_hash=h(f"{text}:{payload}"), comparison_hash=h(comparison),
        evidence_snapshot_hash=h("evidence"), policy_hash=h("policy"))


def root_location() -> ResourceLocationV1:
    return ResourceLocationV1(kind="root")


def issue(issue_id: str, *, origin: str = "model_review", blocking: bool = True,
          dimension: str = "self_contained", code: str = "structure_quality",
          rule: str = "self_contained") -> ResourceIssueV1:
    return ResourceIssueV1(
        issue_id=issue_id, origin=origin, code=code,
        severity="high" if blocking else "low", blocking=blocking,
        blocking_rule=rule if blocking else None, dimension=dimension,
        location=root_location(), impact="读者无法完成", requirement="补充材料",
        acceptance="可独立完成", criteria_version=1, path="reorganize_existing",
        teaching_rule_id=None if origin == "program_gate" else rule,
        executability="executable", rationale="已有材料可整理",
        finding_keys=[] if origin == "model_review" else [])


def initial_output(blocking_issue_id: str = "tmp-1") -> ResourceReviewInitialV1:
    return ResourceReviewInitialV1.model_validate({
        "binding": binding(1).model_dump(mode="json"),
        "dimensions": {"factual_evidence": "fail", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": "目标一", "status": "covered", "reason": "已讲解",
                     "location": root_location().model_dump(mode="json")}],
        "hallucination_score": 0.5,
        "issues": [issue(blocking_issue_id, code="factual_risk", dimension="factual_evidence",
                         rule="factual_evidence").model_dump(mode="json")],
        "omitted_blocking_issues": False,
    })


def gate_result(passed: bool, *, new_codes=(), rule="resource_structure_v1",
                scope="root") -> ResourceProgramGateResultV1:
    keys = []
    new_issues = []
    for code in new_codes:
        keys.append(ResourceGateKeyV1(gate_rule_id=rule, scope_locator=scope, failure_code=code))
        pid = program_issue_id(run_id="run-1", resource_spec_id="spec-1",
                               gate_rule_id=rule, scope_locator=scope, failure_code=code)
        new_issues.append(issue(pid, origin="program_gate", code=code, rule=rule))
    return ResourceProgramGateResultV1(rule_version="resource-gate-v1", passed=passed,
                                       keys=keys, new_issues=new_issues,
                                       blocked_reason="" if passed else "结构缺失")


# --------------------------------------------------------------------------- #
# locations, coverage and illegal sets
# --------------------------------------------------------------------------- #

def test_paragraph_location_requires_paragraph_id():
    with pytest.raises(ValueError):
        ResourceLocationV1(kind="paragraph")


def test_structured_location_requires_unit_or_missing_fields():
    with pytest.raises(ValueError):
        ResourceLocationV1(kind="structured")


def test_root_location_must_be_empty():
    with pytest.raises(ValueError):
        ResourceLocationV1(kind="root", paragraph_id="p1")


def test_coverage_rate_derives_from_targets():
    targets = [
        {"target": "a", "status": "covered", "reason": "x"},
        {"target": "b", "status": "missing", "reason": "y"},
        {"target": "c", "status": "covered", "reason": "z"},
    ]
    assert derived_coverage_rate([type("T", (), t)() for t in targets]) == 2 / 3
    with pytest.raises(ValueError):
        derived_coverage_rate([])


def test_program_issue_cannot_cite_evidence_or_rule():
    base = issue("x", origin="program_gate").model_dump(mode="json")
    base["teaching_rule_id"] = "self_contained"
    with pytest.raises(ValueError):
        ResourceIssueV1.model_validate(base)


def test_high_severity_must_block():
    base = issue("x").model_dump(mode="json")
    base["blocking"] = False
    base["blocking_rule"] = None
    with pytest.raises(ValueError):
        ResourceIssueV1.model_validate(base)


def test_model_issue_id_is_stable_and_prefixed():
    a = model_issue_id(run_id="r", resource_spec_id="s", lineage_id="l", step_id="st", ordinal=1)
    b = model_issue_id(run_id="r", resource_spec_id="s", lineage_id="l", step_id="st", ordinal=1)
    c = model_issue_id(run_id="r", resource_spec_id="s", lineage_id="l", step_id="st", ordinal=2)
    assert a == b and a.startswith("ri_") and a != c


def test_program_issue_id_is_step_independent():
    a = program_issue_id(run_id="r", resource_spec_id="s", gate_rule_id="g", scope_locator="root", failure_code="f")
    b = program_issue_id(run_id="r", resource_spec_id="s", gate_rule_id="g", scope_locator="root", failure_code="f")
    assert a == b and a.startswith("rip_")


# --------------------------------------------------------------------------- #
# two observation origins
# --------------------------------------------------------------------------- #

def test_program_gate_observation_forbids_model_output():
    gate = gate_result(False, new_codes=["structure_quality"])
    obs = {
        "origin": "program_gate", "step_id": "step-1", "binding": binding(1).model_dump(mode="json"),
        "output_hash": None, "comparison_hash": h("cmp"), "parent_content_hash": None,
        "unchanged": False, "consecutive_unchanged": 0, "characters_added": 0, "characters_removed": 0,
        "gate": gate.model_dump(mode="json"), "output": None, "coverage_rate": None, "decision": None,
    }
    ResourceObservationV1.model_validate(obs)
    obs["output"] = initial_output().model_dump(mode="json")
    with pytest.raises(ValueError):
        ResourceObservationV1.model_validate(obs)


def test_model_observation_requires_output_and_decision():
    gate = gate_result(True)
    obs = {
        "origin": "model_review", "step_id": "step-1", "binding": binding(1).model_dump(mode="json"),
        "output_hash": output_hash(initial_output()), "comparison_hash": h("cmp"),
        "parent_content_hash": None, "unchanged": False, "consecutive_unchanged": 0,
        "characters_added": 0, "characters_removed": 0, "gate": gate.model_dump(mode="json"),
        "output": initial_output().model_dump(mode="json"), "coverage_rate": 1.0, "decision": "revise",
    }
    ResourceObservationV1.model_validate(obs)
    obs["decision"] = None
    with pytest.raises(ValueError):
        ResourceObservationV1.model_validate(obs)


def test_failed_gate_cannot_accompany_model_observation():
    gate = gate_result(False, new_codes=["structure_quality"])
    obs = {
        "origin": "model_review", "step_id": "step-1", "binding": binding(1).model_dump(mode="json"),
        "output_hash": output_hash(initial_output()), "comparison_hash": h("cmp"),
        "parent_content_hash": None, "unchanged": False, "consecutive_unchanged": 0,
        "characters_added": 0, "characters_removed": 0, "gate": gate.model_dump(mode="json"),
        "output": initial_output().model_dump(mode="json"), "coverage_rate": 1.0, "decision": "revise",
    }
    with pytest.raises(ValueError):
        ResourceObservationV1.model_validate(obs)


# --------------------------------------------------------------------------- #
# ledger replay: legal and illegal transitions
# --------------------------------------------------------------------------- #

def normalize(output, *, step_id: str, version: int):
    """Replace temporary issue ids with the stable server ids and bind version."""
    issues = [item.model_copy(update={"issue_id": model_issue_id(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="lineage-1",
        step_id=step_id, ordinal=ordinal)}) for ordinal, item in enumerate(output.issues, 1)]
    return output.model_copy(update={"binding": binding(version), "issues": issues})


def _model_observation(*, step_id, version, output, gate=None, parent=None) -> dict:
    output = normalize(output, step_id=step_id, version=version)
    return {
        "origin": "model_review", "step_id": step_id, "binding": binding(version).model_dump(mode="json"),
        "output_hash": output_hash(output), "comparison_hash": h(f"cmp-{version}"),
        "parent_content_hash": parent.binding.artifact_exact_hash if parent else None,
        "unchanged": False, "consecutive_unchanged": 0, "characters_added": 0, "characters_removed": 0,
        "gate": gate.model_dump(mode="json") if gate else None,
        "output": output.model_dump(mode="json"), "coverage_rate": 1.0, "decision": "revise",
    }


def _history_for(output, *, step_id, status):
    return [{"issue": item.model_dump(mode="json"), "introduced_step_id": step_id,
             "introduced_version": 1, "status": status}
            for item in output.issues]


def test_ledger_version_chain_must_increment_by_one():
    first = initial_output()
    obs1 = _model_observation(step_id="s1", version=1, output=first)
    ledger = ResourceLedgerV1.model_validate({"binding": binding(1).model_dump(mode="json"),
                                              "issues": _history_for(normalize(first, step_id="s1", version=1), step_id="s1", status="open"),
                                              "observations": [obs1]})
    # A second observation at the same version is illegal.
    obs2 = _model_observation(step_id="s2", version=1, output=first)
    with pytest.raises(ValueError):
        ResourceLedgerV1.model_validate({"binding": binding(1).model_dump(mode="json"),
                                         "issues": _history_for(normalize(first, step_id="s1", version=1), step_id="s1", status="open"),
                                         "observations": [obs1, obs2]})


def test_initial_observation_cannot_be_a_revision():
    first = initial_output()
    obs1 = _model_observation(step_id="s1", version=1, output=first)
    obs1["parent_content_hash"] = h("parent")
    with pytest.raises(ValueError):
        ResourceLedgerV1.model_validate({"binding": binding(1).model_dump(mode="json"),
                                         "issues": _history_for(normalize(first, step_id="s1", version=1), step_id="s1", status="open"),
                                         "observations": [obs1]})


def test_ledger_reconstructs_fixed_resolution():
    first = normalize(initial_output(), step_id="s1", version=1)
    first_id = first.issues[0].issue_id
    obs1 = _model_observation(step_id="s1", version=1, output=first)
    ledger1 = ResourceLedgerV1.model_validate({
        "binding": binding(1).model_dump(mode="json"),
        "issues": _history_for(first, step_id="s1", status="open"),
        "observations": [obs1],
    })
    assert ledger1.issues[0].status == "open"

    recheck = ResourceReviewOutputV1.model_validate({
        **first.model_dump(mode="json"),
        "issues": [],
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "hallucination_score": 0.1,
        "resolutions": [ResourceResolutionV1(
            issue_id=first_id, result="fixed", reason="已补材料",
            current_location=root_location()).model_dump(mode="json")],
        "reopen": [],
    })
    recheck = normalize(recheck, step_id="s2", version=2)
    obs2 = _model_observation(step_id="s2", version=2, output=recheck, parent=ledger1)
    ledger2 = ResourceLedgerV1.model_validate({
        "binding": binding(2).model_dump(mode="json"),
        "issues": [{"issue": first.issues[0].model_dump(mode="json"),
                    "introduced_step_id": "s1", "introduced_version": 1, "status": "closed"}],
        "observations": [obs1, obs2],
    })
    assert ledger2.issues[0].status == "closed"


def test_ledger_rejects_unknown_resolution_target():
    first = normalize(initial_output(), step_id="s1", version=1)
    obs1 = _model_observation(step_id="s1", version=1, output=first)
    ledger1 = ResourceLedgerV1.model_validate({"binding": binding(1).model_dump(mode="json"),
                                               "issues": _history_for(first, step_id="s1", status="open"),
                                               "observations": [obs1]})
    recheck = ResourceReviewOutputV1.model_validate({
        **first.model_dump(mode="json"),
        "issues": [],
        "resolutions": [ResourceResolutionV1(issue_id="unknown", result="fixed", reason="x",
                                             current_location=root_location()).model_dump(mode="json")],
    })
    recheck = normalize(recheck, step_id="s2", version=2)
    obs2 = _model_observation(step_id="s2", version=2, output=recheck, parent=ledger1)
    with pytest.raises(ValueError):
        ResourceLedgerV1.model_validate({"binding": binding(2).model_dump(mode="json"),
                                         "issues": _history_for(first, step_id="s1", status="open"),
                                         "observations": [obs1, obs2]})


def test_program_issue_closes_only_when_gate_passes():
    gate_fail = gate_result(False, new_codes=["structure_quality"])
    p_id = gate_fail.new_issues[0].issue_id
    obs_gate = {
        "origin": "program_gate", "step_id": "s1", "binding": binding(1).model_dump(mode="json"),
        "output_hash": None, "comparison_hash": h("cmp-1"), "parent_content_hash": None,
        "unchanged": False, "consecutive_unchanged": 0, "characters_added": 0, "characters_removed": 0,
        "gate": gate_fail.model_dump(mode="json"), "output": None, "coverage_rate": None, "decision": None,
    }
    ledger1 = ResourceLedgerV1.model_validate({
        "binding": binding(1).model_dump(mode="json"),
        "issues": [{"issue": gate_fail.new_issues[0].model_dump(mode="json"),
                    "introduced_step_id": "s1", "introduced_version": 1, "status": "open"}],
        "observations": [obs_gate],
    })
    assert ledger1.issues[0].status == "open"

    gate_pass = gate_result(True).model_copy(update={"resolved_program_issues": [p_id]})
    output = normalize(initial_output().model_copy(update={
        "issues": [],
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "hallucination_score": 0.0}), step_id="s2", version=2)
    obs_model = _model_observation(step_id="s2", version=2, output=output, gate=gate_pass, parent=ledger1)
    ledger2 = ResourceLedgerV1.model_validate({
        "binding": binding(2).model_dump(mode="json"),
        "issues": [{"issue": gate_fail.new_issues[0].model_dump(mode="json"),
                    "introduced_step_id": "s1", "introduced_version": 1, "status": "closed"}],
        "observations": [obs_gate, obs_model],
    })
    assert ledger2.issues[0].status == "closed"
