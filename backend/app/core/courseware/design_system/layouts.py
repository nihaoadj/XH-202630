from __future__ import annotations

from app.models.courseware.design import LayoutId, LayoutSpec

LAYOUTS = {item: {"layout_id": item, "version": "1.0"} for item in (
    "cover", "chapter", "focus", "compare", "steps", "practice", "recap", "progress",
)}


def resolve_layout(layout_id: str | None) -> LayoutSpec:
    return LayoutSpec(layout_id=layout_id if layout_id in LAYOUTS else "cover")


__all__ = ["LAYOUTS", "resolve_layout"]
