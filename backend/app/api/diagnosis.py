from fastapi import APIRouter, HTTPException, Query, Request

from app.models.schemas import DiagnosticQuestionListResponse, DiagnosticSubmitRequest, DiagnosticResult
from app.services.diagnosis_service import DiagnosisService
from app.services.knowledge_service import KnowledgeService

router = APIRouter()


@router.get("/questions", response_model=DiagnosticQuestionListResponse)
def get_diagnostic_questions(
    request: Request,
    learning_direction_id: str | None = None,
    knowledge_base_id: str | None = None,
    learner_id: str | None = None,
    skill_node_ids: str | None = None,
    level: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=39),
):
    """获取题目，不向客户端暴露标准答案和解析。"""
    del learner_id  # 预留给后续根据历史作答进行自适应抽题。
    service: KnowledgeService = request.app.container.knowledge_service()
    node_ids = [item.strip() for item in skill_node_ids.split(",")] if skill_node_ids else None
    try:
        direction_id = learning_direction_id or knowledge_base_id
        questions = service.select_diagnostic_questions(direction_id, node_ids, level, limit)
        resolved_id = service._ensure_knowledge_base(direction_id)["knowledge_base_id"]
        return {
            "knowledge_base_id": resolved_id,
            "total": len(questions),
            "questions": [service.public_question(question) for question in questions],
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/submit", response_model=DiagnosticResult)
def submit_diagnosis(payload: DiagnosticSubmitRequest, request: Request):
    """服务端判分，更新学习者画像、知识状态和诊断答题记录。"""
    service: DiagnosisService = request.app.container.diagnosis_service()
    try:
        return service.submit(payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
