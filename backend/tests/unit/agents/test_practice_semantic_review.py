import pytest

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import LLMCallOptions
from app.models.shared.llm import RawLLMResponse
from app.core.security.errors import ApplicationError
from tests.fakes.llm import ScriptedLLMGateway, ScriptedLLMTransport
from tests.fakes.resource_reviews import approve, case, state_for


@pytest.mark.parametrize("case_id,code", [("practice.clean.01", True), ("practice.clean.07", False)])
def test_structure_success_requires_one_semantic_call(case_id, code):
    gateway = ScriptedLLMGateway([approve()])
    result = review_node(state_for(case(case_id)), llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["options"].max_output_tokens == 12288
    assert ("审核实操 code_blocks" in gateway.calls[0]["messages"][0].content) is code
    audit = result["review_audit"]["resources"][0]
    assert audit["structure_status"] == audit["semantic_status"] == "passed"
    assert audit["execution_status"] == "not_run"
    assert result["generated_resources"][0].publication_status == "published"


@pytest.mark.parametrize("defect", ["sequence", "fact", "verification", "preparation"])
def test_semantic_failure_cannot_be_overridden_by_structure(defect):
    raw = approve()
    raw.update(decision="revise", issues=[{"code": "procedure_error", "severity": "high", "description": "step-1 缺陷定位。"}],
        revision_instructions=[{"issue_codes": ["procedure_error"], "target_resource_type": "实操指南", "action": "修正 step-1。"}])
    gateway = ScriptedLLMGateway([raw])
    result = review_node(state_for(case(f"practice.bad.{defect}.01")), llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert result["review_result"]["decision"] == "revise"
    assert result["review_audit"]["resources"][0]["semantic_status"] == "failed"
    assert result["generated_resources"][0].publication_status == "unpublished"


@pytest.mark.parametrize("locked", [False, True])
def test_locked_and_structure_failure_never_call_model(locked):
    state = state_for()
    resource = state["generated_resources"][0]
    state["generated_resources"] = [resource.model_copy(update={"review_status": "human_review"} if locked else {"practice_guide_payload": None})]
    gateway = ScriptedLLMGateway([])
    result = review_node(state, llm_gateway=gateway)
    assert gateway.calls == []
    assert result["review_audit"]["summary"]["logical_call_count"] == 0
    assert result["review_audit"]["resources"][0]["semantic_status"] == "not_run"
    assert result["generated_resources"][0].publication_status == "unpublished"


def test_gateway_failure_stays_unavailable_and_unpublished():
    transport = ScriptedLLMTransport([RuntimeError("provider unavailable")])
    gateway = LLMGateway(transport, default_options=LLMCallOptions(max_attempts=1))
    result = review_node(state_for(), llm_gateway=gateway)
    assert result["review_result"]["decision"] == "human_review"
    assert result["review_audit"]["resources"][0]["semantic_status"] == "unavailable"
    assert result["review_audit"]["summary"]["gateway_attempt_count"] == 1
    assert result["generated_resources"][0].publication_status == "unpublished"


def test_invalid_model_schema_is_a_controlled_failed_call():
    transport = ScriptedLLMTransport([RawLLMResponse(content={})])
    result = review_node(state_for(), llm_gateway=LLMGateway(transport, default_options=LLMCallOptions(max_attempts=1, structured_output_mode="text")))
    assert len(transport.calls) == 1
    assert result["review_audit"]["calls"][0]["status"] == "error"
    assert result["generated_resources"][0].publication_status == "unpublished"


def test_payload_evidence_contract_error_still_propagates_before_model_call():
    state = state_for()
    state["generated_resources"][0].practice_guide_payload["preparation"]["evidence_ids"] = ["outside-frozen-evidence"]
    gateway = ScriptedLLMGateway([])
    with pytest.raises(ApplicationError):
        review_node(state, llm_gateway=gateway)
    assert gateway.calls == []
