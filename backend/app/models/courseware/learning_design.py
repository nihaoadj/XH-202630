"""Versioned teaching-design contracts produced before learner-facing scenes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PageRole = Literal[
    "cover", "learning_map", "concept_explanation", "process_breakdown",
    "case_diagnosis", "comparison_analysis", "practice_workspace",
    "knowledge_check", "summary_action", "review_overview", "review_recall",
    "review_distinction", "review_example",
]
LayoutRecipeId = Literal[
    "editorial_cover", "learning_map_grid", "concept_split", "process_lane",
    "comparison_matrix", "case_diagnostic", "practice_workspace",
    "quiz_focus", "recap_dashboard", "review_overview", "review_recall_grid",
    "review_distinction_grid", "review_example_focus",
]


class ContentBudget(BaseModel):
    """Deterministic page-density target; never supplied as executable styling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_zones: int = Field(default=2, ge=1, le=4)
    max_zones: int = Field(default=4, ge=1, le=4)
    min_chars: int = Field(default=220, ge=0, le=1200)
    max_chars: int = Field(default=650, ge=80, le=1600)


class LearningObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=96)
    statement: str = Field(min_length=1, max_length=240)
    prerequisite_ids: tuple[str, ...] = ()
    core_concepts: tuple[str, ...] = ()
    common_mistakes: tuple[str, ...] = ()
    observable_result: str = Field(min_length=1, max_length=240)
    source_resource_ids: tuple[str, ...] = ()
    source_block_ids: tuple[str, ...] = ()


class LearningObjectiveGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    objectives: tuple[LearningObjective, ...] = ()

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class StoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1, max_length=96)
    kind: Literal["intro", "explain", "example", "compare", "practice", "scenario", "quiz", "recap"]
    required: bool = True
    objective_ids: tuple[str, ...] = ()
    source_resource_ids: tuple[str, ...] = ()
    source_block_ids: tuple[str, ...] = ()
    difficulty: str = "neutral"
    information_density: Literal["low", "medium", "high"] = "medium"
    interaction_purpose: str = Field(default="understand", max_length=120)
    allowed_components: tuple[str, ...] = ()
    allowed_component_ids: tuple[str, ...] = ()
    page_role: PageRole | None = None
    layout_recipe_id: LayoutRecipeId | None = None
    key_question: str = Field(default="", max_length=240)
    required_zones: tuple[str, ...] = ()
    content_budget: ContentBudget = Field(default_factory=ContentBudget)
    # Practice variants are platform-owned visual arrangements. They never
    # change the source order, component registry, or runtime behavior.
    practice_variant: Literal["guided", "code", "verify"] | None = None


class StoryboardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "2.0"] = "2.0"
    scenes: tuple[StoryboardScene, ...] = ()
    objective_graph_hash: str = Field(min_length=1, max_length=128)

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class SourceConcept(BaseModel):
    concept_id: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=160)
    source_refs: tuple[str, ...] = ()
    adopted_source_ids: tuple[str, ...] = ()


class SourceConceptRelation(BaseModel):
    relation_type: Literal["prerequisite", "complementary", "duplicate", "conflict"]
    from_concept_id: str = Field(min_length=1, max_length=96)
    to_concept_id: str = Field(min_length=1, max_length=96)
    source_refs: tuple[str, ...] = ()


class SourceConceptIndex(BaseModel):
    schema_version: Literal["2.0"] = "2.0"
    concepts: tuple[SourceConcept, ...] = ()
    relations: tuple[SourceConceptRelation, ...] = ()


class CoursewareLearningDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "2.0", "3.0"] = "3.0"
    resource_bundle_hash: str = Field(min_length=1, max_length=128)
    learner_context_hash: str = Field(min_length=1, max_length=128)
    objectives: LearningObjectiveGraph
    storyboard: StoryboardSpec
    resource_usage_plan: tuple[dict[str, Any], ...] = ()
    source_concept_index: SourceConceptIndex | None = None
    interaction_quota: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[dict[str, str], ...] = ()


__all__ = [
    "ContentBudget", "CoursewareLearningDesign", "LayoutRecipeId", "LearningObjective", "LearningObjectiveGraph", "PageRole",
    "StoryboardScene", "StoryboardSpec", "SourceConcept", "SourceConceptRelation", "SourceConceptIndex",
]
