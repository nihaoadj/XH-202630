"""Shared runtime guard for courseware-specific LLM agents."""

from app.config import get_settings
from app.core.llm.gateway import LLMGateway


def courseware_ai_available(llm_gateway: LLMGateway | None) -> bool:
    """Return whether the configured normal path may invoke its gateway.

    The injected fake gateway used in offline acceptance intentionally has no
    credential.  A real :class:`LLMGateway`, in contrast, is never considered
    available without a configured key, so the production path cannot quietly
    issue anonymous calls or present a deterministic result as an AI result.
    """

    settings = get_settings()
    if not llm_gateway or not settings.courseware_ai_enabled:
        return False
    if settings.courseware_generation_mode == "emergency_degraded":
        return False
    if isinstance(llm_gateway, LLMGateway):
        return bool(settings.llm_api_key.get_secret_value())
    return True
