from dataclasses import FrozenInstanceError
import importlib

import pytest

from app.agents.resource_workflows.learning_documents.reviewing import resolve_review_profile, select_specialties
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.review_audit import ReviewPolicySnapshotV1
from tests.fakes.resource_reviews import case


@pytest.mark.parametrize("kind,phase,schema", [
    ("讲义", "content_v2", "ReviewLLMOutput"), ("定制讲义", "content_v2", "ReviewLLMOutput"),
    ("案例分析", "content_v2", "ReviewLLMOutput"), ("复习清单", "content_v2", "ReviewLLMOutput"),
    ("个性化纠错训练包", "content_v2", "ReviewLLMOutput"), ("实操指南", "practice_semantic_v2", "ReviewLLMOutput"),
    ("分阶测试题", "assessment_scope_v1", "AssessmentScopeReviewV1"),
    ("分阶测试题", "assessment_package_v1", "ReviewLLMOutput"),
    ("分阶测试题", "assessment_combined_v2", "AssessmentCombinedReviewV2"),
    ("__empty_resource__", "empty_resource_compat_v1", "ReviewLLMOutput"),
])
def test_profiles_bind_exact_schema_and_immutable_rules(kind, phase, schema):
    policy = ReviewPolicySnapshotV1(assessment_strategy="combined_v2", combined_context_tokens=262144)
    profile = resolve_review_profile(resource_type=kind, phase=phase, policy=policy)
    assert profile.output_schema.__name__ == schema
    with pytest.raises(FrozenInstanceError):
        profile.phase = "unknown"


@pytest.mark.parametrize("kind,phase", [("unknown", "content_v2"), ("讲义", "unknown"), ("讲义", "practice_semantic_v2"), ("__empty_resource__", "content_v2"), ("分阶测试题", "assessment_combined_v2")])
def test_unknown_or_unselected_profiles_fail(kind, phase):
    with pytest.raises(ValueError):
        resolve_review_profile(resource_type=kind, phase=phase)


@pytest.mark.parametrize("case_id,expected", [("practice.clean.01", ("specialty.code",)), ("practice.clean.07", ())])
def test_only_validated_nonempty_code_blocks_select_code_specialty(case_id, expected):
    resource = LearningResource.model_validate(case(case_id)["resource"])
    profile = resolve_review_profile(resource_type="实操指南", phase="practice_semantic_v2")
    assert select_specialties(profile=profile, resource=resource) == expected
    resource.practice_guide_payload = None
    with pytest.raises(ValueError):
        select_specialties(profile=profile, resource=resource)


def test_import_has_no_settings_or_model_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("import must not construct settings or invoke a model")
    monkeypatch.setattr("app.config.get_settings", forbidden)
    monkeypatch.setattr("app.core.llm.gateway.LLMGateway.invoke_structured", forbidden)
    module = importlib.import_module("app.agents.resource_workflows.learning_documents.reviewing")
    importlib.reload(module)
