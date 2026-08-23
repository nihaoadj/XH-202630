"""Closed design-system selections; clients select IDs, never arbitrary CSS."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ThemeId = Literal["editorial", "midnight", "paper"]
LayoutId = Literal[
    "cover", "chapter", "focus", "compare", "steps", "practice", "recap", "progress",
]
MotionId = Literal["subtle", "reduced"]


class ThemeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theme_id: ThemeId
    version: Literal["1.0"] = "1.0"


class LayoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layout_id: LayoutId
    version: Literal["1.0"] = "1.0"


class MotionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    motion_id: MotionId
    version: Literal["1.0"] = "1.0"
    reduced_motion: bool = False


class CoursewareDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    design_system_version: Literal["1.0"] = "1.0"
    theme: ThemeSpec = Field(default_factory=lambda: ThemeSpec(theme_id="editorial"))
    layout: LayoutSpec = Field(default_factory=lambda: LayoutSpec(layout_id="cover"))
    motion: MotionSpec = Field(default_factory=lambda: MotionSpec(motion_id="subtle"))


__all__ = ["CoursewareDesign", "LayoutId", "LayoutSpec", "MotionId", "MotionSpec", "ThemeId", "ThemeSpec"]
