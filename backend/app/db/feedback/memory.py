"""内存实现的学习反馈仓库"""
from typing import Dict, List, Optional

from app.db.feedback.base import BaseFeedbackRepository
from app.models.learning_documents.schemas import FeedbackRecord


class MemoryFeedbackRepository(BaseFeedbackRepository):
    """内存实现的学习反馈仓库，用于开发与演示阶段"""

    def __init__(self):
        self._store: Dict[str, FeedbackRecord] = {}
        self._learner_index: Dict[str, List[str]] = {}

    def get(self, feedback_id: str) -> Optional[FeedbackRecord]:
        return self._store.get(feedback_id)

    def save(self, record: FeedbackRecord) -> None:
        self._store[record.feedback_id] = record
        if record.learner_id not in self._learner_index:
            self._learner_index[record.learner_id] = []
        if record.feedback_id not in self._learner_index[record.learner_id]:
            self._learner_index[record.learner_id].append(record.feedback_id)

    def list_by_learner(self, learner_id: str) -> List[FeedbackRecord]:
        feedback_ids = self._learner_index.get(learner_id, [])
        return [self._store[fid] for fid in feedback_ids if fid in self._store]
