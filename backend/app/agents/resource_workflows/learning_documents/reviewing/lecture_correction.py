"""One bounded business correction for recoverable V2 lecture review output.

The gateway keeps its own retry and schema-repair budget untouched.  This helper
only decides whether the *same* frozen review may be asked once more after a
self-contradictory but structurally valid answer, and builds that second prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from .lecture_errors import LectureReviewValidationError
from .payloads import estimate_review_input
from .types import ReviewRequest


@dataclass(frozen=True)
class CorrectionPlan:
    allowed: bool
    stop_reason: str | None = None

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "stop_reason": self.stop_reason}


@dataclass(frozen=True)
class CorrectionRecord:
    """Audit-facing repair summary and the bounded first-result attachment."""

    resource_id: str
    attempted: bool
    stop_reason: str | None
    error_codes: tuple[str, ...]
    error_paths: tuple[str, ...]
    first_attempts: int
    correction_attempts: int
    first_call_id: str
    correction_call_id: str | None
    first_output: dict | None
    first_output_hash: str
    corrected: bool
    final_output_hash: str | None

    def as_dict(self) -> dict:
        return {
            "resource_id": self.resource_id, "attempted": self.attempted,
            "stop_reason": self.stop_reason, "error_codes": list(self.error_codes),
            "error_paths": list(self.error_paths), "first_attempts": self.first_attempts,
            "correction_attempts": self.correction_attempts, "first_call_id": self.first_call_id,
            "correction_call_id": self.correction_call_id, "first_output": self.first_output,
            "first_output_hash": self.first_output_hash, "corrected": self.corrected,
            "final_output_hash": self.final_output_hash,
        }


CORRECTION_INSTRUCTION = """上一次返回的审核结果内部不一致，不能作为有效审核。
请根据同一份正文、冻结目标和冻结证据重新完整审核，并返回完整的审核对象（不是字段补丁）：
- 逐目标结果、具体问题、三维结论和风险分必须互相支持；
- 不要为了满足结构虚构缺陷，也不要删除真实缺陷来换取通过；
- 未检查清楚时明确标记 insufficient 并说明原因；
- 原验收条件、冻结目标、冻结证据和版本绑定不得改变。"""


def plan_correction(*, error: LectureReviewValidationError, remaining_attempts: int,
                    remaining_seconds: float | None, output_reserve_ok: bool) -> CorrectionPlan:
    """Decide from typed state only; never from exception text."""
    if not error.correctable:
        return CorrectionPlan(False, f"not_correctable:{error.code}")
    if remaining_attempts < 1:
        return CorrectionPlan(False, "no_physical_attempt_left")
    if remaining_seconds is not None and remaining_seconds <= 0:
        return CorrectionPlan(False, "workflow_deadline_reached")
    if not output_reserve_ok:
        return CorrectionPlan(False, "context_window_insufficient")
    return CorrectionPlan(True, None)


def correction_payload(*, payload: dict, first_output: dict, errors: list[LectureReviewValidationError]) -> dict:
    """Keep the frozen material intact and append the result under review."""
    annotated = dict(payload)
    annotated["previous_review_under_check"] = first_output
    annotated["review_consistency_errors"] = [
        {"code": item.code, "field": item.path, "relationship": item.hint} for item in errors
    ]
    return annotated


def build_correction_request(*, request: ReviewRequest, first_output: dict,
                             errors: list[LectureReviewValidationError]) -> ReviewRequest:
    system = request.messages[0]
    original = request.messages[1]
    if not isinstance(system, SystemMessage) or not isinstance(original, HumanMessage):
        raise ValueError("lecture correction expects the frozen system/human pair")
    payload = json.loads(original.content)
    body = json.dumps(correction_payload(payload=payload, first_output=first_output, errors=errors),
                      ensure_ascii=False)
    return ReviewRequest(
        request.profile, request.prompt_bundle,
        (SystemMessage(content=system.content + "\n\n" + CORRECTION_INSTRUCTION),
         HumanMessage(content=body)),
        request.resource_id, request.max_output_tokens, request.context_tokens)


def correction_fits(*, request: ReviewRequest, max_output_tokens: int, context_tokens: int | None) -> bool:
    if context_tokens is None:
        return True
    return estimate_review_input(request=request) + max_output_tokens <= context_tokens
