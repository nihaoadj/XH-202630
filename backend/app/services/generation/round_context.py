"""Validate a persisted round identity before granting special generation scope."""

from app.db.feedback.round_base import BaseRoundRepository, RoundConflict
from app.models.feedback.rounds import RoundJobBindingV1
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES


def load_round_context(
    repository: BaseRoundRepository,
    learner: LearnerProfile,
    stage_node_id: str,
    request: GenerateRequest,
    *,
    relation_kind: str = "production",
    source_run_id: str | None = None,
) -> RoundJobBindingV1:
    """Client constraints are never an authority for role, stage or targets.

    Only orchestration/continuation services call this boundary, after user
    authorization. It rechecks ownership and membership on the stored facts.
    """
    stage_node = repository.one("learning_round_stage_nodes", stage_node_id=stage_node_id)
    if stage_node is None:
        raise RoundConflict("ROUND_SCOPE_NOT_FOUND")
    stage = repository.one("learning_round_stages", stage_id=stage_node["stage_id"])
    member = repository.one("learning_round_nodes", round_node_id=stage_node["round_node_id"])
    if not stage or not member or stage["round_id"] != member["round_id"]:
        raise RoundConflict("ROUND_SCOPE_INCONSISTENT")
    parent = repository.one("learning_rounds", round_id=stage["round_id"])
    if not parent or (parent["learner_id"], parent["knowledge_base_id"]) != (learner.learner_id, learner.knowledge_base_id):
        raise RoundConflict("ROUND_SCOPE_OWNER_MISMATCH")
    if request.learner_id != learner.learner_id or request.knowledge_base_id != parent["knowledge_base_id"]:
        raise RoundConflict("ROUND_REQUEST_OWNER_MISMATCH")
    if request.target_skill_nodes != [member["skill_node_id"]] or request.difficulty_preference != stage_node["difficulty"]:
        raise RoundConflict("ROUND_REQUEST_TARGET_MISMATCH")
    allowed = set(stage_node["resource_types"])
    if relation_kind in {"append", "retry"}:
        source = repository.one("learning_round_job_bindings", run_id=source_run_id)
        if source is None or source["stage_node_id"] != stage_node_id:
            raise RoundConflict("ROUND_SOURCE_BINDING_MISMATCH")
        if relation_kind == "append":
            if member["role"] != "primary" or stage["kind"] != "initial":
                raise RoundConflict("ROUND_REVIEW_APPEND_FORBIDDEN")
            allowed = set(GENERAL_GENERATION_RESOURCE_TYPES)
    elif relation_kind != "production":
        raise RoundConflict("ROUND_INVALID_RELATION_KIND")
    if not request.resource_types or not set(request.resource_types) <= allowed:
        raise RoundConflict("ROUND_RESOURCE_SCOPE_MISMATCH")
    return RoundJobBindingV1(
        protocol_version=parent["protocol_version"], round_id=parent["round_id"],
        member_id=member["round_node_id"], node_id=member["skill_node_id"],
        stage_id=stage["stage_id"], stage_node_id=stage_node_id, batch_id=stage_node["batch_id"],
        role=member["role"], stage_kind=stage["kind"],
    )
