from fastapi import APIRouter, HTTPException, Request

from app.services.knowledge_service import KnowledgeService

router = APIRouter()


@router.get("/directions")
def list_learning_directions(request: Request):
    """返回用户可选择的学习方向列表。"""
    service: KnowledgeService = request.app.container.knowledge_service()
    return {"directions": service.list_learning_directions()}


@router.get("/domains")
def list_learning_domains(request: Request):
    """返回领域及其下属学习方向。"""
    service: KnowledgeService = request.app.container.knowledge_service()
    return {"domains": service.list_learning_domains()}


@router.get("/info")
def get_knowledge_base_info(request: Request, knowledge_base_id: str | None = None):
    """返回知识库目录、切片和能力图谱的实时统计信息。"""
    service: KnowledgeService = request.app.container.knowledge_service()
    try:
        return service.get_info(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
