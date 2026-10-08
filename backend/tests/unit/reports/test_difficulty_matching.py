from app.services.reports.difficulty_matching import match_difficulty, normalize_declared_difficulty


def test_declared_difficulty_normalization_is_conservative_for_unknown_labels():
    assert normalize_declared_difficulty("初级") == (0.35, "declared_band")
    assert normalize_declared_difficulty("INTERMEDIATE") == (0.65, "declared_band")
    assert normalize_declared_difficulty("自定义难度") == (None, "unavailable")


def test_difficulty_match_uses_documented_boundaries_and_keeps_missing_data_null():
    assert match_difficulty(learner_readiness=0.51, declared_difficulty="初级").status == "too_easy"
    assert match_difficulty(learner_readiness=0.55, declared_difficulty="中级").status == "matched"
    assert match_difficulty(learner_readiness=0.54, declared_difficulty="中级").status == "challenging"
    assert match_difficulty(learner_readiness=0.39, declared_difficulty="中级").status == "too_hard"

    no_readiness = match_difficulty(learner_readiness=None, declared_difficulty="初级")
    assert no_readiness.gap is None
    assert no_readiness.status == "not_measured"
    no_resource_score = match_difficulty(learner_readiness=0.60, declared_difficulty="未知")
    assert no_resource_score.score is None
    assert no_resource_score.gap is None
    assert no_resource_score.status == "not_measured"
