"""Single asset-free estimator factory. Old PROFILE_PATH/ID are ignored."""
from app.core.llm.counting import CharacterEstimator, EstimateParameters


def load_counter(settings, gateway=None):
    return CharacterEstimator(EstimateParameters(
        ascii_weight=settings.claim_estimate_ascii_weight,
        cjk_weight=settings.claim_estimate_cjk_weight,
        unicode_weight=settings.claim_estimate_unicode_weight,
        margin=settings.claim_estimate_margin,
        message_overhead=settings.claim_estimate_message_overhead,
        request_overhead=settings.claim_estimate_request_overhead))
