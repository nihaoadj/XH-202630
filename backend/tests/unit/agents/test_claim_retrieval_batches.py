"""Bounded retrieval associations, including a query shared by many Claims."""
import pytest
from types import SimpleNamespace

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.retrieval import plan_retrieval_batches
from app.models.reviews.claim_evidence_retrieval import batch_id_for
from app.models.shared.persistence import canonical_hash


def policy():
    return SimpleNamespace(queries_per_request=6)


@pytest.mark.parametrize("count", [8, 16, 19, 40])
@pytest.mark.parametrize("shared", [False, True])
def test_batches_keep_every_association_with_bounded_queries_and_claims(count, shared):
    selected = {f"claim-{i}": (("shared" if shared else f"query-{i}"),) for i in range(count)}
    plans = plan_retrieval_batches(selected, session_id="session", policy=policy())
    assert plans == plan_retrieval_batches(selected, session_id="session", policy=policy())
    actual = set()
    for plan in plans:
        assert len(plan.queries) <= 6
        assert len({cid for ids in plan.claim_ids_by_query.values() for cid in ids}) <= 16
        actual.update((cid, query) for query, ids in plan.claim_ids_by_query.items() for cid in ids)
    assert actual == {(cid, query) for cid, queries in selected.items() for query in queries}


def test_old_valid_plan_keeps_batch_ids_and_hashes_with_partial_persisted_batch():
    selected = {f"claim-{i}": (f"query-{i}",) for i in range(15)}
    plans = plan_retrieval_batches(selected, session_id="session", policy=policy())
    for ordinal, start in enumerate(range(0, 15, 6)):
        chunk = [f"query-{i}" for i in range(start, min(start+6,15))]
        payload = {"queries": chunk, "claims": {f"query-{i}":[f"claim-{i}"] for i in range(start,min(start+6,15))}}
        digest = canonical_hash(payload)
        assert plans[ordinal].input_hash == digest
        assert plans[ordinal].batch_id == batch_id_for(session_id="session", kind="retrieve", ordinal=ordinal, input_hash=digest)
