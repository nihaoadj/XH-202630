import json
import uuid
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from app.agents.feedback import apply_feedback_decision, decide_feedback
from app.db.feedback.base import BaseFeedbackRepository
from app.db.feedback_loop.base import (
    BaseFeedbackLoopRepository,
    FeedbackIdempotencyConflict,
    LearnerProfileVersionConflict,
    LearningPathMutationConflict,
)
from app.db.audit.base import BaseAuditRepository
from app.core.errors import ApplicationError, ErrorCode
from app.models.feedback_loop import (
    FeedbackDecision,
    FeedbackLoopResult,
    FollowUpGenerationStatus,
    LearningAttempt,
    LearningAttemptSubmit,
    ProfileVersionRecord,
)
from app.models.persistence import WorkflowEventType, canonical_hash
from app.models.schemas import (
    FeedbackAnswer,
    FeedbackRecord,
    FeedbackRequest,
    FeedbackResponse,
    LearnerProfile,
    LearningResource,
    ResourceEvaluationQuestion,
    ResourceEvaluationSessionResponse,
    ResourceEvaluationSubmitRequest,
    ResourceEvaluationSubmitResponse,
    RunEvaluationSessionResponse,
    RunEvaluationSubmitRequest,
    RunEvaluationSubmitResponse,
)
from app.services.knowledge_service import KnowledgeService
from app.services.generation_job_service import GenerationJobService
from app.models.schemas import GenerateRequest
from app.agents.feedback_policy import build_mastery_mutations, decide_attempt
from app.services.learning_path_policy import mutate_learning_path
from app.db.knowledge.catalog import KnowledgeCatalogRepository


logger = logging.getLogger(__name__)


class FeedbackService:
    """Handle learning feedback and post-learning evaluations."""

    def __init__(
        self,
        feedback_repo: BaseFeedbackRepository,
        feedback_loop_repo: BaseFeedbackLoopRepository | None = None,
        generation_job_service: GenerationJobService | None = None,
        audit_repo: BaseAuditRepository | None = None,
        knowledge_catalog: KnowledgeCatalogRepository | None = None,
    ):
        self.feedback_repo = feedback_repo
        self.feedback_loop_repo = feedback_loop_repo
        self.generation_job_service = generation_job_service
        self.audit_repo = audit_repo
        self.knowledge_catalog = knowledge_catalog

    def process_learning_attempt(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        req: LearningAttemptSubmit,
        *,
        schedule_followup: Callable[[LearnerProfile, GenerateRequest, str], None] | None = None,
    ) -> FeedbackLoopResult:
        """Commit learner facts first, then enqueue generation as an after-commit side effect."""

        if self.feedback_loop_repo is None:
            raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=503)
        if profile.learner_id != req.learner_id or resource.learner_id != req.learner_id:
            raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=422)
        if resource.resource_id != req.source_resource_id or resource.version != req.source_resource_version:
            raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=422)
        if resource.publication_status != "published":
            raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=422)
        if req.source_run_id and resource.run_id != req.source_run_id:
            raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=422)
        if self.knowledge_catalog is not None and profile.knowledge_base_id:
            allowed_nodes = {
                item.node_id for item in self.knowledge_catalog.list_skill_nodes(profile.knowledge_base_id)
            }
            requested_nodes = {item.knowledge_point_id for item in req.knowledge_point_results}
            if requested_nodes - allowed_nodes:
                raise ApplicationError(ErrorCode.FEEDBACK_ATTEMPT_INVALID, status_code=422)

        request_payload = req.model_dump(mode="json", exclude_none=False)
        request_hash = canonical_hash(request_payload)
        existing = self.feedback_loop_repo.get_by_idempotency_key(req.learner_id, req.idempotency_key)
        if existing:
            if existing.attempt.request_hash != request_hash:
                raise ApplicationError(ErrorCode.FEEDBACK_IDEMPOTENCY_CONFLICT, status_code=409)
            return self._ensure_followup(profile, existing, schedule_followup)

        attempt_id = self._stable_id("att", req.learner_id, req.idempotency_key)
        attempt = LearningAttempt(
            attempt_id=attempt_id,
            request_hash=request_hash,
            **req.model_dump(mode="python"),
        )
        point_ids = [item.knowledge_point_id for item in attempt.knowledge_point_results]
        context = self.feedback_loop_repo.get_context(req.learner_id, point_ids)
        policy = decide_attempt(attempt, context)
        decision_id = self._stable_id("fdc", attempt_id)
        decision_payload = {
            "decision_id": decision_id,
            "learner_id": req.learner_id,
            "attempt_id": attempt_id,
            "action": policy.action.value,
            "reason_codes": list(policy.reason_codes),
            "decision_reason": policy.decision_reason,
            "target_knowledge_point_ids": list(policy.target_knowledge_point_ids),
        }
        decision = FeedbackDecision(
            **decision_payload,
            decision_hash=canonical_hash(decision_payload),
        )
        state_mutations = build_mastery_mutations(attempt, context)
        try:
            learning_path, path_mutation = mutate_learning_path(
                attempt=attempt,
                decision_id=decision_id,
                policy=policy,
                existing=context.learning_path,
            )
        except ValueError as exc:
            raise ApplicationError(ErrorCode.LEARNING_PATH_MUTATION_INVALID, status_code=422) from exc
        new_version = context.profile_version + 1
        profile_patch = self._profile_patch(profile, attempt, decision, state_mutations)
        version_record = ProfileVersionRecord(
            learner_id=profile.learner_id,
            profile_version=new_version,
            source_attempt_id=attempt_id,
            source_decision_id=decision_id,
            change_summary={
                "action": decision.action.value,
                "knowledge_point_ids": point_ids,
                "path_mutation_id": path_mutation.mutation_id,
                "mastery_update_count": len(state_mutations),
            },
        )
        try:
            result = self.feedback_loop_repo.apply_feedback(
                attempt=attempt,
                decision=decision,
                state_mutations=state_mutations,
                learning_path=learning_path,
                path_mutation=path_mutation,
                profile_version=version_record,
                profile_patch=profile_patch,
            )
        except FeedbackIdempotencyConflict as exc:
            raise ApplicationError(ErrorCode.FEEDBACK_IDEMPOTENCY_CONFLICT, status_code=409) from exc
        except LearnerProfileVersionConflict as exc:
            raise ApplicationError(ErrorCode.LEARNER_PROFILE_VERSION_CONFLICT, status_code=409) from exc
        except LearningPathMutationConflict as exc:
            raise ApplicationError(ErrorCode.LEARNING_PATH_MUTATION_INVALID, status_code=409) from exc

        self._apply_profile_copy(profile, profile_patch, state_mutations, new_version)
        self._record_feedback_events(result)
        return self._ensure_followup(profile, result, schedule_followup)

    def list_attempts(self, learner_id: str, limit: int = 20) -> list[LearningAttempt]:
        return self.feedback_loop_repo.list_attempts(learner_id, limit) if self.feedback_loop_repo else []

    def get_current_path(self, learner_id: str):
        return self.feedback_loop_repo.get_current_path(learner_id) if self.feedback_loop_repo else None

    def list_profile_versions(self, learner_id: str, limit: int = 20):
        return self.feedback_loop_repo.list_profile_versions(learner_id, limit) if self.feedback_loop_repo else []

    @staticmethod
    def _stable_id(prefix: str, *parts: object) -> str:
        material = "\x1f".join(str(part) for part in parts)
        return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()[:32]}"

    def _profile_patch(self, profile, attempt, decision, mutations) -> dict:
        weak = list(profile.weak_points)
        strong = list(profile.strong_points)
        targets = decision.target_knowledge_point_ids
        if decision.action.value == "remediate":
            weak = list(dict.fromkeys([*weak, *targets]))
            skill_level = "初级"
        elif decision.action.value == "advance":
            weak = [item for item in weak if item not in targets]
            strong = list(dict.fromkeys([*strong, *targets]))
            skill_level = "高级"
        else:
            skill_level = profile.skill_level
        return {
            "skill_level": skill_level,
            "weak_points": weak,
            "strong_points": strong,
            "last_feedback_summary": {
                "attempt_id": attempt.attempt_id,
                "resource_id": attempt.source_resource_id,
                "overall_score": attempt.overall_score,
                "action": decision.action.value,
                "knowledge_point_ids": [item.knowledge_point_id for item in mutations],
            },
        }

    @staticmethod
    def _apply_profile_copy(profile, patch, mutations, profile_version):
        from app.models.schemas import KnowledgeState

        profile.profile_version = profile_version
        profile.skill_level = patch["skill_level"]
        profile.weak_points = list(patch["weak_points"])
        profile.strong_points = list(patch["strong_points"])
        profile.last_feedback_summary = dict(patch["last_feedback_summary"])
        for item in mutations:
            profile.knowledge_states[item.knowledge_point_id] = KnowledgeState(
                score=item.after.mastery,
                status=item.after.status,
                evidence=[item.source_attempt_id],
            )

    def _ensure_followup(self, profile, result, schedule_followup):
        if result.followup_generation_status == FollowUpGenerationStatus.QUEUED:
            return result
        if result.decision.action.value not in {"remediate", "advance"}:
            return result
        if self.generation_job_service is None:
            return self.feedback_loop_repo.attach_followup(
                attempt_id=result.attempt.attempt_id,
                decision_id=result.decision.decision_id,
                parent_run_id=result.attempt.source_run_id,
                child_run_id=None,
                trigger_type=result.decision.action.value,
                status=FollowUpGenerationStatus.FAILED.value,
                error_code=ErrorCode.FOLLOWUP_GENERATION_FAILED.value,
            )
        difficulty = "初级" if result.decision.action.value == "remediate" else "高级"
        suffix = "补救训练" if result.decision.action.value == "remediate" else "进阶挑战"
        generation_request = GenerateRequest(
            learner_id=result.attempt.learner_id,
            topic=f"{result.decision.target_knowledge_point_ids[0]} {suffix}",
            knowledge_base_id=profile.knowledge_base_id,
            target_skill_nodes=result.decision.target_knowledge_point_ids,
            resource_types=["定制讲义", "分阶测试题"],
            difficulty_preference=difficulty,
            generation_mode="standard",
            include_review=True,
            include_claim_check=True,
            max_iterations=2,
            constraints={"must_include_citations": True, "feedback_attempt_id": result.attempt.attempt_id},
        )
        try:
            followup_run_id = self._stable_id("run", result.attempt.attempt_id, "followup")
            job = self.generation_job_service.create_job(
                profile,
                generation_request,
                run_id=followup_run_id,
                retry_failed=True,
            )
            updated = self.feedback_loop_repo.attach_followup(
                attempt_id=result.attempt.attempt_id,
                decision_id=result.decision.decision_id,
                parent_run_id=result.attempt.source_run_id,
                child_run_id=job.run_id,
                trigger_type=result.decision.action.value,
                status=FollowUpGenerationStatus.QUEUED.value,
            )
            updated.idempotent_replay = result.idempotent_replay
            self._append_event(
                result.attempt.source_run_id,
                WorkflowEventType.FOLLOWUP_GENERATION_CREATED,
                result.attempt.attempt_id,
                {"attempt_id": result.attempt.attempt_id, "decision_id": result.decision.decision_id, "child_run_id": job.run_id},
                "queued",
            )
            if schedule_followup:
                schedule_followup(profile.model_copy(deep=True), generation_request, job.run_id)
            return updated
        except Exception:
            logger.exception("Follow-up generation creation failed attempt_id=%s", result.attempt.attempt_id)
            updated = self.feedback_loop_repo.attach_followup(
                attempt_id=result.attempt.attempt_id,
                decision_id=result.decision.decision_id,
                parent_run_id=result.attempt.source_run_id,
                child_run_id=None,
                trigger_type=result.decision.action.value,
                status=FollowUpGenerationStatus.FAILED.value,
                error_code=ErrorCode.FOLLOWUP_GENERATION_FAILED.value,
            )
            updated.idempotent_replay = result.idempotent_replay
            self._append_event(
                result.attempt.source_run_id,
                WorkflowEventType.FOLLOWUP_GENERATION_FAILED,
                result.attempt.attempt_id,
                {"attempt_id": result.attempt.attempt_id, "decision_id": result.decision.decision_id},
                "failed",
                ErrorCode.FOLLOWUP_GENERATION_FAILED.value,
            )
            return updated

    def _record_feedback_events(self, result: FeedbackLoopResult) -> None:
        run_id = result.attempt.source_run_id
        if not run_id:
            return
        attempt_id = result.attempt.attempt_id
        summary = {
            "attempt_id": attempt_id,
            "decision_id": result.decision.decision_id,
            "overall_score": result.attempt.overall_score,
            "knowledge_point_ids": [item.knowledge_point_id for item in result.knowledge_state_updates],
        }
        self._append_event(run_id, WorkflowEventType.ATTEMPT_SUBMITTED, attempt_id, summary, "submitted")
        self._append_event(run_id, WorkflowEventType.FEEDBACK_DECISION_STARTED, attempt_id, {"attempt_id": attempt_id}, "started")
        self._append_event(run_id, WorkflowEventType.FEEDBACK_DECISION_COMPLETED, attempt_id, {
            **summary, "action": result.decision.action.value, "reason_codes": result.decision.reason_codes,
        }, "completed")
        self._append_event(run_id, WorkflowEventType.KNOWLEDGE_STATE_UPDATED, attempt_id, {
            "attempt_id": attempt_id, "knowledge_point_ids": summary["knowledge_point_ids"], "count": len(result.knowledge_state_updates),
        }, "applied")
        self._append_event(run_id, WorkflowEventType.PROFILE_UPDATED, attempt_id, {
            "attempt_id": attempt_id, "profile_version": result.profile_version,
        }, "applied")
        self._append_event(run_id, WorkflowEventType.PATH_MUTATED, attempt_id, {
            "attempt_id": attempt_id,
            "mutation_id": result.path_mutation.mutation_id,
            "path_id": result.path_mutation.path_id,
            "inserted_node_ids": result.path_mutation.inserted_node_ids,
            "unlocked_node_ids": result.path_mutation.unlocked_node_ids,
            "completed_node_ids": result.path_mutation.completed_node_ids,
        }, "applied")

    def _append_event(self, run_id, event_type, subject_id, payload, status, error_code=None):
        if not run_id or self.audit_repo is None or self.audit_repo.get_run(run_id) is None:
            return
        try:
            self.audit_repo.append_event(
                run_id,
                event_type,
                payload=payload,
                occurred_at=datetime.now(timezone.utc),
                node_name="feedback_loop",
                status=status,
                error_code=error_code,
                event_id=self._stable_id("evt", run_id, event_type.value, subject_id),
            )
        except Exception:
            # Attempt/profile/path facts are already committed; audit outage must not
            # pretend the learner action never happened.
            logger.exception("Feedback audit event failed run_id=%s type=%s", run_id, event_type.value)

    def process_feedback(self, profile: LearnerProfile, req: FeedbackRequest) -> FeedbackResponse:
        history = self.feedback_repo.list_by_learner(req.learner_id)
        decision_result = decide_feedback(profile, req, history)
        apply_feedback_decision(profile, req, decision_result)

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            learner_id=req.learner_id,
            resource_id=req.resource_id,
            correct_rate=req.correct_rate,
            decision=decision_result.decision,
            answers=req.answers,
            feedback_type=req.feedback_type,
            time_spent_seconds=req.time_spent_seconds,
            completed=req.completed,
            self_rating=req.self_rating,
            practice_result=req.practice_result,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )
        self.feedback_repo.save(record)

        return FeedbackResponse(
            learner_id=req.learner_id,
            decision=decision_result.decision,
            message=f"根据正确率 {req.correct_rate:.0%}，系统决定：{decision_result.decision}",
            updated_profile=profile,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )

    def list_history(self, learner_id: str) -> list[FeedbackRecord]:
        return self.feedback_repo.list_by_learner(learner_id)

    def build_evaluation_session(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        knowledge_service: KnowledgeService,
    ) -> ResourceEvaluationSessionResponse:
        questions, _ = self._build_question_specs(profile, resource, knowledge_service)
        return ResourceEvaluationSessionResponse(
            learner_id=profile.learner_id,
            resource_id=resource.resource_id,
            topic=resource.topic,
            total=len(questions),
            questions=questions,
        )

    def build_run_evaluation_session(
        self,
        profile: LearnerProfile,
        run_id: str,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
    ) -> RunEvaluationSessionResponse:
        questions, _ = self._build_run_question_specs(profile, resources, knowledge_service)
        topic = self._merge_topics(resources)
        return RunEvaluationSessionResponse(
            learner_id=profile.learner_id,
            run_id=run_id,
            topic=topic,
            resource_ids=[resource.resource_id for resource in resources],
            total=len(questions),
            questions=questions,
        )

    def submit_evaluation_feedback(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        payload: ResourceEvaluationSubmitRequest,
        knowledge_service: KnowledgeService,
    ) -> ResourceEvaluationSubmitResponse:
        questions, answer_key = self._build_question_specs(profile, resource, knowledge_service)
        if not questions:
            raise ValueError("当前资源暂时没有可用测评题目")

        submitted_answers = {item.question_id: item.answer for item in payload.answers}
        feedback_answers: list[FeedbackAnswer] = []
        wrong_points: list[str] = []
        correct_count = 0

        for question in questions:
            actual_answer = submitted_answers.get(question.question_id)
            expected_answer = answer_key.get(question.question_id)
            is_correct = self._answers_match(expected_answer, actual_answer)
            if is_correct:
                correct_count += 1
            elif question.knowledge_point:
                wrong_points.append(question.knowledge_point)

            feedback_answers.append(
                FeedbackAnswer(
                    question_id=question.question_id,
                    correct=is_correct,
                    answer=actual_answer,
                    knowledge_point=question.knowledge_point,
                    difficulty=question.difficulty,
                    expected_answer=expected_answer,
                )
            )

        correct_rate = correct_count / len(questions)
        practice_result = dict(payload.practice_result or {})
        practice_result["evaluation_total"] = len(questions)
        practice_result["evaluation_correct"] = correct_count
        practice_result["resource_topic"] = resource.topic

        feedback_response = self.process_feedback(
            profile,
            FeedbackRequest(
                learner_id=payload.learner_id,
                resource_id=payload.resource_id,
                correct_rate=correct_rate,
                feedback_type=payload.feedback_type or "evaluation_feedback",
                time_spent_seconds=payload.time_spent_seconds,
                completed=payload.completed,
                self_rating=payload.self_rating,
                practice_result=practice_result,
                answers=feedback_answers,
            ),
        )

        return ResourceEvaluationSubmitResponse(
            learner_id=payload.learner_id,
            resource_id=payload.resource_id,
            correct_rate=correct_rate,
            correct_count=correct_count,
            total_questions=len(questions),
            wrong_knowledge_points=list(dict.fromkeys(point for point in wrong_points if point)),
            feedback=feedback_response,
        )

    def submit_run_evaluation_feedback(
        self,
        profile: LearnerProfile,
        run_id: str,
        resources: list[LearningResource],
        payload: RunEvaluationSubmitRequest,
        knowledge_service: KnowledgeService,
    ) -> RunEvaluationSubmitResponse:
        questions, answer_key = self._build_run_question_specs(profile, resources, knowledge_service)
        if not questions:
            raise ValueError("当前任务暂时没有可用测评题目")

        submitted_answers = {item.question_id: item.answer for item in payload.answers}
        feedback_answers: list[FeedbackAnswer] = []
        wrong_points: list[str] = []
        correct_count = 0

        for question in questions:
            actual_answer = submitted_answers.get(question.question_id)
            expected_answer = answer_key.get(question.question_id)
            is_correct = self._answers_match(expected_answer, actual_answer)
            if is_correct:
                correct_count += 1
            elif question.knowledge_point:
                wrong_points.append(question.knowledge_point)

            feedback_answers.append(
                FeedbackAnswer(
                    question_id=question.question_id,
                    correct=is_correct,
                    answer=actual_answer,
                    knowledge_point=question.knowledge_point,
                    difficulty=question.difficulty,
                    expected_answer=expected_answer,
                )
            )

        correct_rate = correct_count / len(questions)
        primary_resource = resources[0]
        practice_result = dict(payload.practice_result or {})
        practice_result["evaluation_total"] = len(questions)
        practice_result["evaluation_correct"] = correct_count
        practice_result["resource_topic"] = self._merge_topics(resources)
        practice_result["run_id"] = run_id
        practice_result["evaluated_resource_ids"] = [resource.resource_id for resource in resources]
        practice_result["evaluated_resource_count"] = len(resources)

        feedback_response = self.process_feedback(
            profile,
            FeedbackRequest(
                learner_id=payload.learner_id,
                resource_id=primary_resource.resource_id,
                correct_rate=correct_rate,
                feedback_type=payload.feedback_type or "run_evaluation_feedback",
                time_spent_seconds=payload.time_spent_seconds,
                completed=payload.completed,
                self_rating=payload.self_rating,
                practice_result=practice_result,
                answers=feedback_answers,
            ),
        )

        return RunEvaluationSubmitResponse(
            learner_id=payload.learner_id,
            run_id=run_id,
            resource_count=len(resources),
            correct_rate=correct_rate,
            correct_count=correct_count,
            total_questions=len(questions),
            wrong_knowledge_points=list(dict.fromkeys(point for point in wrong_points if point)),
            feedback=feedback_response,
        )

    def _build_question_specs(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        knowledge_service: KnowledgeService,
        limit: int = 5,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        questions: list[ResourceEvaluationQuestion] = []
        answer_key: dict[str, object] = {}

        for item in resource.exercise_items:
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type="short_answer",
                    question=item.question,
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    source="resource",
                )
            )
            answer_key[item.question_id] = item.answer

        if questions:
            return questions[:limit], answer_key

        if not profile.knowledge_base_id:
            return [], {}

        tokens = [resource.topic or "", *(resource.knowledge_points or [])]
        related = []
        for item in knowledge_service.load_diagnostic_questions(profile.knowledge_base_id):
            searchable = " ".join(
                [
                    item.question or "",
                    item.knowledge_point or "",
                    " ".join(item.options or []),
                ]
            )
            if any(token and token in searchable for token in tokens):
                related.append(item)

        if not related:
            related = knowledge_service.select_diagnostic_questions(
                profile.knowledge_base_id,
                limit=limit,
            )

        for item in related[:limit]:
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type=item.question_type,
                    question=item.question,
                    options=item.options or [],
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    source="knowledge_base",
                )
            )
            answer_key[item.question_id] = item.answer

        return questions, answer_key

    def _build_run_question_specs(
        self,
        profile: LearnerProfile,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
        limit: int = 8,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        merged_questions: list[ResourceEvaluationQuestion] = []
        merged_answer_key: dict[str, object] = {}
        seen_question_ids: set[str] = set()

        for resource in resources:
            questions, answer_key = self._build_question_specs(profile, resource, knowledge_service, limit=5)
            for question in questions:
                if question.question_id in seen_question_ids:
                    continue
                merged_questions.append(question)
                merged_answer_key[question.question_id] = answer_key.get(question.question_id)
                seen_question_ids.add(question.question_id)
                if len(merged_questions) >= limit:
                    return merged_questions, merged_answer_key

        return merged_questions, merged_answer_key

    @staticmethod
    def _merge_topics(resources: list[LearningResource]) -> str:
        topics = [resource.topic for resource in resources if resource.topic]
        unique_topics = list(dict.fromkeys(topics))
        return " / ".join(unique_topics[:3]) if unique_topics else ""

    @staticmethod
    def _answers_match(expected: object, actual: object) -> bool:
        return json.dumps(expected, ensure_ascii=False, sort_keys=True) == json.dumps(
            actual,
            ensure_ascii=False,
            sort_keys=True,
        )
