"""Prompt composition for the generic resource issue reviewer."""

from app.agents.resource_workflows.learning_documents.reviewing.types import (
    PromptFragment,
    ReviewProfile,
)

from .common import COMMON_RULES, CORRECTION_RULES, OUTPUT_RULES
from .resources import resource_fragment

__all__ = ["PromptFragment", "ReviewProfile", "COMMON_RULES", "OUTPUT_RULES",
           "CORRECTION_RULES", "resource_fragment"]


def resource_profile_fragments(resource_type: str) -> tuple[PromptFragment, ...]:
    return (COMMON_RULES, resource_fragment(resource_type), OUTPUT_RULES)
