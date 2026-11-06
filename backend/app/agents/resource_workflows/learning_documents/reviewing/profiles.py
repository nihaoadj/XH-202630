"""The single explicit registry of resource/phase review profiles."""

from types import MappingProxyType

from app.models.learning_documents.types import canonical_resource_type
from app.models.reviews.review_audit import PROFILE_VERSIONS, ReviewPolicySnapshotV1
from app.models.shared.agent_contracts import AssessmentCombinedReviewV2, AssessmentScopeReviewV1, PracticeGuidePackageV3, ReviewLLMOutput

from .prompts.common import COMMON, EMPTY, OUTPUT
from .prompts.resources.assessment import COMBINED, PACKAGE, SCOPE
from .prompts.resources.case_study import CASE_STUDY
from .prompts.resources.checklist import CHECKLIST
from .prompts.resources.correction_package import CORRECTION_PACKAGE
from .prompts.resources.practice import PRACTICE
from .prompts.resources.text import TEXT
from .prompts.specialties.code import CODE
from .types import ReviewProfile


def _profile(resource_type, phase, fragments, schema=ReviewLLMOutput, role="reviewer", specialties=(), budget=12288):
    return ReviewProfile(resource_type, phase, PROFILE_VERSIONS[phase], fragments, specialties, schema, role, budget)


_PROFILES = MappingProxyType({
    ("讲义", "content_v2"): _profile("讲义", "content_v2", (COMMON, TEXT, OUTPUT)),
    ("案例分析", "content_v2"): _profile("案例分析", "content_v2", (COMMON, CASE_STUDY, OUTPUT)),
    ("复习清单", "content_v2"): _profile("复习清单", "content_v2", (COMMON, CHECKLIST, OUTPUT)),
    ("个性化纠错训练包", "content_v2"): _profile("个性化纠错训练包", "content_v2", (COMMON, CORRECTION_PACKAGE, OUTPUT)),
    ("实操指南", "practice_semantic_v2"): _profile("实操指南", "practice_semantic_v2", (COMMON, PRACTICE, OUTPUT), specialties=(CODE,)),
    ("分阶测试题", "assessment_scope_v1"): _profile("分阶测试题", "assessment_scope_v1", (SCOPE,), AssessmentScopeReviewV1, "assessment_scope_reviewer", budget=None),
    ("分阶测试题", "assessment_package_v1"): _profile("分阶测试题", "assessment_package_v1", (COMMON, PACKAGE, OUTPUT)),
    ("分阶测试题", "assessment_combined_v2"): _profile("分阶测试题", "assessment_combined_v2", (COMMON, COMBINED, OUTPUT), AssessmentCombinedReviewV2, budget=None),
    ("__empty_resource__", "empty_resource_compat_v1"): _profile("__empty_resource__", "empty_resource_compat_v1", (EMPTY,), budget=None),
})


def resolve_review_profile(*, resource_type: str, phase: str, policy: ReviewPolicySnapshotV1 | dict | None = None) -> ReviewProfile:
    if phase in {"lecture_initial_v1", "lecture_recheck_v1"}:
        if canonical_resource_type(resource_type) != "讲义":
            raise ValueError("lecture profile cannot review another resource type")
        from .lecture_engine import lecture_profile
        return lecture_profile(phase)
    selected = ReviewPolicySnapshotV1.model_validate(policy or {})
    canonical = resource_type if resource_type == "__empty_resource__" and phase == "empty_resource_compat_v1" else canonical_resource_type(resource_type)
    profile = _PROFILES.get((canonical, phase))
    if profile is None:
        raise ValueError("unknown review profile")
    if phase == "assessment_combined_v2" and selected.assessment_strategy != "combined_v2":
        raise ValueError("combined review is not selected by the frozen policy")
    if selected.profile_versions[phase] != profile.version:
        raise ValueError("review profile version mismatch")
    return profile


def select_specialties(*, profile: ReviewProfile, resource) -> tuple[str, ...]:
    if profile.resource_type != "实操指南":
        return ()
    package = PracticeGuidePackageV3.model_validate({k: v for k, v in (resource.practice_guide_payload or {}).items() if k != "payload_hash"})
    # Read the validated schema, never infer code from keywords in Markdown.
    def has_code(value):
        if isinstance(value, dict):
            return bool(value.get("code_blocks")) or any(has_code(v) for v in value.values())
        return isinstance(value, list) and any(has_code(v) for v in value)
    return (CODE.id,) if has_code(package.model_dump(mode="python")) else ()
