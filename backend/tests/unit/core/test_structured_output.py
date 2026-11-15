import pytest
from pydantic import BaseModel, ConfigDict, RootModel

from app.core.security.errors import ErrorCode
from app.core.llm.structured_output import StructuredOutputError, parse_structured_output
from app.models.reviews.resource_review import ResourceIssueV1


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    score: float


class PayloadList(RootModel[list[Payload]]):
    pass


@pytest.mark.parametrize(
    "raw",
    [
        '{"name":"alpha","score":0.8}',
        '```json\n{"name":"alpha","score":0.8}\n```',
        '说明如下：\n{"name":"alpha","score":0.8}\n请查收。',
    ],
)
def test_parser_accepts_plain_fenced_and_explained_json(raw):
    result = parse_structured_output(raw, Payload)
    assert result == Payload(name="alpha", score=0.8)


def test_parser_extracts_balanced_json_without_confusing_quoted_braces():
    raw = 'result: {"name":"value with {braces} and \\"quote\\"","score":0.8} end'
    result = parse_structured_output(raw, Payload)
    assert result.name == 'value with {braces} and "quote"'


def test_parser_accepts_preparsed_model_and_dict():
    model = Payload(name="alpha", score=0.8)
    assert parse_structured_output(model, Payload) is model
    assert parse_structured_output({"name": "alpha", "score": 0.8}, Payload) == model


def test_parser_ignores_harmless_top_level_extra_fields():
    result = parse_structured_output(
        {"name": "alpha", "score": 0.8, "provider_metadata": "ignored"},
        Payload,
    )
    assert result == Payload(name="alpha", score=0.8)


def test_parser_supports_array_root_schema():
    result = parse_structured_output(
        '[{"name":"alpha","score":0.8}]',
        PayloadList,
    )
    assert result.root == [Payload(name="alpha", score=0.8)]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", ErrorCode.LLM_OUTPUT_EMPTY),
        ("   ", ErrorCode.LLM_OUTPUT_EMPTY),
        ('{"name":"alpha"', ErrorCode.LLM_OUTPUT_TRUNCATED),
        ("not json", ErrorCode.LLM_OUTPUT_PARSE_FAILED),
        ('{"name":"a","score":0.1} {"name":"b","score":0.2}', ErrorCode.LLM_OUTPUT_PARSE_FAILED),
            ('{"name":"alpha"}', ErrorCode.LLM_OUTPUT_SCHEMA_INVALID),
        ],
)
def test_parser_returns_stable_error_codes(raw, code):
    with pytest.raises(StructuredOutputError) as caught:
        parse_structured_output(raw, Payload)
    assert caught.value.code == code
    if raw.strip():
        assert raw not in str(caught.value)


def test_finish_reason_length_is_classified_as_truncated():
    with pytest.raises(StructuredOutputError) as caught:
        parse_structured_output("incomplete", Payload, finish_reason="length")
    assert caught.value.code == ErrorCode.LLM_OUTPUT_TRUNCATED


def test_schema_error_safe_detail_does_not_contain_input_value():
    secret = "sensitive-value"
    with pytest.raises(StructuredOutputError) as caught:
        parse_structured_output({"name": secret, "score": "wrong"}, Payload)
    assert caught.value.code == ErrorCode.LLM_OUTPUT_SCHEMA_INVALID
    assert secret not in (caught.value.safe_detail or "")


class IssuePayload(BaseModel):
    issues: list[ResourceIssueV1]


def test_resource_issue_cross_field_error_has_safe_rule_code():
    issue = {
        "issue_id": "temporary-1", "code": "TEST", "severity": "high",
        "blocking": False, "dimension": "self_contained",
        "location": {"kind": "root"}, "impact": "sensitive-content",
        "requirement": "fix", "acceptance": "checked", "criteria_version": 1,
        "path": "reorganize_existing", "teaching_rule_id": "known-rule",
        "executability": "executable", "rationale": "reason",
    }
    with pytest.raises(StructuredOutputError) as caught:
        parse_structured_output({"issues": [issue]}, IssuePayload)
    assert caught.value.safe_detail == "issues.0:value_error:high_severity_must_block"
    assert "sensitive-content" not in caught.value.safe_detail

    issue.update(severity="medium", blocking=True)
    with pytest.raises(StructuredOutputError) as caught:
        parse_structured_output({"issues": [issue]}, IssuePayload)
    assert caught.value.safe_detail == "issues.0:value_error:blocking_rule_missing"
