"""Persistent needs, wait growth and the fixed remediation ordering."""

from datetime import datetime, timezone

from app.db.feedback.round_memory import MemoryRoundRepository
from app.services.learners.remediation import advance_wait, ranked_needs, update_need


def seed(repository, node, status, score, wait=0):
    now = datetime.now(timezone.utc)
    with repository.transaction() as tx:
        tx.insert("learner_remediation_needs", dict(
            need_id=f"need-{node}", learner_id="learner", knowledge_base_id="kb", skill_node_id=node,
            status=status, first_unresolved_attempt_id="attempt-1", last_attempt_id="attempt-1",
            last_score=score, wait_rounds=wait, updated_at=now,
        ))


def test_ordering_is_status_then_wait_then_score_then_node():
    repository = MemoryRoundRepository()
    seed(repository, "practice-old", "practice", 0.7, wait=9)
    seed(repository, "remediate-slow", "remediate", 0.5, wait=1)
    seed(repository, "remediate-waited", "remediate", 0.5, wait=3)
    seed(repository, "remediate-low", "remediate", 0.2, wait=1)
    seed(repository, "resolved", "resolved", 0.9, wait=0)

    ranked = ranked_needs(repository.find("learner_remediation_needs"))

    assert [row["skill_node_id"] for row in ranked] == [
        "remediate-waited",  # longest wait wins inside remediate
        "remediate-low",     # equal wait: lower score first
        "remediate-slow",
        "practice-old",      # practice never outranks remediate
    ]


def test_wait_growth_skips_the_selected_primary_and_resolved_needs():
    repository = MemoryRoundRepository()
    seed(repository, "other", "remediate", 0.4, wait=2)
    seed(repository, "primary", "remediate", 0.4, wait=0)
    seed(repository, "done", "resolved", 0.9, wait=0)

    with repository.transaction() as tx:
        advance_wait(tx, "learner", "kb", "primary")

    rows = {row["skill_node_id"]: row for row in repository.find("learner_remediation_needs")}
    assert rows["other"]["wait_rounds"] == 3
    assert rows["primary"]["wait_rounds"] == 0
    assert rows["done"]["wait_rounds"] == 0


def test_need_lifecycle_keeps_the_first_unresolved_attempt_and_never_clears_on_failure():
    repository = MemoryRoundRepository()
    with repository.transaction() as tx:
        update_need(tx, "learner", "kb", "node", "attempt-1", 0.3, True)
    first = repository.find("learner_remediation_needs")[0]
    assert (first["status"], first["first_unresolved_attempt_id"]) == ("remediate", "attempt-1")

    with repository.transaction() as tx:
        update_need(tx, "learner", "kb", "node", "attempt-2", 0.7, True)
    practice = repository.find("learner_remediation_needs")[0]
    assert (practice["status"], practice["first_unresolved_attempt_id"], practice["last_attempt_id"]) == (
        "practice", "attempt-1", "attempt-2")

    # Ineligible evidence (audit missing) must not clear an existing need.
    with repository.transaction() as tx:
        update_need(tx, "learner", "kb", "node", "attempt-3", 0.95, False)
    still = repository.find("learner_remediation_needs")[0]
    assert (still["status"], still["last_attempt_id"]) == ("practice", "attempt-2")

    with repository.transaction() as tx:
        update_need(tx, "learner", "kb", "node", "attempt-4", 0.95, True)
    resolved = repository.find("learner_remediation_needs")[0]
    assert resolved["status"] == "resolved"

    # A new low score opens a fresh episode instead of reusing the old start.
    with repository.transaction() as tx:
        update_need(tx, "learner", "kb", "node", "attempt-5", 0.2, True)
    reopened = repository.find("learner_remediation_needs")[0]
    assert (reopened["status"], reopened["first_unresolved_attempt_id"], reopened["wait_rounds"]) == (
        "remediate", "attempt-5", 0)
