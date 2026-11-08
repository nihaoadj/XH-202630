"""Round-bound append/recovery creation without expanding review resources."""

from copy import copy
from datetime import datetime, timezone

from app.core.security.errors import ApplicationError, ErrorCode
from app.db.feedback.round_base import RoundConflict
from app.models.learning_documents.schemas import GenerateRequest
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_plans import round_identity
from app.services.generation.round_context import load_round_context


def _invalid(code=ErrorCode.ROUND_SELECTION_INVALID, status=422):
    return ApplicationError(code, status_code=status)


def _scope_error(error: RoundConflict):
    """Translate a stored-fact rejection into the public round error contract."""
    reason = str(error)
    if reason in {"ROUND_SCOPE_NOT_FOUND", "ROUND_SCOPE_OWNER_MISMATCH",
                  "ROUND_REQUEST_OWNER_MISMATCH"}:
        return _invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
    if reason in {"ROUND_SOURCE_BINDING_MISMATCH", "ROUND_SCOPE_INCONSISTENT"}:
        return _invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
    if reason == "ROUND_ROW_VERSION_CONFLICT":
        return _invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
    return _invalid()


def create_round_continuation(service, learner, prepared, run_id=None, submission_hash=None, round_uow_factory=None):
    source = prepared.source_job_run_id
    binding = service.round_repository.one("learning_round_job_bindings", run_id=source)
    if binding is None:
        raise _invalid()
    request = prepared.generation_request
    replacing = prepared.payload.replace_existing_types or prepared.payload.replace_source_run
    identity = run_id or round_identity("run", source, submission_hash or request.model_dump(mode="json"))
    return create_bound_job(service, learner, binding, request, identity,
                            submission_hash or canonical_hash({"source": source, "request": request.model_dump(mode="json")}),
                            relation="retry" if replacing else "append", source_run_id=source,
                            replace_source=prepared.payload.replace_source_run,
                            round_uow_factory=round_uow_factory)


def create_bound_job(service, learner, binding, request, run_id, submission_hash,
                     *, relation, source_run_id, replace_source=False, retry_context=None,
                     round_uow_factory=None):
    factory = round_uow_factory or getattr(service, "round_uow_factory", None)
    if factory is None:
        raise _invalid(ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE, 503)
    try:
        return _create_bound_job(factory, service, learner, binding, request, run_id, submission_hash,
                                 relation=relation, source_run_id=source_run_id,
                                 replace_source=replace_source, retry_context=retry_context)
    except RoundConflict as error:
        raise _scope_error(error) from error


def _create_bound_job(factory, service, learner, binding, request, run_id, submission_hash,
                      *, relation, source_run_id, replace_source=False, retry_context=None):
    with factory() as uow:
        existing = uow.jobs.job_repo.get(run_id)
        if existing is not None:
            if existing.learner_id != learner.learner_id:
                raise _invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
            old_binding = uow.rounds.one("learning_round_job_bindings", run_id=run_id)
            if old_binding is None or old_binding["stage_node_id"] != binding["stage_node_id"]:
                raise _invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
            result = uow.jobs._existing_submission(run_id, submission_hash)
            return result, GenerateRequest.model_validate(existing.request_payload)
        context = load_round_context(uow.rounds, learner, binding["stage_node_id"], request,
                                     relation_kind=relation, source_run_id=source_run_id)
        stage_node = uow.rounds.one("learning_round_stage_nodes", stage_node_id=binding["stage_node_id"])
        stage = uow.rounds.one("learning_round_stages", stage_id=context.stage_id)
        source = uow.jobs.job_repo.get(source_run_id)
        if source is None or source.learner_id != learner.learner_id:
            raise _invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
        if relation == "retry":
            if source.job_status not in {"completed", "failed"}:
                raise _invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
            # A successful artifact of the same stage_node is never replaced by
            # a retry, even when it was published from another Claim-split run.
            published = []
            for row in uow.rounds.find("learning_round_job_bindings", stage_node_id=context.stage_node_id):
                published.extend(uow.feedback.resource_repo.list_by_run(row["run_id"]))
            if any(item.publication_status == "published" and item.resource_type in request.resource_types
                   for item in published):
                raise _invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
            counters = dict(stage_node["budget_counters"])
            recovery = dict(counters.get("resource_recoveries", {}))
            for resource in request.resource_types:
                count = recovery.get(resource, 0)
                if count >= stage["budget_snapshot"]["H"]:
                    raise _invalid(ErrorCode.ROUND_CORRECTION_BUDGET_EXHAUSTED, 409)
                recovery[resource] = count + 1
            counters["resource_recoveries"] = recovery
            uow.rounds.compare_and_set("learning_round_stage_nodes", stage_node["stage_node_id"],
                                      stage_node["row_version"], {"budget_counters": counters,
                                                                 "recovery_count": stage_node["recovery_count"] + 1})
        else:
            # Append can add missing primary types, never replace successful
            # material or reset an existing resource's exhausted budget.
            requested = set(request.resource_types)
            if requested & set(stage_node["resource_types"]):
                raise _invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
            types = [*stage_node["resource_types"], *request.resource_types]
            uow.rounds.compare_and_set("learning_round_stage_nodes", stage_node["stage_node_id"],
                                      stage_node["row_version"], {"resource_types": types})
            budget = dict(stage["budget_snapshot"])
            budget["scopes"] = {**budget["scopes"], context.stage_node_id: len(types) * budget["resource_tokens"]}
            budget["runtime_scopes"] = {**budget["runtime_scopes"], context.stage_node_id:
                                       len(types) * (1 + budget["H"]) * budget["workflow_seconds"]}
            uow.rounds.compare_and_set("learning_round_stages", stage["stage_id"], stage["row_version"],
                                      {"budget_snapshot": budget})
        jobs = copy(uow.jobs)
        jobs.round_repository = uow.rounds
        jobs._trusted_round_binding = context
        result = jobs.create_job(learner, request, run_id=run_id, batch_id=context.batch_id,
                                 submission_hash=submission_hash, resource_retry_context=retry_context)
        uow.rounds.insert("learning_round_job_bindings", dict(
            run_id=run_id, stage_node_id=context.stage_node_id, relation_kind=relation,
            source_run_id=source_run_id, created_at=datetime.now(timezone.utc),
        ))
        if replace_source:
            jobs.mark_superseded(source_run_id, run_id)
        return result, request
