"""诊断仓储的内存实现。"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Iterable

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.models.learners.history import DiagnosticRunRecord
from app.models.learning_documents.schemas import DiagnosticAnswerRecord, KnowledgeState


class MemoryDiagnosisRepository(BaseDiagnosisRepository):
    def __init__(self):
        self.answers: dict[str, list[DiagnosticAnswerRecord]] = defaultdict(list)
        self.knowledge_states: dict[tuple[str, str], dict[str, KnowledgeState]] = {}
        self.runs: dict[str, list[DiagnosticRunRecord]] = defaultdict(list)
        self._sources: set[tuple[str, str]] = set()

    def save_submission(
        self,
        learner_id: str,
        knowledge_base_id: str,
        answers: Iterable[DiagnosticAnswerRecord],
        knowledge_states: dict[str, KnowledgeState],
        source_id: str | None = None,
    ) -> None:
        records = list(answers)
        if source_id is None or (learner_id, source_id) not in self._sources:
            self.answers[learner_id].extend(records)
            if source_id is not None:
                self._sources.add((learner_id, source_id))
        self.knowledge_states[(learner_id, knowledge_base_id)] = dict(knowledge_states)

    def save_run(self, run: DiagnosticRunRecord) -> None:
        if any(item.diagnostic_result_id == run.diagnostic_result_id for item in self.runs[run.learner_id]):
            return
        self.runs[run.learner_id].append(run.model_copy(deep=True))

    def list_runs_by_learner(self, learner_id: str) -> list[DiagnosticRunRecord]:
        return [deepcopy(item) for item in reversed(self.runs.get(learner_id, []))]
