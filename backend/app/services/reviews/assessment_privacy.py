"""Public projections never expose assessment answers through audit side doors."""
from app.models.reviews.claims import STRUCTURED_ASSESSMENT_SOURCE, UNIFIED_ASSESSMENT_SOURCE


def public_claims(response):
    hidden = {c.claim_id for c in response.claims if c.extractor_prompt_version in {STRUCTURED_ASSESSMENT_SOURCE, UNIFIED_ASSESSMENT_SOURCE}}
    return response.model_copy(update={
        "claims": [c for c in response.claims if c.claim_id not in hidden],
        "judgements": [j for j in response.judgements if j.claim_id not in hidden],
    })


def public_review(review):
    # Preserve summary counters and decision, never disclose private findings.
    if isinstance(review, dict):
        return {k: v for k, v in review.items() if k in {
            "review_id", "resource_id", "status", "decision", "claim_total", "claim_supported",
            "claim_unsupported", "claim_metric_status", "claim_hallucination_rate", "revision_count",
        }}
    return review.model_copy(update={"claims": [], "issues": [], "revision_instructions": []})


def public_timeline(timeline):
    if not any(r.get("resource_type") in {"分阶测试题", "个性化纠错训练包"} for r in timeline.resource_versions):
        return timeline
    steps = [s.model_copy(update={k: None if k == "error_message" else "测评审核详情已隐藏"
                                 for k in ("input_summary", "output_summary", "decision_reason", "error_message")
                                 if k in type(s).model_fields}) for s in timeline.steps]
    # Recorded event payloads contain identifiers/counts. Reuse SSE's existing
    # allowlist so HTTP replay cannot expose a more permissive payload.
    from app.services.runs.events import _public_payload
    events = [e.model_copy(update={"payload": _public_payload(e)})
              for e in timeline.events]
    return timeline.model_copy(update={"steps": steps, "events": events,
                                       "reviews": [public_review(r) for r in timeline.reviews]})
