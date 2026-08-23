"""Deterministic shape validation for renderer-bound courseware scenes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_scene_shape(scene: Mapping[str, Any]) -> list[str]:
    """Return bounded contract errors without interpreting learner content."""

    errors: list[str] = []
    for field in ("kind", "title", "blocks", "source_refs", "source_map"):
        if field not in scene:
            errors.append(f"missing:{field}")
    if not isinstance(scene.get("kind"), str) or not scene.get("kind"):
        errors.append("invalid:kind")
    if not isinstance(scene.get("title"), str) or not scene.get("title", "").strip():
        errors.append("invalid:title")
    if not isinstance(scene.get("blocks"), list) or not scene.get("blocks"):
        errors.append("invalid:blocks")
    if not isinstance(scene.get("source_refs"), list) or not scene.get("source_refs"):
        errors.append("invalid:source_refs")
    if not isinstance(scene.get("source_map"), Mapping):
        errors.append("invalid:source_map")
    if scene.get("kind") == "practice" and not scene.get("steps"):
        errors.append("invalid:practice_steps")
    if scene.get("kind") == "quiz":
        options = scene.get("options") or []
        answers = scene.get("answer") or []
        if len(options) < 2 or not answers or not set(answers).issubset(set(options)):
            errors.append("invalid:quiz_answers")
    return errors


def validate_storyboard_bindings(scene: Mapping[str, Any], learning_design: Mapping[str, Any]) -> list[str]:
    """Enforce that a producer fills a frozen storyboard slot without widening it."""
    storyboard = (learning_design.get("storyboard") or {}) if isinstance(learning_design, Mapping) else {}
    slot = next((item for item in storyboard.get("scenes") or [] if item.get("scene_id") == scene.get("scene_id")), None)
    if slot is None:
        return ["scene_id"]
    errors: list[str] = []
    if scene.get("kind") != slot.get("kind"):
        errors.append("kind")
    if set(scene.get("objective_ids") or []) != set(slot.get("objective_ids") or []):
        errors.append("objective_ids")
    if not set(scene.get("source_refs") or []).issubset(set(slot.get("source_resource_ids") or [])):
        errors.append("source_resource_ids")
    if not set(scene.get("source_block_ids") or []).issubset(set(slot.get("source_block_ids") or [])):
        errors.append("source_block_ids")
    allowed = set(slot.get("allowed_component_ids") or slot.get("allowed_components") or [])
    components = {str(item.get("component")) for item in (scene.get("component_blocks") or []) if isinstance(item, Mapping)}
    if not components.issubset(allowed):
        errors.append("component_ids")
    return errors


__all__ = ["validate_scene_shape", "validate_storyboard_bindings"]
