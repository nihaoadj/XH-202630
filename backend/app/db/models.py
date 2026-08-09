"""SQLAlchemy ORM 模型定义"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserProfileORM(Base):
    __tablename__ = "users"

    user_id = Column(String(64), primary_key=True, index=True, comment="鐢ㄦ埛鍞竴鏍囪瘑")
    display_name = Column(String(128), nullable=False, comment="鐢ㄦ埛鏄剧ず鍚嶇О")
    identity = Column(String(64), nullable=False, comment="鐢ㄦ埛韬唤")
    education = Column(String(64), nullable=False, comment="瀛﹀巻")
    major = Column(String(128), nullable=False, comment="涓撲笟")
    job_role = Column(String(128), nullable=True, comment="宀椾綅")
    experience_years = Column(Integer, nullable=True, comment="骞撮檺")
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LearnerProfileORM(Base):
    """学习者画像数据库表"""
    __tablename__ = "learner_profiles"

    learner_id = Column(String(64), primary_key=True, index=True, comment="学习者唯一标识")
    learner_type = Column(String(64), nullable=False, comment="学习者类型")
    education = Column(String(32), nullable=False, comment="学历")
    major = Column(String(64), nullable=False, comment="专业方向")
    target_domain = Column(String(128), nullable=True, comment="目标领域")
    knowledge_base_id = Column(String(128), nullable=True, comment="知识库 ID")
    theory_scores = Column(JSON, default=dict, comment="理论测试得分")
    knowledge_states = Column(JSON, default=dict, comment="知识状态")
    skill_level = Column(String(16), default="初级", comment="技能水平")
    weak_points = Column(JSON, default=list, comment="知识盲区")
    strong_points = Column(JSON, default=list, comment="优势领域")
    learning_goal = Column(String(512), nullable=False, comment="学习目标")
    learning_preferences = Column(JSON, default=dict, comment="学习偏好")
    last_feedback_summary = Column(JSON, default=dict, comment="最近反馈摘要")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="更新时间")


class GeneratedResourceORM(Base):
    """生成的学习资源记录表

    支持文本内容与多媒体文件两种存储方式：
    - 文本类资源：storage_type='text'，内容保存在 content_text 中
    - 文件类资源：storage_type='file'，文件保存在 backend/data/generated_resources/ 下，
      表中记录 file_path、file_size、mime_type，content_text 可保存摘要
    """
    __tablename__ = "generated_resources"

    resource_id = Column(String(64), primary_key=True, index=True, comment="资源唯一标识")
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=True, index=True)
    generation_step_id = Column(String(128), ForeignKey("agent_steps.step_id"), nullable=True, index=True)
    learner_id = Column(String(64), nullable=False, index=True, comment="学习者ID")
    topic = Column(String(256), nullable=False, comment="学习主题")
    resource_type = Column(String(32), nullable=False, comment="资源类型：讲义/实操指南/分阶测试题/ppt/video/pdf/audio/image")
    difficulty = Column(String(16), nullable=False, comment="难度等级")
    storage_type = Column(String(16), nullable=False, default="text", comment="存储方式：text | file")
    content_text = Column(String, nullable=True, comment="文本内容或文件摘要")
    file_path = Column(String(512), nullable=True, comment="文件相对路径")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    mime_type = Column(String(64), nullable=True, comment="文件 MIME 类型")
    knowledge_points = Column(JSON, default=list, comment="覆盖知识点")
    source_refs = Column(JSON, default=list, comment="知识溯源引用")
    learning_path_node = Column(String(128), nullable=True, comment="学习路径节点")
    review_status = Column(String(32), nullable=True, comment="审核状态")
    review_id = Column(String(64), nullable=True, comment="审核记录 ID")
    publication_status = Column(String(32), nullable=False, default="unpublished", index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    claim_count = Column(Integer, nullable=True, comment="Claim 总数")
    hallucination_rate = Column(Float, nullable=True, comment="幻觉率")
    difficulty_match = Column(Boolean, nullable=True, comment="难度是否匹配")
    version = Column(Integer, default=1, comment="资源版本")
    parent_resource_id = Column(String(64), nullable=True, comment="父资源 ID")
    exercise_items = Column(JSON, default=list, comment="练习项")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")


class FeedbackRecordORM(Base):
    """学习反馈记录表"""
    __tablename__ = "feedback_records"

    feedback_id = Column(String(64), primary_key=True, comment="反馈唯一标识")
    learner_id = Column(String(64), nullable=False, index=True, comment="学习者ID")
    resource_id = Column(String(64), nullable=False, comment="资源ID")
    correct_rate = Column(Float, nullable=False, comment="答题正确率")
    decision = Column(String(32), nullable=False, comment="系统决策")
    answers = Column(JSON, default=list, comment="答题详情")
    feedback_type = Column(String(32), nullable=True, comment="反馈类型")
    time_spent_seconds = Column(Integer, nullable=True, comment="耗时")
    completed = Column(Boolean, nullable=True, comment="是否完成")
    self_rating = Column(Integer, nullable=True, comment="自评")
    practice_result = Column(JSON, default=dict, comment="实操结果")
    decision_reason = Column(String(512), nullable=True, comment="决策理由")
    next_action = Column(String(32), nullable=True, comment="下一步动作")
    recommended_topics = Column(JSON, default=list, comment="推荐主题")
    updated_knowledge_states = Column(JSON, default=dict, comment="更新后的知识状态")
    regenerate_suggestion = Column(JSON, default=dict, comment="再生成建议")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")


class GenerationJobORM(Base):
    """异步资源生成任务表"""
    __tablename__ = "generation_jobs"

    run_id = Column(String(128), primary_key=True, comment="生成任务唯一标识")
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False, index=True, comment="学习者ID")
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=True, index=True, comment="知识库ID")
    topic = Column(String(256), nullable=False, comment="生成主题")
    status = Column(String(32), nullable=False, default="queued", comment="任务状态")
    request_payload = Column(JSON, default=dict, comment="原始生成请求")
    resource_ids = Column(JSON, default=list, comment="产出的资源ID列表")
    error_message = Column(String(512), nullable=True, comment="错误信息")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    started_at = Column(DateTime(timezone=True), nullable=True, comment="开始执行时间")
    finished_at = Column(DateTime(timezone=True), nullable=True, comment="完成时间")


# 以下模型承接知识库、图谱、审核和评测。JSON 仅用于可扩展负载；可查询的核心
# 关联均保留为独立字段，以便比赛演示时追踪“知识点—证据—资源—审核”链路。
class KnowledgeBaseORM(Base):
    __tablename__ = "knowledge_bases"

    knowledge_base_id = Column(String(128), primary_key=True, comment="知识库唯一标识")
    name = Column(String(256), nullable=False)
    version = Column(String(64), nullable=False, default="0.1.0")
    domain = Column(String(256), nullable=True)
    description = Column(Text, nullable=True)
    learner_levels = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LearningDomainORM(Base):
    __tablename__ = "learning_domains"

    domain_id = Column(String(128), primary_key=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=100)
    enabled = Column(Boolean, nullable=False, default=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LearningTrackORM(Base):
    __tablename__ = "learning_tracks"
    __table_args__ = (UniqueConstraint("domain_id", "track_id", name="uq_domain_track"),)

    track_id = Column(String(128), primary_key=True)
    domain_id = Column(String(128), ForeignKey("learning_domains.domain_id"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    target_audience = Column(JSON, default=list)
    difficulty_levels = Column(JSON, default=list)
    sort_order = Column(Integer, nullable=False, default=100)
    enabled = Column(Boolean, nullable=False, default=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class QuestionnaireTemplateORM(Base):
    """问卷模板表：保存通用问卷和方向问卷的版本化配置。"""
    __tablename__ = "questionnaire_templates"

    questionnaire_id = Column(String(128), primary_key=True)
    scope = Column(String(32), nullable=False, index=True, comment="common/domain/track")
    domain_id = Column(String(128), ForeignKey("learning_domains.domain_id"), nullable=True, index=True)
    track_id = Column(String(128), ForeignKey("learning_tracks.track_id"), nullable=True, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=True, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(64), nullable=False, default="1.0.0")
    enabled = Column(Boolean, nullable=False, default=True)
    source_path = Column(String(1024), nullable=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class QuestionnaireQuestionORM(Base):
    """问卷题目表：保存题干、选项、展示条件和画像映射规则。"""
    __tablename__ = "questionnaire_questions"
    __table_args__ = (UniqueConstraint("questionnaire_id", "question_id", name="uq_questionnaire_question"),)

    question_uid = Column(String(256), primary_key=True)
    questionnaire_id = Column(String(128), ForeignKey("questionnaire_templates.questionnaire_id"), nullable=False, index=True)
    question_id = Column(String(128), nullable=False, index=True)
    field_key = Column(String(128), nullable=False)
    title = Column(Text, nullable=False)
    question_type = Column(String(32), nullable=False)
    required = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=100)
    hint = Column(Text, nullable=True)
    options = Column(JSON, default=list)
    validation = Column(JSON, default=dict)
    show_when = Column(JSON, default=dict)
    profile_mapping = Column(JSON, default=dict)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class QuestionnaireSubmissionORM(Base):
    """问卷提交表：记录用户一次完整问卷提交及其画像更新快照。"""
    __tablename__ = "questionnaire_submissions"

    submission_id = Column(String(128), primary_key=True)
    questionnaire_id = Column(String(128), ForeignKey("questionnaire_templates.questionnaire_id"), nullable=False, index=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False, index=True)
    track_id = Column(String(128), ForeignKey("learning_tracks.track_id"), nullable=True, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=True, index=True)
    purpose = Column(String(64), nullable=False, default="initial_profile")
    answers_snapshot = Column(JSON, default=dict)
    profile_updates = Column(JSON, default=dict)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QuestionnaireAnswerORM(Base):
    """问卷答案明细表：保留每道题的原始答案与当时的画像映射规则。"""
    __tablename__ = "questionnaire_answers"
    __table_args__ = (UniqueConstraint("submission_id", "question_id", name="uq_questionnaire_submission_answer"),)

    answer_id = Column(String(128), primary_key=True)
    submission_id = Column(String(128), ForeignKey("questionnaire_submissions.submission_id"), nullable=False, index=True)
    questionnaire_id = Column(String(128), ForeignKey("questionnaire_templates.questionnaire_id"), nullable=False, index=True)
    question_id = Column(String(128), nullable=False, index=True)
    field_key = Column(String(128), nullable=True)
    answer = Column(JSON, nullable=True)
    profile_mapping = Column(JSON, default=dict)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocumentORM(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "source_path", name="uq_kb_document_path"),)

    document_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    source_path = Column(String(1024), nullable=False)
    content_hash = Column(String(64), nullable=False)
    knowledge_points = Column(JSON, default=list)
    learner_levels = Column(JSON, default=list)
    document_version = Column(String(64), nullable=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class KnowledgeDocumentVersionORM(Base):
    """Immutable content-addressed version of one logical knowledge document."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "document_id",
            "content_hash",
            name="uq_kb_document_content_version",
        ),
    )

    document_version = Column(String(128), primary_key=True)
    document_id = Column(String(128), nullable=False, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    source_path = Column(String(1024), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_version = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunkORM(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "document_id", "chunk_index", name="uq_document_chunk_index"),)

    chunk_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    document_id = Column(String(128), ForeignKey("knowledge_documents.document_id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunkVersionORM(Base):
    """Immutable Chunk history used to resolve SourceRef after re-indexing."""

    __tablename__ = "knowledge_chunk_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_version",
            "chunk_ordinal",
            "chunking_config_hash",
            name="uq_document_version_chunk_ordinal",
        ),
    )

    chunk_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    document_id = Column(String(128), nullable=False, index=True)
    document_version = Column(String(128), ForeignKey("knowledge_document_versions.document_version"), nullable=False, index=True)
    chunk_ordinal = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False, index=True)
    chunking_config_hash = Column(String(64), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_path = Column(String(1024), nullable=False)
    title = Column(String(512), nullable=False)
    section = Column(String(512), nullable=True)
    page = Column(Integer, nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    knowledge_points = Column(JSON, default=list)
    learner_levels = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeIndexStatusORM(Base):
    """Latest reconciled SQL/Chroma index status for one knowledge base."""

    __tablename__ = "knowledge_index_status"

    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), primary_key=True)
    status = Column(String(32), nullable=False, default="pending")
    index_schema_version = Column(String(32), nullable=False, default="1.0")
    active_snapshot_hash = Column(String(64), nullable=True)
    expected_chunk_count = Column(Integer, nullable=False, default=0)
    sql_chunk_count = Column(Integer, nullable=False, default=0)
    vector_chunk_count = Column(Integer, nullable=False, default=0)
    smoke_status = Column(String(32), nullable=True)
    last_error_code = Column(String(128), nullable=True)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagSkillNodeORM(Base):
    __tablename__ = "rag_skill_nodes"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "name", name="uq_kb_skill_node_name"),)

    node_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    level = Column(String(32), nullable=True)
    knowledge_points = Column(JSON, default=list)
    assessment_methods = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SkillNodeRelationORM(Base):
    __tablename__ = "skill_node_relations"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "parent_node_id", "child_node_id", name="uq_skill_edge"),)

    relation_id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    parent_node_id = Column(String(128), ForeignKey("rag_skill_nodes.node_id"), nullable=False)
    child_node_id = Column(String(128), ForeignKey("rag_skill_nodes.node_id"), nullable=False)
    relation_type = Column(String(32), nullable=False, default="prerequisite")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DiagnosticQuestionORM(Base):
    __tablename__ = "diagnostic_questions"

    question_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    skill_node_id = Column(String(128), ForeignKey("rag_skill_nodes.node_id"), nullable=True, index=True)
    knowledge_point = Column(String(256), nullable=True, index=True)
    question_type = Column(String(32), nullable=False)
    difficulty = Column(String(32), nullable=True)
    question = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    answer = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DiagnosticAnswerORM(Base):
    __tablename__ = "diagnostic_answers"
    __table_args__ = (UniqueConstraint("learner_id", "question_id", "attempt_no", name="uq_diagnostic_attempt"),)

    answer_id = Column(String(128), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False, index=True)
    question_id = Column(String(128), ForeignKey("diagnostic_questions.question_id"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False, default=1)
    answer = Column(JSON, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeStateORM(Base):
    __tablename__ = "knowledge_states"
    __table_args__ = (UniqueConstraint("learner_id", "knowledge_base_id", "skill_node_id", name="uq_learner_skill_state"),)

    state_id = Column(String(128), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    skill_node_id = Column(String(128), ForeignKey("rag_skill_nodes.node_id"), nullable=False, index=True)
    mastery_score = Column(Float, nullable=True)
    status = Column(String(32), nullable=True)
    evidence = Column(JSON, default=list)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentRunORM(Base):
    __tablename__ = "agent_runs"

    run_id = Column(String(128), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=True, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=True, index=True)
    topic = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="running")
    request_hash = Column(String(64), nullable=True, index=True)
    workflow_status = Column(String(32), nullable=True)
    execution_status = Column(String(32), nullable=True)
    current_node = Column(String(128), nullable=True)
    current_step_id = Column(String(128), nullable=True)
    current_step_sequence = Column(Integer, nullable=False, default=0)
    last_event_sequence = Column(Integer, nullable=False, default=0)
    generation_attempt = Column(Integer, nullable=False, default=1)
    revision_count = Column(Integer, nullable=False, default=0)
    retrieval_status = Column(String(32), nullable=True)
    final_decision = Column(String(256), nullable=True)
    last_error_code = Column(String(128), nullable=True)
    replay_completeness = Column(String(32), nullable=False, default="complete")
    owner_instance_id = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    input_payload = Column(JSON, default=dict)
    output_payload = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)


class AgentStepORM(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_no", name="uq_agent_run_step"),)

    step_id = Column(String(128), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    step_no = Column(Integer, nullable=False)
    agent_name = Column(String(128), nullable=False)
    node_name = Column(String(128), nullable=True)
    action = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="success")
    input_payload = Column(JSON, default=dict)
    output_payload = Column(JSON, default=dict)
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    decision_reason = Column(Text, nullable=True)
    evidence_refs = Column(JSON, default=list)
    resource_ids = Column(JSON, default=list)
    review_ids = Column(JSON, default=list)
    generation_attempt = Column(Integer, nullable=False, default=1)
    retry_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    llm_call_id = Column(String(128), nullable=True)
    model_name = Column(String(128), nullable=True)
    provider_request_id = Column(String(256), nullable=True)
    structured_output_mode = Column(String(32), nullable=True)
    finish_reason = Column(String(64), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    llm_duration_ms = Column(Integer, nullable=True)
    llm_attempts = Column(JSON, default=list)
    retrieval_status = Column(String(32), nullable=True)
    retrieval_config_hash = Column(String(64), nullable=True)
    retrieval_query_hashes = Column(JSON, default=list)
    retrieval_candidate_count = Column(Integer, nullable=True)
    retrieval_dropped_candidate_count = Column(Integer, nullable=True)
    retrieval_partial_failure_count = Column(Integer, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)


class WorkflowEventORM(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_sequence", name="uq_workflow_event_sequence"),
    )

    event_id = Column(String(128), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    event_sequence = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    step_id = Column(String(128), ForeignKey("agent_steps.step_id"), nullable=True, index=True)
    step_sequence = Column(Integer, nullable=True)
    node_name = Column(String(128), nullable=True)
    status = Column(String(32), nullable=True)
    payload = Column(JSON, default=dict)
    payload_hash = Column(String(64), nullable=False)
    error_code = Column(String(128), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    persisted_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkflowCheckpointORM(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "step_id", name="uq_workflow_checkpoint_step"),
    )

    checkpoint_id = Column(String(128), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    event_sequence = Column(Integer, nullable=False)
    step_id = Column(String(128), ForeignKey("agent_steps.step_id"), nullable=False, index=True)
    step_sequence = Column(Integer, nullable=False)
    node_name = Column(String(128), nullable=False)
    state_projection = Column(JSON, nullable=False)
    state_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RetrievalEvidenceSnapshotORM(Base):
    __tablename__ = "retrieval_evidence_snapshots"

    evidence_id = Column(String(128), primary_key=True)
    schema_version = Column(String(16), nullable=False, default="1.0")
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    retrieval_step_id = Column(String(128), ForeignKey("agent_steps.step_id"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), nullable=False, index=True)
    document_id = Column(String(128), nullable=False, index=True)
    document_version = Column(String(128), nullable=False)
    chunk_id = Column(String(128), nullable=False, index=True)
    query_hash = Column(String(64), nullable=False)
    query_rank = Column(Integer, nullable=False)
    rank = Column(Integer, nullable=False)
    raw_score = Column(Float, nullable=False)
    score_kind = Column(String(32), nullable=False)
    normalized_score = Column(Float, nullable=False)
    excerpt = Column(Text, nullable=False)
    excerpt_hash = Column(String(64), nullable=False)
    locator = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=False)
    snapshot_hash = Column(String(64), nullable=False)
    retrieved_at = Column(DateTime(timezone=True), nullable=False)
    persisted_at = Column(DateTime(timezone=True), server_default=func.now())


class SchemaMigrationORM(Base):
    __tablename__ = "schema_migrations"

    migration_id = Column(String(128), primary_key=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResourceReviewORM(Base):
    __tablename__ = "resource_reviews"

    review_id = Column(String(128), primary_key=True)
    resource_id = Column(String(64), ForeignKey("generated_resources.resource_id"), nullable=False, index=True)
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=True, index=True)
    status = Column(String(32), nullable=False)
    claim_total = Column(Integer, nullable=False, default=0)
    claim_supported = Column(Integer, nullable=False, default=0)
    claim_unsupported = Column(Integer, nullable=False, default=0)
    suspected_hallucinations = Column(Integer, nullable=False, default=0)
    hallucination_rate = Column(Float, nullable=False, default=0.0)
    review_pass_rate = Column(Float, nullable=False, default=0.0)
    revision_count = Column(Integer, nullable=False, default=0)
    issues = Column(JSON, default=list)
    revision_instructions = Column(JSON, default=list)
    review_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ResourceClaimORM(Base):
    __tablename__ = "resource_claims"

    claim_id = Column(String(128), primary_key=True)
    review_id = Column(String(128), ForeignKey("resource_reviews.review_id"), nullable=False, index=True)
    resource_id = Column(String(64), ForeignKey("generated_resources.resource_id"), nullable=False, index=True)
    knowledge_point = Column(String(256), nullable=True, index=True)
    claim_text = Column(Text, nullable=False)
    supported = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=True)
    evidence_refs = Column(JSON, default=list)
    issue_type = Column(String(64), nullable=True)
    correction = Column(Text, nullable=True)
    review_comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ContestEvalCaseORM(Base):
    __tablename__ = "contest_eval_cases"

    case_id = Column(String(128), primary_key=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    target_skill_nodes = Column(JSON, default=list)
    expected_document_ids = Column(JSON, default=list)
    expected_chunk_ids = Column(JSON, default=list)
    expected_answer = Column(JSON, nullable=True)
    difficulty = Column(String(32), nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ContestEvalResultORM(Base):
    __tablename__ = "contest_eval_results"
    __table_args__ = (UniqueConstraint("case_id", "experiment_name", name="uq_eval_case_experiment"),)

    result_id = Column(String(128), primary_key=True)
    case_id = Column(String(128), ForeignKey("contest_eval_cases.case_id"), nullable=False, index=True)
    experiment_name = Column(String(128), nullable=False)
    run_id = Column(String(128), ForeignKey("agent_runs.run_id"), nullable=True, index=True)
    retrieval_hit = Column(Boolean, nullable=True)
    coverage_rate = Column(Float, nullable=True)
    hallucination_rate = Column(Float, nullable=True)
    difficulty_match = Column(Boolean, nullable=True)
    metrics = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
