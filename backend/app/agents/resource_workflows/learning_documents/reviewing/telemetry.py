"""Private call ledger. Public trace retains its historical single-call fields."""

from time import monotonic
import re

from app.models.reviews.review_audit import ReviewAuditRecordV1, ReviewCallRecordV1, summarize_review_calls


def issue_locations(*, review, resource):
    return [{"code": issue["code"], "severity": issue["severity"],
             "knowledge_point": issue.get("knowledge_point") if issue.get("knowledge_point") in resource.knowledge_points else None,
             "question_ids": list(dict.fromkeys(re.findall(r"\bq-\d{3}\b", issue.get("description", "")))),
             "step_ids": list(dict.fromkeys(re.findall(r"\b(?:step-[1-8]|prepare|verify|reflect)\b", issue.get("description", ""))))}
            for issue in review.get("issues", [])[:3]]


class ReviewCallCollector:
    def __init__(self):
        self.calls: list[ReviewCallRecordV1] = []
        self.started_at = monotonic()

    def start(self, *, request, context, review_id=None):
        record = ReviewCallRecordV1(
            call_id=context.call_id, resource_id=request.resource_id, review_id=review_id,
            phase=request.profile.phase, profile_version=request.profile.version,
            prompt_fingerprint=request.prompt_bundle.fingerprint,
            fragment_versions={f.id: f.version for f in request.prompt_bundle.fragments},
            gateway_role=request.profile.gateway_role, output_schema=request.profile.output_schema.__name__,
        )
        self.calls.append(record)
        return len(self.calls) - 1

    def finish(self, *, index, result, error=False):
        self.calls[index] = self.calls[index].model_copy(update={
            "call_id": result.call_id, "status": "error" if error else "success",
            "error_code": str(result.error.code) if error else None,
            "error_category": result.error.category if error else None,
            "model_name": result.model_name, "latency_ms": result.latency_ms,
            "retry_count": result.retry_count, "attempts": [a.model_copy(deep=True) for a in result.attempts],
            "usage": result.usage.model_copy(deep=True),
        })

    def invalid_result(self, *, call_id):
        for index, call in enumerate(self.calls):
            if call.call_id == call_id:
                self.calls[index] = call.model_copy(update={"status": "invalid_result", "error_code": "LLM_OUTPUT_SCHEMA_INVALID", "error_category": "post_validation"})


def build_review_audit(*, collector, run_id, step_id, generation_attempt, revision_count, policy, decision, resources):
    return ReviewAuditRecordV1(
        run_id=run_id, step_id=step_id, generation_attempt=generation_attempt, revision_count=revision_count,
        policy=policy, decision=decision, node_wall_ms=max(0, int((monotonic() - collector.started_at) * 1000)),
        resources=resources, calls=collector.calls, summary=summarize_review_calls(collector.calls),
    )
