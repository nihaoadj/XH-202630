"""Versioned, platform-owned courseware visual language."""

from app.core.courseware.design_system.layouts import LAYOUTS, resolve_layout
from app.core.courseware.design_system.motion import MOTIONS, resolve_motion
from app.core.courseware.design_system.themes import THEMES, resolve_theme
from app.core.courseware.design_system.tokens import DESIGN_SYSTEM_VERSION, TOKENS
from app.core.courseware.design_system.recipes import RECIPES, resolve_recipe

__all__ = [
    "DESIGN_SYSTEM_VERSION", "LAYOUTS", "MOTIONS", "THEMES", "TOKENS",
    "resolve_layout", "resolve_motion", "resolve_theme", "RECIPES", "resolve_recipe",
]
