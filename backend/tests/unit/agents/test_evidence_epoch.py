"""Evidence-epoch carry-over: immutable predecessor, explicit transition, stop counter.

These are engine/contract tests, not DTO tests: each case runs the production
review engine over two or three real versions, with a scripted gateway only for
the external model answer.
"""

import json
from datetime import datetime, timezone

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import review_resource_v1
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.models.reviews.evidence_context import (
    EvidenceContextCarryOverV1,
    context_id,
    validate_context_transition,
)
from app.models.reviews.lecture_review import LectureLedgerV1
from app.models.reviews.lecture_review_v2 import LectureLedgerV2
from app.models.reviews.resource_review import ResourceLedgerV1
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import canonical_hash
from tests.fakes.llm import ScriptedLLMGateway

from tests.unit.agents.test_lecture_review_engine import (
    invoke as invoke_v1,
    lecture_state as lecture_state_v1,
    response as response_v1,
)
from tests.unit.agents.test_lecture_review_v2_engine import (
    CONTENT,
    builder,
    covered,
    coverage_issue,
    invoke,
    lecture_state,
    location,
    output_for,
)
from tests.unit.agents.test_resource_issue_engine import _policy, _resource, _state

REVISED = CONTENT + "\n\n## 补充\n当 k=60 时，融合分也可以按倒数名次相加估算。"


def _extra_evidence(state):
    base = state["retrieved_evidence"][0]
    return base.model_copy(update={
        "evidence_id": "ev-epoch-extra",
        "chunk_id": "chunk-epoch-extra",
        "excerpt": "补充冻结摘录：融合分可用倒数名次相加估算。",
        "excerpt_hash": "e" * 64,
        "query": "补充查询",
        "query_hash": "f" * 64,
        "query_rank": 9,
        "rank": 9,
    })


def _resolve(issue_id, *, content, result="fixed"):
    return {
        "issue_id": issue_id,
        "result": result,
        "reason": "已按原验收条件补齐推导",
        "current_location": location(content, "p000002"),
        "previous_location": location(CONTENT, "p000002"),
        "evidence_refs": [],
    }


def _lecture_v2_epoch_state(*, attempts=3):
    state, resource = lecture_state(attempts=attempts)
    first = ScriptedLLMGateway([builder(missing=True, issue=True)])
    outcome, _ = invoke(state, resource, first)
    parent = outcome.ledger
    assert parent is not None and parent.issues
    parent_dump = parent.model_dump(mode="json")
    open_id = next(item.issue.issue_id for item in parent.issues if item.status == "open")
    state["lecture_ledgers"] = {resource.resource_spec_id: parent_dump}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": CONTENT}}
    state["retrieved_evidence"] = [*state["retrieved_evidence"], _extra_evidence(state)]
    revised = resource.model_copy(update={
        "version": 2, "resource_id": "res-2",
        "parent_resource_id": resource.resource_id, "content_text": REVISED})
    return state, revised, parent, parent_dump, open_id


def _fixed_answer(open_id):
    def answer(call):
        payload = json.loads(call["messages"][1].content)
        rows = [covered(item, REVISED) for item in payload["targets"]]
        return output_for(payload["binding"], rows,
                          resolutions=[_resolve(open_id, content=REVISED)])
    return answer


def _epoch_ledger(state, revised, open_id):
    second, _ = invoke(state, revised, ScriptedLLMGateway([_fixed_answer(open_id)]), step="review-2")
    assert second.ledger is not None
    return second.ledger


def test_lecture_v2_evidence_change_creates_an_audited_epoch():
    state, revised, parent, parent_dump, open_id = _lecture_v2_epoch_state()
    ledger = _epoch_ledger(state, revised, open_id)

    # The new epoch is bound to the predecessor and to its own frozen context.
    assert ledger.carry_over is not None
    assert ledger.carry_over.previous_ledger_hash == canonical_hash(parent_dump)
    assert ledger.carry_over.previous_context_id == parent.binding.evidence_context_id
    assert ledger.binding.parent_evidence_context_hash == parent.binding.evidence_context_id
    assert ledger.binding.evidence_context_id != parent.binding.evidence_context_id
    assert ledger.binding.evidence_context_id == context_id(ledger.binding)
    validate_context_transition(parent.binding, ledger.binding)
    # The carried issue keeps its original definition and is resolved once.
    assert [item.issue for item in ledger.issues] == [item.issue for item in parent.issues]
    assert ledger.issues[0].status == "closed"
    assert ledger.issues[0].introduced_step_id == parent.issues[0].introduced_step_id
    assert len(ledger.observations) == 1 and ledger.observations[-1].decision == "approve"
    # The predecessor ledger itself is never rewritten.
    assert parent.model_dump(mode="json") == parent_dump


def test_lecture_v2_epoch_rejects_missing_and_forged_resolutions():
    for mode in ("missing", "forged"):
        state, revised, _parent, _dump, open_id = _lecture_v2_epoch_state(attempts=1)

        def answer(call, mode=mode, open_id=open_id):
            payload = json.loads(call["messages"][1].content)
            rows = [covered(item, REVISED) for item in payload["targets"]]
            resolutions = ([] if mode == "missing"
                           else [_resolve("li2_" + "0" * 64, content=REVISED)])
            return output_for(payload["binding"], rows, resolutions=resolutions)

        outcome, _ = invoke(state, revised, ScriptedLLMGateway([answer]), step="review-2")
        assert outcome.ledger is None
        assert outcome.repair.error_codes == ("RESOLUTION_SET_INCOMPLETE",)
        # The code is correctable, but the frozen single attempt is already spent.
        assert outcome.stop_reason == "no_physical_attempt_left"


def test_lecture_v2_carried_stop_counter_is_not_reset_by_a_new_context():
    state, resource = lecture_state(attempts=3)
    first, _ = invoke(state, resource, ScriptedLLMGateway([builder(missing=True, issue=True)]))
    parent = first.ledger
    open_id = next(item.issue.issue_id for item in parent.issues if item.status == "open")
    state["lecture_ledgers"] = {resource.resource_spec_id: parent.model_dump(mode="json")}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": CONTENT}}
    same = resource.model_copy(update={"version": 2, "resource_id": "res-2",
                                       "parent_resource_id": resource.resource_id})

    def still_open(call):
        payload = json.loads(call["messages"][1].content)
        rows = [covered(item, CONTENT) for item in payload["targets"]]
        return output_for(payload["binding"], rows,
                          resolutions=[_resolve(open_id, content=CONTENT, result="still_open")])

    second, _ = invoke(state, same, ScriptedLLMGateway([still_open]), step="review-2")
    assert second.ledger is not None
    assert second.ledger.observations[-1].unchanged is True
    assert second.ledger.observations[-1].consecutive_unchanged == 1
    assert second.ledger.observations[-1].decision == "revise"

    # A third version with new evidence must continue at 1, not restart at 0.
    state["lecture_ledgers"] = {resource.resource_spec_id: second.ledger.model_dump(mode="json")}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": CONTENT}}
    state["retrieved_evidence"] = [*state["retrieved_evidence"], _extra_evidence(state)]
    third_resource = same.model_copy(update={"version": 3, "resource_id": "res-3",
                                              "parent_resource_id": "res-2"})
    third, _ = invoke(state, third_resource, ScriptedLLMGateway([still_open]), step="review-3")
    ledger = third.ledger
    assert ledger is not None and ledger.carry_over is not None
    assert ledger.carry_over.consecutive_unchanged == 1
    assert ledger.observations[-1].consecutive_unchanged == 2
    assert ledger.observations[-1].decision == "human_review"
    assert third.stop_reason == "revision_no_progress"


def test_rewritten_acceptance_in_a_carry_over_is_rejected():
    state, revised, _parent, _dump, open_id = _lecture_v2_epoch_state()
    dump = _epoch_ledger(state, revised, open_id).model_dump(mode="json")
    dump = json.loads(json.dumps(dump))
    dump["carry_over"]["open_issues"][0]["issue"]["acceptance"] = "只要提到名词即可"
    dump["carry_over"]["open_issue_hash"] = canonical_hash(
        {"open_issues": dump["carry_over"]["open_issues"]})
    with pytest.raises(ValueError, match="carried issue definitions"):
        LectureLedgerV2.model_validate(dump)


def test_lecture_v1_evidence_epoch_carries_the_open_issue():
    state, resource = lecture_state_v1()
    (raw, parent, _, _), _ = invoke_v1(
        state, resource, ScriptedLLMGateway([lambda call: response_v1(call, blocking=True)]))
    assert raw["decision"] == "revise"
    parent_dump = parent.model_dump(mode="json")
    open_id = parent.issues[0].issue.issue_id
    state["lecture_ledgers"] = {resource.resource_spec_id: parent_dump}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": resource.content_text}}
    state["retrieved_evidence"] = [*state["retrieved_evidence"], _extra_evidence(state)]
    revised_content = resource.content_text + "\n补充：两路名次均已列出。"
    revised = resource.model_copy(update={"version": 2, "resource_id": "version2",
                                          "parent_resource_id": resource.resource_id,
                                          "content_text": revised_content})

    def fixed(call):
        return response_v1(call, resolutions=[{
            "issue_id": open_id, "result": "fixed", "reason": "已补齐两路名次",
            "current_location": {"paragraph_id": "p000001", "quote": "题目"},
            "previous_location": {"paragraph_id": "p000001", "quote": "题目"},
            "evidence_refs": []}])

    (raw, ledger, _, _), _ = invoke_v1(state, revised, ScriptedLLMGateway([fixed]), step="review-2")
    assert isinstance(ledger, LectureLedgerV1)
    assert ledger.carry_over is not None
    assert ledger.carry_over.previous_ledger_hash == canonical_hash(parent_dump)
    assert ledger.binding.parent_evidence_context_hash == parent.binding.evidence_context_id
    assert ledger.issues[0].status == "closed" and raw["decision"] == "approve"
    assert parent.model_dump(mode="json") == parent_dump


def _resource_evidence():
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import text_hash
    from app.models.knowledge.knowledge import EvidenceItem, ScoreKind, SourceLocator, SourceType

    def one(ident, excerpt, *, rank=1):
        return EvidenceItem(
            evidence_id=ident, knowledge_base_id="kb-1", document_id="doc-1",
            document_version="v1", chunk_id=f"chunk-{ident}", query="目标一",
            query_hash="a" * 64, query_rank=rank, rank=rank, raw_score=0.9,
            score_kind=ScoreKind.SIMILARITY, normalized_score=0.8, excerpt=excerpt,
            excerpt_hash=text_hash(excerpt),
            locator=SourceLocator(
                knowledge_base_id="kb-1", document_id="doc-1", document_version="v1",
                chunk_id=f"chunk-{ident}", source_type=SourceType.MARKDOWN,
                source_path="docs/a.md", title="a.md", section="1"),
            config_hash="c" * 64,
            retrieved_at=datetime(2026, 11, 8, tzinfo=timezone.utc))

    return [one("ev-base", "目标一的讲解。"), one("ev-extra", "目标一的补充讲解。", rank=2)]


def _resource_issue():
    return {
        "issue_id": "tmp-1", "origin": "model_review", "code": "coverage_gap",
        "severity": "high", "blocking": True, "blocking_rule": "target_coverage",
        "dimension": "coverage", "affected_target_ids": ["目标一"],
        "location": {"kind": "root"}, "impact": "读者学不到目标一",
        "requirement": "补充目标一的讲解", "acceptance": "正文出现目标一的讲解与例子",
        "criteria_version": 1, "path": "reorganize_existing",
        "teaching_rule_id": "target_coverage", "executability": "executable",
        "rationale": "可整理已有材料",
    }


def _resource_run(resource, state, *, evidence, outcomes, step):
    gateway = ScriptedLLMGateway(outcomes)
    collector = ReviewCallCollector()
    context = LLMCallContext(run_id="run-1", step_id=step, node_name="reviewer",
                             schema_name="ResourceReviewInitialV1", generation_attempt=1)
    outcome = review_resource_v1(
        state=state, resource=resource, evidence=evidence, step_id=step, context=context,
        gateway=gateway, collector=collector, review_id=f"rev-{step}",
        step_guard=lambda **kw: None)
    return outcome, gateway


def test_resource_evidence_epoch_resolves_the_carried_model_issue():
    policy = _policy()
    resource = _resource()
    evidence = _resource_evidence()

    def revise(call):
        payload = json.loads(call["messages"][1].content)
        return {
            "binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": [{"target": t, "status": "missing" if t == "目标一" else "covered",
                         "reason": "仍缺讲解"} for t in payload["targets"]],
            "hallucination_score": 0.0, "issues": [_resource_issue()],
            "omitted_blocking_issues": False,
        }

    first, _ = _resource_run(resource, _state(policy, resource), evidence=evidence[:1],
                             outcomes=[revise], step="step-1")
    parent = first.ledger
    assert isinstance(parent, ResourceLedgerV1) and parent.issues
    parent_dump = parent.model_dump(mode="json")
    open_id = next(item.issue.issue_id for item in parent.issues if item.status == "open")

    child = resource.model_copy(update={
        "version": 2, "resource_id": "res-2", "parent_resource_id": "res-1",
        "content_text": resource.content_text + "\n目标一的补充讲解。"})
    state = _state(policy, child)
    state["resource_ledgers"] = {"spec-1": parent_dump}
    state["resource_revision"] = {"spec-1": {"previous_text": resource.content_text}}

    def fixed(call):
        payload = json.loads(call["messages"][1].content)
        return {
            "binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": [{"target": t, "status": "covered", "reason": "已讲解",
                         "location": {"kind": "root"}} for t in payload["targets"]],
            "hallucination_score": 0.0, "issues": [],
            "resolutions": [{"issue_id": open_id, "result": "fixed", "reason": "已补齐",
                             "current_location": {"kind": "root"}}],
            "omitted_blocking_issues": False,
        }

    second, _ = _resource_run(child, state, evidence=evidence, outcomes=[fixed], step="step-2")
    ledger = second.ledger
    assert ledger is not None and ledger.carry_over is not None
    assert ledger.carry_over.previous_ledger_hash == canonical_hash(parent_dump)
    assert ledger.binding.parent_evidence_context_hash == parent.binding.evidence_context_id
    assert ledger.issues[0].status == "closed"
    assert ledger.observations[-1].decision == "approve"
    assert parent.model_dump(mode="json") == parent_dump


def test_closed_issue_is_reviewed_again_when_evidence_changes():
    state, revised, _parent, _dump, open_id = _lecture_v2_epoch_state()
    closed = _epoch_ledger(state, revised, open_id)
    assert closed.issues[0].status == "closed"
    frozen = closed.model_dump(mode="json")
    state["lecture_ledgers"] = {revised.resource_spec_id: frozen}
    state["lecture_revision"] = {revised.resource_spec_id: {"previous_content": REVISED}}
    extra = _extra_evidence(state).model_copy(update={"evidence_id": "ev-third-context",
                                                    "chunk_id": "chunk-third-context"})
    state["retrieved_evidence"] = [*state["retrieved_evidence"], extra]
    third = revised.model_copy(update={"version": 3, "resource_id": "res-3",
                                       "parent_resource_id": revised.resource_id})
    gateway = ScriptedLLMGateway([builder(missing=True, issue=True)])
    outcome, _ = invoke(state, third, gateway, step="review-3")
    ledger = outcome.ledger
    assert ledger is not None
    assert len(gateway.calls) == 1  # a new full review, never inherited approval
    assert ledger.carry_over.previous_ledger_hash == canonical_hash(frozen)
    assert ledger.carry_over.open_issues == []
    assert ledger.observations[-1].decision == "revise"
    assert any(item.status == "open" and item.introduced_version == 3 for item in ledger.issues)
    assert closed.model_dump(mode="json") == frozen
