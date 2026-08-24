"""Single deterministic registry for supported resource generation Agents."""

from __future__ import annotations

from app.core.security.errors import ApplicationError, ErrorCode
from app.models.learning_documents.types import (
    RESOURCE_TYPE_ALIASES,
    SUPPORTED_RESOURCE_TYPES,
    canonical_resource_type,
)

from .assessment import AssessmentAgent
from .base import ResourceGenerationAgent
from .case_study import CaseStudyAgent
from .checklist import ReviewChecklistAgent
from .correction_package import CorrectionTrainingPackageAgent
from .practice import PracticeGuideAgent
from .text import TextResourceAgent


RESOURCE_AGENT_TYPES = {
    "讲义": TextResourceAgent,
    "实操指南": PracticeGuideAgent,
    "分阶测试题": AssessmentAgent,
    "复习清单": ReviewChecklistAgent,
    "案例分析": CaseStudyAgent,
    "个性化纠错训练包": CorrectionTrainingPackageAgent,
}


def normalize_resource_type(resource_type: str) -> str:
    try:
        normalized = canonical_resource_type(resource_type)
    except ValueError:
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
    return normalized


def get_resource_agent(resource_type: str) -> ResourceGenerationAgent:
    normalized = normalize_resource_type(resource_type)
    return RESOURCE_AGENT_TYPES[normalized]()


def validate_resource_agent_registry() -> None:
    if set(RESOURCE_AGENT_TYPES) != set(SUPPORTED_RESOURCE_TYPES):
        raise RuntimeError("RESOURCE_AGENT_REGISTRY_INCOMPLETE")
    for resource_type, agent_type in RESOURCE_AGENT_TYPES.items():
        agent = agent_type()
        if agent.resource_type != resource_type:
            raise RuntimeError("RESOURCE_AGENT_REGISTRY_ROUTE_MISMATCH")


validate_resource_agent_registry()
