"""Resolve the immutable evidence boundary shared by generation and review."""
from __future__ import annotations

from pydantic import BaseModel

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
