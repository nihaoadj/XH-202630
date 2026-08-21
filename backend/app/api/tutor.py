"""Private HTTP contract for interactive Tutor sessions."""

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.dependencies import ensure_profile_access
from app.models.tutor import (
    TutorSession,
    TutorSessionCreateRequest,
    TutorSessionDetail,
    TutorSessionListResponse,
    TutorTurnResponse,
    TutorTurnSubmitRequest,
)


router = APIRouter()


def _accessible_profile(request: Request, learner_id: str):
    profile = ensure_profile_access(
        request,
        request.app.container.profile_service().get(learner_id),
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    return profile


def _accessible_session(request: Request, session_id: str):
    service = request.app.container.tutor_service()
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Tutor 会话不存在")
    profile = _accessible_profile(request, session.learner_id)
    return service, session, profile


@router.post("/sessions", response_model=TutorSession, status_code=201)
def create_session(payload: TutorSessionCreateRequest, request: Request):
    profile = _accessible_profile(request, payload.learner_id)
    return request.app.container.tutor_service().create_session(profile, payload)


@router.get("/sessions", response_model=TutorSessionListResponse)
def list_sessions(
    learner_id: str,
    request: Request,
    status: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    batch_id: str | None = Query(default=None),
    context_type: str | None = Query(default=None),
    question_id: str | None = Query(default=None),
):
    _accessible_profile(request, learner_id)
    return request.app.container.tutor_service().list_sessions(
        learner_id,
        status=status,
        resource_id=resource_id,
        run_id=run_id,
        batch_id=batch_id,
        context_type=context_type,
        question_id=question_id,
    )


@router.get("/sessions/{session_id}", response_model=TutorSessionDetail)
def get_session(session_id: str, request: Request):
    service, _, _ = _accessible_session(request, session_id)
    return service.get_session_detail(session_id)


@router.post(
    "/sessions/{session_id}/turns",
    response_model=TutorTurnResponse,
)
def submit_turn(
    session_id: str,
    payload: TutorTurnSubmitRequest,
    request: Request,
):
    service, _, profile = _accessible_session(request, session_id)
    return service.submit_turn(profile, session_id, payload)


@router.post("/sessions/{session_id}/close", response_model=TutorSession)
def close_session(session_id: str, request: Request):
    service, _, _ = _accessible_session(request, session_id)
    return service.close_session(session_id)

