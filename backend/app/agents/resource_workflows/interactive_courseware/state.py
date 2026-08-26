"""Serializable state contracts for the interactive-courseware workflow.

The workflow deliberately persists identifiers, versions and hashes rather than
source prose.  Repositories remain the source of truth for the actual scene
and artifact records.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CoursewareWorkflowState:
    run_id: str
    stage: str = "queued"
    spec_id: str | None = None
    snapshot_hashes: dict[str, str] = field(default_factory=dict)
    scene_ids: tuple[str, ...] = ()
    checkpoint_id: str | None = None
    checkpoint_stage: str | None = None
    checkpoint_attempt: int = 0
    input_hash: str | None = None
    output_hash: str | None = None
    workflow_version: str = "courseware-v1"
    completed_nodes: tuple[str, ...] = ()
