"""Container wiring for round append/recovery transactions."""

from app.config import Settings
from app.containers import Container


def test_round_uow_factory_opens_fresh_transactions_on_the_container_repositories(monkeypatch):
    # The deployment .env owned by the operator is not part of this test.
    monkeypatch.setenv("RESOURCE_REVIEW_CONTEXT_TOKENS", "129024")
    settings = Settings(_env_file=None, db_type="memory")
    container = Container()
    container.config.from_dict(settings.model_dump(mode="python"))

    first = container.round_uow_factory()
    second = container.round_uow_factory()
    assert first is not second
    # Append/retry must write through the same repository objects the round
    # facade and the job service read; class-level provider copies would not.
    assert first.original_rounds is container.round_repository()
    assert first.original_feedback is container.feedback_service()
    assert first.original_learners is container.learner_repository()
    with first as uow:
        assert uow.rounds is container.round_repository()
