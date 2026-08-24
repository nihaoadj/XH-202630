"""Review service domain."""

__all__ = ["ReviewService", "compute_competition_claim_metrics"]


def __getattr__(name: str):
    if name == "ReviewService":
        from app.services.reviews.reviews import ReviewService

        return ReviewService
    if name == "compute_competition_claim_metrics":
        from app.services.reviews.claim_evaluation import compute_competition_claim_metrics

        return compute_competition_claim_metrics
    raise AttributeError(name)
