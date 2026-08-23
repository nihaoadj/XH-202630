"""Versioned, non-executable content contracts for interactive courseware.

These models are the only values an LLM may produce for this workflow. The
renderer owns HTML, CSS and JavaScript; it never renders model-supplied markup.
"""

from __future__ import annotations

from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.courseware.learning_design import CoursewareLearningDesign
from app.models.courseware.design import CoursewareDesign


SceneKind = Literal["intro", "explain", "practice", "quiz", "recap"]
ComponentKind = Literal[
    "callout", "key_point", "compare", "steps", "ordered_steps",
    "single_choice", "multiple_choice", "recap",
    "flashcard", "matching", "ordering",
]
PedagogicalRole = Literal["explain", "example", "warning", "recap"]


def _clean_ids(value: list[str]) -> list[str]:
    cleaned = [item.strip() for item in value if item and item.strip()]
    if not cleaned or len(cleaned) != len(set(cleaned)):
        raise ValueError("来源块 ID 必须非空且不重复")
    return cleaned


class CoursewareScenePlan(BaseModel):
    """A course-design decision. It contains no learner-facing prose."""

    source_resource_id: str = Field(min_length=1, max_length=96)
    kind: SceneKind
    title: str = Field(min_length=1, max_length=120)
    learning_objective: str = Field(default="理解本场景的核心内容。", min_length=1, max_length=240)
    source_block_ids: list[str] = Field(default_factory=list, max_length=12)
    required: bool = True

    @field_validator("source_block_ids")
    @classmethod
    def clean_source_block_ids(cls, value: list[str]) -> list[str]:
        return _clean_ids(value) if value else value


class CoursewareSpec(BaseModel):
    """The structured outline generated before individual scenes."""

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=160)
    learning_objectives: list[str] = Field(default_factory=list, max_length=8)
    scenes: list[CoursewareScenePlan] = Field(min_length=1, max_length=8)
    # Deterministic platform-owned design produced before model scene prose.
    learning_design: CoursewareLearningDesign | None = None
    design: CoursewareDesign | None = None

    @field_validator("learning_objectives")
    @classmethod
    def clean_objectives(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class SceneSourceRef(BaseModel):
    source_resource_id: str = Field(min_length=1, max_length=96)
    source_block_ids: list[str] = Field(min_length=1, max_length=12)
    transformation: Literal["summary", "paraphrase", "quote", "adapted_step"] = "paraphrase"

    _clean_blocks = field_validator("source_block_ids")(_clean_ids)


class CoursewareBlock(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    block_id: str = Field(min_length=1, max_length=96)
    component: ComponentKind = "callout"
    text: str = Field(min_length=1, max_length=1200)
    pedagogical_role: PedagogicalRole = "explain"
    source_refs: list[SceneSourceRef] = Field(min_length=1, max_length=4)
    front: str | None = Field(default=None, max_length=800)
    back: str | None = Field(default=None, max_length=1200)
    pairs: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    ordering_items: list[str] = Field(default_factory=list, max_length=8)
    correct_order: list[str] = Field(default_factory=list, max_length=8)


class TextComponentSpec(CoursewareBlock):
    component: Literal["callout", "key_point", "compare", "recap", "flashcard", "matching", "ordering"] = "callout"


class StepsComponentSpec(CoursewareBlock):
    component: Literal["steps", "ordered_steps"]


class ChoiceComponentSpec(CoursewareBlock):
    component: Literal["single_choice", "multiple_choice"]


# The discriminator is deliberately platform-owned. Unknown component names
# fail structured parsing before they reach the renderer.
ComponentSpec = Annotated[
    Union[TextComponentSpec, StepsComponentSpec, ChoiceComponentSpec],
    Field(discriminator="component"),
]


class CoursewareSceneSpec(BaseModel):
    """A renderer-safe, source-traceable learner-facing scene."""

    schema_version: Literal["1.0"] = "1.0"
    kind: SceneKind
    title: str = Field(min_length=1, max_length=120)
    blocks: list[ComponentSpec] = Field(min_length=1, max_length=10)
    steps: list[str] = Field(default_factory=list, max_length=10)
    options: list[str] = Field(default_factory=list, max_length=8)
    answer: list[str] = Field(default_factory=list, max_length=8)
    feedback: str | None = Field(default=None, max_length=800)
    # Explicit mappings are accepted from the model, while the renderer-safe
    # fallback below derives them from the first cited block for legacy scenes.
    title_source_refs: list[SceneSourceRef] = Field(default_factory=list, max_length=4)
    feedback_source_refs: list[SceneSourceRef] = Field(default_factory=list, max_length=4)

    @field_validator("blocks", mode="before")
    @classmethod
    def default_legacy_component(cls, value):
        # Older structured responses omitted component for plain text blocks.
        # Normalize that wire shape before discriminator parsing.
        return [
            {**item, "component": "callout"} if isinstance(item, dict) and "component" not in item else item
            for item in value
        ]

    @model_validator(mode="after")
    def validate_interactions(self):
        if self.kind == "practice" and not self.steps:
            raise ValueError("实践场景必须含步骤")
        if self.kind == "quiz":
            if len(self.options) < 2 or not self.answer or not set(self.answer).issubset(set(self.options)):
                raise ValueError("测验必须包含可用选项与答案")
        elif self.options or self.answer:
            raise ValueError("仅测验场景可包含选项和答案")
        return self

    @property
    def source_refs(self) -> list[str]:
        refs = [ref for block in self.blocks for ref in block.source_refs]
        refs.extend(self.title_source_refs)
        refs.extend(self.feedback_source_refs)
        return sorted({ref.source_resource_id for ref in refs})

    @property
    def source_block_ids(self) -> list[str]:
        refs = [ref for block in self.blocks for ref in block.source_refs]
        refs.extend(self.title_source_refs)
        refs.extend(self.feedback_source_refs)
        return sorted({block_id for ref in refs for block_id in ref.source_block_ids})

    def to_renderer_scene(self) -> dict:
        """Flatten provenance into the existing fixed renderer's JSON shape."""
        block_maps = [
            sorted({block_id for ref in block.source_refs for block_id in ref.source_block_ids})
            for block in self.blocks
        ]
        result = {
            "kind": self.kind, "title": self.title,
            "blocks": [block.text for block in self.blocks], "steps": self.steps,
            "options": self.options, "answer": self.answer, "feedback": self.feedback,
            "source_refs": self.source_refs, "source_block_ids": self.source_block_ids,
            "source_map": {"blocks": block_maps},
            "component_blocks": [block.model_dump(mode="json") for block in self.blocks],
        }
        # Every learner-visible field gets a stable source-map entry. Explicit
        # refs win; deterministic fallback preserves old AI/fallback payloads.
        first_map = block_maps[0] if block_maps else []
        title_map = sorted({block_id for ref in self.title_source_refs for block_id in ref.source_block_ids}) or first_map
        result["source_map"]["title"] = [title_map]
        if self.feedback:
            result["source_map"]["feedback"] = [
                sorted({block_id for ref in self.feedback_source_refs for block_id in ref.source_block_ids}) or first_map
            ]
        if self.steps:
            result["source_map"]["steps"] = [block_maps[min(index, len(block_maps) - 1)] for index in range(len(self.steps))]
        if self.options:
            result["source_map"]["options"] = [block_maps[0] for _ in self.options]
            result["source_map"]["answer"] = [block_maps[0] for _ in self.answer]
        return result


class CoursewareReviewIssue(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    severity: Literal["info", "warning", "error"] = "warning"
    instruction: str = Field(min_length=1, max_length=400)
    block_id: str | None = Field(default=None, max_length=96)


class CoursewareReviewDecision(BaseModel):
    """AI review signal; deterministic release gates remain final authority."""

    decision: Literal["approved", "revision_required", "rejected", "unavailable"]
    issues: list[CoursewareReviewIssue] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    trace_metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)
