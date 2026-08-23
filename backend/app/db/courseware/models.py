"""SQLAlchemy models deliberately separate from generated_resources."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func

from app.db.shared.models import Base


class CoursewareGenerationJobORM(Base):
    __tablename__ = "courseware_generation_jobs"
    __table_args__ = (
        Index("uq_courseware_job_request", "learner_id", "request_hash", unique=True),
    )

    run_id = Column(String(64), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), nullable=True, index=True)
    title = Column(String(160), nullable=True)
    publish_mode = Column(String(16), nullable=False, default="manual")
    source_resource_ids = Column(JSON, nullable=False, default=list)
    source_batch_id = Column(String(128), nullable=True, index=True)
    request_options = Column(JSON, nullable=False, default=dict)
    source_snapshots = Column(JSON, nullable=False, default=list)
    request_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    warnings = Column(JSON, nullable=False, default=list)
    error_code = Column(String(128), nullable=True)
    error_message = Column(String(512), nullable=True)
    resource_id = Column(String(64), nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=0)
    release_policy = Column(String(16), nullable=False, default="resilient")
    next_event_sequence = Column(Integer, nullable=False, default=1)
    deadline_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested_at = Column(DateTime(timezone=True), nullable=True)
    released_release_id = Column(String(96), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class CoursewareWorkflowCheckpointORM(Base):
    __tablename__ = "courseware_workflow_checkpoints"
    __table_args__ = (Index("uq_courseware_checkpoint", "run_id", "stage", "attempt", unique=True),)

    checkpoint_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(32), nullable=False)
    attempt = Column(Integer, nullable=False)
    state_json = Column(JSON, nullable=False, default=dict)
    input_hash = Column(String(64), nullable=False)
    output_hash = Column(String(64), nullable=False)
    workflow_version = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoursewareReleaseORM(Base):
    __tablename__ = "courseware_releases"
    __table_args__ = (Index("uq_courseware_release_candidate", "run_id", "candidate_no", unique=True),)

    release_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id = Column(String(64), nullable=True, index=True)
    candidate_no = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="building", index=True)
    release_policy = Column(String(16), nullable=False)
    scene_set_hash = Column(String(64), nullable=False)
    snapshot_set_hash = Column(String(64), nullable=False)
    manifest_json = Column(JSON, nullable=False, default=dict)
    manifest_sha256 = Column(String(64), nullable=True)
    provenance_json = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(128), nullable=True)
    error_message = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class CoursewareResourceORM(Base):
    __tablename__ = "courseware_resources"

    resource_id = Column(String(64), primary_key=True)
    resource_family_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, unique=True)
    batch_id = Column(String(128), nullable=True, index=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), nullable=True, index=True)
    title = Column(String(160), nullable=False)
    topic = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="published", index=True)
    version = Column(Integer, nullable=False, default=1)
    file_path = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=False)
    artifact_sha256 = Column(String(64), nullable=False)
    renderer_version = Column(String(32), nullable=False)
    runtime_version = Column(String(32), nullable=False)
    source_summary = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    published_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    released_release_id = Column(String(96), nullable=True, index=True)


class CoursewareSourceLinkORM(Base):
    __tablename__ = "courseware_source_links"
    __table_args__ = (
        Index("uq_courseware_source_link", "courseware_resource_id", "source_resource_id", unique=True),
    )

    link_id = Column(String(96), primary_key=True)
    courseware_resource_id = Column(String(64), ForeignKey("courseware_resources.resource_id", ondelete="CASCADE"), nullable=False, index=True)
    source_resource_id = Column(String(64), ForeignKey("generated_resources.resource_id", ondelete="CASCADE"), nullable=False, index=True)
    source_run_id = Column(String(128), nullable=True)
    source_version = Column(Integer, nullable=False, default=1)
    source_content_hash = Column(String(64), nullable=False)
    source_role = Column(String(32), nullable=False)
    source_snapshot = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareSpecORM(Base):
    __tablename__ = "courseware_specs"

    spec_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    prompt_version = Column(String(32), nullable=False, default="deterministic-v1")
    runtime_version = Column(String(32), nullable=False)
    spec_json = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="approved")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareSceneORM(Base):
    __tablename__ = "courseware_scenes"
    __table_args__ = (Index("uq_courseware_scene_order", "spec_id", "scene_order", unique=True),)

    scene_id = Column(String(96), primary_key=True)
    spec_id = Column(String(96), ForeignKey("courseware_specs.spec_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_order = Column(Integer, nullable=False)
    kind = Column(String(32), nullable=False)
    scene_json = Column(JSON, nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="approved", index=True)
    attempt = Column(Integer, nullable=False, default=0)
    input_snapshot_hash = Column(String(64), nullable=False, default="")
    agent_version = Column(String(32), nullable=False, default="deterministic-v1")
    prompt_version = Column(String(32), nullable=False, default="deterministic-v1")
    review_instruction = Column(String(400), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    lease_owner = Column(String(96), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    error_code = Column(String(128), nullable=True)
    error_message = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoursewareSceneRevisionORM(Base):
    __tablename__ = "courseware_scene_revisions"
    __table_args__ = (Index("uq_courseware_scene_revision", "scene_id", "revision_no", unique=True),)

    revision_id = Column(String(96), primary_key=True)
    scene_id = Column(String(96), ForeignKey("courseware_scenes.scene_id", ondelete="CASCADE"), nullable=False, index=True)
    revision_no = Column(Integer, nullable=False)
    trigger = Column(String(32), nullable=False)
    actor_id = Column(String(96), nullable=True)
    reason = Column(String(400), nullable=True)
    before_content_hash = Column(String(64), nullable=True)
    after_content_hash = Column(String(64), nullable=False)
    input_snapshot_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(160), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareOutboxORM(Base):
    __tablename__ = "courseware_outbox"

    outbox_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_id = Column(String(96), nullable=True, index=True)
    event_type = Column(String(64), nullable=False)
    task_kind = Column(String(64), nullable=False, default="courseware.scene.revise")
    status = Column(String(32), nullable=False, default="queued", index=True)
    claimed_by = Column(String(96), nullable=True, index=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error_code = Column(String(128), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    idempotency_key = Column(String(160), nullable=False, unique=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareReviewORM(Base):
    __tablename__ = "courseware_reviews"

    review_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    scene_id = Column(String(96), ForeignKey("courseware_scenes.scene_id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String(32), nullable=False)
    decision = Column(String(32), nullable=False)
    issues = Column(JSON, nullable=False, default=list)
    reviewer_version = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareEventORM(Base):
    __tablename__ = "courseware_events"
    __table_args__ = (Index("uq_courseware_event_sequence", "run_id", "event_sequence", unique=True),)

    event_id = Column(String(96), primary_key=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    event_sequence = Column(Integer, nullable=False)
    stage = Column(String(32), nullable=False)
    scene_id = Column(String(96), nullable=True)
    status = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareLearningEventORM(Base):
    __tablename__ = "courseware_learning_events"
    __table_args__ = (Index("uq_courseware_learning_event_occurrence", "occurrence_id", unique=True),
                      Index("ix_courseware_learning_event_release_order", "resource_id", "release_id", "sequence"))

    event_id = Column(String(160), primary_key=True)
    occurrence_id = Column(String(160), nullable=False)
    event_schema_version = Column(String(16), nullable=False, default="1.0")
    event_type = Column(String(48), nullable=False)
    resource_id = Column(String(128), nullable=False, index=True)
    resource_version = Column(Integer, nullable=False, default=1)
    release_id = Column(String(128), nullable=False, index=True)
    release_version = Column(Integer, nullable=False, default=1)
    scene_id = Column(String(128), nullable=True)
    scene_version = Column(String(16), nullable=False, default="1.0")
    component_id = Column(String(128), nullable=True)
    component_version = Column(String(16), nullable=False, default="1.0")
    state = Column(JSON, nullable=False, default=dict)
    sequence = Column(Integer, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoursewareArtifactORM(Base):
    __tablename__ = "courseware_artifacts"

    artifact_id = Column(String(96), primary_key=True)
    courseware_resource_id = Column(String(64), ForeignKey("courseware_resources.resource_id", ondelete="CASCADE"), nullable=False, index=True)
    release_id = Column(String(96), ForeignKey("courseware_releases.release_id", ondelete="CASCADE"), nullable=True, index=True)
    artifact_format = Column(String(32), nullable=False)
    file_path = Column(String(512), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    manifest = Column(JSON, nullable=False, default=dict)
    required = Column(Integer, nullable=False, default=1)
    artifact_status = Column(String(32), nullable=False, default="ready", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
