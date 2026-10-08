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
    if scene.get("kind") == "practice" and not scene.get("steps") and scene.get("practice_json_schema_version") != "3.0":
        errors.append("invalid:practice_steps")
    if scene.get("practice_json_schema_version") == "3.0":
        blocks = scene.get("component_blocks") or []
        if not blocks or any(
            not isinstance(block, Mapping)
            or not str(block.get("source_json_path") or "").strip()
            or not str(block.get("evidence_json_path") or "").strip()
            for block in blocks
        ):
            errors.append("invalid:practice_component_json_mapping")
        variant = str(scene.get("practice_variant") or "")
        component_by_path = {
            str(block.get("source_json_path")): str(block.get("component"))
            for block in blocks if isinstance(block, Mapping)
        }
        phase_contracts = {
            "prepare": {"preparation.goal": "key_point", "preparation.items": "steps"},
            "verify": {"verification.goal": "key_point", "verification.checklist": "steps"},
            "reflect": {"reflection.goal": "key_point", "reflection.summary": "callout"},
        }
        if variant in phase_contracts and component_by_path != phase_contracts[variant]:
            errors.append("invalid:practice_phase_component_contract")
        if variant in {"guided", "code"}:
            subject = str(scene.get("practice_json_subject") or "")
            required = {
                f"{subject}.instruction_text": "key_point",
                f"{subject}.verification": "callout",
            }
            non_code_paths = {path: component for path, component in component_by_path.items() if ".code_blocks." not in path}
            has_code = any(".code_blocks." in path and component == "code_block" for path, component in component_by_path.items())
            if non_code_paths != required or (variant == "code") != has_code:
                errors.append("invalid:practice_step_component_contract")
            if str(scene.get("title_source_json_path") or "") != f"{subject}.title":
                errors.append("invalid:practice_step_title_mapping")
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
