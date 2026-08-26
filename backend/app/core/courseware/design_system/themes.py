from __future__ import annotations

from app.models.courseware.design import ThemeSpec, ThemeId

THEMES = {
    "editorial": {"surface": "#ffffff", "surface_alt": "#eaf2fa", "panel": "#f8fbfe", "canvas": "#eef4fa", "ink": "#14243a", "muted": "#58708a", "accent": "#155fa8", "accent_soft": "#dcebfa", "border": "#bfd0e2", "focus": "#e69b26", "data_1": "#155fa8", "data_2": "#14a38b", "data_3": "#e58b2a"},
    "midnight": {"surface": "#172033", "surface_alt": "#22314a", "panel": "#111b2d", "canvas": "#0d1422", "ink": "#f4f8fc", "muted": "#b5c5d8", "accent": "#8fc7ff", "accent_soft": "#1f4265", "border": "#536a85", "focus": "#ffd36e", "data_1": "#8fc7ff", "data_2": "#57d9bd", "data_3": "#ffd36e"},
    "paper": {"surface": "#fffdf7", "surface_alt": "#f4ead8", "panel": "#fffbf2", "canvas": "#f4f0e5", "ink": "#2a241b", "muted": "#766958", "accent": "#6d4c2f", "accent_soft": "#eadcc5", "border": "#cbbda7", "focus": "#ad5f00", "data_1": "#7c5130", "data_2": "#55735b", "data_3": "#b97024"},
}


def resolve_theme(theme_id: str | None) -> ThemeSpec:
    return ThemeSpec(theme_id=theme_id if theme_id in THEMES else "editorial")


__all__ = ["THEMES", "resolve_theme"]
