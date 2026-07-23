"""SQLAlchemy ORM 模型定义"""
from sqlalchemy import Boolean, Column, String, Integer, Float, JSON, DateTime, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


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
