"""内存诊断仓库，便于无数据库的演示模式。"""
from collections import defaultdict
from typing import Iterable

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.models.schemas import DiagnosticAnswerRecord, KnowledgeState


class MemoryDiagnosisRepository(BaseDiagnosisRepository):
    def __init__(self):
        self.answers: dict[str, list[DiagnosticAnswerRecord]] = defaultdict(list)
        self.knowledge_states: dict[tuple[str, str], dict[str, KnowledgeState]] = {}

    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
    ) -> None:
        self.answers[learner_id].extend(answers)
        self.knowledge_states[(learner_id, knowledge_base_id)] = dict(knowledge_states)
