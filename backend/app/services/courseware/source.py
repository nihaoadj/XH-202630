"""Compatibility exports; implementation belongs to app.agents.resource_workflows.interactive_courseware.source."""

from app.agents.resource_workflows.interactive_courseware.source import (
    ROLE_BY_TYPE as ROLE_BY_TYPE,
    CoursewareAdmissionError as CoursewareAdmissionError,
    content_hash as content_hash,
    _clip as _clip,
    _knowledge_base_id as _knowledge_base_id,
    _practice_source_blocks as _practice_source_blocks,
    _structured_practice_source_blocks as _structured_practice_source_blocks,
    _required_practice_package as _required_practice_package,
    _snapshot as _snapshot,
    admit_and_snapshot as admit_and_snapshot,
    frozen_source_batch_id as frozen_source_batch_id,
)
