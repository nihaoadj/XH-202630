"""诊断记录仓库抽象。"""
from abc import ABC, abstractmethod
from typing import Iterable

from app.models.schemas import DiagnosticAnswerRecord, KnowledgeState


class BaseDiagnosisRepository(ABC):
    @abstractmethod
    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
    ) -> None:
        """保存一次诊断答题，并更新每个能力节点的最新状态。"""
