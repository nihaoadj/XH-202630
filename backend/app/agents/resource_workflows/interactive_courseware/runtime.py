"""Shared runtime guard for courseware-specific LLM agents."""

from app.config import get_settings
from app.core.llm_gateway import LLMGateway


def courseware_ai_available(llm_gateway: LLMGateway | None) -> bool:
    settings = get_settings()
    return bool(llm_gateway and settings.courseware_ai_enabled and settings.llm_api_key.get_secret_value())
