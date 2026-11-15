"""New review inputs retain complete current content and bounded issue history."""

import json

import pytest
from pydantic import ValidationError as SchemaError

from app.agents.resource_workflows.learning_documents.reviewing import ReviewCallCollector
from app.agents.resource_workflows.learning_documents.reviewing.executor import ReviewInputBudgetError
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import review_resource_v1
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.registry import output_schema
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.revision import build_revision_work_order
from app.core.llm.structured_output import StructuredOutputError, parse_structured_output
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash
from app.models.reviews.resource_review import ResourceLocationV1
from app.models.reviews.resource_review_model_output import MarkdownModelLocationV3
from app.models.shared.llm import LLMCallContext
from tests.fakes.llm import ScriptedLLMGateway
from tests.unit.agents.test_resource_issue_engine import _resource, _state, _policy, _approve_outcome, _run
from tests.unit.agents.test_resource_issue_closure_regressions import _issue
from tests.unit.agents.test_resource_type_agents import CASE_STUDY_MARKDOWN


def policy(**kwargs):
    return _policy().model_copy(update={"input_contract": "single_representation_v1", **kwargs})


def _v3_issue(location):
    issue = _issue(location=location).model_dump(mode="json")
    issue["location"] = location
    return issue


def test_legacy_policy_hash_and_prompt_remain_unchanged():
    old = _policy()
    assert "input_contract" not in old.model_dump(mode="json")
    assert policy_hash(old) == policy_hash(old.model_dump(mode="json"))
    _, old_gateway, _ = _run(policy=old)
    _, new_gateway, _ = _run(policy=policy())
    assert "single_representation_v1" not in old_gateway.calls[0]["messages"][0].content
    assert "single_representation_v1" in new_gateway.calls[0]["messages"][0].content
    with pytest.raises(SchemaError):
        ResourceReviewPolicyV1.model_validate({**old.model_dump(), "input_contract": "unknown"})


def test_initial_prose_has_one_current_content_and_no_parent():
    _, gateway, _ = _run(resource=_resource(content="唯一完整新版正文"), policy=policy())
    payload = json.loads(gateway.calls[0]["messages"][-1].content)
    assert payload["text"] == "唯一完整新版正文"
    assert "structured_payload" not in payload
    assert "previous_content" not in payload
    assert "parent_issue_context" not in payload


def test_v2_numbers_markdown_lines_and_server_fills_heading_path():
    resource = _resource(content="# 标题\n正文\n\n## 小节\n问题句")
    def review(kwargs):
        payload = json.loads(kwargs["messages"][-1].content)
        assert payload["input_contract"] == "single_representation_v2"
        assert payload["text"].splitlines()[4] == "p000005 | 问题句"
        assert "single_representation_v2" in kwargs["messages"][0].content
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_issue(location={"kind": "paragraph", "paragraph_id": "p000005",
                                         "heading_path": ["错误标题"], "quote": "问题句"}).model_dump(mode="json")]
        return out
    outcome, _, _ = _run(resource=resource, policy=policy(input_contract="single_representation_v2"), outcomes=[review])
    assert outcome.ledger is not None
    location = outcome.ledger.issues[0].issue.location
    assert location.paragraph_id == "p000005"
    assert location.heading_path == ["标题", "小节"]
    assert location.quote == "问题句"


@pytest.mark.parametrize("resource_type", ["讲义", "案例分析"])
def test_v3_accepts_contiguous_range_and_keeps_old_location_serialization(resource_type):
    if resource_type == "案例分析":
        content = CASE_STUDY_MARKDOWN.replace("团队需要根据冻结证据回答检索问题。", "第一行\n第二行")
        start_id, end_id = "p000005", "p000006"
        expected_path = ["受控检索案例分析", "案例背景"]
    else:
        content = "# 标题\n第一行\n第二行\n结尾"
        start_id, end_id = "p000002", "p000003"
        expected_path = ["标题"]
    resource = _resource(resource_type, content=content)
    def review(kwargs):
        payload = json.loads(kwargs["messages"][-1].content)
        assert payload["input_contract"] == "single_representation_v3"
        assert f"{end_id} | 第二行" in payload["text"].splitlines()
        assert "end_paragraph_id" in kwargs["messages"][0].content
        schema = kwargs["output_schema"].model_json_schema()
        assert "heading_path" not in json.dumps(schema)
        assert "heading_path" not in kwargs["messages"][0].content
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_v3_issue({"kind": "paragraph", "paragraph_id": start_id,
                                    "end_paragraph_id": end_id, "quote": "第一行\n第二行"})]
        return out
    outcome, _, _ = _run(resource=resource, policy=policy(input_contract="single_representation_v3"), outcomes=[review])
    assert outcome.ledger is not None
    location = outcome.ledger.issues[0].issue.location
    assert (location.paragraph_id, location.end_paragraph_id) == (start_id, end_id)
    assert location.heading_path == expected_path
    assert "end_paragraph_id" not in ResourceLocationV1(kind="paragraph", paragraph_id="p000002").model_dump(mode="json")


def test_v3_model_schema_rejects_even_empty_heading_placeholder():
    with pytest.raises(SchemaError):
        MarkdownModelLocationV3.model_validate({
            "kind": "paragraph", "paragraph_id": "p000001", "heading_path": [],
        })


def test_v3_schema_route_keeps_old_and_structured_review_contracts():
    assert output_schema("讲义", recheck=False, input_contract="single_representation_v3").__name__ == "MarkdownModelReviewInitialV3"
    assert output_schema("案例分析", recheck=True, input_contract="single_representation_v3").__name__ == "MarkdownModelReviewRecheckV3"
    assert output_schema("讲义", recheck=False, input_contract="single_representation_v2").__name__ == "ResourceReviewInitialV1"
    assert output_schema("复习清单", recheck=False, input_contract="single_representation_v3").__name__ == "ResourceReviewInitialV1"


@pytest.mark.parametrize("end_id, quote", [
    ("p000001", None), ("p000002", None), ("p999999", None),
    ("p000004", "不是原文"),
])
def test_v3_rejects_invalid_range_or_quote(end_id, quote):
    resource = _resource(content="第一行\n第二行\n第三行\n第四行")
    def review(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        loc = {"kind": "paragraph", "paragraph_id": "p000002", "end_paragraph_id": end_id}
        if quote is not None:
            loc["quote"] = quote
        out["issues"] = [_v3_issue(loc)]
        return out
    outcome, _, _ = _run(resource=resource, policy=policy(input_contract="single_representation_v3"), outcomes=[review])
    assert outcome.ledger is None
    assert outcome.stop_reason == "not_correctable:LOCATION_OUT_OF_BOUNDS"


def test_v2_cannot_introduce_v3_range():
    resource = _resource(content="第一行\n第二行")
    def review(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_issue(location={"kind": "paragraph", "paragraph_id": "p000001",
                                         "end_paragraph_id": "p000002"}).model_dump(mode="json")]
        return out
    outcome, _, _ = _run(resource=resource, policy=policy(input_contract="single_representation_v2"), outcomes=[review])
    assert outcome.ledger is None
    assert outcome.stop_reason == "not_correctable:LOCATION_OUT_OF_BOUNDS"


@pytest.mark.parametrize("input_contract", ["single_representation_v3", "single_representation_v4"])
def test_recheck_keeps_parent_range_and_new_range_separate(input_contract):
    parent = _resource(content="# 旧标题\n旧问题第一行\n旧问题第二行")
    p = policy(input_contract=input_contract)
    def first(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_v3_issue({"kind": "paragraph", "paragraph_id": "p000002",
                                    "end_paragraph_id": "p000003"})]
        if input_contract == "single_representation_v4":
            for field in ("origin", "criteria_version", "blocking_rule", "affected_target_ids"):
                out["issues"][0].pop(field)
        return out
    initial, _, _ = _run(resource=parent, policy=p, outcomes=[first])
    assert initial.ledger is not None
    ledger = initial.ledger
    child = parent.model_copy(update={"resource_id": "res-2", "parent_resource_id": parent.resource_id,
                                      "version": 2, "content_text": "新版第一行\n新版第二行"})
    state = _state(p, child)
    state["resource_ledgers"] = {"spec-1": ledger.model_dump(mode="json")}
    state["resource_revision"] = {"spec-1": build_revision_work_order(
        resource_spec_id="spec-1", resource=parent, previous=ledger,
        revision_kind="ordinary", targets=("目标一",)).as_dict()}
    def recheck(kwargs):
        data = json.loads(kwargs["messages"][-1].content)
        old = data["parent_issue_context"][0]
        assert old["location"]["end_paragraph_id"] == "p000003"
        assert "heading_path" not in old["location"]
        assert "heading_path" not in data["old_issues"][0]["issue"]["location"]
        assert old["excerpt"] == "旧问题第一行\n旧问题第二行"
        assert "旧标题" not in data["text"]
        out = _approve_outcome(kwargs)
        out["resolutions"] = [{"issue_id": ledger.issues[0].issue.issue_id,
                               "result": "fixed", "reason": "新版已修复。",
                               "previous_location": old["location"],
                               "current_location": {"kind": "paragraph", "paragraph_id": "p000001",
                                                    "end_paragraph_id": "p000002"}}]
        return out
    outcome = review_resource_v1(state=state, resource=child, evidence=[], step_id="step-2",
        context=LLMCallContext(run_id="run-1", step_id="step-2", node_name="reviewer",
                              schema_name="ResourceReviewRecheckV1", generation_attempt=2),
        gateway=ScriptedLLMGateway([recheck]), collector=ReviewCallCollector(),
        review_id="rev-2", step_guard=lambda **kw: None)
    assert outcome.ledger is not None
    assert outcome.ledger.issues[0].status == "closed"


def test_v4_only_coverage_issue_can_report_affected_targets():
    def review(kwargs):
        out = _approve_outcome(kwargs)
        issue = _v3_issue({"kind": "root"})
        for field in ("origin", "criteria_version", "blocking_rule"):
            issue.pop(field)
        issue["affected_target_ids"] = ["目标一"]
        out["issues"] = [issue]
        schema = kwargs["output_schema"]
        assert "binding" not in schema.model_fields
        with pytest.raises(StructuredOutputError) as exc:
            parse_structured_output(out, schema)
        assert exc.value.safe_detail == "issues.0.self_contained.affected_target_ids:extra_forbidden"
        issue.update(dimension="coverage", teaching_rule_id="target_coverage")
        out["targets"][0].update(status="missing", location=None)
        return out

    outcome, _, _ = _run(policy=policy(input_contract="single_representation_v4"), outcomes=[review])
    assert outcome.raw["decision"] == "revise"
    issue = outcome.ledger.issues[0].issue
    assert issue.affected_target_ids == ["目标一"]
    assert issue.blocking_rule == "model_coverage_v1"


def test_v4_result_from_another_call_is_not_bound_to_the_resource():
    def wrong_call(kwargs):
        gateway = ScriptedLLMGateway([_approve_outcome])
        return gateway.invoke_structured(**kwargs).model_copy(update={"call_id": "wrong-call"})

    outcome, _, _ = _run(policy=policy(input_contract="single_representation_v4"), outcomes=[wrong_call])
    assert outcome.ledger is None
    assert outcome.stop_reason == "not_correctable:BINDING_MISMATCH"
    assert outcome.repair.error_paths == ("call_id",)
    assert outcome.raw["issues"][0]["code"] == "other"


def test_v4_bounded_correction_gets_specific_field_without_reintroducing_binding():
    def incomplete(kwargs):
        out = _approve_outcome(kwargs)
        out["targets"] = [{**out["targets"][0], "target": "未冻结的目标"}]
        return out

    def correct(kwargs):
        payload = json.loads(kwargs["messages"][1].content)
        assert "binding" not in payload
        assert "binding" not in payload["previous_review_under_check"]
        assert payload["review_consistency_errors"][0]["code"] == "TARGET_SET_INCOMPLETE"
        assert kwargs["options"].max_attempts == 1
        return _approve_outcome(kwargs)

    outcome, gateway, _ = _run(policy=policy(input_contract="single_representation_v4"),
                               outcomes=[incomplete, correct])
    assert len(gateway.calls) == 2
    assert outcome.repair.corrected
    assert outcome.ledger.binding.evidence_context_id
    assert outcome.raw["decision"] == "approve"


@pytest.mark.parametrize("location", [
    {"kind": "paragraph", "paragraph_id": "p999999"},
    {"kind": "paragraph", "paragraph_id": "p000002", "quote": "别处的文字"},
])
def test_v2_still_rejects_unknown_id_or_wrong_quote(location):
    resource = _resource(content="# 标题\n正文")
    def review(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_issue(location=location).model_dump(mode="json")]
        return out
    outcome, _, _ = _run(resource=resource, policy=policy(input_contract="single_representation_v2"), outcomes=[review])
    assert outcome.ledger is None
    assert outcome.stop_reason == "not_correctable:LOCATION_OUT_OF_BOUNDS"


@pytest.mark.parametrize("result", ["fixed", "still_open", "unverifiable", "false_positive", "omitted", "bad_location", "unseen_parent"])
@pytest.mark.parametrize("input_contract", ["single_representation_v1", "single_representation_v2"])
def test_recheck_uses_stable_issue_context_and_validates_resolution(result, input_contract):
    parent = _resource(content="原问题片段\n" + "不应重复发送的旧版全文" * 200)
    p = policy(max_physical_attempts=1, input_contract=input_contract)
    def first(kwargs):
        out = _approve_outcome(kwargs)
        out["dimensions"]["self_contained"] = "fail"
        out["issues"] = [_issue(location={"kind": "paragraph", "paragraph_id": "p000001"}).model_dump(mode="json")]
        return out
    initial, _, _ = _run(resource=parent, policy=p, outcomes=[first])
    ledger = initial.ledger
    child = parent.model_copy(update={"resource_id": "res-2", "parent_resource_id": parent.resource_id,
                                      "version": 2, "content_text": "新版已提供完整解释。"})
    state = _state(p, child)
    state["resource_ledgers"] = {"spec-1": ledger.model_dump(mode="json")}
    state["resource_revision"] = {"spec-1": build_revision_work_order(
        resource_spec_id="spec-1", resource=parent, previous=ledger,
        revision_kind="ordinary", targets=("目标一",)).as_dict()}
    def recheck(kwargs):
        data = json.loads(kwargs["messages"][-1].content)
        assert "不应重复发送的旧版全文" not in kwargs["messages"][-1].content
        assert not ({"previous_content", "previous_structured_payload", "previous_location_index"} & data.keys())
        assert data["parent_issue_context"][0]["excerpt"] == "原问题片段"
        assert data["old_issues"][0]["issue"]["acceptance"] == "verify"
        out = _approve_outcome(kwargs)
        out["resolutions"] = [{"issue_id": ledger.issues[0].issue.issue_id,
                               "result": "false_positive" if result == "unseen_parent" else
                                         "fixed" if result in {"bad_location", "omitted"} else result,
                               "reason": "按原验收条件核对新版。",
                               "current_location": {"kind": "root"},
                               "previous_location": {"kind": "paragraph", "paragraph_id": "p000001"}}]
        if result in {"still_open", "unverifiable"}:
            out["dimensions"]["self_contained"] = "fail"
        if result == "omitted":
            out["resolutions"] = []
        elif result == "bad_location":
            out["resolutions"][0]["current_location"] = {"kind": "paragraph", "paragraph_id": "invented"}
        elif result == "unseen_parent":
            out["resolutions"][0]["previous_location"] = {"kind": "paragraph", "paragraph_id": "p000002"}
        return out
    outcome = review_resource_v1(state=state, resource=child, evidence=[], step_id="step-2",
        context=LLMCallContext(run_id="run-1", step_id="step-2", node_name="reviewer",
                              schema_name="ResourceReviewRecheckV1", generation_attempt=2),
        gateway=ScriptedLLMGateway([recheck]), collector=ReviewCallCollector(), review_id="rev-2", step_guard=lambda **kw: None)
    if result in {"omitted", "bad_location", "unseen_parent"}:
        assert outcome.ledger is None and outcome.raw["decision"] == "human_review"
        return
    assert outcome.ledger is not None
    assert outcome.ledger.issues[0].status == ("open" if result in {"still_open", "unverifiable"} else "closed")
    assert outcome.ledger.observations[-1].characters_removed > 0


def test_structured_correction_has_json_once_and_no_learning_status():
    from tests.unit.agents.test_structured_correction_package import package
    from app.core.learning_documents.correction_package import render_correction_markdown
    pack = package()
    resource = _resource("个性化纠错训练包", content=render_correction_markdown(pack),
                         knowledge_points=["embedding"], correction_package_payload=pack.model_dump(mode="json"),
                         correction_package_payload_hash=pack.payload_hash)
    s = _state(policy(), resource); s["resource_specs"][0]["knowledge_points"] = ["embedding"]
    g = ScriptedLLMGateway([_approve_outcome])
    outcome = review_resource_v1(state=s, resource=resource, evidence=[], step_id="step-1",
        context=LLMCallContext(run_id="run-1", step_id="step-1", node_name="reviewer", schema_name="ResourceReviewInitialV1"),
        gateway=g, collector=ReviewCallCollector(), review_id="rev-1", step_guard=lambda **kw: None)
    payload = json.loads(g.calls[0]["messages"][-1].content)
    assert outcome.raw["decision"] == "approve"
    assert "text" not in payload and "paragraph_ids" not in payload["location_index"]
    assert payload["structured_payload"]["content"] == pack.content.model_dump(mode="json")
    assert "concept_application" not in g.calls[0]["messages"][-1].content


def test_budget_failure_has_quantities_and_zero_gateway_calls():
    p = policy(context_tokens=16400)
    gateway = ScriptedLLMGateway([])
    resource = _resource()
    with pytest.raises(ReviewInputBudgetError) as exc:
        review_resource_v1(state=_state(p, resource), resource=resource, evidence=[], step_id="step-1",
            context=LLMCallContext(run_id="run-1", step_id="step-1", node_name="reviewer", schema_name="ResourceReviewInitialV1"),
            gateway=gateway, collector=ReviewCallCollector(), review_id="rev-1")
    detail = json.loads(exc.value.safe_detail())
    assert detail["context_limit"] == 16400 and detail["reserved_output_tokens"] == 16384
    assert detail["exceeded_tokens"] > 0 and not gateway.calls


@pytest.mark.parametrize("cause,code", [("budget", "REVIEW_INPUT_BUDGET_EXCEEDED"),
                                        ("binding", "WORKFLOW_CONTRACT_INVALID")])
def test_reviewer_classifies_local_failure_without_claiming_model_output_error(cause, code, monkeypatch):
    from app.agents.resource_workflows.learning_documents import reviewer_agent
    from app.agents.resource_workflows.learning_documents.workflow import decide_node
    # Evidence routing has its own integration coverage; isolate the real
    # reviewer -> engine -> fail-closed -> finalization error boundary here.
    monkeypatch.setattr(reviewer_agent, "resolve_review_evidence_context", lambda *_: [])
    monkeypatch.setattr(reviewer_agent, "source_refs_are_scoped", lambda *_: True)
    state = _state(policy(context_tokens=16400) if cause == "budget" else policy(), _resource())
    state.update(trace=[], errors=[], generation_attempt=1)
    if cause == "binding":
        state["resource_specs"][0]["resource_family_id"] = "wrong-parent-family"
    gateway = ScriptedLLMGateway([])
    result = reviewer_agent.review_node(state, llm_gateway=gateway)
    assert result["errors"][0]["code"] == code
    assert result["generated_resources"][0].publication_status == "unpublished"
    assert result["review_result"]["decision"] == "human_review" and not gateway.calls
    if cause == "budget":
        assert json.loads(result["errors"][0]["safe_detail"])["exceeded_tokens"] > 0
        finalized = decide_node({**state, **result})
        assert "上下文预算" in finalized["final_decision"]
        assert "额度已用尽" not in finalized["final_decision"]
