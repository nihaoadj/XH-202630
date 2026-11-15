"""Safe extraction and strict validation of structured LLM output."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.security.errors import ErrorCode


T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """A sanitized parser failure with a stable public error code."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        retryable: bool = True,
        safe_detail: str | None = None,
    ):
        self.code = code
        self.retryable = retryable
        self.safe_detail = safe_detail
        super().__init__(code.value)


def _strip_complete_code_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) < 3 or not lines[0].strip().startswith("```"):
        return text.strip()
    if lines[-1].strip() != "```":
        return text.strip()
    return "\n".join(lines[1:-1]).strip()


def _json_candidates(text: str) -> tuple[list[str], bool]:
    """Find balanced top-level JSON values while respecting quoted strings."""

    candidates: list[str] = []
    start: int | None = None
    stack: list[str] = []
    in_string = False
    escaped = False
    saw_unclosed = False

    for index, char in enumerate(text):
        if start is None:
            if char in "[{":
                start = index
                stack = [char]
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char in "[{":
            stack.append(char)
            continue
        if char not in "]}":
            continue

        expected = "[" if char == "]" else "{"
        if not stack or stack[-1] != expected:
            start = None
            stack = []
            continue
        stack.pop()
        if not stack:
            candidates.append(text[start : index + 1])
            start = None

    if start is not None and stack:
        saw_unclosed = True
    return candidates, saw_unclosed


def _load_json_text(text: str, *, finish_reason: str | None = None) -> Any:
    normalized = _strip_complete_code_fence(text)
    if not normalized:
        raise StructuredOutputError(ErrorCode.LLM_OUTPUT_EMPTY)

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass

    candidates, saw_unclosed = _json_candidates(normalized)
    valid_values: list[Any] = []
    for candidate in candidates:
        try:
            valid_values.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue

    if len(valid_values) == 1:
        return valid_values[0]
    if len(valid_values) > 1:
        raise StructuredOutputError(
            ErrorCode.LLM_OUTPUT_PARSE_FAILED,
            safe_detail="multiple_json_values",
        )
    if finish_reason == "length" or saw_unclosed:
        raise StructuredOutputError(ErrorCode.LLM_OUTPUT_TRUNCATED)
    raise StructuredOutputError(ErrorCode.LLM_OUTPUT_PARSE_FAILED)


def parse_structured_output(
    value: Any,
    output_schema: type[T],
    *,
    finish_reason: str | None = None,
) -> T:
    """Parse text/dict/model output and validate it against one strict DTO."""

    if isinstance(value, output_schema):
        return value
    if isinstance(value, str):
        value = _load_json_text(value, finish_reason=finish_reason)
    elif value is None:
        raise StructuredOutputError(ErrorCode.LLM_OUTPUT_EMPTY)

    try:
        return output_schema.model_validate(value)
    except ValidationError as exc:
        # OpenAI-compatible JSON mode models occasionally add harmless
        # top-level metadata (for example a title or source identifier) even
        # when asked for an exact schema.  Keep the contract strict for every
        # required field and value, but safely ignore *only* extra top-level
        # fields so that an otherwise valid learning resource is not discarded.
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        if (
            isinstance(value, dict)
            and errors
            and all(item.get("type") == "extra_forbidden" and len(item.get("loc", ())) == 1
                    for item in errors)
        ):
            allowed = set(output_schema.model_fields)
            try:
                return output_schema.model_validate(
                    {key: item for key, item in value.items() if key in allowed}
                )
            except ValidationError as repaired:
                exc = repaired
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "root"
        detail = f"{location}:{first.get('type', 'validation_error')}"
        # ResourceIssueV1's cross-field validators use fixed messages. Expose
        # only a known rule code: arbitrary Pydantic messages can echo input.
        issue_rule_codes = {
            "high severity issue must block": "high_severity_must_block",
            "blocking issue requires a blocking rule": "blocking_rule_missing",
            "program gate issue cannot cite evidence or findings": "program_gate_references_forbidden",
            "program gate issue has a fixed reconstruction path": "program_gate_path_invalid",
            "issue requires evidence, a teaching rule, or finding keys": "issue_support_missing",
            "technical addition requires frozen evidence": "technical_evidence_missing",
            "path and executability disagree": "path_executability_mismatch",
            "duplicate affected target": "duplicate_affected_target",
            "blocking coverage issue requires affected targets": "coverage_targets_missing",
            "only coverage issues may affect specific targets": "affected_targets_not_coverage",
        }
        loc = first.get("loc", ())
        if (
            len(loc) in {2, 3}
            and loc[0] == "issues"
            and isinstance(loc[1], int)
            and (len(loc) == 2 or loc[2] in {"coverage", "factual_evidence", "difficulty", "self_contained"})
            and first.get("type") == "value_error"
        ):
            message = first.get("msg", "").removeprefix("Value error, ")
            if rule_code := issue_rule_codes.get(message):
                detail = f"{detail}:{rule_code}"
        raise StructuredOutputError(
            ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
            safe_detail=detail,
        ) from None
