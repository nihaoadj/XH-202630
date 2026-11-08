"""Resolve the immutable evidence boundary shared by generation and review."""
from __future__ import annotations

from pydantic import BaseModel
from types import SimpleNamespace
from app.models.reviews.evidence_lineage import evidence_item_hash, resource_lineage
from app.models.reviews.claim_evidence_retrieval import ClaimReviewEvidenceSetV1

from app.core.security.errors import ApplicationError, ErrorCode
from app.models.knowledge.knowledge import EvidenceAllocation, RESOURCE_AWARE_STRATEGY, LEGACY_RETRIEVAL_STRATEGY
from app.models.shared.agent_contracts import ResourceSpec


def contract_error():
    return ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)


def allocation_for_state(state):
    strategy = state.get("retrieval_strategy_version", LEGACY_RETRIEVAL_STRATEGY)
    if strategy == LEGACY_RETRIEVAL_STRATEGY:
        return None
    if strategy != RESOURCE_AWARE_STRATEGY:
        raise contract_error()
    try:
        allocation = EvidenceAllocation.model_validate(state.get("evidence_allocation"))
        allocation.validate_evidence(state.get("retrieved_evidence", []), state.get("resource_types", []))
        if allocation.config_hash != state.get("retrieval_config_hash"):
            raise ValueError("allocation config mismatch")
        return allocation
    except (ValueError, TypeError, KeyError) as exc:
        raise contract_error() from exc


def scoped_node_map(node_map, evidence_ids):
    allowed = set(evidence_ids)
    return {node: [item for item in ids if item in allowed]
            for node, ids in node_map.items() if any(item in allowed for item in ids)}


def validate_spec(state, spec):
    evidence = state.get("retrieved_evidence", [])
    by_id = {item.evidence_id: item for item in evidence}
    if any(item not in by_id for item in spec.evidence_ids):
        raise contract_error()
    allocation = allocation_for_state(state)
    if allocation is not None:
        if spec.resource_type not in allocation.resource_types:
            raise contract_error()
        expected = allocation.available_ids(spec.resource_type)
        expected_map = scoped_node_map(state.get("node_evidence_map", {}), expected)
        if spec.evidence_ids != expected or spec.node_evidence_map != expected_map:
            raise contract_error()
        if spec.resource_type == "分阶测试题" and any(
            node not in expected_map for node in state.get("target_skill_nodes", [])
        ):
            raise contract_error()
    return [by_id[item] for item in spec.evidence_ids]


def evidence_for_resource(state, resource):
    allocation = allocation_for_state(state)
    raw_specs = state.get("resource_specs") or []
    try:
        specs = [ResourceSpec.model_validate(item) for item in raw_specs]
    except (ValueError, TypeError) as exc:
        raise contract_error() from exc
    if specs:
        matches = [item for item in specs if item.resource_spec_id == resource.resource_spec_id]
        if len(matches) != 1 or matches[0].resource_type != resource.resource_type:
            raise contract_error()
        return validate_spec(state, matches[0])
    if allocation is not None:
        raise contract_error()
    return list(state.get("retrieved_evidence", []))


def _authorized_scope_ids(state, resource, *, purpose: str | None) -> set[str]:
    """Scope ids that explicitly authorise this resource version.

    Own scopes and generation scopes of verified ancestors apply. Every edge
    keeps the same run, spec and family; siblings cannot share these grants.
    """

    scopes = state.get("claim_evidence_scopes") or {}
    if not scopes:
        return set()
    allowed: set[str] = set()
    def grant(item, target):
        try:
            scope = ClaimReviewEvidenceSetV1.model_validate(item)
            if (scope.run_id != state.get("run_id") or scope.resource_id != target.resource_id
                    or scope.resource_version != target.version):
                raise ValueError("scope identity mismatch")
            pool = {item.evidence_id: item for item in state.get("supplement_retrieved_evidence", [])}
            for ident in scope.added_evidence_ids:
                evidence = pool.get(ident)
                if evidence is None or evidence_item_hash(evidence) != scope.snapshot_hashes[ident]:
                    raise ValueError("scope snapshot hash mismatch")
            allowed.update(scope.added_evidence_ids)
        except (ValueError, KeyError, TypeError) as exc:
            raise contract_error() from exc

    for item in scopes.get(resource.resource_id, []):
        if not isinstance(item, dict):
            continue
        if purpose is not None and item.get("purpose") != purpose:
            continue
        if item.get("resource_version") != resource.version:
            raise contract_error()
        grant(item, resource)
    history = state.get("claim_evidence_lineage") or {}
    def get_parent(ident):
        raw = history.get(ident)
        return SimpleNamespace(**raw) if raw is not None else None

    if getattr(resource, "parent_resource_id", None):
        try:
            boundary = (state.get("resource_retry_context") or {}).get("source_resource") or {}
            ancestors = list(resource_lineage(
                resource, get_parent, within_run=True, boundary_resource_id=boundary.get("resource_id"),
            ))[1:]
        except ValueError as exc:
            raise contract_error() from exc
    else:
        ancestors = []
    for parent in ancestors:
        for item in scopes.get(parent.resource_id, []):
            if not isinstance(item, dict) or item.get("purpose") != "generation":
                continue
            if item.get("resource_version") != parent.version:
                raise contract_error()
            grant(item, parent)
    return allowed


def supplement_evidence_for_resource(state, resource, *, purpose: str | None = None):
    """Return supplements explicitly authorised for this resource version.

    The base pool keeps its original validation.  Supplements are read from the
    in-process channel that the rejudge node filled from persisted snapshots and
    are accepted only when the resource's frozen scope names them, so a sibling
    resource outside the verified lineage cannot inherit them.
    """

    allowed = _authorized_scope_ids(state, resource, purpose=purpose)
    if not allowed:
        return []
    pool = state.get("supplement_retrieved_evidence") or []
    resolved = [
        item for item in pool
        if getattr(item, "evidence_id", None) in allowed
        and item.knowledge_base_id == state.get("knowledge_base_id")
    ]
    if allowed - {item.evidence_id for item in resolved}:
        raise contract_error()
    return resolved


def resolve_review_evidence_context(state, resource, *, purpose: str | None = None):
    """Base evidence plus only the supplements explicitly granted to a scope."""

    base = evidence_for_resource(state, resource)
    supplements = supplement_evidence_for_resource(state, resource, purpose=purpose)
    if not supplements:
        return base
    known = {item.evidence_id for item in base}
    return [*base, *[item for item in supplements if item.evidence_id not in known]]


def resolve_generation_evidence_context(state, spec, previous=None):
    """Base spec evidence plus the child's authorised generation supplements.

    ``previous`` is the version being revised; the new child inherits its own
    and its ancestors' ``generation`` scopes. A first generation (``previous`` is
    ``None``) never sees supplement excerpts.
    """

    base = validate_spec(state, spec)
    if previous is None:
        return base, []
    allowed = _authorized_scope_ids(state, previous, purpose="generation")
    if not allowed:
        return base, []
    pool = state.get("supplement_retrieved_evidence") or []
    known = {item.evidence_id for item in base}
    supplements = [
        item for item in pool
        if getattr(item, "evidence_id", None) in allowed
        and item.knowledge_base_id == state.get("knowledge_base_id")
        and item.evidence_id not in known
    ]
    if not supplements:
        raise contract_error()
    if allowed - known - {item.evidence_id for item in supplements}:
        raise contract_error()
    return [*base, *supplements], [item.evidence_id for item in supplements]


def validate_payload_evidence(resource, evidence):
    allowed = {item.evidence_id for item in evidence}
    def visit(value):
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="python")
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"evidence_ids", "summary_evidence_ids", "source_evidence_ids"}:
                    if not isinstance(item, list) or not set(item) <= allowed:
                        raise contract_error()
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for field in ("assessment_payload", "practice_guide_payload", "review_practice_payload"):
        visit(getattr(resource, field, None))
