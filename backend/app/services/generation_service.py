from typing import List

from app.agents.workflow import build_workflow
from app.core.file_storage import save_text_resource
from app.db.resource.base import BaseResourceRepository
from app.models.schemas import GenerateRequest, GenerateResponse, LearnerProfile, LearningResource


def _build_report(learner: LearnerProfile, diagnosis: dict, review: dict) -> dict:
    """构建生成报告摘要"""
    return {
        "learner_id": learner.learner_id,
        "ability_tags": diagnosis.get("ability_tags", []),
        "weak_points": diagnosis.get("weak_points", learner.weak_points),
        "recommended_difficulty": diagnosis.get("recommended_difficulty", learner.skill_level),
        "hallucination_score": review.get("hallucination_score", 1.0),
        "coverage_rate": review.get("coverage_rate", 0.0),
        "difficulty_match": review.get("difficulty_match", False),
    }


def _persist_resources(
    resources: List[LearningResource],
    learner_id: str,
    topic: str,
    resource_repo: BaseResourceRepository,
) -> List[LearningResource]:
    """将生成的资源持久化到文件系统与数据库"""
    persisted = []
    for resource in resources:
        if resource.storage_type == "text" and resource.content_text:
            file_path, file_size, mime_type = save_text_resource(
                learner_id=learner_id,
                resource_type=resource.resource_type,
                text=resource.content_text,
                resource_id=resource.resource_id,
            )
            resource.file_path = file_path
            resource.file_size = file_size
            resource.mime_type = mime_type

        resource_repo.save(resource, learner_id, topic)
        persisted.append(resource)
    return persisted


class GenerationService:
    """个性化资源生成业务服务
    
    通过构造函数注入依赖。
    """

    def __init__(
        self,
        resource_repo: BaseResourceRepository,
        workflow
    ):
        """初始化服务
        
        Args:
            resource_repo: 资源仓库（通过DI容器注入）
            workflow: Agent工作流（通过DI容器注入）
        """
        self.resource_repo = resource_repo
        self.workflow = workflow

    def generate(self, learner: LearnerProfile, req: GenerateRequest) -> GenerateResponse:
        """生成个性化学习资源"""
        initial_state = {
            "learner": learner,
            "topic": req.topic,
            "resource_types": req.resource_types,
            "diagnosis": {},
            "retrieved_chunks": [],
            "generated_resources": [],
            "review_result": {},
            "final_decision": "",
            "trace": [],
            "iteration": 0,
        }

        result = self.workflow.invoke(initial_state)
        raw_resources = result.get("generated_resources", [])
        persisted_resources = _persist_resources(
            raw_resources,
            req.learner_id,
            req.topic,
            self.resource_repo,
        )

        return GenerateResponse(
            learner_id=req.learner_id,
            topic=req.topic,
            resources=persisted_resources,
            trace=result.get("trace", []),
            report=_build_report(
                learner,
                result.get("diagnosis", {}),
                result.get("review_result", {}),
            ),
        )
