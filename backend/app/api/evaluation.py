from fastapi import APIRouter, Request

from app.models.schemas import EvaluationSummary
from app.services.evaluation_service import EvaluationService

router = APIRouter()


@router.get("/summary", response_model=EvaluationSummary)
def get_evaluation_summary(request: Request):
    """聚合已持久化的评测结果；没有真实结果时返回空统计。"""
    service: EvaluationService = request.app.container.evaluation_service()
    return service.get_summary()
