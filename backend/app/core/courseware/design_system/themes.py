from __future__ import annotations

from app.models.courseware.design import ThemeSpec, ThemeId

THEMES = {
    "editorial": {"surface": "#ffffff", "canvas": "#f4f8fc", "ink": "#172033", "accent": "#123b68", "border": "#bfd0e2", "focus": "#e69b26"},
    "midnight": {"surface": "#172033", "canvas": "#0d1422", "ink": "#f4f8fc", "accent": "#8fc7ff", "border": "#536a85", "focus": "#ffd36e"},
    "paper": {"surface": "#fffdf7", "canvas": "#f4f0e5", "ink": "#2a241b", "accent": "#6d4c2f", "border": "#cbbda7", "focus": "#ad5f00"},
}


def resolve_theme(theme_id: str | None) -> ThemeSpec:
    return ThemeSpec(theme_id=theme_id if theme_id in THEMES else "editorial")


__all__ = ["THEMES", "resolve_theme"]
