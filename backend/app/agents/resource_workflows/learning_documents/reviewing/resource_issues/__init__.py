"""Public entry points for the generic resource reviewer (T44).

This package owns the single shared closed loop for the six text resources
(讲义 / 实操指南 / 分阶测试题 / 案例分析 / 复习清单 / 个性化纠错训练包).
Importing it creates no clients and performs no registration side effects; the
registry validation at import is read-only.
"""

from .engine import ResourceReviewOutcome, review_resource_v1, run_program_gate
from .ledger import (
    append_model_observation_v1,
    append_program_gate_observation_v1,
    replay_resource_ledger,
)
from .persistence import ResourceReviewRepository, verify_binding_hashes
from .registry import REGISTRY, adapter_for, adapter_types, output_schema, profile_fragments
from .revision import (
    ResourceRevisionWorkOrderV1,
    build_revision_work_order,
    failure_placeholder_work_order,
)
from .validation import ValidationError, ValidationOutcome, validate_resource_review

__all__ = [
    "REGISTRY", "adapter_for", "adapter_types", "output_schema", "profile_fragments",
    "review_resource_v1", "run_program_gate", "ResourceReviewOutcome",
    "append_model_observation_v1", "append_program_gate_observation_v1",
    "replay_resource_ledger", "ResourceReviewRepository", "verify_binding_hashes",
    "ResourceRevisionWorkOrderV1", "build_revision_work_order",
    "failure_placeholder_work_order", "ValidationError", "ValidationOutcome",
    "validate_resource_review",
]
