"""Deterministic field-level provenance construction and hard validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models.courseware.provenance import ProvenanceEdge, ProvenanceGraph, ProvenanceNode


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _refs_for_field(scene: dict[str, Any], field: str, index: int | None = None) -> list[str]:
    source_map = scene.get("source_map") or {}
    values = source_map.get(field) or []
    if index is not None and isinstance(values, list) and values and index < len(values):
        values = [values[index]]
    refs: list[str] = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, list):
            refs.extend(str(value) for value in item if value)
        elif item:
            refs.append(str(item))
    return sorted(set(refs))


def build_provenance_graph(document: dict[str, Any], snapshots: list[dict[str, Any]]) -> ProvenanceGraph:
    """Build a graph without copying learner profile data into the graph."""
    snapshot_by_id = {str(item.get("resource_id")): item for item in snapshots}
    nodes: list[ProvenanceNode] = []
    edges: list[ProvenanceEdge] = []
    block_hashes: dict[str, str] = {}
    snapshot_hashes: dict[str, str] = {}
    for snapshot_id, snapshot in snapshot_by_id.items():
        snapshot_hash = str(snapshot.get("content_hash") or _hash(snapshot))
        snapshot_hashes[snapshot_id] = snapshot_hash
        nodes.append(ProvenanceNode(node_id=f"snapshot:{snapshot_id}", kind="source_snapshot", snapshot_hash=snapshot_hash))
        for block in snapshot.get("blocks") or []:
            block_id = str(block.get("block_id") or "")
            if not block_id:
                continue
            block_hash = _hash({"snapshot": snapshot_id, "block": block})
            block_hashes[block_id] = block_hash
            nodes.append(ProvenanceNode(
                node_id=f"block:{block_id}", kind="source_block", snapshot_hash=snapshot_hash,
                metadata={"source_resource_id": snapshot_id, "block_hash": block_hash},
            ))
            edges.append(ProvenanceEdge(
                source_node_id=f"snapshot:{snapshot_id}", target_node_id=f"block:{block_id}",
                transformation="extract", snapshot_hash=snapshot_hash,
            ))

    visible = covered = 0
    for scene_index, scene in enumerate(document.get("scenes") or []):
        scene_id = f"scene:{scene_index}"
        scene_snapshot_ids = [str(value) for value in scene.get("source_refs") or []]
        scene_snapshot_ids = sorted(set(scene_snapshot_ids))
        scene_hash = _hash(scene)
        artifact_id = f"artifact:scene:{scene_index}"
        nodes.append(ProvenanceNode(node_id=artifact_id, kind="artifact_node", snapshot_hash=scene_hash))
        field_specs: list[tuple[str, Any, int | None]] = [("title", scene.get("title"), None)]
        if scene.get("lead"):
            field_specs.append(("lead", scene.get("lead"), None))
        field_specs.extend(("blocks", value, index) for index, value in enumerate(scene.get("blocks") or []))
        field_specs.extend(("steps", value, index) for index, value in enumerate(scene.get("steps") or []))
        field_specs.extend(("options", value, index) for index, value in enumerate(scene.get("options") or []))
        field_specs.extend(("answer", value, index) for index, value in enumerate(scene.get("answer") or []))
        if scene.get("feedback"):
            field_specs.append(("feedback", scene.get("feedback"), None))
        if scene.get("conclusion"):
            field_specs.append(("conclusion", scene.get("conclusion"), None))
        for field, value, index in field_specs:
            visible += 1
            field_path = f"scenes[{scene_index}].{field}" + (f"[{index}]" if index is not None else "")
            node_id = f"field:{field_path}"
            block_ids = _refs_for_field(scene, field, index)
            valid_blocks = [block_id for block_id in block_ids if block_id in block_hashes]
            nodes.append(ProvenanceNode(
                node_id=node_id, kind="generated_field", snapshot_hash=scene_hash, field_path=field_path,
                metadata={"missing_source_block_ids": sorted(set(block_ids) - set(valid_blocks)),
                          "source_mapping_missing": not bool(block_ids)},
            ))
            field_covered = False
            for block_id in valid_blocks:
                source_snapshot = next(
                    (source_id for source_id, snapshot in snapshot_by_id.items()
                     if any(str(item.get("block_id")) == block_id for item in snapshot.get("blocks") or [])),
                    None,
                )
                if source_snapshot is None or source_snapshot not in scene_snapshot_ids:
                    continue
                edges.append(ProvenanceEdge(
                    source_node_id=f"block:{block_id}", target_node_id=node_id,
                    transformation="paraphrase", snapshot_hash=snapshot_hashes[source_snapshot],
                ))
                evidence_id = f"evidence:{field_path}:{block_id}"
                nodes.append(ProvenanceNode(
                    node_id=evidence_id, kind="evidence_span", snapshot_hash=snapshot_hashes[source_snapshot],
                    field_path=field_path,
                    metadata={"source_block_id": block_id, "span_hash": block_hashes[block_id],
                              "transformation": "paraphrase"},
                ))
                edges.append(ProvenanceEdge(
                    source_node_id=f"block:{block_id}", target_node_id=evidence_id,
                    transformation="extract", snapshot_hash=snapshot_hashes[source_snapshot],
                ))
                edges.append(ProvenanceEdge(
                    source_node_id=evidence_id, target_node_id=node_id,
                    transformation="paraphrase", snapshot_hash=snapshot_hashes[source_snapshot],
                ))
                field_covered = True
            if field_covered:
                covered += 1
            edges.append(ProvenanceEdge(
                source_node_id=node_id, target_node_id=artifact_id,
                transformation="renders", snapshot_hash=scene_hash,
            ))

        for block_index, component in enumerate(scene.get("component_blocks") or []):
            visible += 1
            field_path = f"scenes[{scene_index}].component_blocks[{block_index}].component"
            node_id = f"property:{field_path}"
            nodes.append(ProvenanceNode(node_id=node_id, kind="component_property", snapshot_hash=scene_hash, field_path=field_path,
                                        metadata={"component": component.get("component")}))
            refs = component.get("source_refs") or []
            block_ids: list[str] = []
            for ref in refs:
                if isinstance(ref, dict):
                    block_ids.extend(str(item) for item in ref.get("source_block_ids") or [])
            property_covered = False
            for block_id in sorted(set(block_ids)):
                if block_id in block_hashes:
                    source_snapshot = next((source_id for source_id, snapshot in snapshot_by_id.items()
                                            if any(str(item.get("block_id")) == block_id
                                                   for item in snapshot.get("blocks") or [])), None)
                    edges.append(ProvenanceEdge(
                        source_node_id=f"block:{block_id}", target_node_id=node_id,
                        transformation="paraphrase", snapshot_hash=snapshot_hashes.get(source_snapshot, scene_hash),
                    ))
                    property_covered = True
            if not block_ids:
                node.metadata["source_mapping_missing"] = True
            if property_covered:
                covered += 1
                # Component properties must be downstream of a generated field,
                # never directly of a scene-global source block.
                for field_node in (item for item in nodes if item.kind == "generated_field"):
                    if any(edge.source_node_id == f"block:{block_id}" and edge.target_node_id == field_node.node_id
                           for edge in edges for block_id in block_ids):
                        edges.append(ProvenanceEdge(source_node_id=field_node.node_id, target_node_id=node_id,
                                                    transformation="adapted_step", snapshot_hash=field_node.snapshot_hash))
                        break
            edges.append(ProvenanceEdge(source_node_id=node_id, target_node_id=artifact_id,
                                        transformation="renders", snapshot_hash=scene_hash))

    root_hash = _hash({"document": document, "snapshots": [snapshot_hashes[key] for key in sorted(snapshot_hashes)]})
    return ProvenanceGraph(root_hash=root_hash, nodes=nodes, edges=edges,
                           learner_visible_field_count=visible, covered_field_count=covered)


def validate_provenance_graph(graph: ProvenanceGraph) -> list[dict[str, str]]:
    """Return stable hard-gate errors; callers must quarantine on any error."""
    node_ids = {node.node_id for node in graph.nodes}
    errors: list[dict[str, str]] = []
    for edge in graph.edges:
        if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
            errors.append({"code": "PROVENANCE_UNKNOWN_NODE", "message": "来源图包含未知节点"})
        if edge.source_node_id.startswith("block:") and edge.target_node_id.startswith(("field:", "evidence:", "property:")):
            source = next(node for node in graph.nodes if node.node_id == edge.source_node_id)
            if source.snapshot_hash != edge.snapshot_hash:
                errors.append({"code": "PROVENANCE_COMPONENT_CROSS_SNAPSHOT" if edge.target_node_id.startswith("property:")
                               else "PROVENANCE_CROSS_SNAPSHOT", "message": "来源节点跨快照引用"})
        if edge.source_node_id.startswith("evidence:") and edge.target_node_id.startswith("field:"):
            source = next(node for node in graph.nodes if node.node_id == edge.source_node_id)
            if source.snapshot_hash != edge.snapshot_hash:
                errors.append({"code": "PROVENANCE_FIELD_CROSS_SNAPSHOT", "message": "字段跨快照引用证据"})
    if any(node.metadata.get("missing_source_block_ids") for node in graph.nodes):
        errors.append({"code": "PROVENANCE_UNKNOWN_SOURCE_BLOCK", "message": "来源图包含未知来源块"})
    missing_fields = [node for node in graph.nodes
                      if node.kind == "generated_field" and node.metadata.get("source_mapping_missing")]
    if missing_fields:
        errors.append({"code": "PROVENANCE_FIELD_WITHOUT_SOURCE", "message": "学习者可见字段缺少独立来源映射"})
    if any((node.field_path or "").endswith(".answer") or ".answer[" in (node.field_path or "")
           for node in missing_fields):
        errors.append({"code": "PROVENANCE_ANSWER_WITHOUT_SOURCE", "message": "答案字段缺少独立来源映射"})
    if any(node.metadata.get("source_mapping_missing") for node in graph.nodes if node.kind == "component_property"):
        errors.append({"code": "PROVENANCE_COMPONENT_PROPERTY_WITHOUT_SOURCE", "message": "组件属性缺少自身来源映射"})
    if graph.learner_visible_field_count != graph.covered_field_count:
        errors.append({"code": "PROVENANCE_FIELD_COVERAGE_INCOMPLETE", "message": "存在未覆盖的学习者可见字段"})
    if graph.coverage < 1.0:
        errors.append({"code": "PROVENANCE_COVERAGE_INCOMPLETE", "message": "来源图覆盖率必须为 100%"})
    return errors


__all__ = ["build_provenance_graph", "validate_provenance_graph"]
