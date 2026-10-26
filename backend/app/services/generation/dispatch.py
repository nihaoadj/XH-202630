"""HTTP submission identity and delivery choice; no process-local durable intent."""
import uuid
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.persistence import canonical_hash


def submission_identity(learner, payload, key, scope):
    if key is None:
        return {}
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ApplicationError(ErrorCode.REQUEST_VALIDATION_ERROR, status_code=422)
    identity = canonical_hash({"account": learner.user_id, "scope": scope, "key": key})
    return {"run_id": str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
            "submission_hash": canonical_hash(payload.model_dump(mode="json"))}


def schedule_generation(service, background_tasks, learner, request, run_id, batch_id=None):
    if getattr(service, "durable_dispatch", False):
        return
    arguments = (learner, request, run_id) if batch_id is None else (learner, request, run_id, batch_id)
    background_tasks.add_task(service.run_job, *arguments)
