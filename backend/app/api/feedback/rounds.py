"""Authenticated learning-round endpoints; business logic stays in services."""

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app.api.dependencies import ensure_profile_access
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.feedback.rounds import (
    LearningRoundDetailV1, LearningRoundListV1, RoundAttemptProcessingV1, RoundAttemptSubmitV1,
    RoundCandidatesV1, RoundCorrectionSelectionV1, RoundCreationResponseV1, RoundEvaluationRequestV1,
    RoundEvaluationSessionV1, RoundFeedbackResultV1, RoundNextSelectionV1, RoundResultNotSubmittedV1,
)
from app.services.feedback.round_assessment import RoundAssessment
from app.services.feedback.round_corrections import RoundCorrections
from app.services.feedback.round_feedback import RoundFeedback
from app.services.generation.dispatch import schedule_generation

router = APIRouter()


def profile_for(request, learner_id):
    profile = ensure_profile_access(request, request.app.container.profile_service().get(learner_id))
    if profile is None:
        raise ApplicationError(ErrorCode.ROUND_SELECTION_INVALID, status_code=404)
    return profile


def owned_round(request, round_id):
    service = request.app.container.round_learning_service()
    return service, profile_for(request, service.learner_id_for_round(round_id))


def schedule_round(service, profile, result, background_tasks):
    for member in result.members:
        for run_id in member.job_ids:
            job = service.feedback.generation_job_service.get_job(run_id)
            from app.models.learning_documents.schemas import GenerateRequest
            schedule_generation(service.feedback.generation_job_service, background_tasks, profile,
                                GenerateRequest.model_validate(job.request_payload), run_id, member.batch_id)


@router.get("/rounds", response_model=LearningRoundListV1)
def list_rounds(request: Request, learner_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    profile_for(request, learner_id)
    return request.app.container.round_learning_service().list(learner_id, offset, limit)


@router.get("/rounds/{round_id}", response_model=LearningRoundDetailV1)
def detail(round_id: str, request: Request):
    service, profile = owned_round(request, round_id)
    return service.detail(profile.learner_id, round_id)


@router.get("/rounds/{round_id}/candidates", response_model=RoundCandidatesV1)
def candidates(round_id: str, request: Request):
    service, profile = owned_round(request, round_id)
    return service.candidates(profile, round_id)


@router.post("/rounds/next/select", response_model=RoundCreationResponseV1, status_code=202)
def next_round(payload: RoundNextSelectionV1, request: Request, background_tasks: BackgroundTasks):
    profile = profile_for(request, payload.learner_id)
    service = request.app.container.round_learning_service()
    result = service.next(profile, payload)
    schedule_round(service, profile, result, background_tasks)
    return result


@router.post("/rounds/{round_id}/stages/{stage_id}/evaluation-session", response_model=RoundEvaluationSessionV1)
def evaluation(round_id: str, stage_id: str, payload: RoundEvaluationRequestV1, request: Request):
    service, profile = owned_round(request, round_id)
    if payload.learner_id != profile.learner_id:
        raise ApplicationError(ErrorCode.ROUND_ASSESSMENT_INVALID, status_code=404)
    return RoundAssessment(service).session(profile, round_id, stage_id)


@router.post("/rounds/{round_id}/stages/{stage_id}/attempts", response_model=RoundFeedbackResultV1 | RoundAttemptProcessingV1)
def submit(round_id: str, stage_id: str, payload: RoundAttemptSubmitV1, request: Request, response: Response):
    service, profile = owned_round(request, round_id)
    if payload.learner_id != profile.learner_id:
        raise ApplicationError(ErrorCode.ROUND_ASSESSMENT_INVALID, status_code=404)
    result = RoundFeedback(service).submit(profile, round_id, stage_id, payload)
    if isinstance(result, RoundAttemptProcessingV1):
        response.status_code = 202
    return result


@router.get("/rounds/{round_id}/stages/{stage_id}/result", response_model=RoundFeedbackResultV1 | RoundAttemptProcessingV1 | RoundResultNotSubmittedV1)
def result(round_id: str, stage_id: str, request: Request, response: Response):
    service, profile = owned_round(request, round_id)
    result = RoundFeedback(service).result(profile, round_id, stage_id)
    if isinstance(result, RoundAttemptProcessingV1):
        response.status_code = 202
    return result


@router.post("/rounds/{round_id}/corrections", response_model=RoundCreationResponseV1, status_code=202)
def corrections(round_id: str, payload: RoundCorrectionSelectionV1, request: Request, background_tasks: BackgroundTasks):
    service, profile = owned_round(request, round_id)
    if payload.learner_id != profile.learner_id:
        raise ApplicationError(ErrorCode.ROUND_SELECTION_INVALID, status_code=404)
    result = RoundCorrections(service).create(profile, round_id, payload)
    schedule_round(service, profile, result, background_tasks)
    return result
