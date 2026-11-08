"""Review service domain: the single public entry for quality metrics."""

__all__ = [
    "ResourceQualityNotFound",
    "ResourceQualityQueryService",
    "ReviewService",
    "aggregate_quality_summary",
    "compute_competition_claim_metrics",
    "evaluate_difficulty_fixtures",
    "ordinary_coverage_metric",
]


def __getattr__(name: str):
    if name == "ReviewService":
        from app.services.reviews.reviews import ReviewService

        return ReviewService
    if name == "compute_competition_claim_metrics":
        from app.services.reviews.claim_evaluation import compute_competition_claim_metrics

        return compute_competition_claim_metrics
    if name == "evaluate_difficulty_fixtures":
        from app.services.reviews.claim_evaluation import evaluate_difficulty_fixtures

        return evaluate_difficulty_fixtures
    if name in {"ResourceQualityQueryService", "ResourceQualityNotFound"}:
        from app.services.reviews import quality_query

        return getattr(quality_query, name)
    if name == "aggregate_quality_summary":
        from app.services.reviews.quality_metrics import aggregate_quality_summary

        return aggregate_quality_summary
    if name == "ordinary_coverage_metric":
        from app.services.reviews.quality_metrics import ordinary_coverage_metric

        return ordinary_coverage_metric
    raise AttributeError(name)
