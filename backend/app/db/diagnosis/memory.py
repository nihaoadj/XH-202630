"""诊断仓储的内存实现。"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Iterable

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.models.history_schemas import DiagnosticRunRecord
from app.models.schemas import DiagnosticAnswerRecord, KnowledgeState


class MemoryDiagnosisRepository(BaseDiagnosisRepository):
    def __init__(self):
        self.answers: dict[str, list[DiagnosticAnswerRecord]] = defaultdict(list)
        self.knowledge_states: dict[tuple[str, str], dict[str, KnowledgeState]] = {}
        self.runs: dict[str, list[DiagnosticRunRecord]] = defaultdict(list)

    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
    ) -> None:
        self.answers[learner_id].extend(answers)
        self.knowledge_states[(learner_id, knowledge_base_id)] = dict(knowledge_states)

    def save_run(self, run: DiagnosticRunRecord) -> None:
        self.runs[run.learner_id].append(run.model_copy(deep=True))

    def list_runs_by_learner(self, learner_id: str) -> list[DiagnosticRunRecord]:
        return [deepcopy(item) for item in reversed(self.runs.get(learner_id, []))]
