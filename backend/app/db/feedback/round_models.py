"""Learning-round facts. Imported explicitly by the round migration."""

from sqlalchemy import Column, Boolean, Float, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, CheckConstraint, text

from app.db.shared.models import Base


class LearningRoundORM(Base):
    __tablename__ = "learning_rounds"
    __table_args__ = (
        UniqueConstraint("learner_id", "selection_key", name="uq_round_selection"),
        Index("uq_round_source", "learner_id", "protocol_version", "source_attempt_id", unique=True,
              sqlite_where=text("source_attempt_id IS NOT NULL"), postgresql_where=text("source_attempt_id IS NOT NULL")),
        Index("uq_round_next", "parent_round_id", unique=True,
              sqlite_where=text("parent_round_id IS NOT NULL AND protocol_version = 'learning-round/v1'"),
              postgresql_where=text("parent_round_id IS NOT NULL AND protocol_version = 'learning-round/v1'")),
        Index("ix_round_page", "learner_id", "created_at", "round_id"),
        CheckConstraint("protocol_version IN ('learning-round/v1','legacy-correction/v1')", name="ck_round_protocol"),
    )
    round_id = Column(String(128), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False)
    knowledge_base_id = Column(String(128), nullable=False)
    learning_direction_id = Column(String(128), nullable=True)
    protocol_version = Column(String(32), nullable=False)
    parent_round_id = Column(String(128), ForeignKey("learning_rounds.round_id"), nullable=True)
    source_attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=True)
    selection_key = Column(String(128), nullable=False)
    selection_hash = Column(String(64), nullable=False)
    budget_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    row_version = Column(Integer, nullable=False, default=1)


class LearningRoundNodeORM(Base):
    __tablename__ = "learning_round_nodes"
    __table_args__ = (
        UniqueConstraint("round_id", "skill_node_id", name="uq_round_node"),
        Index("uq_round_role", "round_id", "role", unique=True,
              sqlite_where=text("role IN ('primary','review')"), postgresql_where=text("role IN ('primary','review')")),
        CheckConstraint("role IN ('primary','review','legacy')", name="ck_round_role"),
    )
    round_node_id = Column(String(128), primary_key=True)
    round_id = Column(String(128), ForeignKey("learning_rounds.round_id"), nullable=False)
    skill_node_id = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False)
    tier = Column(Integer, nullable=True)
    name = Column(String(256), nullable=False)


class LearningRoundStageORM(Base):
    __tablename__ = "learning_round_stages"
    __table_args__ = (
        UniqueConstraint("round_id", "ordinal", name="uq_round_stage_ordinal"),
        UniqueConstraint("round_id", "selection_key", name="uq_round_stage_selection"),
        CheckConstraint("(kind = 'initial' AND ordinal = 0) OR (kind = 'correction' AND ordinal > 0)", name="ck_round_stage_kind"),
        CheckConstraint("state IN ('producing','awaiting_assessment','completed')", name="ck_round_stage_state"),
    )
    stage_id = Column(String(128), primary_key=True)
    round_id = Column(String(128), ForeignKey("learning_rounds.round_id"), nullable=False)
    kind = Column(String(16), nullable=False)
    ordinal = Column(Integer, nullable=False)
    selection_key = Column(String(128), nullable=False)
    selection_hash = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False)
    budget_snapshot = Column(JSON, nullable=False)
    budget_counters = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    row_version = Column(Integer, nullable=False, default=1)


class LearningRoundStageNodeORM(Base):
    __tablename__ = "learning_round_stage_nodes"
    __table_args__ = (
        UniqueConstraint("stage_id", "round_node_id", name="uq_stage_member"),
        Index("uq_stage_batch", "batch_id", unique=True, sqlite_where=text("batch_id IS NOT NULL"),
              postgresql_where=text("batch_id IS NOT NULL")),
        Index("uq_member_correction_source", "round_node_id", "source_attempt_id", unique=True,
              sqlite_where=text("source_attempt_id IS NOT NULL"), postgresql_where=text("source_attempt_id IS NOT NULL")),
    )
    stage_node_id = Column(String(128), primary_key=True)
    stage_id = Column(String(128), ForeignKey("learning_round_stages.stage_id"), nullable=False)
    round_node_id = Column(String(128), ForeignKey("learning_round_nodes.round_node_id"), nullable=False)
    source_attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=True)
    batch_id = Column(String(128), nullable=True)
    request_snapshot = Column(JSON, nullable=False)
    resource_types = Column(JSON, nullable=False)
    difficulty = Column(String(32), nullable=False)
    config_hash = Column(String(64), nullable=False)
    budget_counters = Column(JSON, nullable=False, default=dict)
    recovery_count = Column(Integer, nullable=False, default=0)
    row_version = Column(Integer, nullable=False, default=1)


class LearningRoundJobBindingORM(Base):
    __tablename__ = "learning_round_job_bindings"
    run_id = Column(String(128), ForeignKey("generation_jobs.run_id"), primary_key=True)
    stage_node_id = Column(String(128), ForeignKey("learning_round_stage_nodes.stage_node_id"), nullable=False, index=True)
    relation_kind = Column(String(16), nullable=False)
    source_run_id = Column(String(128), ForeignKey("generation_jobs.run_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("relation_kind IN ('production','append','retry')", name="ck_round_binding_kind"),
        Index("ix_round_binding_order", "stage_node_id", "created_at", "run_id"),
    )


class LearningRoundEvaluationSessionORM(Base):
    __tablename__ = "learning_round_evaluation_sessions"
    session_id = Column(String(128), primary_key=True)
    stage_id = Column(String(128), ForeignKey("learning_round_stages.stage_id"), nullable=False, unique=True)
    manifest_hash = Column(String(64), nullable=False)
    manifest = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=True, unique=True)
    grading_state = Column(String(16), nullable=False, default="idle")
    submission_key = Column(String(128), nullable=True)
    submission_hash = Column(String(64), nullable=True)
    grading_owner = Column(String(128), nullable=True)
    grading_generation = Column(Integer, nullable=False, default=0)
    grading_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("grading_state IN ('idle','grading','submitted')", name="ck_round_grading_state"),
        CheckConstraint("(grading_state = 'submitted' AND attempt_id IS NOT NULL) OR (grading_state != 'submitted' AND attempt_id IS NULL)", name="ck_round_session_submission"),
    )


class FeedbackNodeDecisionORM(Base):
    __tablename__ = "feedback_node_decisions"
    node_decision_id = Column(String(128), primary_key=True)
    attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=False)
    round_node_id = Column(String(128), ForeignKey("learning_round_nodes.round_node_id"), nullable=False)
    score = Column(Float, nullable=False)
    action = Column(String(32), nullable=False)
    reason = Column(String(2000), nullable=False)
    targets = Column(JSON, nullable=False, default=list)
    role = Column(String(16), nullable=False)
    correction_eligible = Column(Boolean, nullable=False)
    error_summary = Column(JSON, nullable=False, default=dict)
    decision_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("attempt_id", "round_node_id", name="uq_feedback_round_member"),)


class LearnerRemediationNeedORM(Base):
    __tablename__ = "learner_remediation_needs"
    need_id = Column(String(128), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False)
    knowledge_base_id = Column(String(128), nullable=False)
    skill_node_id = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False)
    first_unresolved_attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=False)
    last_attempt_id = Column(String(128), ForeignKey("learning_attempts.attempt_id"), nullable=False)
    last_score = Column(Float, nullable=False)
    wait_rounds = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    row_version = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("learner_id", "knowledge_base_id", "skill_node_id", name="uq_remediation_node"),
        CheckConstraint("status IN ('remediate','practice','resolved')", name="ck_remediation_status"),
        CheckConstraint("wait_rounds >= 0", name="ck_remediation_wait"),
        Index("ix_remediation_pending", "learner_id", "knowledge_base_id", "status"),
    )


class LearningRoundBudgetReservationORM(Base):
    __tablename__ = "learning_round_budget_reservations"
    reservation_id = Column(String(128), primary_key=True)
    stage_id = Column(String(128), ForeignKey("learning_round_stages.stage_id"), nullable=False)
    stage_node_id = Column(String(128), ForeignKey("learning_round_stage_nodes.stage_node_id"), nullable=True)
    session_id = Column(String(128), ForeignKey("learning_round_evaluation_sessions.session_id"), nullable=True)
    scope_id = Column(String(128), nullable=False)
    run_id = Column(String(128), ForeignKey("generation_jobs.run_id"), nullable=True)
    call_id = Column(String(128), nullable=False)
    gateway_attempt = Column(Integer, nullable=False)
    row_version = Column(Integer, nullable=False, default=1)
    reserved_seconds = Column(Float, nullable=False, default=0)
    known_seconds = Column(Float, nullable=True)
    reserved_tokens = Column(Integer, nullable=False)
    known_tokens = Column(Integer, nullable=True)
    state = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("scope_id", "call_id", "gateway_attempt", name="uq_round_budget_attempt"),
        CheckConstraint("(stage_node_id IS NULL) != (session_id IS NULL)", name="ck_round_budget_scope"),
        CheckConstraint("reserved_tokens >= 0 AND (known_tokens IS NULL OR known_tokens >= 0) AND gateway_attempt > 0", name="ck_round_budget_usage"),
        CheckConstraint("state IN ('reserved','settled','unknown')", name="ck_round_budget_state"),
    )


ROUND_MODELS = (
    LearningRoundORM, LearningRoundNodeORM, LearningRoundStageORM, LearningRoundStageNodeORM,
    LearningRoundJobBindingORM, LearningRoundEvaluationSessionORM, FeedbackNodeDecisionORM,
    LearnerRemediationNeedORM, LearningRoundBudgetReservationORM,
)
