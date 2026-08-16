from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.models.schemas import ReportResponse
from app.services.profile_service import ProfileService
from app.services.report_service import ReportService

router = APIRouter()


@router.get("/{learner_id}", response_model=ReportResponse)
def get_report(learner_id: str, request: Request):
    """获取学情报告"""
    container = request.app.container
    
    profile_service: ProfileService = container.profile_service()
    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    report_service: ReportService = container.report_service()
    return report_service.build_report(profile)
