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
from app.core.learning_tiers import difficulty_for_tier


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

    @staticmethod
    def _initial_diagnostic_flow(learner) -> dict | None:
        preferences = learner.learning_preferences
        metadata = preferences.metadata if preferences and isinstance(preferences.metadata, dict) else {}
        value = metadata.get("initial_diagnostic_flow")
        return dict(value) if isinstance(value, dict) else None

    def _initial_round_questions(self, knowledge_base_id: str, flow: dict):
        return self.knowledge_service.select_initial_tier_diagnostic_questions(
            knowledge_base_id, tier=int(flow["current_tier"]),
        )

    def initial_questions_for_learner(self, learner_id: str):
        learner = self.learner_repo.get(learner_id)
        if learner is None or not learner.knowledge_base_id:
            raise LookupError("学习者画像不存在")
        flow = self._initial_diagnostic_flow(learner)
        if not flow or flow.get("status") not in {"pending", "retest"}:
            raise ValueError("当前没有待完成的初始分阶诊断")
        return learner.knowledge_base_id, self._initial_round_questions(learner.knowledge_base_id, flow)

    @staticmethod
    def _initial_recommended_node(node_ids: list[str], correct_counts: dict[str, int], nodes: dict[str, object]) -> str | None:
        """Choose one weakest learnable node, respecting dependencies in the round."""
        if not node_ids:
            return None
        def downstream_count(node_id: str) -> int:
            pending = list(getattr(nodes.get(node_id), "children", []))
            seen: set[str] = set()
            while pending:
                child_id = pending.pop(0)
                if child_id in seen or child_id not in nodes:
                    continue
                seen.add(child_id)
                pending.extend(getattr(nodes[child_id], "children", []))
            return len(seen)

        chosen = sorted(
            node_ids,
            key=lambda node_id: (correct_counts.get(node_id, 0), -downstream_count(node_id), node_id),
        )[0]
        round_ids = set(node_ids)
        queue = list(getattr(nodes.get(chosen), "prerequisites", []))
        prerequisites: list[str] = []
        seen = set(queue)
        while queue:
            node_id = queue.pop(0)
            if node_id not in round_ids or node_id not in nodes:
                continue
            prerequisites.append(node_id)
            for parent_id in getattr(nodes[node_id], "prerequisites", []):
                if parent_id not in seen:
                    seen.add(parent_id)
                    queue.append(parent_id)
        # The first available prerequisite is deliberately preferred to the
        # dependent weak node; its node ID makes parallel branches stable.
        return sorted(set(prerequisites))[0] if prerequisites else chosen

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
        initial_flow = self._initial_diagnostic_flow(learner)
        if initial_flow and initial_flow.get("status") in {"pending", "retest"}:
            expected = self._initial_round_questions(knowledge_base_id, initial_flow)
            expected_ids = {question.question_id for question in expected}
            submitted_ids = {answer.question_id for answer in request.answers}
            if submitted_ids != expected_ids or len(request.answers) != len(expected):
                raise ValueError("初始分阶诊断必须提交服务端指定的 9 道题")
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
        required_dimensions = {"concept", "scenario", "misconception"}
        raw_scores: dict[str, float] = {}
        coverage: dict[str, dict] = {}
        blind_spot_trace: list[dict] = []
        for node_id, node_records in by_node.items():
            dimensions = {
                str(questions[record.question_id].metadata.get("diagnostic_dimension"))
                for record in node_records
                if questions[record.question_id].metadata.get("diagnostic_dimension") in required_dimensions
            }
            correct_count = sum(record.score for record in node_records)
            complete = len(node_records) >= 3 and dimensions == required_dimensions
            coverage[node_id] = {
                "measurement_status": "measured" if complete else "needs_evidence",
                "valid_question_count": len(node_records),
                "correct_question_count": int(correct_count),
                "covered_dimensions": sorted(dimensions),
                "latest_observed_accuracy": correct_count / len(node_records),
            }
            for record in node_records:
                question = questions[record.question_id]
                dimension = question.metadata.get("diagnostic_dimension")
                if dimension in required_dimensions:
                    blind_spot_trace.append({
                        "question_id": record.question_id,
                        "skill_node_id": node_id,
                        "diagnostic_dimension": dimension,
                        "correct": record.correct,
                        "measurement_status": "measured" if complete else "needs_evidence",
                    })
            if complete:
                # Laplace smoothing prevents a very small perfect sample from
                # being displayed as certain 100% mastery.
                raw_scores[node_id] = (correct_count + 1) / (len(node_records) + 2)

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
        initial_status = None
        assessed_tier = None
        final_tier = None
        next_questions = []
        initial_recommended_node_id = None
        initial_final = True
        if initial_flow and initial_flow.get("status") in {"pending", "retest"}:
            assessed_tier = int(initial_flow["current_tier"])
            passed = sum(record.correct for record in records) >= 6
            if not passed and assessed_tier > 1:
                next_tier = assessed_tier - 1
                next_round = self.knowledge_service.select_initial_tier_diagnostic_questions(
                    knowledge_base_id, tier=next_tier,
                )
                next_node_ids = list(dict.fromkeys(question.skill_node_id for question in next_round if question.skill_node_id))
                initial_flow["status"] = "retest"
                initial_flow["current_tier"] = next_tier
                initial_flow.setdefault("rounds", [])[-1]["status"] = "failed"
                initial_flow["rounds"].append({"tier": next_tier, "node_ids": next_node_ids, "status": "pending"})
                learner.learning_preferences.metadata["initial_diagnostic_flow"] = initial_flow
                self.learner_repo.save(learner)
                initial_status = "retest"
                initial_final = False
                next_questions = [self.knowledge_service.public_question(question) for question in next_round]
            else:
                final_tier = assessed_tier
                initial_flow["status"] = "final"
                initial_flow["final_tier"] = final_tier
                initial_flow.setdefault("rounds", [])[-1]["status"] = "passed" if passed else "floor_reached"
                learner.skill_level = difficulty_for_tier(final_tier)
                initial_recommended_node_id = self._initial_recommended_node(
                    list(raw_scores), {node_id: item["correct_question_count"] for node_id, item in coverage.items()}, nodes,
                )
                initial_flow["initial_recommended_node_id"] = initial_recommended_node_id
                learner.learning_preferences.metadata["initial_diagnostic_flow"] = initial_flow
                self.learner_repo.save(learner)
                initial_status = "final"
        elif raw_scores:
            average = sum(raw_scores.values()) / len(raw_scores)
            learner.skill_level = "初级" if average < 0.6 else "中级" if average <= 0.85 else "进阶"
            self.learner_repo.save(learner)

        self.diagnosis_repo.save_submission(
            knowledge_base_id=knowledge_base_id,
            learner_id=learner.learner_id,
            answers=records,
            knowledge_states={},
            source_id=source_id,
        )

        if not initial_final:
            states = {
                node_id: KnowledgeState(score=None, status="needs_evidence", evidence=[], last_updated=occurred_at.isoformat(), **item)
                for node_id, item in coverage.items()
            }
        elif self.mastery_service is not None:
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
            if final_tier is not None:
                self.mastery_service.finalize_initial_placement(learner, tier=final_tier)
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

        # Evidence-poor submissions are intentionally visible to the caller,
        # but are never written as objective ability states.
        for node_id, item in coverage.items():
            if item["measurement_status"] == "needs_evidence":
                states[node_id] = KnowledgeState(
                    score=None,
                    status="needs_evidence",
                    evidence=[],
                    last_updated=occurred_at.isoformat(),
                    **item,
                )

        weak_nodes = [node_id for node_id, state in states.items() if state.status == "weak"] if initial_final else []
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
            initial_diagnostic_status=initial_status,
            questionnaire_tier=(int(initial_flow["questionnaire_tier"]) if initial_flow else None),
            assessed_tier=assessed_tier,
            final_tier=final_tier,
            next_diagnostic_questions=next_questions,
            initial_recommended_node_id=initial_recommended_node_id,
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
                raw_result={
                    **result.model_dump(mode="json"),
                    "blind_spot_trace": blind_spot_trace,
                    "measurement_coverage": coverage,
                    "initial_diagnostic_status": initial_status,
                    "assessed_tier": assessed_tier,
                    "final_tier": final_tier,
                    "initial_recommended_node_id": initial_recommended_node_id,
                    "submitted_at": occurred_at.isoformat(),
                },
                created_at=result.created_at,
            )
        )
        return result
