"""诊断判分、学习状态更新和持久化服务。"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.learner.base import BaseLearnerRepository
from app.models.schemas import (
    DiagnosticAnswerRecord,
    DiagnosticResult,
    DiagnosticSubmitRequest,
    KnowledgeState,
    LearningPathItem,
)
from app.services.knowledge_service import KnowledgeService


def _answers_match(expected: object, actual: object) -> bool:
    """统一比较 JSON 值，避免列表、数字等答案类型的表示差异。"""
    return json.dumps(expected, ensure_ascii=False, sort_keys=True) == json.dumps(
        actual, ensure_ascii=False, sort_keys=True
    )


class DiagnosisService:
    def __init__(
        self,
        knowledge_service: KnowledgeService,
        learner_repo: BaseLearnerRepository,
        diagnosis_repo: BaseDiagnosisRepository,
    ):
        self.knowledge_service = knowledge_service
        self.learner_repo = learner_repo
        self.diagnosis_repo = diagnosis_repo

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
            raise ValueError(f"包含不存在的诊断题：{', '.join(missing)}")

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
        states: dict[str, KnowledgeState] = {}
        for node_id, node_records in by_node.items():
            score = sum(record.score for record in node_records) / len(node_records)
            status = "weak" if score < 0.6 else "learning" if score < 0.8 else "mastered"
            states[node_id] = KnowledgeState(
                score=score,
                status=status,
                evidence=[record.question_id for record in node_records],
                last_updated=datetime.now(timezone.utc).isoformat(),
            )

        named_states = {nodes[node_id].name: state for node_id, state in states.items() if node_id in nodes}
        learner.knowledge_base_id = knowledge_base_id
        learner.knowledge_states.update(named_states)
        learner.theory_scores.update(
            {nodes[node_id].name: round(state.score * 100, 1) for node_id, state in states.items() if node_id in nodes}
        )
        # 自适应诊断只覆盖用户已了解、值得进一步测量的节点。未出题的
        # not_started 节点不能因为本次提交而从待补列表中消失。
        assessed_names = {nodes[node_id].name for node_id in states if node_id in nodes}
        preserved_weak_points = [point for point in learner.weak_points if point not in assessed_names]
        preserved_strong_points = [point for point in learner.strong_points if point not in assessed_names]
        learner.weak_points = list(dict.fromkeys(
            preserved_weak_points
            + [nodes[node_id].name for node_id, state in states.items() if state.status == "weak" and node_id in nodes]
        ))
        learner.strong_points = list(dict.fromkeys(
            preserved_strong_points
            + [nodes[node_id].name for node_id, state in states.items() if state.status == "mastered" and node_id in nodes]
        ))
        average = sum(record.score for record in records) / len(records)
        learner.skill_level = "初级" if average < 0.6 else "中级" if average < 0.8 else "进阶"
        self.learner_repo.save(learner)

        self.diagnosis_repo.save_submission(knowledge_base_id=knowledge_base_id, learner_id=learner.learner_id, answers=records, knowledge_states=states)

        weak_nodes = [node_id for node_id, state in states.items() if state.status == "weak"]
        recommended_path = [
            LearningPathItem(order=index, topic=nodes[node_id].name, reason="诊断掌握度低于 60%，建议先补齐基础证据与练习。")
            for index, node_id in enumerate(weak_nodes, start=1)
            if node_id in nodes
        ]
        return DiagnosticResult(
            diagnostic_result_id=f"diag_{uuid.uuid4().hex[:16]}",
            learner_id=learner.learner_id,
            knowledge_base_id=knowledge_base_id,
            ability_level=learner.skill_level,
            weak_points=learner.weak_points,
            strong_points=learner.strong_points,
            knowledge_states=named_states,
            recommended_path=recommended_path,
            created_at=datetime.now(timezone.utc),
        )
