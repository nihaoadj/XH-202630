"""Application use cases for safe, stateful Tutor interactions."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.agents.tutor import (
    TutorAgent,
    TutorContextBuilder,
    TutorGroundingValidationError,
)
from app.agents.tutor_policy import decide_tutor_policy
from app.config import Settings, get_settings
from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGatewayError
from app.db.learner.base import BaseLearnerRepository
from app.db.resource.base import BaseResourceRepository
from app.db.tutor.base import (
    BaseTutorRepository,
    TutorIdempotencyConflict,
    TutorPersistenceConflict,
)
from app.models.persistence import canonical_hash
from app.models.schemas import ExerciseItem, LearnerProfile, LearningResource
from app.models.tutor import (
    TutorQuestionContext,
    TutorSession,
    TutorSessionCreateRequest,
    TutorSessionDetail,
    TutorSessionListResponse,
    TutorTurn,
    TutorTurnResponse,
    TutorTurnSubmitRequest,
)
from app.services.knowledge_service import KnowledgeService


class TutorService:
    """Coordinate access-safe Tutor sessions without mutating formal learning state."""

    def __init__(
        self,
        *,
        tutor_repo: BaseTutorRepository,
        learner_repo: BaseLearnerRepository,
        resource_repo: BaseResourceRepository,
        knowledge_service: KnowledgeService,
        context_builder: TutorContextBuilder,
        tutor_agent: TutorAgent,
        settings: Settings | None = None,
    ):
        self.tutor_repo = tutor_repo
        self.learner_repo = learner_repo
        self.resource_repo = resource_repo
        self.knowledge_service = knowledge_service
        self.context_builder = context_builder
        self.tutor_agent = tutor_agent
        self.settings = settings or get_settings()

    @staticmethod
    def _stable_id(prefix: str, *parts: object) -> str:
        material = "\x1f".join(str(part) for part in parts)
        return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()[:32]}"

    def create_session(
        self,
        profile: LearnerProfile,
        payload: TutorSessionCreateRequest,
    ) -> TutorSession:
        if profile.learner_id != payload.learner_id:
            raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=422)
        resource, resources, source_run_id = self._resolve_source(profile, payload)
        question = self._resolve_question_context(
            profile,
            resources,
            payload.question_id,
        )

        existing = self.tutor_repo.list_sessions(
            profile.learner_id,
            status="active",
            source_resource_id=(
                resource.resource_id if payload.source_type == "resource" else None
            ),
            source_run_id=(source_run_id if payload.source_type == "run" else None),
            context_type=payload.context_type,
            question_id=payload.question_id,
        )
        if existing:
            return existing[0]

        now = datetime.now(timezone.utc)
        identity = (
            payload.learner_id,
            payload.source_type,
            resource.resource_id if payload.source_type == "resource" else source_run_id,
            payload.context_type,
            payload.question_id or "resource",
            now.isoformat(),
        )
        session = TutorSession(
            session_id=self._stable_id("tus", *identity),
            learner_id=profile.learner_id,
            source_type=payload.source_type,
            source_resource_id=resource.resource_id,
            source_run_id=source_run_id,
            knowledge_base_id=profile.knowledge_base_id,
            context_type=payload.context_type,
            question_id=payload.question_id,
            skill_node_id=question.skill_node_id if question else None,
            path_node_id=(
                question.path_node_id
                if question
                else resource.learning_path_node
            ),
            knowledge_point=(
                question.knowledge_point
                if question
                else (resource.knowledge_points[0] if resource.knowledge_points else None)
            ),
            created_at=now,
            updated_at=now,
        )
        return self.tutor_repo.create_session(session)

    def get_session(self, session_id: str) -> TutorSession | None:
        return self.tutor_repo.get_session(session_id)

    def get_session_detail(self, session_id: str) -> TutorSessionDetail:
        session = self.tutor_repo.get_session(session_id)
        if session is None:
            raise ApplicationError(ErrorCode.TUTOR_SESSION_NOT_FOUND, status_code=404)
        turns = [
            TutorTurnResponse.from_turn(item)
            for item in self.tutor_repo.list_turns(session_id)
        ]
        return TutorSessionDetail(session=session, turns=turns)

    def list_sessions(
        self,
        learner_id: str,
        *,
        status: str | None = None,
        resource_id: str | None = None,
        run_id: str | None = None,
        context_type: str | None = None,
        question_id: str | None = None,
    ) -> TutorSessionListResponse:
        sessions = self.tutor_repo.list_sessions(
            learner_id,
            status=status,
            source_resource_id=resource_id,
            source_run_id=run_id,
            context_type=context_type,
            question_id=question_id,
        )
        return TutorSessionListResponse(
            learner_id=learner_id,
            total=len(sessions),
            sessions=sessions,
        )

    def close_session(self, session_id: str) -> TutorSession:
        session = self.tutor_repo.get_session(session_id)
        if session is None:
            raise ApplicationError(ErrorCode.TUTOR_SESSION_NOT_FOUND, status_code=404)
        if session.status == "closed":
            return session
        closed = self.tutor_repo.update_session_state(
            session_id,
            status="closed",
            closed_at=datetime.now(timezone.utc),
        )
        if closed is None:
            raise ApplicationError(ErrorCode.TUTOR_SESSION_NOT_FOUND, status_code=404)
        return closed

    def submit_turn(
        self,
        profile: LearnerProfile,
        session_id: str,
        payload: TutorTurnSubmitRequest,
    ) -> TutorTurnResponse:
        session = self.tutor_repo.get_session(session_id)
        if session is None or session.learner_id != profile.learner_id:
            raise ApplicationError(ErrorCode.TUTOR_SESSION_NOT_FOUND, status_code=404)

        request_hash = canonical_hash({"message": payload.message})
        existing = self.tutor_repo.get_turn_by_client_message_id(
            session_id,
            payload.client_message_id,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ApplicationError(
                    ErrorCode.TUTOR_IDEMPOTENCY_CONFLICT,
                    status_code=409,
                )
            return TutorTurnResponse.from_turn(existing, idempotent_replay=True)
        if session.status != "active":
            raise ApplicationError(ErrorCode.TUTOR_SESSION_CLOSED, status_code=409)

        resource, resources = self._resources_for_session(session)
        question = self._resolve_question_context(
            profile,
            resources,
            session.question_id,
        )
        turn_id = self._stable_id("tut", session_id, payload.client_message_id)
        policy = decide_tutor_policy(
            turn_count=session.turn_count,
            current_hint_level=session.current_hint_level,
            user_message=payload.message,
            max_hint_level=self.settings.tutor_max_hint_level,
        )
        grounding = self.context_builder.resolve_grounding(
            session=session,
            resource=resource,
            message=payload.message,
            turn_id=turn_id,
            question_context=question,
        )

        now = datetime.now(timezone.utc)
        if grounding.status == "evidence_insufficient":
            turn = TutorTurn(
                turn_id=turn_id,
                session_id=session_id,
                sequence=session.turn_count + 1,
                client_message_id=payload.client_message_id,
                request_hash=request_hash,
                user_message=payload.message,
                assistant_message=(
                    "当前知识库证据不足，我暂时不能给出确定性的专业解释。"
                    "你可以换一种问法，或回到当前学习资料核对相关知识点。"
                ),
                pedagogy_action="evidence_insufficient",
                hint_level=policy.hint_level,
                follow_up_question=None,
                target_knowledge_points=[session.knowledge_point]
                if session.knowledge_point
                else [],
                grounding_status="evidence_insufficient",
                grounding_source="none",
                evidence_refs=[],
                retrieval_query_hash=grounding.retrieval_query_hash,
                retrieval_status=grounding.retrieval_status,
                error_code=ErrorCode.EVIDENCE_INSUFFICIENT.value,
                created_at=now,
            )
        else:
            recent = self.tutor_repo.list_turns(
                session_id,
                limit=self.settings.tutor_max_context_turns,
            )
            agent_input = self.context_builder.build_input(
                session=session,
                turn_id=turn_id,
                profile=profile,
                resource=resource,
                question_context=question,
                recent_turns=recent,
                message=payload.message,
                hint_level=policy.hint_level,
                allowed_actions=policy.allowed_actions,
                grounding=grounding,
            )
            try:
                agent_result = self.tutor_agent.invoke(agent_input)
            except TutorGroundingValidationError as exc:
                raise ApplicationError(
                    ErrorCode.TUTOR_GROUNDING_INVALID,
                    status_code=502,
                ) from exc
            except LLMGatewayError as exc:
                try:
                    code = ErrorCode(exc.error.code)
                except ValueError:
                    code = ErrorCode.LLM_UPSTREAM_UNAVAILABLE
                raise ApplicationError(code, status_code=503) from exc

            cited = set(agent_result.output.cited_evidence_ids)
            evidence_refs = [
                item for item in grounding.evidence if item.evidence_id in cited
            ]
            metadata = agent_result.llm_result.trace_metadata()
            turn = TutorTurn(
                turn_id=turn_id,
                session_id=session_id,
                sequence=session.turn_count + 1,
                client_message_id=payload.client_message_id,
                request_hash=request_hash,
                user_message=payload.message,
                assistant_message=agent_result.output.answer_text,
                pedagogy_action=agent_result.output.pedagogy_action,
                hint_level=policy.hint_level,
                follow_up_question=agent_result.output.follow_up_question,
                target_knowledge_points=agent_result.output.target_knowledge_points,
                grounding_status="grounded",
                grounding_source=grounding.source,
                evidence_refs=evidence_refs,
                retrieval_query_hash=grounding.retrieval_query_hash,
                retrieval_status=grounding.retrieval_status,
                llm_call_id=metadata.get("llm_call_id"),
                model_name=metadata.get("model_name"),
                input_tokens=metadata.get("input_tokens"),
                output_tokens=metadata.get("output_tokens"),
                total_tokens=metadata.get("total_tokens"),
                llm_duration_ms=metadata.get("llm_duration_ms"),
                retry_count=metadata.get("retry_count", 0),
                created_at=now,
            )

        try:
            stored = self.tutor_repo.append_turn(turn)
        except TutorIdempotencyConflict as exc:
            raise ApplicationError(
                ErrorCode.TUTOR_IDEMPOTENCY_CONFLICT,
                status_code=409,
            ) from exc
        except TutorPersistenceConflict as exc:
            raise ApplicationError(
                ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT,
                status_code=409,
            ) from exc
        return TutorTurnResponse.from_turn(
            stored,
            idempotent_replay=stored.turn_id != turn.turn_id,
        )

    def _resolve_source(
        self,
        profile: LearnerProfile,
        payload: TutorSessionCreateRequest,
    ) -> tuple[LearningResource, list[LearningResource], str | None]:
        if payload.source_type == "resource":
            resource = self.resource_repo.get(payload.resource_id or "")
            if (
                resource is None
                or resource.learner_id != profile.learner_id
                or resource.publication_status != "published"
            ):
                raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=404)
            if payload.run_id and payload.run_id != resource.run_id:
                raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=422)
            return resource, [resource], resource.run_id

        resources = self.resource_repo.list_by_learner_with_filter(
            profile.learner_id,
            run_id=payload.run_id,
        )
        if not resources:
            raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=404)
        return resources[0], resources, payload.run_id

    def _resources_for_session(
        self,
        session: TutorSession,
    ) -> tuple[LearningResource, list[LearningResource]]:
        if session.source_resource_id:
            resource = self.resource_repo.get(session.source_resource_id)
            if (
                resource is not None
                and resource.learner_id == session.learner_id
                and resource.publication_status == "published"
            ):
                if session.source_type == "resource":
                    return resource, [resource]
        resources = self.resource_repo.list_by_learner_with_filter(
            session.learner_id,
            run_id=session.source_run_id,
        )
        if not resources:
            raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=404)
        selected = next(
            (
                item
                for item in resources
                if item.resource_id == session.source_resource_id
            ),
            resources[0],
        )
        return selected, resources

    def _resolve_question_context(
        self,
        profile: LearnerProfile,
        resources: list[LearningResource],
        question_id: str | None,
    ) -> TutorQuestionContext | None:
        if question_id is None:
            return None
        load_assessment = getattr(
            self.knowledge_service,
            "load_assessment_questions",
            None,
        )
        assessment_questions = (
            load_assessment(profile.knowledge_base_id)
            if load_assessment is not None
            else []
        )
        diagnostic_questions = self.knowledge_service.load_diagnostic_questions(
            profile.knowledge_base_id
        )
        questions = list(assessment_questions)
        seen_question_ids = {item.question_id for item in questions}
        questions.extend(
            item
            for item in diagnostic_questions
            if item.question_id not in seen_question_ids
        )
        for question in questions:
            if question.question_id == question_id:
                path_node_id = next(
                    (
                        item.learning_path_node
                        for item in resources
                        if item.learning_path_node == question.skill_node_id
                    ),
                    resources[0].learning_path_node if resources else None,
                )
                return TutorQuestionContext(
                    question_id=question.question_id,
                    question=question.question,
                    question_type=question.question_type,
                    options=question.options or [],
                    skill_node_id=question.skill_node_id,
                    path_node_id=path_node_id,
                    knowledge_point=question.knowledge_point,
                    difficulty=question.difficulty,
                )
        for resource in resources:
            for exercise in resource.exercise_items:
                public_question_id = f"{resource.resource_id}:{exercise.question_id}"
                if question_id in {exercise.question_id, public_question_id}:
                    return self._exercise_context(
                        resource,
                        exercise,
                        question_id=question_id,
                    )
        raise ApplicationError(ErrorCode.TUTOR_CONTEXT_INVALID, status_code=422)

    @staticmethod
    def _exercise_context(
        resource: LearningResource,
        exercise: ExerciseItem,
        *,
        question_id: str,
    ) -> TutorQuestionContext:
        return TutorQuestionContext(
            question_id=question_id,
            question=exercise.question,
            question_type=exercise.question_type,
            options=exercise.options or [],
            skill_node_id=exercise.skill_node_id or resource.learning_path_node,
            path_node_id=resource.learning_path_node,
            knowledge_point=exercise.knowledge_point,
            difficulty=exercise.difficulty,
        )

