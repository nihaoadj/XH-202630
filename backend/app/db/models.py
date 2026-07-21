"""SQLAlchemy ORM 模型定义"""
from sqlalchemy import Column, String, Integer, Float, JSON, DateTime, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class LearnerProfileORM(Base):
    """学习者画像数据库表"""
    __tablename__ = "learner_profiles"

    learner_id = Column(String(64), primary_key=True, index=True, comment="学习者唯一标识")
    education = Column(String(32), nullable=False, comment="学历")
    major = Column(String(64), nullable=False, comment="专业方向")
    theory_scores = Column(JSON, default=dict, comment="理论测试得分")
    skill_level = Column(String(16), default="初级", comment="技能水平")
    weak_points = Column(JSON, default=list, comment="知识盲区")
    strong_points = Column(JSON, default=list, comment="优势领域")
    learning_goal = Column(String(512), nullable=False, comment="学习目标")
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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
