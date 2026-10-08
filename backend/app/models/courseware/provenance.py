"""Public, renderer-independent provenance graph contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProvenanceNodeKind = Literal[
    "source_snapshot", "source_block", "evidence_span", "generated_field", "component_property", "artifact_node"
]


class ProvenanceNode(BaseModel):
    node_id: str = Field(min_length=1, max_length=240)
    kind: ProvenanceNodeKind
    snapshot_hash: str = Field(min_length=1, max_length=128)
    field_path: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceEdge(BaseModel):
    source_node_id: str = Field(min_length=1, max_length=240)
    target_node_id: str = Field(min_length=1, max_length=240)
    transformation: Literal["snapshot", "extract", "summary", "paraphrase", "quote", "adapted_step", "renders", "supports"]
    snapshot_hash: str = Field(min_length=1, max_length=128)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ProvenanceGraph(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    root_hash: str = Field(min_length=1, max_length=128)
    nodes: list[ProvenanceNode] = Field(default_factory=list)
    edges: list[ProvenanceEdge] = Field(default_factory=list)
    learner_visible_field_count: int = Field(default=0, ge=0)
    covered_field_count: int = Field(default=0, ge=0)

    @property
    def coverage(self) -> float:
        if self.learner_visible_field_count == 0:
            return 1.0
        return self.covered_field_count / self.learner_visible_field_count

    def as_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root_hash": self.root_hash,
            "coverage": self.coverage,
            "learner_visible_field_count": self.learner_visible_field_count,
            "covered_field_count": self.covered_field_count,
            "nodes": [node.model_dump(mode="json") for node in self.nodes],
            "edges": [edge.model_dump(mode="json") for edge in self.edges],
        }


__all__ = ["ProvenanceEdge", "ProvenanceGraph", "ProvenanceNode"]
