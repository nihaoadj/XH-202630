"""Versioned, non-executable content contracts for interactive courseware.

These models are the only values an LLM may produce for this workflow. The
renderer owns HTML, CSS and JavaScript; it never renders model-supplied markup.
"""

from __future__ import annotations

from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.courseware.learning_design import (
    ContentBudget, CoursewareLearningDesign, LayoutRecipeId, PageRole,
)
from app.models.courseware.design import CoursewareDesign


SceneKind = Literal["intro", "explain", "example", "compare", "practice", "scenario", "quiz", "recap"]
ComponentKind = Literal[
    "callout", "key_point", "compare", "steps", "ordered_steps",
    "single_choice", "multiple_choice", "recap",
    "flashcard", "matching", "ordering",
    "branching_scenario", "categorization", "word_bank_cloze", "timeline_explorer",
    "metric_strip", "process_flow", "concept_map", "evidence_card", "comparison_table",
    "decision_path", "code_steps", "conclusion_bar",
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
    preferred_component_ids: list[str] = Field(default_factory=list, max_length=8)
    required: bool = True
    page_role: PageRole | None = None
    layout_recipe_id: LayoutRecipeId | None = None
    key_question: str = Field(default="", max_length=240)
    required_zones: list[str] = Field(default_factory=list, max_length=4)
    content_budget: ContentBudget = Field(default_factory=ContentBudget)

    @field_validator("source_block_ids")
    @classmethod
    def clean_source_block_ids(cls, value: list[str]) -> list[str]:
        return _clean_ids(value) if value else value


class CoursewareObjectiveEnrichment(BaseModel):
    objective_id: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    teaching_intent: str = Field(min_length=1, max_length=240)


class CoursewareSceneEnrichment(BaseModel):
    scene_id: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    teaching_intent: str = Field(min_length=1, max_length=240)
    preferred_component_ids: list[str] = Field(default_factory=list, max_length=8)


class CoursewarePlanEnrichmentV2(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    course_title: str = Field(min_length=1, max_length=160)
    course_summary: str = Field(min_length=1, max_length=500)
    objectives: list[CoursewareObjectiveEnrichment] = Field(default_factory=list, max_length=8)
    scenes: list[CoursewareSceneEnrichment] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({item.objective_id for item in self.objectives}) != len(self.objectives):
            raise ValueError("enrichment objective_id 重复")
        if len({item.scene_id for item in self.scenes}) != len(self.scenes):
            raise ValueError("enrichment scene_id 重复")
        return self


class CoursewareSpec(BaseModel):
    """The structured outline generated before individual scenes."""

    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=160)
    learning_objectives: list[str] = Field(default_factory=list, max_length=8)
    scenes: list[CoursewareScenePlan] = Field(min_length=1, max_length=24)
    # Deterministic platform-owned design produced before model scene prose.
    learning_design: CoursewareLearningDesign | None = None
    design: CoursewareDesign | None = None
    enrichment: CoursewarePlanEnrichmentV2 | None = None

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
    component_id: str | None = Field(default=None, max_length=128)
    start_node_id: str | None = Field(default=None, max_length=96)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    categories: list[dict[str, Any]] = Field(default_factory=list, max_length=5)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    prompt_segments: list[str] = Field(default_factory=list, max_length=7)
    blanks: list[dict[str, Any]] = Field(default_factory=list, max_length=6)
    tokens: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_component_payload(self):
        if self.component == "flashcard":
            if not self.front or not self.back:
                raise ValueError("flashcard 必须包含 front 和 back")
        elif self.component == "matching":
            if len(self.pairs) < 2:
                raise ValueError("matching 至少需要两组 pairs")
            normalized = []
            for pair in self.pairs:
                if not isinstance(pair, dict) or not str(pair.get("left") or "").strip() or not str(pair.get("right") or "").strip():
                    raise ValueError("matching 的每组 pair 必须包含 left 和 right")
                normalized.append((str(pair["left"]).strip(), str(pair["right"]).strip()))
            if len(normalized) != len(set(normalized)):
                raise ValueError("matching 的 pairs 不得重复")
        elif self.component == "ordering":
            if len(self.ordering_items) < 2 or len(self.correct_order) != len(self.ordering_items):
                raise ValueError("ordering 必须同时包含完整 ordering_items 和 correct_order")
            if len(set(self.ordering_items)) != len(self.ordering_items) or set(self.ordering_items) != set(self.correct_order):
                raise ValueError("ordering 的正确顺序必须覆盖全部 ordering_items")
        elif self.component == "branching_scenario":
            from app.core.courseware.components import validate_component_payload
            if not validate_component_payload(self.component, self.model_dump(mode="json")):
                raise ValueError("branching_scenario payload 不符合 v2 契约")
        elif self.component == "categorization":
            from app.core.courseware.components import validate_component_payload
            if not validate_component_payload(self.component, self.model_dump(mode="json")):
                raise ValueError("categorization payload 不符合 v2 契约")
        elif self.component == "word_bank_cloze":
            from app.core.courseware.components import validate_component_payload
            if not validate_component_payload(self.component, self.model_dump(mode="json")):
                raise ValueError("word_bank_cloze payload 不符合 v2 契约")
        elif self.component == "timeline_explorer":
            from app.core.courseware.components import validate_component_payload
            if not validate_component_payload(self.component, self.model_dump(mode="json")):
                raise ValueError("timeline_explorer payload 不符合 v2 契约")
        elif self.component in {"metric_strip", "process_flow", "concept_map", "evidence_card", "comparison_table", "decision_path", "code_steps", "conclusion_bar"}:
            from app.core.courseware.components import validate_component_payload
            if not validate_component_payload(self.component, self.model_dump(mode="json")):
                raise ValueError("结构化视觉组件 payload 不符合 v3 契约")
        return self


class TextComponentSpec(CoursewareBlock):
    component: Literal["callout", "key_point", "compare", "recap", "flashcard", "matching", "ordering"] = "callout"


class StepsComponentSpec(CoursewareBlock):
    component: Literal["steps", "ordered_steps"]


class ChoiceComponentSpec(CoursewareBlock):
    component: Literal["single_choice", "multiple_choice"]


class BranchingScenarioSpec(CoursewareBlock):
    schema_version: Literal["2.0"] = "2.0"
    component: Literal["branching_scenario"]


class CategorizationSpec(CoursewareBlock):
    schema_version: Literal["2.0"] = "2.0"
    component: Literal["categorization"]


class WordBankClozeSpec(CoursewareBlock):
    schema_version: Literal["2.0"] = "2.0"
    component: Literal["word_bank_cloze"]


class TimelineExplorerSpec(CoursewareBlock):
    schema_version: Literal["2.0"] = "2.0"
    component: Literal["timeline_explorer"]


class VisualComponentSpec(CoursewareBlock):
    schema_version: Literal["3.0"] = "3.0"
    component: Literal[
        "metric_strip", "process_flow", "concept_map", "evidence_card", "comparison_table",
        "decision_path", "code_steps", "conclusion_bar",
    ]


# The discriminator is deliberately platform-owned. Unknown component names
# fail structured parsing before they reach the renderer.
ComponentSpec = Annotated[
    Union[
        TextComponentSpec, StepsComponentSpec, ChoiceComponentSpec,
        BranchingScenarioSpec, CategorizationSpec, WordBankClozeSpec, TimelineExplorerSpec, VisualComponentSpec,
    ],
    Field(discriminator="component"),
]


class CoursewareSceneSpec(BaseModel):
    """A renderer-safe, source-traceable learner-facing scene."""

    schema_version: Literal["1.0", "2.0"] = "2.0"
    kind: SceneKind
    title: str = Field(min_length=1, max_length=120)
    blocks: list[ComponentSpec] = Field(min_length=1, max_length=10)
    steps: list[str] = Field(default_factory=list, max_length=10)
    options: list[str] = Field(default_factory=list, max_length=8)
    answer: list[str] = Field(default_factory=list, max_length=8)
    feedback: str | None = Field(default=None, max_length=800)
    lead: str | None = Field(default=None, max_length=500)
    conclusion: str | None = Field(default=None, max_length=500)
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
            if self.steps:
                raise ValueError("测验场景只能保留一个主要答题操作")
            if not str(self.feedback or "").strip():
                raise ValueError("测验必须包含来源支持的反馈")
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
            "lead": self.lead, "conclusion": self.conclusion,
        }
        # Every learner-visible field gets a stable source-map entry. Explicit
        # refs win; deterministic fallback preserves old AI/fallback payloads.
        first_map = block_maps[0] if block_maps else []
        title_map = sorted({block_id for ref in self.title_source_refs for block_id in ref.source_block_ids}) or first_map
        result["source_map"]["title"] = [title_map]
        if self.lead:
            result["source_map"]["lead"] = [first_map]
        if self.conclusion:
            result["source_map"]["conclusion"] = [block_maps[-1] if block_maps else first_map]
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


class CoursewarePracticeEnrichment(BaseModel):
    """Small, source-bound model contract for a platform-owned steps page.

    Practice pages keep component IDs and provenance in the deterministic
    storyboard.  The model only supplies pedagogical wording and ordered
    actions, avoiding a large discriminated-union response for the resource
    type that most often needs reliable guided interaction.
    """

    title: str = Field(min_length=1, max_length=120)
    lead: str = Field(min_length=1, max_length=500)
    steps: list[str] = Field(min_length=1, max_length=1)
    conclusion: str = Field(min_length=1, max_length=500)

    @field_validator("steps")
    @classmethod
    def clean_steps(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if len(cleaned) != 1:
            raise ValueError("步骤页必须只包含一条当前操作")
        return cleaned


class CoursewarePracticeStepBoundary(BaseModel):
    """A structural source-block grouping, never learner-facing prose."""

    title: str = Field(min_length=1, max_length=160)
    source_block_ids: list[str] = Field(min_length=1, max_length=32)

    _clean_blocks = field_validator("source_block_ids")(_clean_ids)


class CoursewarePracticeStepExtraction(BaseModel):
    """LLM candidate for one guide's ordered, source-bound step structure.

    Context blocks are deliberately outside the operation sequence: guide
    introductions, code fences, appendices and checklists must not become fake
    learner steps just because they have their own source block.
    """

    steps: list[CoursewarePracticeStepBoundary] = Field(min_length=1, max_length=16)
    context_block_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_partition_ids(self):
        all_ids = [block_id for step in self.steps for block_id in step.source_block_ids] + self.context_block_ids
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("实操步骤与上下文来源块不得重复")
        return self


class CoursewareNarrativeEnrichment(BaseModel):
    """Minimal model contract for a platform-owned introduction or recap."""

    title: str = Field(min_length=1, max_length=120)
    lead: str = Field(min_length=1, max_length=500)
    conclusion: str = Field(min_length=1, max_length=500)


class CoursewareReviewIssue(BaseModel):
    code: str = Field(default="QUALITY", min_length=1, max_length=64)
    dimension: str | None = Field(default=None, max_length=64)
    severity: Literal["info", "warning", "error"] = "warning"
    scope: Literal["course", "scenes", "scene", "block"] = "course"
    scene_id: str | None = Field(default=None, max_length=96)
    affected_scene_ids: list[str] = Field(default_factory=list, max_length=12)
    instruction: str = Field(min_length=1, max_length=400)
    block_id: str | None = Field(default=None, max_length=96)


class CoursewareReviewDecision(BaseModel):
    """AI review signal; deterministic release gates remain final authority."""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    decision: Literal["approved", "revision_required", "rejected", "unavailable"] | None = None
    status: Literal["pass", "revise", "reject", "unavailable"] | None = None
    issues: list[CoursewareReviewIssue] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    summary: str | None = Field(default=None, max_length=1000)
    trace_metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_v2_status(cls, values):
        if isinstance(values, dict) and not values.get("decision") and values.get("status"):
            values = dict(values)
            values["decision"] = {"pass": "approved", "revise": "revision_required", "reject": "rejected"}.get(values["status"], values["status"])
        return values

    @model_validator(mode="after")
    def validate_review_scope(self):
        if self.decision is None:
            raise ValueError("review decision/status required")
        if self.schema_version == "2.0":
            known = {"objective_alignment", "coherence", "explanation_depth", "example_usefulness", "misconception_handling", "practice_gradient", "feedback_quality", "interaction_purpose", "cognitive_load"}
            if set(self.rubric_scores) - known:
                raise ValueError("unknown rubric dimension")
            for issue in self.issues:
                if issue.severity == "error" and issue.scope in {"scene", "block"} and not issue.scene_id:
                    raise ValueError("localized error requires scene_id")
                if issue.scope == "block" and not issue.block_id:
                    raise ValueError("block issue requires block_id")
                if issue.scope == "scenes" and not issue.affected_scene_ids:
                    raise ValueError("multi-scene issue requires affected_scene_ids")
        return self
