"""Stable public contracts for the interactive-courseware domain."""

from app.models.courseware.contracts import (
    CoursewareEvent,
    CoursewareJobCreateRequest,
    CoursewareBatchCreateRequest,
    CoursewareBatchJobResponse,
    CoursewareJobDetail,
    CoursewareJobListResponse,
    CoursewareJobResponse,
    CoursewareJobState,
    CoursewareResourceDetail,
    CoursewareSceneStatus,
    CoursewareSourceSummary,
)
from app.models.courseware.provenance import ProvenanceEdge, ProvenanceGraph, ProvenanceNode
from app.models.courseware.design import CoursewareDesign, LayoutSpec, MotionSpec, ThemeSpec
from app.models.courseware.events import CoursewareEventType, CoursewareLearningEvent

__all__ = [
    "CoursewareEvent",
    "CoursewareJobCreateRequest",
    "CoursewareBatchCreateRequest",
    "CoursewareBatchJobResponse",
    "CoursewareJobDetail",
    "CoursewareJobListResponse",
    "CoursewareJobResponse",
    "CoursewareJobState",
    "CoursewareResourceDetail",
    "CoursewareSceneStatus",
    "CoursewareSourceSummary",
    "ProvenanceEdge",
    "ProvenanceGraph",
    "ProvenanceNode",
    "CoursewareDesign",
    "ThemeSpec",
    "LayoutSpec",
    "MotionSpec",
    "CoursewareEventType",
    "CoursewareLearningEvent",
]
