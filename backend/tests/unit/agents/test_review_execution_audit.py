from datetime import datetime, timedelta, timezone

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import LLMCallOptions, RawLLMResponse
from tests.fakes.llm import ScriptedLLMGateway, ScriptedLLMTransport
from tests.fakes.resource_reviews import approve, case, scope_output, state_for


def test_two_stage_usage_sums_logical_calls_without_double_counting_attempts():
    sample = case("assessment.clean.01")
    gateway = ScriptedLLMGateway([scope_output(sample), approve()])
    result = review_node(state_for(sample), llm_gateway=gateway)
    audit = result["review_audit"]
    assert audit["summary"]["logical_call_count"] == audit["summary"]["gateway_attempt_count"] == 2
    assert audit["summary"]["usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    assert result["trace"][0]["llm_call_id"] == audit["calls"][-1]["call_id"]
    assert result["trace"][0]["total_tokens"] == 15
    assert "review_audit" not in result["trace"][0].get("output_payload", {})


def test_post_validation_failure_still_records_completed_scope_call():
    sample = case("assessment.clean.01")
    raw = scope_output(sample)
    raw["findings"].pop()
    gateway = ScriptedLLMGateway([raw])
    result = review_node(state_for(sample), llm_gateway=gateway)
    assert result["review_result"]["decision"] == "human_review"
    assert len(gateway.calls) == 1
    assert result["review_audit"]["calls"][0]["status"] == "invalid_result"
    assert result["review_audit"]["summary"]["usage"]["total_tokens"] == 15
    assert result["errors"][0]["source"] == "assessment_scope_reviewer"
    assert result["errors"][0]["category"] == "assessment_scope"


def test_deadline_is_one_logical_call_with_zero_transport_and_unknown_usage():
    state = state_for()
    state["workflow_deadline_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    transport = ScriptedLLMTransport([])
    result = review_node(state, llm_gateway=LLMGateway(transport))
    summary = result["review_audit"]["summary"]
    assert transport.calls == []
    assert summary["logical_call_count"] == 1 and summary["gateway_attempt_count"] == 0
    assert summary["usage"]["total_tokens"] is None
    assert summary["known_usage"]["total_tokens"] == 0
    assert summary["usage_complete"]["total_tokens"] is False


def test_unknown_usage_does_not_become_zero():
    gateway = LLMGateway(ScriptedLLMTransport([RawLLMResponse(content=approve())]),
                         default_options=LLMCallOptions(max_attempts=1, structured_output_mode="text"))
    result = review_node(state_for(), llm_gateway=gateway)
    assert result["review_audit"]["summary"]["usage"]["input_tokens"] is None


def test_empty_compatibility_call_remains_a_contract_error():
    gateway = ScriptedLLMGateway([approve()])
    result = review_node({"run_id": "empty", "generated_resources": []}, llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert result["review_result"]["decision"] == "human_review"
    assert result["errors"][0]["code"] == "WORKFLOW_CONTRACT_INVALID"
    assert result["review_audit"]["calls"][0]["resource_id"] is None


def test_multiple_resources_keep_distinct_call_and_review_ownership():
    state = state_for()
    first = state["generated_resources"][0]
    state["generated_resources"].append(first.model_copy(update={"resource_id": "second-resource"}))
    result = review_node(state, llm_gateway=ScriptedLLMGateway([approve(), approve()]))
    assert result["review_audit"]["summary"]["logical_call_count"] == 2
    assert len({c["review_id"] for c in result["review_audit"]["calls"]}) == 2


def test_schema_repair_attempts_and_usage_are_not_double_counted():
    from app.models.shared.llm import LLMUsage
    transport = ScriptedLLMTransport([
        RawLLMResponse(content={}, usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)),
        RawLLMResponse(content=approve(), usage=LLMUsage(input_tokens=20, output_tokens=10, total_tokens=30)),
    ])
    gateway = LLMGateway(transport, default_options=LLMCallOptions(max_attempts=2, structured_output_mode="text"), sleep=lambda _: None)
    summary = review_node(state_for(), llm_gateway=gateway)["review_audit"]["summary"]
    assert summary["logical_call_count"] == 1 and summary["gateway_attempt_count"] == 2
    assert summary["retry_count"] == 1
    assert summary["usage"]["total_tokens"] == 45


def test_legacy_scope_rejection_preserves_summary_and_skips_package_call():
    sample = case("assessment.clean.01")
    output = scope_output(sample)
    output["findings"][0].update(decision="out_of_scope", supported_evidence_ids=[])
    gateway = ScriptedLLMGateway([output])
    result = review_node(state_for(sample), llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert result["review_result"]["decision"] == "revise"
    assert result["review_result"]["coverage_rate"] == 0.0
    assert result["review_result"]["hallucination_score"] == 0.0
    assert result["review_result"]["difficulty_match"] is True
