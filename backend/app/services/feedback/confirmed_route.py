"""Read confirmed follow-up configuration from persisted round ownership links."""


def confirmed_route(repository, learner_id, source):
    if source is None:
        return None
    source_round = source.metadata.get("round_context", {}).get("round_id")
    choices = []
    for round_row in repository.find("learning_rounds", learner_id=learner_id):
        is_next = round_row["source_attempt_id"] == source.attempt_id
        if not is_next and round_row["round_id"] != source_round:
            continue
        members = {m["round_node_id"]: m for m in repository.find("learning_round_nodes", round_id=round_row["round_id"])}
        for stage in repository.find("learning_round_stages", round_id=round_row["round_id"]):
            rows = repository.find("learning_round_stage_nodes", stage_id=stage["stage_id"])
            correction = [row for row in rows if row["source_attempt_id"] == source.attempt_id]
            if not correction and not (is_next and stage["kind"] == "initial"):
                continue
            selected = correction or rows
            primary = next((row for row in selected if members[row["round_node_id"]]["role"] == "primary"), selected[0])
            requests = primary["request_snapshot"].get("requests", [])
            if not requests:
                continue
            payload = {"include_claim_check": any(request.get("include_claim_check", False) for request in requests),
                       "include_claim_evidence_retrieval": any(request.get("include_claim_evidence_retrieval", False) for request in requests),
                       "claim_post_retrieval_max_iterations": max(request.get("claim_post_retrieval_max_iterations", 0) for request in requests)}
            nodes = [{"skill_node_id": members[row["round_node_id"]]["skill_node_id"],
                      "name": members[row["round_node_id"]]["name"],
                      "tier": members[row["round_node_id"]]["tier"]} for row in selected]
            if correction:
                payload["targets"] = [{"node_id": members[row["round_node_id"]]["skill_node_id"],
                                       "source_attempt_id": row["source_attempt_id"]} for row in correction]
            else:
                review = next((row for row in selected if members[row["round_node_id"]]["role"] == "review"), None)
                payload.update(primary_node_id=members[primary["round_node_id"]]["skill_node_id"],
                               primary_resource_types=primary["resource_types"],
                               review_node_id=members[review["round_node_id"]]["skill_node_id"] if review else None)
            choices.append((stage["created_at"], stage["stage_id"], {
                "confirmed": True, "route": "correction" if correction else "learning",
                "label": "强化巩固" if correction else "下一轮学习", "payload": payload,
                "roundId": round_row["round_id"], "stageId": stage["stage_id"], "nodes": nodes,
            }))
    return sorted(choices, key=lambda item: (item[0], item[1]))[0][2] if choices else None
