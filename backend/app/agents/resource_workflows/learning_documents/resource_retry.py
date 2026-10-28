"""Import one frozen text-resource context without rerunning upstream agents."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agents.shared.evidence_scope import contract_error, validate_spec
from app.core.retrieval.knowledge_ids import evidence_id, query_hash, retrieval_config_hash
from app.models.knowledge.knowledge import (
    EvidenceAllocation, EvidenceItem, LEGACY_RETRIEVAL_STRATEGY,
    RESOURCE_AWARE_STRATEGY, RetrievalStatus,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import ResourceSpec, build_trace_item, start_step
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash
from app.models.shared.workflow import StepStatus


def _json_model(model, value):
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


def _remap(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_remap(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _remap(item, mapping) for key, item in value.items()}
    return value


def _project_allocation(allocation, selected, mapping, step_id):
    data = allocation.model_dump(mode="json")
    retained = allocation.available_ids(selected)
    bindings = {
        key: [item for item in values if item["resource_type"] in (None, selected)]
        for key, values in data["query_bindings"].items()
    }
    bindings = {key: values for key, values in bindings.items() if values}
    hashes = {
        mapping[old]: [key for key in data["evidence_query_hashes"][old] if key in bindings]
        for old in retained
    }
    # Never invent query attribution for historical evidence.
    if any(not values for values in hashes.values()):
        raise ValueError("retained evidence has no selected query binding")
    used = {key for values in hashes.values() for key in values}
    bindings = {key: values for key, values in bindings.items() if key in used}
    data.update(
        step_id=step_id, resource_types=[selected],
        evidence_ids=[mapping[item] for item in retained],
        common_evidence_ids=[mapping[item] for item in data["common_evidence_ids"]],
        resource_specific_evidence_ids={selected: [mapping[item] for item in data["resource_specific_evidence_ids"][selected]]},
        query_bindings=bindings, evidence_query_hashes=hashes,
        gaps=[item for item in data["gaps"] if item.get("resource_type") in (None, selected)],
        binding_hash=retrieval_config_hash(bindings),
    )
    data["allocation_hash"] = retrieval_config_hash({key: value for key, value in data.items() if key != "allocation_hash"})
    return _json_model(EvidenceAllocation, data)


def reuse_resource_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """Validate and clone trusted server-side retry input into this run's scope."""
    try:
        context = state["resource_retry_context"]
        if not isinstance(context, dict) or context.get("schema_version") != "1.0":
            raise ValueError("unsupported retry context")
        if context.get("source_run_id") == state.get("run_id"):
            raise ValueError("retry requires a new run identity")
        if context.get("context_hash") != canonical_hash({key: value for key, value in context.items() if key != "context_hash"}):
            raise ValueError("retry context hash mismatch")
        spec = _json_model(ResourceSpec, context["spec"])
        if spec.resource_spec_id != context["source_spec_id"] or spec.dependencies:
            raise ValueError("unsupported source spec")
        if state.get("resource_types") != [spec.resource_type]:
            raise ValueError("retry request must select exactly the frozen resource")
        snapshots = [_json_model(PersistedEvidenceSnapshot, item) for item in context["evidence"]]
        by_id = {item.evidence_id: item for item in snapshots}
        if not snapshots or len(by_id) != len(snapshots):
            raise ValueError("missing or duplicate source evidence")
        if any(item.run_id != context["source_run_id"] or item.knowledge_base_id != state.get("knowledge_base_id") for item in snapshots):
            raise ValueError("evidence crosses source scope")
        if not spec.evidence_ids or any(item not in by_id for item in spec.evidence_ids):
            raise ValueError("spec references missing evidence")
        if any(not set(ids) <= set(spec.evidence_ids) for ids in spec.node_evidence_map.values()):
            raise ValueError("node evidence crosses spec scope")
        strategy = context["retrieval_strategy_version"]
        allocation = None
        if strategy == RESOURCE_AWARE_STRATEGY:
            allocation = _json_model(EvidenceAllocation, context["evidence_allocation"])
            if allocation.evidence_ids != [item.evidence_id for item in snapshots]:
                raise ValueError("allocation evidence order mismatch")
            if allocation.available_ids(spec.resource_type) != spec.evidence_ids:
                raise ValueError("allocation differs from frozen spec")
        elif strategy != LEGACY_RETRIEVAL_STRATEGY or context.get("evidence_allocation") is not None:
            raise ValueError("unsupported retrieval strategy")
        config_hash = context["retrieval_config_hash"]
        if any(item.config_hash != config_hash for item in snapshots) or (allocation and allocation.config_hash != config_hash):
            raise ValueError("retrieval config differs from frozen evidence")
        step = start_step(state)
        mapping = {}
        evidence = []
        queries = context.get("query_texts") or {}
        for old_id in spec.evidence_ids:
            snapshot = by_id[old_id]
            new_id = evidence_id(run_id=state["run_id"], step_id=step["step_id"],
                                 knowledge_base_id=snapshot.knowledge_base_id,
                                 retrieval_query_hash=snapshot.query_hash,
                                 knowledge_chunk_id=snapshot.chunk_id, config_hash=config_hash)
            mapping[old_id] = new_id
            query = queries.get(old_id)
            if query and query_hash(query) != snapshot.query_hash:
                raise ValueError("historical query hash mismatch")
            payload = snapshot.model_dump(mode="json", exclude={"run_id", "retrieval_step_id", "snapshot_hash", "persisted_at"})
            payload.update(evidence_id=new_id, query=query or "历史检索文本未持久化，仅保留哈希：" + snapshot.query_hash)
            evidence.append(_json_model(EvidenceItem, payload))
        projected = _project_allocation(allocation, spec.resource_type, mapping, step["step_id"]) if allocation else None
        spec_data = spec.model_dump(mode="json")
        spec_data.update(
            resource_spec_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state['run_id']}:{context['source_spec_id']}")),
            evidence_ids=[mapping[item] for item in spec.evidence_ids],
            node_evidence_map=_remap(spec.node_evidence_map, mapping),
        )
        cloned_spec = _json_model(ResourceSpec, spec_data)
        source = _json_model(LearningResource, context["source_resource"]) if context.get("source_resource") else None
        if source and (source.run_id != context["source_run_id"] or source.resource_spec_id != spec.resource_spec_id or source.resource_family_id != spec.resource_family_id or source.resource_type != spec.resource_type or source.representation.value != "text" or source.learner_id != state.get("learner_id")):
            raise ValueError("source resource crosses retry scope")
        if not isinstance(context["diagnosis"], dict) or not isinstance(context["learning_plan"], dict):
            raise ValueError("invalid frozen upstream output")
        constraints = dict(state.get("constraints") or {})
        constraints["revision_feedback"] = _remap(context.get("revision_feedback") or {}, mapping)
        result = {
            "diagnosis": context["diagnosis"], "learning_plan": context["learning_plan"],
            "retrieved_evidence": evidence, "resource_specs": [cloned_spec.model_dump(mode="json")],
            "node_evidence_map": cloned_spec.node_evidence_map,
            "evidence_allocation": projected.model_dump(mode="json") if projected else None,
            "retrieval_strategy_version": strategy, "retrieval_config_hash": config_hash,
            "retrieval_status": RetrievalStatus.AVAILABLE.value, "constraints": constraints,
            "regeneration_source": source, "current_node": "reuse_context",
        }
        validate_spec({**state, **result}, cloned_spec)
        trace = build_trace_item(state, agent_name="supervisor", action="复用冻结上下文",
                                 status=StepStatus.SUCCESS, input_summary="导入所选资源的冻结输入",
                                 output_summary=f"复用 {len(evidence)} 条冻结证据，仅生成所选资源",
                                 decision_reason="手动单份重生成，不执行诊断、检索或规划。",
                                 evidence_refs=[item.evidence_id for item in evidence], step_context=step)
        trace["node_name"] = "reuse_context"
        result["trace"] = [trace]
        return result
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise contract_error() from exc
