"""资源审核查询服务。"""
from typing import Optional

from app.db.audit.base import BaseAuditRepository
from app.models.learning_documents.schemas import ReviewSummary


class ReviewService:
    def __init__(self, audit_repo: BaseAuditRepository):
        self.audit_repo = audit_repo

    def get_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        return self.audit_repo.get_review_by_resource(resource_id)
