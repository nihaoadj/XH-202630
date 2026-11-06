"""Private policy/binding and CAS helpers. Repository access is injected."""
from copy import deepcopy
from datetime import datetime, timezone

from app.models.courseware.content_review import (
    ContentReviewBindingV1, ContentReviewBlocked, ContentReviewBusy, ContentReviewConflict, ContentReviewPolicyV1,
    FrozenBudgetV1, json_hash, validate_private_spec,
)


def read_state(repo, run_id):
    get_spec = getattr(repo, "get_spec_by_run", None)
    get_binding = getattr(repo, "get_run_content_review_binding", None)
    # The legacy budget port only needs jobs/events. A partial private-state
    # port must still fail closed rather than lose the independent binding.
    if get_spec is None and get_binding is None:
        return None, None
    if not callable(get_spec) or not callable(get_binding):
        raise ContentReviewBlocked("incomplete private content repository port")
    spec = get_spec(run_id)
    binding = get_binding(run_id)
    namespace = (spec or {}).get("spec_json", {}).get("content_review")
    if namespace is None and binding is None:
        return None, spec
    if namespace is None or binding is None:
        raise ContentReviewBlocked("missing independent policy/binding")
    try:
        state = validate_private_spec(spec["spec_json"])
        binding = ContentReviewBindingV1.model_validate(binding)
    except (ValueError, KeyError, TypeError) as exc:
        raise ContentReviewBlocked("invalid frozen content protocol") from exc
    if state.policy.mode != "content_v1" or binding.spec_id != spec["spec_id"] or binding.policy_hash != json_hash(state.policy.model_dump(mode="json")):
        raise ContentReviewBlocked("policy/binding mismatch")
    if spec["content_hash"] != json_hash(spec["spec_json"]):
        raise ContentReviewBlocked("private spec hash mismatch")
    return state, spec


def mutate_spec(repo, run_id, transform, guard=lambda: None):
    for _ in range(8):
        state, old = read_state(repo, run_id)
        if state is None:
            raise ContentReviewBlocked("content policy missing")
        new = deepcopy(old)
        transform(new["spec_json"])
        guard()
        new["content_hash"] = json_hash(new["spec_json"])
        record = new["spec_json"]["content_review"].get("record")
        new["status"] = "approved" if record and record["status"] in {"approved", "degraded", "not_applicable"} else "pending"
        try:
            return repo.save_content_review_spec_once(run_id, old["spec_id"], old["content_hash"], new)
        except ContentReviewConflict:
            continue
    raise ContentReviewConflict("CAS contention limit")


def freeze_policy(settings, gateway, deadline):
    from app.core.llm.gateway import LLMGateway
    actual = getattr(gateway, "underlying_gateway", gateway)
    if not settings.courseware_content_review_context_tokens:
        raise ContentReviewBlocked("confirmed model context window required")
    if isinstance(actual, LLMGateway) or not getattr(actual, "offline_content_review", False):
        raise ContentReviewBlocked("verified production TokenEstimatorProfile required")
    stages = ("planner", "scene", "quality_review", "revision")
    names = ("planner", "scene_composition", "quality_review", "revision")
    model_fingerprint = model_configuration_fingerprint(settings)
    return ContentReviewPolicyV1(context_tokens=settings.courseware_content_review_context_tokens,
        release_policy=settings.courseware_release_policy, model_fingerprint=model_fingerprint,
        estimator_id="fixture-tokenizer-v1", max_revision_rounds=min(1, settings.courseware_auto_revision_max_attempts),
        budget=FrozenBudgetV1(total_tokens=settings.courseware_total_llm_token_budget,
            stage_tokens={s: getattr(settings, f"courseware_{n}_token_budget") for s, n in zip(stages, names)},
            stage_seconds={s: getattr(settings, f"courseware_{n}_max_seconds") for s, n in zip(stages, names)},
            quality_reserve=settings.courseware_quality_review_reserved_tokens,
            revision_reserve=settings.courseware_revision_reserved_tokens,
            call_seconds=getattr(settings, "courseware_llm_call_timeout_seconds", 30.0), deadline=deadline.isoformat()))


def model_configuration_fingerprint(settings):
    fields = ("llm_model", "llm_base_url", "llm_thinking_mode", "llm_structured_output_mode", "llm_max_attempts",
              "llm_request_timeout_seconds", "llm_resource_generation_max_attempts", "llm_retry_base_delay_seconds", "llm_retry_max_delay_seconds")
    return json_hash({field: getattr(settings, field, None) for field in fields})


def guard_owner(state, owner):
    if state.execution_owner != owner or not state.lease_until or datetime.fromisoformat(state.lease_until) <= datetime.now(timezone.utc):
        raise ContentReviewBusy("content execution lease lost")
