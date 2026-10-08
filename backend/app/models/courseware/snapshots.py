"""Immutable, privacy-minimized inputs for courseware design."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResourceBundleSnapshot(BaseModel):
    """One frozen resource in a bundle; learner prose is intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1, max_length=96)
    resource_type: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=128)
    batch_id: str | None = Field(default=None, max_length=128)
    topic: str | None = Field(default=None, max_length=240)
    knowledge_points: tuple[str, ...] = ()
    has_verifiable_exercises: bool = False
    source_block_ids: tuple[str, ...] = ()
    source_graph: dict[str, Any] = Field(default_factory=dict)
    frozen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "ResourceBundleSnapshot":
        graph = snapshot.get("source_graph") or {}
        if not graph.get("nodes"):
            # Compatibility for old persisted snapshots: reconstruct only
            # resource/block nodes, never copy arbitrary source dictionaries.
            resource_id = str(snapshot["resource_id"])
            nodes = [{"node_id": f"resource:{resource_id}", "node_type": "resource", "resource_id": resource_id,
                      "version": int(snapshot.get("version") or 1)}]
            edges = []
            for item in snapshot.get("blocks") or []:
                block_id = str(item.get("block_id"))
                nodes.append({"node_id": f"block:{block_id}", "node_type": "block", "block_id": block_id})
                edges.append({"from": f"resource:{resource_id}", "to": f"block:{block_id}", "relation": "contains"})
            graph = {"schema_version": "1.0", "nodes": nodes, "edges": edges}
        return cls(
            resource_id=str(snapshot["resource_id"]), resource_type=str(snapshot.get("resource_type") or ""),
            role=str(snapshot.get("role") or ""), version=int(snapshot.get("version") or 1),
            content_hash=str(snapshot.get("content_hash") or ""),
            batch_id=str(snapshot["batch_id"]) if snapshot.get("batch_id") else None,
            topic=str(snapshot["topic"]) if snapshot.get("topic") else None,
            knowledge_points=tuple(str(item) for item in (snapshot.get("knowledge_points") or []) if str(item).strip()),
            has_verifiable_exercises=any(
                bool(item.get("question")) and item.get("answer") is not None
                for item in (snapshot.get("exercise_items") or []) if isinstance(item, dict)
            ),
            source_block_ids=tuple(str(item.get("block_id")) for item in snapshot.get("blocks") or []),
            source_graph=graph,
        )


class LearnerContextSnapshot(BaseModel):
    """Only design-relevant context; never raw identity or sensitive profile data."""

    model_config = ConfigDict(extra="forbid")

    level: str | None = Field(default=None, max_length=64)
    goal: str | None = Field(default=None, max_length=240)
    weak_points: tuple[str, ...] = ()
    language: str = Field(default="zh-CN", max_length=32)
    pace: str = Field(default="neutral", max_length=32)
    accessibility_preferences: tuple[str, ...] = ()

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


__all__ = ["LearnerContextSnapshot", "ResourceBundleSnapshot"]
