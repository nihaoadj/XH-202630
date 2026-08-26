"""Versioned, platform-owned courseware visual language."""

from app.core.courseware.design_system.layouts import LAYOUTS, resolve_layout
from app.core.courseware.design_system.motion import MOTIONS, resolve_motion
from app.core.courseware.design_system.themes import THEMES, resolve_theme
from app.core.courseware.design_system.tokens import DESIGN_SYSTEM_VERSION, TOKENS
from app.core.courseware.design_system.recipes import RECIPES, resolve_recipe
from app.core.courseware.design_system.visual_styles import (
    PRACTICE_STYLE_OPTIONS,
    REVIEW_QUESTION_PAGE_ROLES,
    REVIEW_QUESTION_STYLE_MINIMUM,
    STEP_STYLE_SELECTION_COUNT,
    VISUAL_STYLE_METADATA,
    practice_style_family,
    select_practice_step_styles,
    select_review_question_styles,
    select_practice_visual_style,
    visual_style_for_scene,
)

__all__ = [
    "DESIGN_SYSTEM_VERSION", "LAYOUTS", "MOTIONS", "THEMES", "TOKENS",
    "resolve_layout", "resolve_motion", "resolve_theme", "RECIPES", "resolve_recipe",
    "PRACTICE_STYLE_OPTIONS", "REVIEW_QUESTION_PAGE_ROLES", "REVIEW_QUESTION_STYLE_MINIMUM", "STEP_STYLE_SELECTION_COUNT", "VISUAL_STYLE_METADATA", "practice_style_family",
    "select_practice_step_styles",
    "select_review_question_styles",
    "select_practice_visual_style", "visual_style_for_scene",
]
