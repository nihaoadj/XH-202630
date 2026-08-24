from app.models.reviews.claims import (
    ClaimCandidate,
    ClaimJudgementCandidate,
    ClaimType,
    ClaimVerdict,
    materialize_claims,
    materialize_judgements,
)
from app.models.learning_documents.schemas import LearningResource
from app.services.reviews.claim_evaluation import (
    DifficultyFixtureResult,
    compute_competition_claim_metrics,
    evaluate_difficulty_fixtures,
)


def _resource(resource_id, version, publication_status, parent=None):
    return LearningResource(
        resource_id=resource_id,
        resource_type="讲义",
        difficulty="初级",
        content_text="事实",
        knowledge_points=["skill-a"],
        source_refs=[],
        version=version,
        parent_resource_id=parent,
        publication_status=publication_status,
    )


def _claim(resource_id, version, verdict):
    claims = materialize_claims(
        candidates=[ClaimCandidate(
            claim_text="事实",
            claim_type=ClaimType.FACTUAL,
            source_text="事实",
            source_start=0,
            source_end=2,
            knowledge_point_id="skill-a",
        )],
        resource_content="事实",
        resource_id=resource_id,
        resource_version=version,
        review_id=f"rev-{resource_id}",
        run_id="run",
        allowed_evidence_ids={"ev"},
        allowed_knowledge_point_ids={"skill-a"},
        extractor_prompt_version="v1",
        extractor_model=None,
    )
    evidence_ids = [] if verdict == ClaimVerdict.NOT_IN_EVIDENCE else ["ev"]
    judgements = materialize_judgements(
        claims=claims,
        candidates=[ClaimJudgementCandidate(
            claim_id=claims[0].claim_id,
            verdict=verdict,
            evidence_ids=evidence_ids,
            reason="判定",
            confidence=1.0,
        )],
        allowed_evidence_ids={"ev"},
        judge_prompt_version="v1",
        judge_model=None,
    )
    return claims, judgements


def test_competition_metric_only_counts_final_published_leaf():
    old_claims, old_judgements = _claim("old", 1, ClaimVerdict.NOT_IN_EVIDENCE)
    final_claims, final_judgements = _claim("final", 2, ClaimVerdict.SUPPORTED)
    metrics = compute_competition_claim_metrics(
        resources=[_resource("old", 1, "unpublished"), _resource("final", 2, "published", "old")],
        claims=old_claims + final_claims,
        judgements=old_judgements + final_judgements,
        target_skill_node_ids=["skill-a", "skill-b"],
    )
    assert metrics.factual_claim_total == 1
    assert metrics.claim_hallucination_rate == 0.0
    assert metrics.knowledge_coverage_rate == 0.5


def test_difficulty_evaluation_uses_fixed_fixture_version_and_confusion_matrix():
    result = evaluate_difficulty_fixtures([
        DifficultyFixtureResult(case_id="1", fixture_version="gold-v1", expected_difficulty="初级", predicted_difficulty="初级"),
        DifficultyFixtureResult(case_id="2", fixture_version="gold-v1", expected_difficulty="中级", predicted_difficulty="初级"),
    ])
    assert result.accuracy == 0.5
    assert result.confusion_matrix["中级"]["初级"] == 1
