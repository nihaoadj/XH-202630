"""Frozen Claim routing and independent, bounded revision allowances."""

from collections import Counter

NEW_CLAIM_WORKFLOW = "contradiction_first_v3"
GAP_REVISION_THRESHOLD = 8


def contradiction_first(state):
    return (state.get("include_claim_evidence_retrieval", False)
            and state.get("claim_workflow_version") in {"contradiction_first_v1", "contradiction_first_v2", NEW_CLAIM_WORKFLOW})


def include_large_gaps(state):
    return (state.get("include_claim_evidence_retrieval", False)
            and state.get("claim_workflow_version") in {"contradiction_first_v2", NEW_CLAIM_WORKFLOW})


def _current_bad(state, judgements):
    """One completed factual problem per Claim, bound to the current review."""
    resources = {r.resource_id: r for r in state.get("generated_resources", [])}
    claims = {c["claim_id"]: c for c in state.get("extracted_claims", []) if isinstance(c, dict)}
    review_ids = state.get("review_result", {}).get("review_ids", {})
    selected = {}
    for item in judgements:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        claim = claims.get(item.get("claim_id"))
        if not claim or claim.get("claim_type") != "factual":
            continue
        resource = resources.get(claim.get("resource_id"))
        if resource is None:
            continue
        binding = (claim.get("run_id"), claim.get("resource_id"), claim.get("resource_version"), claim.get("review_id"))
        expected_review = review_ids.get(resource.resource_id) or resource.review_id
        if (binding != tuple(item.get(k) for k in ("run_id", "resource_id", "resource_version", "review_id"))
                or binding[:3] != (state.get("run_id"), resource.resource_id, resource.version)
                or (expected_review and binding[3] != expected_review)
                or item.get("verdict") not in {"contradicted", "not_in_evidence"}):
            continue
        previous = selected.get(item["claim_id"])
        if previous is None or item["verdict"] == "contradicted":
            selected[item["claim_id"]] = item
    return list(selected.values())


def resource_key(resource):
    return resource.resource_spec_id or resource.resource_type


def resource_keys(state):
    return {r.resource_id: resource_key(r) for r in state.get("generated_resources", [])}


def post_retrieval_ids(state):
    keys = set(state.get("claim_post_retrieval_resource_keys", []))
    return {rid for rid, key in resource_keys(state).items() if key in keys}


def revision_available(state, phase):
    total = state.get("claim_revision_count", 0)
    post = state.get("claim_post_retrieval_revision_count", 0)
    if phase == "post_retrieval":
        return post < state.get("claim_post_retrieval_max_iterations", 0)
    return total - post < state.get("claim_max_iterations", 1)


def select_revision_bad(state, bad):
    """Choose one phase without borrowing or resetting another phase's quota."""
    if not contradiction_first(state):
        return bad, "legacy_v1"
    if include_large_gaps(state):
        bad = _current_bad(state, bad)
    post_ids = post_retrieval_ids(state)
    pre = [j for j in bad if j.get("verdict") == "contradicted"
           and j.get("resource_id") not in post_ids]
    if include_large_gaps(state):
        contradicted_ids = {j["resource_id"] for j in pre}
        gap_first = state.get("claim_workflow_version") == NEW_CLAIM_WORKFLOW
        threshold = state.get("claim_gap_revision_threshold", GAP_REVISION_THRESHOLD) if gap_first else GAP_REVISION_THRESHOLD
        gaps = [j for j in bad if j["verdict"] == "not_in_evidence"
                and j["resource_id"] not in post_ids
                and (gap_first or j["resource_id"] in contradicted_ids)]
        counts = Counter(j["resource_id"] for j in gaps)
        pre.extend(j for j in gaps if counts[j["resource_id"]] > threshold)
    post = [j for j in bad if j.get("resource_id") in post_ids]
    if pre and revision_available(state, "contradiction"):
        return pre, "contradiction"
    if post and revision_available(state, "post_retrieval"):
        return post, "post_retrieval"
    return bad, "exhausted"


def contradicted_resource_ids(state):
    judgements = state.get("claim_judgements", [])
    if include_large_gaps(state):
        judgements = _current_bad(state, judgements)
    return {j.get("resource_id") for j in judgements
            if isinstance(j, dict) and j.get("verdict") == "contradicted"}
