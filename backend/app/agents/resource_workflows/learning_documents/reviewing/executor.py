"""Exactly one logical gateway call, with existing bounded gateway retries."""

from app.core.llm.gateway import LLMGatewayError

from .payloads import estimate_review_input


class ReviewInputBudgetError(ValueError):
    pass


def invoke_review(*, request, llm_gateway, call_context, collector, review_id=None,
                  options_override: dict | None = None):
    """One logical review call; the gateway owns its bounded internal retries.

    ``options_override`` lets a caller opt into the frozen lecture attempt budget
    or a single-attempt correction.  It never changes gateway code or defaults.
    """
    options = llm_gateway.options_for(request.profile.gateway_role, temperature=0.0)
    if request.max_output_tokens is not None:
        options = options.model_copy(update={"max_output_tokens": request.max_output_tokens})
    if options_override:
        options = options.model_copy(update=dict(options_override))
    if request.profile.phase == "assessment_combined_v2":
        if request.context_tokens is None or estimate_review_input(request=request) + options.max_output_tokens > request.context_tokens:
            raise ReviewInputBudgetError("combined review input_budget exceeded")
    index = collector.start(request=request, context=call_context, review_id=review_id)
    # Bypass LLM-call accounting (T41): bind the review stage and the reviewed
    # resource label around the single logical gateway call.
    from app.agents.shared.llm_accounting import stage_labeled_scope

    labels = [request.resource_id, review_id] if request.resource_id else None
    with stage_labeled_scope(
        "review", labels=labels, step_id=getattr(call_context, "step_id", None),
    ):
        try:
            result = llm_gateway.invoke_structured(messages=list(request.messages), output_schema=request.profile.output_schema,
                                                    context=call_context, options=options)
        except LLMGatewayError as exc:
            collector.finish(index=index, result=exc, error=True)
            raise
    collector.finish(index=index, result=result)
    return result
