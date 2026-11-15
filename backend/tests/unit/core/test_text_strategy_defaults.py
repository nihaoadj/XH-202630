"""Default text strategies freeze new policies without making provider calls."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.llm.counting import CharacterEstimator
from app.agents.resource_workflows.learning_documents.claim_extraction.budget import frozen_snapshot
from app.services.generation.resource_review_policy import freeze_resource_review_policy
from app.services.generation.lecture_policy import freeze_lecture_policy
from tests.fakes.claim_extraction import NeutralScriptedGateway


@pytest.fixture(autouse=True)
def isolate_strategy_environment(monkeypatch):
    for key in (
        "RESOURCE_REVIEW_STRATEGY", "RESOURCE_REVIEW_CONTEXT_TOKENS",
        "CLAIM_EXTRACTION_STRATEGY", "LECTURE_REVIEW_STRATEGY",
        "LECTURE_REVIEW_CONTEXT_TOKENS", "LLM_THINKING_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_strategies_freeze_new_review_and_claim_policies():
    settings = Settings(_env_file=None, resource_review_context_tokens=129024)
    request = SimpleNamespace(include_review=True, include_claim_check=True, resource_types=["讲义"])
    assert settings.resource_review_strategy == "resource_issue_v1"
    assert settings.claim_extraction_strategy == "neutral_estimate_v1"
    assert freeze_lecture_policy(request, settings) == {}
    review = freeze_resource_review_policy(request, settings)
    assert review["resource_review_policy"]["strategy"] == "resource_issue_v1"
    assert review["resource_review_policy"]["context_tokens"] == 129024
    claim = frozen_snapshot(settings, request, NeutralScriptedGateway([]), CharacterEstimator())
    assert claim["claim_extraction_mode"] == "neutral_estimate_v1"
    assert claim["claim_extraction_policy"]["source_locating"]["mode"] == "tolerant_v1"
    assert claim["claim_extraction_policy"]["source_locating"]["locator_algorithm_version"] == "locator-v2"


def test_new_default_still_requires_explicit_model_window():
    with pytest.raises(ValidationError, match="RESOURCE_REVIEW_CONTEXT_TOKENS is required"):
        Settings(_env_file=None)


def test_explicit_legacy_strategies_remain_available():
    settings = Settings(_env_file=None, resource_review_strategy="compat", claim_extraction_strategy="legacy_v3")
    request = SimpleNamespace(include_review=True, include_claim_check=True, resource_types=["讲义"])
    assert freeze_resource_review_policy(request, settings) == {}
    assert frozen_snapshot(settings, request, None, None) == {}


def test_deployment_environment_can_override_strategy_defaults(monkeypatch):
    monkeypatch.setenv("RESOURCE_REVIEW_STRATEGY", "compat")
    monkeypatch.setenv("CLAIM_EXTRACTION_STRATEGY", "legacy_v3")
    settings = Settings(_env_file=None)
    assert settings.resource_review_strategy == "compat"
    assert settings.claim_extraction_strategy == "legacy_v3"
