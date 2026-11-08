"""Read-only registry: resource type -> adapter + profile + output schema.

The generic engine has exactly one implementation; per-type behaviour lives in
the adapter and the explicitly selected prompt fragments.  There is no dynamic
discovery, no reflection and no fallback to a legacy reviewer here.
"""

from __future__ import annotations

from types import MappingProxyType

from app.models.reviews.resource_review import (
    ResourceReviewInitialV1,
    ResourceReviewRecheckV1,
)
from app.models.reviews.resource_review_policy import RESOURCE_ADAPTER_TYPES, validate_registry_mapping

from .adapters.assessment import AssessmentAdapter
from .adapters.base import ResourceReviewAdapter
from .adapters.case_study import CaseStudyAdapter
from .adapters.checklist import ChecklistAdapter
from .adapters.correction_package import CorrectionPackageAdapter
from .adapters.lecture import LectureAdapter
from .adapters.practice import PracticeAdapter
from .prompts import resource_profile_fragments


_ADAPTERS = {
    "讲义": LectureAdapter,
    "实操指南": PracticeAdapter,
    "分阶测试题": AssessmentAdapter,
    "案例分析": CaseStudyAdapter,
    "复习清单": ChecklistAdapter,
    "个性化纠错训练包": CorrectionPackageAdapter,
}


def adapter_types() -> tuple[str, ...]:
    return tuple(_ADAPTERS)


def adapter_for(resource_type: str) -> ResourceReviewAdapter:
    adapter_type = _ADAPTERS.get(resource_type)
    if adapter_type is None:
        raise ValueError(f"no resource review adapter for {resource_type!r}")
    return adapter_type()


def profile_fragments(resource_type: str):
    return resource_profile_fragments(resource_type)


def output_schema(resource_type: str, *, recheck: bool):
    adapter_for(resource_type)  # validate the type first
    return ResourceReviewRecheckV1 if recheck else ResourceReviewInitialV1


# Fails at import if the frozen type set and the adapter set ever drift.
validate_registry_mapping(dict.fromkeys(_ADAPTERS, True))

REGISTRY = MappingProxyType({name: cls() for name, cls in _ADAPTERS.items()})

__all__ = ["REGISTRY", "adapter_for", "adapter_types", "output_schema",
           "profile_fragments", "RESOURCE_ADAPTER_TYPES"]
