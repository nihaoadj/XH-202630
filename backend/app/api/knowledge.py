from fastapi import APIRouter, HTTPException, Request

from app.services.knowledge_service import KnowledgeService

router = APIRouter()


@router.get("/info")
def get_knowledge_base_info(request: Request, knowledge_base_id: str | None = None):
    """返回知识库目录、切片和能力图谱的实时统计信息。"""
    service: KnowledgeService = request.app.container.knowledge_service()
    try:
        return service.get_info(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
