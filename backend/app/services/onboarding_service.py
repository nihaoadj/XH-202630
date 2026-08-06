"""根据 onboarding 问卷创建初始学习画像。"""
from __future__ import annotations

from typing import Any

from app.db.learner.base import BaseLearnerRepository
from app.db.questionnaire.base import BaseQuestionnaireRepository
from app.db.user.base import BaseUserRepository
from app.models.schemas import (
    InitialProfileQuestionnaire,
    InitialProfileResponse,
    KnowledgeState,
    LearnerProfile,
    LearningPreferences,
)
from app.models.user_schemas import UserProfile
from app.services.knowledge_service import KnowledgeService


class OnboardingService:
    COMMON_QUESTIONNAIRE_ID = "common_initial_profile_v1"

    def __init__(
        self,
        learner_repo: BaseLearnerRepository,
        knowledge_service: KnowledgeService,
        questionnaire_repo: BaseQuestionnaireRepository,
        user_repo: BaseUserRepository,
    ):
        self.learner_repo = learner_repo
        self.knowledge_service = knowledge_service
        self.questionnaire_repo = questionnaire_repo
        self.user_repo = user_repo

    def create_initial_profile(self, request: InitialProfileQuestionnaire) -> InitialProfileResponse:
        manifest = self.knowledge_service._ensure_knowledge_base(request.learning_direction_id)
        self._validate_answers(request, manifest)
        user = self._resolve_user(request)
        nodes = self.knowledge_service.list_skill_nodes(manifest["knowledge_base_id"])
        node_by_id = {node.node_id: node for node in nodes}

        diagnostic_node_ids, screening_results = self._diagnostic_node_ids(request, node_by_id)
        not_started_node_ids = [node.node_id for node in nodes if node.node_id not in diagnostic_node_ids]
        existing = self.learner_repo.get(request.learner_id)
        profile = self._build_profile(
            request,
            existing,
            user,
            manifest["knowledge_base_id"],
            node_by_id,
            diagnostic_node_ids,
            not_started_node_ids,
        )
        self.learner_repo.save(profile)
        self._save_questionnaire_submissions(request, manifest, profile)

        questions = (
            self.knowledge_service.select_diagnostic_questions(
                manifest["knowledge_base_id"], skill_node_ids=diagnostic_node_ids
            )
            if diagnostic_node_ids
            else []
        )
        return InitialProfileResponse(
            learner_id=profile.learner_id,
            profile=profile,
            diagnostic_node_ids=diagnostic_node_ids,
            not_started_node_ids=not_started_node_ids,
            screening_results=screening_results,
            diagnostic_questions=[self.knowledge_service.public_question(question) for question in questions],
            next_step="提交诊断答案到 POST /api/diagnosis/submit，然后进入第 5 步选择资源类型。",
        )

    def questionnaire(self, learning_direction_id: str | None = None) -> list[dict[str, Any]]:
        manifest = self.knowledge_service._ensure_knowledge_base(learning_direction_id)
        common, track = self._questionnaire_templates(manifest["knowledge_base_id"])
        return [*common.get("questions", []), *track.get("questions", [])]

    def _resolve_user(self, request: InitialProfileQuestionnaire) -> UserProfile:
        payload = self._answer_payload(request)
        user_id = payload.get("user_id")
        if not user_id:
            raise ValueError("用户基础信息不存在，请先创建用户资料")
        user = self.user_repo.get(user_id)
        if user is None:
            raise ValueError("用户基础信息不存在，请先创建用户资料")
        return user

    def _validate_answers(self, request: InitialProfileQuestionnaire, manifest: dict[str, Any]) -> None:
        questions = self._question_by_id(manifest["knowledge_base_id"])
        answers = self._answer_payload(request)
        for question_id, question in questions.items():
            answer = answers.get(question_id)
            if question.get("required") and self._is_empty_answer(answer):
                raise ValueError(f"缺少必答字段: {question_id}")
            if self._is_empty_answer(answer) or question.get("type") == "text":
                continue
            self._validate_option_answer(question, answer)

    def _diagnostic_node_ids(
        self, request: InitialProfileQuestionnaire, node_by_id: dict[str, Any]
    ) -> tuple[list[str], dict[str, bool]]:
        selected = set()
        if not node_by_id:
            return [], {}
        questions = self._question_by_id(request.learning_direction_id)
        answers = self._answer_payload(request)
        for question_id, answer in answers.items():
            values = answer if isinstance(answer, list) else [answer]
            for value in values:
                selected.update(self._option_metadata(questions, question_id, value).get("diagnostic_scope_add", []))
        return [node_id for node_id in node_by_id if node_id in selected], {}

    def _build_profile(
        self,
        request: InitialProfileQuestionnaire,
        existing: LearnerProfile | None,
        user: UserProfile,
        knowledge_base_id: str,
        node_by_id: dict[str, Any],
        diagnostic_node_ids: list[str],
        not_started_node_ids: list[str],
    ) -> LearnerProfile:
        questions = self._question_by_id(knowledge_base_id)
        answers = self._answer_payload(request)
        mapped = self._profile_mapping_values(questions, answers)
        score_values = list(mapped["self_report_scores"]) or [25]
        average = sum(score_values) / len(score_values)
        skill_level = "初级" if average < 40 else "中级" if average < 75 else "进阶"

        prior_states = dict(existing.knowledge_states) if existing else {}
        for node_id in diagnostic_node_ids:
            name = node_by_id[node_id].name
            if name not in prior_states or self._is_onboarding_state(prior_states[name]):
                prior_states[name] = KnowledgeState(
                    status="self_reported",
                    evidence=["onboarding: user selected this node as known"],
                )
        for node_id in not_started_node_ids:
            name = node_by_id[node_id].name
            if name not in prior_states or self._is_onboarding_state(prior_states[name]):
                prior_states[name] = KnowledgeState(
                    status="not_started",
                    evidence=["onboarding: user did not select this node as known"],
                )

        prior_scores = dict(existing.theory_scores) if existing else {}
        prior_scores.update(mapped["theory_scores"])
        old_preferences = existing.learning_preferences if existing and existing.learning_preferences else LearningPreferences()
        metadata = dict(old_preferences.metadata)
        metadata["onboarding"] = {**answers, "learning_direction_id": request.learning_direction_id}
        metadata["user_id"] = user.user_id
        metadata["user_profile_snapshot"] = user.model_dump(mode="json")
        metadata.update(mapped["learning_preferences_metadata"])
        difficulty_preference = mapped["learning_preferences"].get(
            "difficulty_preference",
            old_preferences.difficulty_preference or "自适应推荐",
        )
        preferences = LearningPreferences(
            preferred_resource_types=old_preferences.preferred_resource_types,
            difficulty_preference=difficulty_preference,
            time_budget_minutes=old_preferences.time_budget_minutes,
            language=old_preferences.language or "zh-CN",
            metadata=metadata,
        )
        not_started_names = [node_by_id[node_id].name for node_id in not_started_node_ids]
        preserved_weak_points = list(existing.weak_points) if existing else []
        return LearnerProfile(
            learner_id=request.learner_id,
            learner_type=mapped["root"].get("learner_type") or user.identity or (existing.learner_type if existing else "问卷学习者"),
            education=user.education,
            major=user.major,
            target_domain=self.knowledge_service._ensure_knowledge_base(knowledge_base_id).get("domain"),
            knowledge_base_id=knowledge_base_id,
            theory_scores=prior_scores,
            knowledge_states=prior_states,
            skill_level=skill_level,
            weak_points=list(dict.fromkeys(preserved_weak_points + not_started_names)),
            strong_points=list(existing.strong_points) if existing else [],
            learning_goal=mapped["root"].get("learning_goal") or (existing.learning_goal if existing else "未填写"),
            learning_preferences=preferences,
            last_feedback_summary=existing.last_feedback_summary if existing else {},
        )

    @staticmethod
    def _is_onboarding_state(state: KnowledgeState) -> bool:
        return bool(state.evidence) and all(item.startswith("onboarding:") for item in state.evidence)

    def _questionnaire_templates(self, knowledge_base_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        common = self.questionnaire_repo.get_questionnaire_template(self.COMMON_QUESTIONNAIRE_ID)
        track = self.questionnaire_repo.get_questionnaire_for_track(knowledge_base_id, knowledge_base_id)
        if common is None:
            raise ValueError("数据库中缺少通用初始画像问卷")
        if track is None:
            raise ValueError(f"数据库中缺少学习方向问卷: {knowledge_base_id}")
        return common, track

    def _question_by_id(self, learning_direction_id: str | None) -> dict[str, dict[str, Any]]:
        manifest = self.knowledge_service._ensure_knowledge_base(learning_direction_id)
        common, track = self._questionnaire_templates(manifest["knowledge_base_id"])
        return {question["question_id"]: question for question in [*common["questions"], *track["questions"]]}

    @staticmethod
    def _answer_payload(request: InitialProfileQuestionnaire) -> dict[str, Any]:
        payload = dict(request.answers or {})
        payload.update(request.model_extra or {})
        return payload

    @staticmethod
    def _is_empty_answer(value: Any) -> bool:
        return value is None or value == "" or value == []

    def _validate_option_answer(self, question: dict[str, Any], answer: Any) -> None:
        valid_values = {
            option.get("value", option.get("label"))
            for option in question.get("options", [])
            if isinstance(option, dict)
        }
        if not valid_values:
            return
        values = answer if isinstance(answer, list) else [answer]
        invalid = [value for value in values if value not in valid_values]
        if invalid:
            raise ValueError(f"{question['question_id']} 包含不支持的选项: {', '.join(invalid)}")
        exclusive = set((question.get("validation") or {}).get("exclusive_option_values", []))
        if exclusive & set(values) and len(values) > 1:
            raise ValueError(f"{question['question_id']} 的互斥选项不能与其他选项同时选择")

    def _option_metadata(self, questions: dict[str, dict[str, Any]], question_id: str, value: str | None) -> dict[str, Any]:
        if value is None:
            return {}
        for option in questions.get(question_id, {}).get("options", []):
            if isinstance(option, dict) and option.get("value", option.get("label")) == value:
                return option
        return {}

    def _self_report_score(self, questions: dict[str, dict[str, Any]], question_id: str, value: str | None) -> float | None:
        score = self._option_metadata(questions, question_id, value).get("self_report_score")
        return float(score) if score is not None else None

    def _profile_mapping_values(
        self,
        questions: dict[str, dict[str, Any]],
        answers: dict[str, Any],
    ) -> dict[str, Any]:
        mapped = {
            "root": {},
            "theory_scores": {},
            "learning_preferences": {},
            "learning_preferences_metadata": {},
            "self_report_scores": [],
        }
        for question_id, question in questions.items():
            answer = answers.get(question_id)
            if self._is_empty_answer(answer):
                continue
            mapping = question.get("profile_mapping") or {}
            target_path = mapping.get("target_path")
            transform = mapping.get("transform", "answer")
            value = self._transform_answer(questions, question_id, answer, transform)
            if value is None or not target_path:
                continue
            self._assign_profile_value(mapped, target_path, value)

            values = answer if isinstance(answer, list) else [answer]
            for option_value in values:
                score = self._self_report_score(questions, question_id, option_value)
                if score is not None:
                    mapped["self_report_scores"].append(score)
        return mapped

    def _transform_answer(
        self,
        questions: dict[str, dict[str, Any]],
        question_id: str,
        answer: Any,
        transform: str,
    ) -> Any:
        if transform == "answer":
            return [] if answer == ["无"] else answer
        if transform == "join_semicolon":
            return "；".join(str(item) for item in answer) if isinstance(answer, list) else str(answer)
        if transform == "option.profile_value":
            return self._option_metadata(questions, question_id, answer).get("profile_value", answer)
        if transform == "option.self_report_score":
            values = answer if isinstance(answer, list) else [answer]
            scores = [self._self_report_score(questions, question_id, value) for value in values]
            scores = [score for score in scores if score is not None]
            if not scores:
                return None
            return sum(scores) / len(scores)
        return answer

    @staticmethod
    def _assign_profile_value(mapped: dict[str, Any], target_path: str, value: Any) -> None:
        if target_path.startswith("theory_scores."):
            mapped["theory_scores"][target_path.removeprefix("theory_scores.")] = value
            return
        if target_path.startswith("learning_preferences.metadata."):
            key = target_path.removeprefix("learning_preferences.metadata.")
            mapped["learning_preferences_metadata"][key] = value
            return
        if target_path.startswith("learning_preferences."):
            key = target_path.removeprefix("learning_preferences.")
            if key == "focus_nodes":
                mapped["learning_preferences_metadata"]["focus_nodes"] = value
            else:
                mapped["learning_preferences"][key] = value
            return
        mapped["root"][target_path] = value

    def _save_questionnaire_submissions(
        self,
        request: InitialProfileQuestionnaire,
        manifest: dict[str, Any],
        profile: LearnerProfile,
    ) -> None:
        common, track = self._questionnaire_templates(manifest["knowledge_base_id"])
        answers = self._answer_payload(request)
        for template in (common, track):
            question_ids = {question["question_id"] for question in template.get("questions", [])}
            template_answers = {
                key: value
                for key, value in answers.items()
                if key in question_ids and not self._is_empty_answer(value)
            }
            if not template_answers:
                continue
            self.questionnaire_repo.save_submission(
                questionnaire_id=template["questionnaire_id"],
                learner_id=request.learner_id,
                answers=template_answers,
                track_id=manifest["knowledge_base_id"],
                knowledge_base_id=manifest["knowledge_base_id"],
                profile_updates=profile.model_dump(mode="json"),
                metadata={"purpose": "initial_profile"},
            )
