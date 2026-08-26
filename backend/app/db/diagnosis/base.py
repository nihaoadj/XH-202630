"""诊断仓储接口定义。"""
from abc import ABC, abstractmethod
from typing import Iterable

from app.models.learners.history import DiagnosticRunRecord
from app.models.learning_documents.schemas import DiagnosticAnswerRecord, KnowledgeState


class BaseDiagnosisRepository(ABC):
    @abstractmethod
    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
        source_id: str | None = None,
    ) -> None:
        """保存一次诊断答题提交。"""

    @abstractmethod
    def save_run(self, run: DiagnosticRunRecord) -> None:
        """保存一次诊断结果快照。"""

    @abstractmethod
    def list_runs_by_learner(self, learner_id: str) -> list[DiagnosticRunRecord]:
        """返回指定学习者的诊断历史。"""
