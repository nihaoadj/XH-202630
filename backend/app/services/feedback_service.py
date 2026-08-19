import json
import uuid
import hashlib
import logging
import random
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
    BatchEvaluationSessionResponse,
    LearnerProfile,
    LearningResource,
    ResourceEvaluationQuestion,
    ResourceEvaluationSessionResponse,
    ResourceEvaluationSubmitRequest,
    ResourceEvaluationSubmitResponse,
    RunAttemptSubmitRequest,
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
            questions=self._shuffle_question_options(questions, profile.learner_id, resource.resource_id),
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
            questions=self._shuffle_question_options(questions, profile.learner_id, run_id),
        )

    def build_batch_evaluation_session(
        self,
        profile: LearnerProfile,
        batch_id: str,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
    ) -> BatchEvaluationSessionResponse:
        questions, _ = self._build_run_question_specs(profile, resources, knowledge_service)
        return BatchEvaluationSessionResponse(
            learner_id=profile.learner_id,
            batch_id=batch_id,
            topic=self._merge_topics(resources),
            resource_ids=[resource.resource_id for resource in resources],
            total=len(questions),
            questions=self._shuffle_question_options(questions, profile.learner_id, batch_id),
        )

    def submit_run_attempt(
        self,
        profile: LearnerProfile,
        run_id: str,
        resources: list[LearningResource],
        payload: RunAttemptSubmitRequest,
        knowledge_service: KnowledgeService,
        *,
        schedule_followup: Callable[[LearnerProfile, GenerateRequest, str], None] | None = None,
    ) -> FeedbackLoopResult:
        questions, answer_key = self._build_run_question_specs(profile, resources, knowledge_service)
        if not questions:
            raise ValueError("当前任务暂时没有可用测评题目")

        selected_resource = self._select_attempt_resource(resources, payload.source_resource_id)
        submitted_answers = {item.question_id: item.answer for item in payload.answers}
        point_results: dict[str, dict[str, object]] = {}

        for question in questions:
            knowledge_point_id = self._question_result_key(question)
            result = point_results.setdefault(
                knowledge_point_id,
                {
                    "question_ids": [],
                    "correct_count": 0,
                    "total_count": 0,
                    "skill_node_ids": [],
                    "knowledge_points": [],
                    "diagnostic_dimensions": [],
                },
            )
            result["question_ids"].append(question.question_id)
            result["total_count"] += 1
            if question.skill_node_id and question.skill_node_id not in result["skill_node_ids"]:
                result["skill_node_ids"].append(question.skill_node_id)
            if question.knowledge_point and question.knowledge_point not in result["knowledge_points"]:
                result["knowledge_points"].append(question.knowledge_point)
            if question.diagnostic_dimension and question.diagnostic_dimension not in result["diagnostic_dimensions"]:
                result["diagnostic_dimensions"].append(question.diagnostic_dimension)
            if self._answer_score(
                question.question_type,
                answer_key.get(question.question_id),
                submitted_answers.get(question.question_id),
            ) >= 1.0:
                result["correct_count"] += 1

        metadata = dict(payload.metadata)
        evaluation_sources = list(dict.fromkeys(question.source for question in questions))
        metadata.update(
            {
                "evaluation_source": evaluation_sources[0] if len(evaluation_sources) == 1 else "mixed",
                "question_count": len(questions),
                "question_trace": [
                    self._question_trace_item(question, selected_resource.learning_path_node)
                    for question in questions
                ],
                "point_trace": {
                    knowledge_point_id: {
                        "skill_node_ids": values["skill_node_ids"],
                        "knowledge_points": values["knowledge_points"],
                        "diagnostic_dimensions": values["diagnostic_dimensions"],
                    }
                    for knowledge_point_id, values in point_results.items()
                },
            }
        )

        attempt = LearningAttemptSubmit(
            learner_id=payload.learner_id,
            source_resource_id=selected_resource.resource_id,
            source_resource_version=selected_resource.version,
            source_run_id=run_id,
            path_node_id=payload.path_node_id,
            idempotency_key=payload.idempotency_key,
            expected_profile_version=payload.expected_profile_version,
            started_at=payload.started_at,
            submitted_at=payload.submitted_at,
            duration_ms=payload.duration_ms,
            hint_count=payload.hint_count,
            knowledge_point_results=[
                {
                    "knowledge_point_id": knowledge_point_id,
                    "question_ids": values["question_ids"],
                    "correct_count": values["correct_count"],
                    "total_count": values["total_count"],
                }
                for knowledge_point_id, values in point_results.items()
            ],
            metadata=metadata,
        )
        return self.process_learning_attempt(
            profile,
            selected_resource,
            attempt,
            schedule_followup=schedule_followup,
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
            is_correct = self._answer_score(question.question_type, expected_answer, actual_answer) >= 1.0
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
            is_correct = self._answer_score(question.question_type, expected_answer, actual_answer) >= 1.0
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
        limit: int = 10,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        questions: list[ResourceEvaluationQuestion] = []
        answer_key: dict[str, object] = {}

        generated_items = self._usable_resource_exercises(resource)
        if generated_items:
            for item in generated_items[:limit]:
                question_id = f"{resource.resource_id}:{item.question_id}"
                questions.append(
                    ResourceEvaluationQuestion(
                        question_id=question_id,
                        question_type=item.question_type,
                        question=item.question,
                        options=item.options,
                        skill_node_id=item.skill_node_id or resource.learning_path_node,
                        path_node_id=resource.learning_path_node,
                        knowledge_point=item.knowledge_point,
                        difficulty=item.difficulty,
                        diagnostic_dimension=item.diagnostic_dimension,
                        source="resource",
                    )
                )
                answer_key[question_id] = item.answer
            return questions, answer_key

        if not profile.knowledge_base_id:
            return questions, answer_key

        target_skill_nodes = [item for item in self._resource_target_skill_nodes(resource) if item]
        load_assessment = getattr(knowledge_service, "load_assessment_questions", None)
        candidates = load_assessment(profile.knowledge_base_id) if load_assessment else []
        question_source = "assessment_bank"
        if not candidates:
            # 兼容尚未配置独立测评题库的其他知识库。
            candidates = knowledge_service.load_diagnostic_questions(profile.knowledge_base_id)
            question_source = "knowledge_base"
        related = [
            item
            for item in candidates
            if target_skill_nodes and item.skill_node_id in target_skill_nodes
        ]
        seen_related_ids = {item.question_id for item in related}

        tokens = [resource.topic or "", *(resource.knowledge_points or [])]
        for item in candidates:
            if item.question_id in seen_related_ids:
                continue
            searchable = " ".join(
                [
                    item.question or "",
                    item.knowledge_point or "",
                    " ".join(item.options or []),
                ]
            )
            if any(token and token in searchable for token in tokens):
                related.append(item)
                seen_related_ids.add(item.question_id)

        if len(related) < limit:
            select_assessment = getattr(knowledge_service, "select_assessment_questions", None)
            if question_source == "assessment_bank" and select_assessment:
                selected = select_assessment(
                    profile.knowledge_base_id,
                    # 只有确实命中题库节点时才把路径节点作为硬过滤，兼容历史资源中
                    # 使用展示名称或旧节点 ID 的 learning_path_node。
                    skill_node_ids=target_skill_nodes if related else None,
                    limit=limit,
                )
            else:
                selected = knowledge_service.select_diagnostic_questions(
                    profile.knowledge_base_id,
                    limit=limit,
                )
            for item in selected:
                if item.question_id in seen_related_ids:
                    continue
                related.append(item)
                seen_related_ids.add(item.question_id)
                if len(related) >= limit:
                    break

        for item in self._order_questions_for_coverage(related)[:limit]:
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type=item.question_type,
                    question=item.question,
                    options=item.options or [],
                    skill_node_id=item.skill_node_id,
                    path_node_id=resource.learning_path_node,
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    diagnostic_dimension=item.metadata.get("diagnostic_dimension"),
                    source=question_source,
                )
            )
            answer_key[item.question_id] = item.answer

        return questions, answer_key

    @staticmethod
    def _resource_target_skill_nodes(resource: LearningResource) -> list[str]:
        values = []
        if resource.learning_path_node:
            values.append(resource.learning_path_node)
        return list(dict.fromkeys(values))

    @staticmethod
    def _usable_resource_exercises(resource: LearningResource) -> list:
        return [
            item
            for item in resource.exercise_items
            if item.question.strip() and item.answer is not None
        ]

    @staticmethod
    def _order_questions_for_coverage(questions: list) -> list:
        dimensions = ("concept", "scenario", "misconception")
        ordered = []
        seen = set()
        for dimension in dimensions:
            for question in questions:
                if question.question_id in seen:
                    continue
                diagnostic_dimension = getattr(question, "diagnostic_dimension", None)
                if diagnostic_dimension is None:
                    diagnostic_dimension = getattr(question, "metadata", {}).get("diagnostic_dimension")
                if diagnostic_dimension == dimension:
                    ordered.append(question)
                    seen.add(question.question_id)
        for question in questions:
            if question.question_id not in seen:
                ordered.append(question)
        return ordered

    @staticmethod
    def _shuffle_question_options(
        questions: list[ResourceEvaluationQuestion],
        learner_id: str,
        session_id: str,
    ) -> list[ResourceEvaluationQuestion]:
        """Shuffle choices deterministically so a session stays resumable and gradable."""
        shuffled_questions = []
        for question in questions:
            options = list(question.options or [])
            if len(options) > 1:
                seed_material = f"{learner_id}\x1f{session_id}\x1f{question.question_id}"
                seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
                random.Random(seed).shuffle(options)
            shuffled_questions.append(question.model_copy(update={"options": options}))
        return shuffled_questions

    @staticmethod
    def _question_result_key(question: ResourceEvaluationQuestion) -> str:
        return question.skill_node_id or question.knowledge_point or "综合能力"

    @staticmethod
    def _question_trace_item(question: ResourceEvaluationQuestion, fallback_path_node_id: str | None) -> dict[str, object]:
        return {
            "question_id": question.question_id,
            "question_type": question.question_type,
            "skill_node_id": question.skill_node_id,
            "path_node_id": question.path_node_id or fallback_path_node_id,
            "knowledge_point": question.knowledge_point,
            "difficulty": question.difficulty,
            "diagnostic_dimension": question.diagnostic_dimension,
            "source": question.source,
        }

    def _answer_score(self, question_type: str | None, expected: object, actual: object) -> float:
        normalized_type = (question_type or "").lower()
        if normalized_type in {"multiple_choice", "multi_choice", "multiple_select", "checkbox"}:
            expected_values = self._normalize_answer_set(expected)
            actual_values = self._normalize_answer_set(actual)
            if not expected_values:
                return 1.0 if not actual_values else 0.0
            return 1.0 if expected_values == actual_values else 0.0
        return 1.0 if self._answers_match(expected, actual) else 0.0

    @staticmethod
    def _normalize_answer_set(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = [value]
        return {str(item).strip().casefold() for item in raw_values if str(item).strip()}

    @staticmethod
    def _normalize_answer_value(value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [FeedbackService._normalize_answer_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key).strip(): FeedbackService._normalize_answer_value(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _answers_match(expected: object, actual: object) -> bool:
        return json.dumps(
            FeedbackService._normalize_answer_value(expected),
            ensure_ascii=False,
            sort_keys=True,
        ) == json.dumps(
            FeedbackService._normalize_answer_value(actual),
            ensure_ascii=False,
            sort_keys=True,
        )

    def _build_run_question_specs(
        self,
        profile: LearnerProfile,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
        questions_per_skill_node: int = 2,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        """Build a balanced session with at least two questions per covered skill node."""
        candidates: list[ResourceEvaluationQuestion] = []
        answer_key: dict[str, object] = {}
        seen_question_ids: set[str] = set()
        skill_nodes = list(dict.fromkeys(
            resource.learning_path_node for resource in resources if resource.learning_path_node
        ))

        resources_with_generated_questions = [
            resource
            for resource in resources
            if self._usable_resource_exercises(resource)
        ]
        # 任务中只要有资源携带 AI 生成题，就只聚合这些题；只有整个任务均未生成
        # 可判分题目时，才由每个资源对应的能力节点触发题库回退。
        question_resources = resources_with_generated_questions or resources

        for resource in question_resources:
            questions, resource_answer_key = self._build_question_specs(
                profile,
                resource,
                knowledge_service,
                limit=50,
            )
            for question in questions:
                if question.question_id in seen_question_ids:
                    continue
                candidates.append(question)
                answer_key[question.question_id] = resource_answer_key.get(question.question_id)
                seen_question_ids.add(question.question_id)
                if question.skill_node_id and question.skill_node_id not in skill_nodes:
                    skill_nodes.append(question.skill_node_id)

        if not skill_nodes:
            return candidates, answer_key

        # AI-generated resource exercises can be sparse. Supplement each covered
        # node from the assessment bank so every node has a comparable check.
        load_assessment = getattr(knowledge_service, "load_assessment_questions", None)
        assessment_candidates = load_assessment(profile.knowledge_base_id) if load_assessment else []
        assessment_source = "assessment_bank"
        if not assessment_candidates:
            assessment_candidates = knowledge_service.load_diagnostic_questions(profile.knowledge_base_id)
            assessment_source = "knowledge_base"

        for skill_node_id in skill_nodes:
            current_count = sum(question.skill_node_id == skill_node_id for question in candidates)
            if current_count >= questions_per_skill_node:
                continue
            for item in assessment_candidates:
                if item.question_id in seen_question_ids or item.skill_node_id != skill_node_id:
                    continue
                candidates.append(
                    ResourceEvaluationQuestion(
                        question_id=item.question_id,
                        question_type=item.question_type,
                        question=item.question,
                        options=item.options or [],
                        skill_node_id=item.skill_node_id,
                        path_node_id=skill_node_id,
                        knowledge_point=item.knowledge_point,
                        difficulty=item.difficulty,
                        diagnostic_dimension=item.metadata.get("diagnostic_dimension"),
                        source=assessment_source,
                    )
                )
                answer_key[item.question_id] = item.answer
                seen_question_ids.add(item.question_id)
                current_count += 1
                if current_count >= questions_per_skill_node:
                    break

        selected_questions: list[ResourceEvaluationQuestion] = []
        selected_answer_key: dict[str, object] = {}
        for skill_node_id in skill_nodes:
            node_questions = self._order_questions_for_coverage(
                [question for question in candidates if question.skill_node_id == skill_node_id]
            )[:questions_per_skill_node]
            for question in node_questions:
                selected_questions.append(question)
                selected_answer_key[question.question_id] = answer_key[question.question_id]

        return selected_questions, selected_answer_key

    @staticmethod
    def _merge_topics(resources: list[LearningResource]) -> str:
        topics = [resource.topic for resource in resources if resource.topic]
        unique_topics = list(dict.fromkeys(topics))
        return " / ".join(unique_topics[:3]) if unique_topics else ""

    @staticmethod
    def _select_attempt_resource(resources: list[LearningResource], resource_id: str | None) -> LearningResource:
        if resource_id:
            for resource in resources:
                if resource.resource_id == resource_id:
                    return resource
            raise ValueError("指定的反馈资源不存在")
        for resource in resources:
            if resource.publication_status == "published":
                return resource
        return resources[0]
