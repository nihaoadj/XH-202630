import json

from app.agents.policies import may_publish
from app.db.claim.memory import MemoryClaimRepository
from app.models.claims import (
    ClaimCandidate,
    ClaimJudgementCandidate,
    ClaimType,
    ClaimVerdict,
    materialize_claims,
    materialize_judgements,
)
from app.models.schemas import LearningResource
from app.services.claim_evaluation import compute_competition_claim_metrics
from app.services.p0_09_acceptance import (
    FIXTURE_VERSION,
    SUITE_ID,
    SUITE_VERSION,
    build_safe_evidence_bundle,
    evaluate_official_metrics,
    load_suite,
    safe_fixture_summary,
)


def _audit(*, resource_id, version, verdict):
    text = "RRF 使用排名倒数进行融合。"
    evidence = [] if verdict == ClaimVerdict.NOT_IN_EVIDENCE else ["ev-p009"]
    claims = materialize_claims(
        candidates=[ClaimCandidate(
            claim_text=text,
            claim_type=ClaimType.FACTUAL,
            source_text=text,
            source_start=0,
            source_end=len(text),
            knowledge_point_id="kp-rrf",
            source_evidence_ids=evidence,
        )],
        resource_content=text,
        resource_id=resource_id,
        resource_version=version,
        review_id=f"review-{resource_id}",
        run_id="run-p009-claim-revision",
        allowed_evidence_ids={"ev-p009"},
        allowed_knowledge_point_ids={"kp-rrf"},
        extractor_prompt_version="p009-v1",
        extractor_model=None,
    )
    judgements = materialize_judgements(
        claims=claims,
        candidates=[ClaimJudgementCandidate(
            claim_id=claims[0].claim_id,
            verdict=verdict,
            evidence_ids=evidence,
            reason="固定 fixture 判定",
            confidence=1.0,
        )],
        allowed_evidence_ids={"ev-p009"},
        judge_prompt_version="p009-v1",
        judge_model=None,
    )
    return claims, judgements


def test_fixture_suite_is_versioned_stable_and_complete():
    suite = load_suite()
    assert suite["suite_id"] == SUITE_ID
    assert suite["suite_version"] == SUITE_VERSION
    assert suite["fixture_version"] == FIXTURE_VERSION
    assert suite["knowledge"]["document_version"].startswith("dv_")
    assert all(value.startswith("chk_") for value in suite["knowledge"]["chunk_ids"])
    assert len(suite["learners"]) == 3
    assert len(set(suite["resource_types"])) >= 3
    assert len(suite["failure_injections"]) == 10


def test_small_fixture_values_are_not_reported_as_official_metric_passes():
    metrics = evaluate_official_metrics(load_suite())
    by_id = {item.metric_id: item for item in metrics}
    assert by_id["M-HALLUCINATION"].actual_value == 0.0
    assert by_id["M-DIFFICULTY"].actual_value == 1.0
    assert by_id["M-COVERAGE"].actual_value == 1.0
    assert {item.status for item in metrics} == {"NOT_MEASURABLE"}
    assert by_id["M-FEEDBACK-UPLIFT"].actual_value is None


def test_safe_fixture_summary_excludes_sensitive_and_free_text_payloads():
    encoded = str(safe_fixture_summary(load_suite())).lower()
    for forbidden in ("api_key", "prompt", "raw provider", "learning_goal", "answers"):
        assert forbidden not in encoded


def test_claim_revision_preserves_v1_and_v2_audits():
    repository = MemoryClaimRepository()
    v1_claims, v1_judgements = _audit(
        resource_id="resource-v1",
        version=1,
        verdict=ClaimVerdict.NOT_IN_EVIDENCE,
    )
    v2_claims, v2_judgements = _audit(
        resource_id="resource-v2",
        version=2,
        verdict=ClaimVerdict.SUPPORTED,
    )
    repository.save_audit(v1_claims, v1_judgements)
    repository.save_audit(v2_claims, v2_judgements)

    claims = repository.list_claims_by_run("run-p009-claim-revision")
    judgements = repository.list_judgements_by_run("run-p009-claim-revision")
    assert len(claims) == len(judgements) == 2
    assert claims[0].claim_id != claims[1].claim_id
    assert {item.resource_version for item in claims} == {1, 2}
    assert {item.verdict for item in judgements} == {
        ClaimVerdict.NOT_IN_EVIDENCE,
        ClaimVerdict.SUPPORTED,
    }

    resources = [
        LearningResource(
            resource_id="resource-v1",
            resource_type="讲义",
            difficulty="初级",
            content_text="v1",
            knowledge_points=["kp-rrf"],
            source_refs=[],
            version=1,
            publication_status="unpublished",
        ),
        LearningResource(
            resource_id="resource-v2",
            resource_type="讲义",
            difficulty="初级",
            content_text="v2",
            knowledge_points=["kp-rrf"],
            source_refs=[],
            version=2,
            parent_resource_id="resource-v1",
            publication_status="published",
        ),
    ]
    metric = compute_competition_claim_metrics(
        resources=resources,
        claims=claims,
        judgements=judgements,
        target_skill_node_ids=["kp-rrf"],
    )
    assert metric.metric_status == "complete"
    assert metric.claim_hallucination_rate == 0.0
    assert metric.knowledge_coverage_rate == 1.0


def test_publication_policy_rejects_every_non_final_review_state():
    assert may_publish(decision="approve", review_status="approved", is_leaf=True)
    unsafe = [
        ("approve", "draft", True),
        ("approve", "unreviewed_draft", True),
        ("revise", "revision_requested", True),
        ("reject", "rejected", True),
        ("human_review", "human_review", True),
        ("approve", "approved", False),
    ]
    assert not any(
        may_publish(decision=decision, review_status=status, is_leaf=is_leaf)
        for decision, status, is_leaf in unsafe
    )


def test_safe_evidence_bundle_is_allowlisted():
    bundle = build_safe_evidence_bundle(
        run_id="run-safe-1",
        timeline_summary={
            "status": "completed",
            "last_event_sequence": 12,
            "step_count": 7,
            "revision_count": 1,
            "prompt": "must not leak",
        },
        resource_versions=[{
            "resource_id": "res-1",
            "resource_type": "tutorial",
            "version": 2,
            "publication_status": "published",
            "raw_model_response": "must not leak",
        }],
        review_decisions=[{"review_id": "rev-1", "decision": "approve", "reason": "private"}],
        claim_metric_summary={"metric_status": "complete", "factual_claim_total": 3, "prompt": "private"},
        evidence_items=[{"evidence_id": "ev-1", "chunk_id": "chk-1", "locator": "section-1", "excerpt": "private"}],
        feedback_summary={"attempt_id": "att-1", "action": "advance", "learner_name": "private"},
        child_run_ids=["run-child-1"],
    )

    encoded = json.dumps(bundle, ensure_ascii=False)
    assert bundle["bundle_schema"] == "p0-09-safe-evidence-v1"
    assert bundle["child_run_ids"] == ["run-child-1"]
    assert "must not leak" not in encoded
    assert "private" not in encoded
    assert "prompt" not in encoded
