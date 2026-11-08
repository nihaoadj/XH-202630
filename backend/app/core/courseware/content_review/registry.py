"""The sole static source/schema adapter registry. Tests may inject a registry."""
from types import MappingProxyType
from app.core.courseware.content_review.adapters.review_practice import ReviewPracticeAdapter
from app.core.courseware.content_review.adapters.practice_guide import PracticeGuideAdapter
from app.models.courseware.content_review import ContentReviewBlocked

ADAPTERS = MappingProxyType({("复习清单", "2.0"): ReviewPracticeAdapter(), ("实操指南", "3.0"): PracticeGuideAdapter()})


def resolve_adapter(snapshot, registry=ADAPTERS):
    versions = [v["schema_version"] for k, v in snapshot.items() if k.endswith("_payload") and isinstance(v, dict) and "schema_version" in v]
    if len(versions) != 1:
        raise ContentReviewBlocked("ambiguous source schema")
    try:
        return registry[(snapshot["resource_type"], versions[0])]
    except KeyError as exc:
        raise ContentReviewBlocked("unknown adapter version") from exc
