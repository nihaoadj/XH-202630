"""SQLAlchemy models deliberately separate from generated_resources."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func

from app.db.models import Base


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
    source_snapshots = Column(JSON, nullable=False, default=list)
    request_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    warnings = Column(JSON, nullable=False, default=list)
    error_code = Column(String(128), nullable=True)
    error_message = Column(String(512), nullable=True)
    resource_id = Column(String(64), nullable=True, index=True)
    attempt = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class CoursewareResourceORM(Base):
    __tablename__ = "courseware_resources"

    resource_id = Column(String(64), primary_key=True)
    resource_family_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(64), ForeignKey("courseware_generation_jobs.run_id", ondelete="CASCADE"), nullable=False, unique=True)
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
    error_code = Column(String(128), nullable=True)
    error_message = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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


class CoursewareArtifactORM(Base):
    __tablename__ = "courseware_artifacts"

    artifact_id = Column(String(96), primary_key=True)
    courseware_resource_id = Column(String(64), ForeignKey("courseware_resources.resource_id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_format = Column(String(32), nullable=False)
    file_path = Column(String(512), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    manifest = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
