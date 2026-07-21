from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import GenerateRequest, GenerateResponse
from app.services.learner_service import LearnerService
from app.services.generation_service import GenerationService

router = APIRouter()


@router.post("/", response_model=GenerateResponse)
def generate_resources(req: GenerateRequest, request: Request):
    """根据学习者画像生成个性化资源"""
    container = request.app.container
    
    learner_service: LearnerService = container.learner_service()
    learner = learner_service.get(req.learner_id)
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_service: GenerationService = container.generation_service()
    return generation_service.generate(learner, req)
