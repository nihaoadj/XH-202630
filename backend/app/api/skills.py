from fastapi import APIRouter, HTTPException, Query, Request

from app.services.knowledge_service import KnowledgeService

router = APIRouter()


@router.get("/nodes")
def list_skill_nodes(
    request: Request,
    knowledge_base_id: str | None = None,
    level: str | None = None,
    target_domain: str | None = Query(default=None, description="预留的领域筛选参数"),
):
    """查询当前知识库的能力节点及前置依赖边。"""
    del target_domain  # 领域由 knowledge_base_id 所指向的知识库确定。
    service: KnowledgeService = request.app.container.knowledge_service()
    try:
        nodes = service.list_skill_nodes(knowledge_base_id, level)
        resolved_id = nodes[0].knowledge_base_id if nodes else service._ensure_knowledge_base(knowledge_base_id)["knowledge_base_id"]
        return {"knowledge_base_id": resolved_id, "nodes": nodes, "edges": service.list_edges(knowledge_base_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
