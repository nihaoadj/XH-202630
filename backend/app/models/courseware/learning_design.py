"""Versioned teaching-design contracts produced before learner-facing scenes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class StoryboardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
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

    schema_version: Literal["1.0", "2.0"] = "2.0"
    resource_bundle_hash: str = Field(min_length=1, max_length=128)
    learner_context_hash: str = Field(min_length=1, max_length=128)
    objectives: LearningObjectiveGraph
    storyboard: StoryboardSpec
    resource_usage_plan: tuple[dict[str, Any], ...] = ()
    source_concept_index: SourceConceptIndex | None = None
    interaction_quota: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[dict[str, str], ...] = ()


__all__ = [
    "CoursewareLearningDesign", "LearningObjective", "LearningObjectiveGraph",
    "StoryboardScene", "StoryboardSpec", "SourceConcept", "SourceConceptRelation", "SourceConceptIndex",
]
