"""Safe extraction and strict validation of structured LLM output."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import ErrorCode


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
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "root"
        detail = f"{location}:{first.get('type', 'validation_error')}"
        raise StructuredOutputError(
            ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
            safe_detail=detail,
        ) from None
