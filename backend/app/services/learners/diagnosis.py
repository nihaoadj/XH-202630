"""诊断判分、学习状态更新与结果持久化。"""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.learners.base import BaseLearnerRepository
from app.models.learners.history import DiagnosticRunRecord
from app.models.learning_documents.schemas import (
    DiagnosticAnswerRecord,
    DiagnosticResult,
    DiagnosticSubmitRequest,
    KnowledgeState,
    LearningPathItem,
)
from app.services.knowledge.knowledge import KnowledgeService
from app.services.learners.mastery import MasteryService


def _answers_match(expected: object, actual: object) -> bool:
    return json.dumps(expected, ensure_ascii=False, sort_keys=True) == json.dumps(
        actual, ensure_ascii=False, sort_keys=True
    )


class DiagnosisService:
    def __init__(
        self,
        knowledge_service: KnowledgeService,
        learner_repo: BaseLearnerRepository,
        diagnosis_repo: BaseDiagnosisRepository,
        mastery_service: MasteryService | None = None,
    ):
        self.knowledge_service = knowledge_service
        self.learner_repo = learner_repo
        self.diagnosis_repo = diagnosis_repo
        self.mastery_service = mastery_service

    def submit(self, request: DiagnosticSubmitRequest) -> DiagnosticResult:
        learner = self.learner_repo.get(request.learner_id)
        if learner is None:
            raise LookupError("学习者画像不存在")

        manifest = self.knowledge_service._ensure_knowledge_base(
            request.learning_direction_id or request.knowledge_base_id
        )
        knowledge_base_id = manifest["knowledge_base_id"]
        questions = {
            question.question_id: question
            for question in self.knowledge_service.load_diagnostic_questions(knowledge_base_id)
        }
        if len({answer.question_id for answer in request.answers}) != len(request.answers):
            raise ValueError("同一次诊断不能重复提交同一道题")
        missing = sorted({answer.question_id for answer in request.answers} - set(questions))
        if missing:
            raise ValueError(f"包含不存在的诊断题: {', '.join(missing)}")

        records: list[DiagnosticAnswerRecord] = []
        by_node: dict[str, list[DiagnosticAnswerRecord]] = defaultdict(list)
        for submitted in request.answers:
            question = questions[submitted.question_id]
            correct = _answers_match(question.answer, submitted.answer)
            record = DiagnosticAnswerRecord(
                question_id=submitted.question_id,
                answer=submitted.answer,
                correct=correct,
                score=1.0 if correct else 0.0,
            )
            records.append(record)
            if question.skill_node_id:
                by_node[question.skill_node_id].append(record)

        nodes = {node.node_id: node for node in self.knowledge_service.list_skill_nodes(knowledge_base_id)}
        raw_scores: dict[str, float] = {}
        for node_id, node_records in by_node.items():
            raw_scores[node_id] = sum(record.score for record in node_records) / len(node_records)

        occurred_at = datetime.now(timezone.utc)
        source_payload = {
            "learner_id": learner.learner_id,
            "knowledge_base_id": knowledge_base_id,
            "answers": [item.model_dump(mode="json") for item in request.answers],
        }
        source_hash = hashlib.sha256(
            json.dumps(source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        source_id = f"diagnosis_{source_hash[:32]}"
        learner.knowledge_base_id = knowledge_base_id
        average = sum(record.score for record in records) / len(records)
        learner.skill_level = "初级" if average < 0.6 else "中级" if average <= 0.85 else "进阶"
        self.learner_repo.save(learner)

        self.diagnosis_repo.save_submission(
            knowledge_base_id=knowledge_base_id,
            learner_id=learner.learner_id,
            answers=records,
            knowledge_states={},
            source_id=source_id,
        )

        if self.mastery_service is not None:
            projected, _, _ = self.mastery_service.apply_diagnosis(
                learner,
                raw_scores,
                source_id=source_id,
                source_hash=source_hash,
                occurred_at=occurred_at,
            )
            projected_by_id = {item.skill_node_id: item for item in projected}
            states = {
                node_id: KnowledgeState(
                    score=projected_by_id[node_id].mastery_score,
                    status=projected_by_id[node_id].status.value,
                    evidence=[projected_by_id[node_id].last_evidence_id]
                    if projected_by_id[node_id].last_evidence_id else [],
                    last_updated=projected_by_id[node_id].last_updated.isoformat()
                    if projected_by_id[node_id].last_updated else None,
                )
                for node_id in raw_scores
            }
            learner = self.learner_repo.get(learner.learner_id) or learner
        else:
            states = {
                node_id: KnowledgeState(
                    score=score,
                    status="weak" if score < 0.6 else "learning" if score <= 0.85 else "mastered",
                    evidence=[record.question_id for record in by_node[node_id]],
                    last_updated=occurred_at.isoformat(),
                )
                for node_id, score in raw_scores.items()
            }
            learner.knowledge_states.update(states)
            learner.theory_scores.update({node_id: round(score * 100, 1) for node_id, score in raw_scores.items()})
            self.learner_repo.save(learner)

        weak_nodes = [node_id for node_id, state in states.items() if state.status == "weak"]
        recommended_path = [
            LearningPathItem(order=index, topic=nodes[node_id].name, reason="诊断掌握度低于 60%，建议先补齐基础证据与练习。")
            for index, node_id in enumerate(weak_nodes, start=1)
            if node_id in nodes
        ]
        result = DiagnosticResult(
            diagnostic_result_id=source_id,
            learner_id=learner.learner_id,
            knowledge_base_id=knowledge_base_id,
            ability_level=learner.skill_level,
            weak_points=learner.weak_points,
            strong_points=learner.strong_points,
            knowledge_states=states,
            recommended_path=recommended_path,
            created_at=datetime.now(timezone.utc),
        )
        self.diagnosis_repo.save_run(
            DiagnosticRunRecord(
                diagnostic_result_id=result.diagnostic_result_id,
                learner_id=result.learner_id,
                knowledge_base_id=result.knowledge_base_id,
                ability_level=result.ability_level,
                weak_points=result.weak_points,
                strong_points=result.strong_points,
                knowledge_states_snapshot={
                    key: value.model_dump(mode="json") for key, value in result.knowledge_states.items()
                },
                recommended_path=[item.model_dump(mode="json") for item in result.recommended_path],
                raw_result=result.model_dump(mode="json"),
                created_at=result.created_at,
            )
        )
        return result
