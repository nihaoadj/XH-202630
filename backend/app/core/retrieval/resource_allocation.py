"""Deterministic selection and ID-only allocation for the optional E1 policy."""
from app.core.retrieval.knowledge_ids import query_hash, retrieval_config_hash
from app.models.knowledge.knowledge import EvidenceAllocation


def purposes_for_chunk(request, origins, chunk_id):
    return [purpose for query in origins.get(chunk_id, [])
            for purpose in request.query_bindings[query]]


def select_resource_chunks(request, ranked, origins):
    limit = request.policy.max_evidence_count
    selected: list[str] = []
    common: list[str] = []
    promotions: list[dict[str, str]] = []

    def matching(predicate):
        return [item[0].chunk_id for item in ranked
                if any(predicate(p) for p in purposes_for_chunk(request, origins, item[0].chunk_id))]

    def take(ids, *, public=False):
        for chunk in ids:
            if chunk in selected:
                continue
            if len(selected) >= limit:
                return False
            selected.append(chunk)
            if public:
                common.append(chunk)
            return True
        return False

    nodes = list(dict.fromkeys(p.node_id for values in request.query_bindings.values()
                              for p in values if p.resource_type is None and p.node_id))
    for node in nodes or [None]:
        public = matching(lambda p: p.resource_type is None and p.node_id == node)
        if public:
            chosen = public[0]
        else:
            alternate = matching(lambda p: p.node_id == node) if node else []
            chosen = alternate[0] if alternate else None
            if chosen:
                promotions.append({"reason": "common_promoted_from_specific", "node_id": node or "", "chunk_id": chosen})
        if chosen and chosen not in selected and len(selected) < limit:
            selected.append(chosen)
            common.append(chosen)
    if not common and ranked:
        chunk = ranked[0][0].chunk_id
        selected.append(chunk)
        common.append(chunk)
        promotions.append({"reason": "minimal_common_from_valid_candidate", "chunk_id": chunk})

    groups = {resource_type: matching(lambda p, r=resource_type: p.resource_type == r)
              for resource_type in request.resource_types}
    # Every type receives its first opportunity before more public evidence.
    for ids in groups.values():
        take(ids)
    public = matching(lambda p: p.resource_type is None)
    while len(selected) < limit:
        changed = take(public, public=True)
        for ids in groups.values():
            changed = take(ids) or changed
        if not changed:
            break
    return selected, common, promotions


def build_evidence_allocation(request, evidence, origins, common_chunks, gaps):
    ids = [item.evidence_id for item in evidence]
    common = set(common_chunks)
    bindings = {query_hash(query): [p.model_dump(mode="json") for p in purposes]
                for query, purposes in request.query_bindings.items()}
    data = {
        "strategy_version": request.policy.strategy_version,
        "step_id": request.step_id,
        "config_hash": evidence[0].config_hash,
        "resource_types": request.resource_types,
        "evidence_ids": ids,
        "common_evidence_ids": [item.evidence_id for item in evidence if item.chunk_id in common],
        "resource_specific_evidence_ids": {
            resource_type: [item.evidence_id for item in evidence if any(
                p.resource_type == resource_type for p in purposes_for_chunk(request, origins, item.chunk_id))]
            for resource_type in request.resource_types
        },
        "query_bindings": bindings,
        "evidence_query_hashes": {item.evidence_id: [query_hash(query) for query in origins[item.chunk_id]] for item in evidence},
        "gaps": gaps,
        "binding_hash": retrieval_config_hash(bindings),
    }
    data["allocation_hash"] = retrieval_config_hash(data)
    allocation = EvidenceAllocation.model_validate(data)
    allocation.validate_evidence(evidence, request.resource_types)
    return allocation
