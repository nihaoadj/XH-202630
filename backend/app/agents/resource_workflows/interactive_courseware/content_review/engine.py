"""One engine for all adapters: prepare, batch, validate, bounded repair."""
from app.core.courseware.content_review import content_identity
from app.core.courseware.content_review.identity import approval_identity
from app.models.courseware.content_review import ContentReviewRecordV1, json_hash
from app.models.courseware.content_review import ContentReviewBusy
from .batching import plan_batches, resolve_estimator
from .executor import execute_batch
from .profiles import REVIEW_PROFILE, REVISION_PROFILE
from .prompts.builder import fingerprint
from .results import passed, validate_results
from .revision import apply_patch


def review_content(*, run_id, snapshot, design, candidate, adapter, policy, gateway, revision_gateway=None, revision_rounds=0, forced_ids=None, prior_results=(), prior_batches=()):
    original = candidate
    prepared = adapter.prepare(run_id, snapshot, design, candidate)
    prompt_hash = json_hash([fingerprint(REVIEW_PROFILE), fingerprint(REVISION_PROFILE)])
    def identity(p):
        return content_identity(run_id, snapshot, design, p.inventory, p.evidence, policy, prompt_hash)
    current_identity = identity(prepared)
    results, batches, reason = list(prior_results) if forced_ids else [], list(prior_batches) if forced_ids else [], ""
    status = "not_applicable" if not prepared.items else "pending"
    try:
        if prepared.items:
            estimator = resolve_estimator(policy, gateway)
            if forced_ids:
                failed = set(forced_ids)
            else:
                for batch in plan_batches(prepared, current_identity, policy, REVIEW_PROFILE, estimator):
                    result = validate_results(execute_batch(gateway, run_id, batch, REVIEW_PROFILE), batch)
                    batches.append(result); results.extend(result.results)
                failed = {r.item_id for r in results if not passed([r])}
            user_failed = any(i.origin == "user" and i.item_id in failed for i in prepared.items)
            if failed and not user_failed and revision_rounds < policy.max_revision_rounds and revision_gateway is not None:
                revision_rounds += 1
                from dataclasses import replace
                targets = set(failed)
                targets.update(d for i in prepared.items if i.item_id in failed for d in i.dependency_ids)
                subset = replace(prepared, items=tuple(i for i in prepared.items if i.item_id in targets and i.origin == "ai"))
                # Plan every repair batch before sending any patch request.
                revision_batches = plan_batches(subset, current_identity, policy, REVISION_PROFILE, estimator, revision=True)
                candidate = prepared.candidate
                for batch in revision_batches:
                    raw = execute_batch(revision_gateway, run_id, batch, REVISION_PROFILE, revision=True)
                    candidate = apply_patch(adapter, replace(prepared, candidate=candidate), current_identity, raw, [i.item_id for i in batch.items])
                revised = adapter.prepare(run_id, snapshot, design, candidate)
                changed = {i.item_id for i in revised.items if next((old.value_hash for old in prepared.items if old.item_id == i.item_id), None) != i.value_hash}
                recheck_ids = targets | changed
                results = [r for r in results if r.item_id not in recheck_ids]
                prepared = revised; current_identity = identity(prepared)
                subset = replace(prepared, items=tuple(i for i in prepared.items if i.item_id in recheck_ids))
                for batch in plan_batches(subset, current_identity, policy, REVIEW_PROFILE, estimator):
                    result = validate_results(execute_batch(revision_gateway, run_id, batch, REVIEW_PROFILE), batch)
                    batches.append(result); results.extend(result.results)
            expected = {i.item_id for i in prepared.items}
            status = "approved" if set(r.item_id for r in results) == expected and passed(results) else "needs_revision"
    except Exception as exc:
        # Control loss must propagate, never be converted into an approval.
        if isinstance(exc, ContentReviewBusy) or getattr(exc, "code", "") in {"COURSEWARE_LEASE_LOST", "COURSEWARE_CANCELLED", "COURSEWARE_RUN_TIMEOUT"}:
            raise
        status, reason = "unavailable", type(exc).__name__
    if status in {"unavailable", "needs_revision"}:
        user_items = [i for i in prepared.items if i.origin == "user"]
        if any(not any(r.item_id == i.item_id and r.value_hash == i.value_hash and passed([r]) for r in results) for i in user_items):
            status = "blocked"
    if status in {"unavailable", "needs_revision"}:
        if policy.release_policy == "strict":
            status = "blocked"
        else:
            status = "degraded"
            prepared = adapter.prepare(run_id, snapshot, design, {})
            current_identity = identity(prepared)
    return ContentReviewRecordV1(identity=approval_identity(current_identity, results, status), source_hash=json_hash(snapshot), design_hash=json_hash(design),
        inventory_hash=json_hash(prepared.inventory.model_dump(mode="json")), evidence_hash=json_hash(prepared.evidence.model_dump(mode="json")),
        value_hash=json_hash(prepared.candidate), adapter_version=adapter.version, prompt_fingerprint=prompt_hash,
        fragment_versions={f.id: f.version for f in (*REVIEW_PROFILE.fragments, *REVISION_PROFILE.fragments)},
        model_fingerprint=policy.model_fingerprint, status=status, reason=reason or ("semantic_review_failed" if status in {"degraded", "blocked"} else ""),
        original_values=original, approved_values=prepared.candidate if status in {"approved", "not_applicable", "degraded"} else {},
        candidate_schema=adapter.candidate_model.__name__, revision_rounds=revision_rounds, batches=batches, results=results)
