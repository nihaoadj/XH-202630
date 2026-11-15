"""Existing courseware stage order, shared by replay and persistence sorting."""

from types import MappingProxyType


COURSEWARE_CHECKPOINT_STAGE_ORDER = MappingProxyType({
    "snapshot": 1, "design": 2, "scenes": 3, "rule_review": 4,
    "quality_review": 5, "candidate_artifact": 6, "release": 7,
})
