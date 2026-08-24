from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, func

from app.db.shared.models import Base


class DiagnosticRunORM(Base):
    __tablename__ = "diagnostic_runs"

    diagnostic_result_id = Column(String(128), primary_key=True)
    learner_id = Column(String(64), ForeignKey("learner_profiles.learner_id"), nullable=False, index=True)
    knowledge_base_id = Column(String(128), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=True, index=True)
    ability_level = Column(String(64), nullable=False)
    weak_points = Column(JSON, default=list)
    strong_points = Column(JSON, default=list)
    knowledge_states_snapshot = Column(JSON, default=dict)
    recommended_path = Column(JSON, default=list)
    raw_result = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
