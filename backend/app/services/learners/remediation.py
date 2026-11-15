"""Persistent unresolved needs, independent of production scheduling."""

from datetime import datetime, timezone

from app.models.shared.persistence import canonical_hash


def update_need(repository, learner_id, knowledge_base_id, node_id, attempt_id, score, eligible=True):
    old = repository.one("learner_remediation_needs", learner_id=learner_id,
                         knowledge_base_id=knowledge_base_id, skill_node_id=node_id)
    if not eligible:
        return old
    status = "remediate" if score < .6 else "practice" if score < .8 else "resolved"
    values = dict(status=status, last_attempt_id=attempt_id, last_score=score, updated_at=datetime.now(timezone.utc))
    if old:
        if old["last_attempt_id"] == attempt_id:
            return old
        if old["status"] == "resolved" and status != "resolved":
            values.update(first_unresolved_attempt_id=attempt_id, wait_rounds=0)
        return repository.compare_and_set("learner_remediation_needs", old["need_id"], old["row_version"], values)
    return repository.insert("learner_remediation_needs", dict(
        need_id="need_" + canonical_hash([learner_id, knowledge_base_id, node_id])[:48],
        learner_id=learner_id, knowledge_base_id=knowledge_base_id, skill_node_id=node_id,
        first_unresolved_attempt_id=attempt_id, wait_rounds=0, **values,
    ))


def advance_wait(repository, learner_id, knowledge_base_id, primary_node_id):
    for row in repository.find("learner_remediation_needs", learner_id=learner_id, knowledge_base_id=knowledge_base_id):
        if row["status"] != "resolved" and row["skill_node_id"] != primary_node_id:
            repository.compare_and_set("learner_remediation_needs", row["need_id"], row["row_version"], {
                "wait_rounds": row["wait_rounds"] + 1, "updated_at": datetime.now(timezone.utc),
            })


def ranked_needs(rows):
    return sorted((row for row in rows if row["status"] != "resolved"), key=lambda row: (
        0 if row["status"] == "remediate" else 1, -row["wait_rounds"], row["last_score"], row["skill_node_id"],
    ))
