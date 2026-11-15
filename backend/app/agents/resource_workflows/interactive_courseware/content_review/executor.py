from app.models.shared.llm import LLMCallContext


def execute_batch(gateway, run_id, batch, profile, *, revision=False):
    options = gateway.options_for(profile.role, temperature=0.0).model_copy(update={
        "max_output_tokens": batch.output_tokens, "max_attempts": 1,
        "allow_text_fallback": False, "allow_schema_repair": False, "schema_repair_attempts": 0,
    })
    result = gateway.invoke_structured(messages=list(batch.messages), output_schema=profile.schema,
        context=LLMCallContext(run_id=run_id, step_id=f"{run_id}:{batch.batch_id}:{'revision' if revision else 'review'}",
                               node_name="courseware_content_reviewer", schema_name=profile.schema.__name__), options=options)
    return result.output


# ---------------------------------------------------------------------------
# Bypass LLM-call accounting (T41): bind the content-review stage with the
# batch label (review / revision / recheck routes share this entry).
# ---------------------------------------------------------------------------
import functools as _functools

from app.agents.shared.llm_accounting import stage_labeled_scope as _stage_labeled_scope

_execute_batch = execute_batch


@_functools.wraps(_execute_batch)
def execute_batch(*args, **kwargs):
    run_id = kwargs.get("run_id")
    batch = kwargs.get("batch")
    revision = kwargs.get("revision", False)
    if run_id is None and len(args) >= 2:
        run_id = args[1]
    if batch is None and len(args) >= 3:
        batch = args[2]
    label = getattr(batch, "batch_id", None) or "content-batch"
    with _stage_labeled_scope(
        "content_review",
        labels=[label, "revision" if revision else "review"],
    ):
        return _execute_batch(*args, **kwargs)
