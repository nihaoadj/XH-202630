"""Deterministic source-trace and teaching-quality release gates."""

import re
from typing import Any

from app.core.courseware.components import is_registered_component


_FENCED_CODE = re.compile(r"```.*?```", flags=re.DOTALL)
# This deliberately requires a tag name directly after ``<``.  The former
# ``<[^>]+>`` rule crossed newlines and treated ordinary Python comparisons
# (for example ``score < limit`` followed later by ``count > 0``) as HTML.
_HTML_TAG = re.compile(r"</?[a-z][a-z0-9:_-]*(?:\s+[^<>]*)?/?>", flags=re.IGNORECASE)
_UNSAFE_URI = re.compile(r"(?:javascript\s*:|https?://)", flags=re.IGNORECASE)


def _contains_unsafe_learner_content(value: Any) -> bool:
    """Reject actual markup/URLs, while allowing source-bound code examples.

    The deterministic renderer renders learner content as text, but URLs and
    markup are still disallowed by the courseware contract.  Fenced code is a
    first-class source block in practice guides and may legitimately contain
    comparison operators or API examples, so it must not be scanned as prose.
    """
    prose = _FENCED_CODE.sub("", str(value or ""))
    return bool(_HTML_TAG.search(prose) or _UNSAFE_URI.search(prose))


def source_trace_review(
    document: dict[str, Any], snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    allowed_sources = {item["resource_id"] for item in snapshots}
    allowed_blocks = {block["block_id"] for item in snapshots for block in item.get("blocks", [])}
    issues: list[dict[str, Any]] = []
    for index, scene in enumerate(document.get("scenes") or []):
        refs = set(scene.get("source_refs") or [])
        if not refs:
            issues.append({"code": "MISSING_SOURCE_REF", "scene_order": index})
        elif not refs.issubset(allowed_sources):
            issues.append({"code": "UNKNOWN_SOURCE_REF", "scene_order": index})
        block_refs = set(scene.get("source_block_ids") or [])
        if not block_refs:
            issues.append({"code": "MISSING_SOURCE_BLOCK_REF", "scene_order": index})
        elif not block_refs.issubset(allowed_blocks):
            issues.append({"code": "UNKNOWN_SOURCE_BLOCK_REF", "scene_order": index})
        source_map = scene.get("source_map") or {}
        mapped_blocks: set[str] = set()
        try:
            for groups in source_map.values():
                for group in groups:
                    mapped_blocks.update(str(value) for value in group)
        except (TypeError, AttributeError):
            issues.append({"code": "INVALID_BLOCK_SOURCE_MAP", "scene_order": index})
            continue
        if not mapped_blocks or not mapped_blocks.issubset(allowed_blocks):
            issues.append({"code": "INVALID_BLOCK_SOURCE_MAP", "scene_order": index})
        component_blocks = scene.get("component_blocks") or []
        for block in component_blocks:
            block_refs = block.get("source_refs") if isinstance(block, dict) else None
            if not isinstance(block, dict) or not is_registered_component(
                    block.get("component"), str(block.get("schema_version") or "1.0")):
                issues.append({"code": "UNKNOWN_COMPONENT", "scene_order": index})
                continue
            if not block_refs:
                issues.append({"code": "MISSING_BLOCK_SOURCE_REF", "scene_order": index})
                continue
            for ref in block_refs:
                if not isinstance(ref, dict) or ref.get("source_resource_id") not in allowed_sources:
                    issues.append({"code": "UNKNOWN_BLOCK_SOURCE_REF", "scene_order": index})
                elif not set(ref.get("source_block_ids") or []).issubset(allowed_blocks):
                    issues.append({"code": "UNKNOWN_BLOCK_SOURCE_BLOCK_REF", "scene_order": index})
    return issues

def quality_review(document: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = document.get("scenes") or []
    issues: list[dict[str, Any]] = []
    kinds = [scene.get("kind") for scene in scenes]
    if not kinds or kinds[0] != "intro":
        issues.append({"code": "MISSING_INTRO"})
    if not kinds or kinds[-1] != "recap":
        issues.append({"code": "MISSING_RECAP"})
    if len(scenes) > 24:
        issues.append({"code": "TOO_MANY_SCENES"})
    for index, scene in enumerate(scenes):
        if not scene.get("title") or not (scene.get("blocks") or scene.get("steps") or scene.get("options")):
            issues.append({"code": "EMPTY_SCENE", "scene_order": index})
        if scene.get("kind") == "quiz" and (not scene.get("options") or not scene.get("answer")):
            issues.append({"code": "INVALID_QUIZ", "scene_order": index})
        learner_values = [scene.get("title"), scene.get("lead"), *(scene.get("blocks") or []), *(scene.get("steps") or []), *(scene.get("options") or []), scene.get("feedback"), scene.get("conclusion")]
        if any(_contains_unsafe_learner_content(value) for value in learner_values):
            issues.append({"code": "UNSAFE_LEARNER_CONTENT", "scene_order": index})
    return issues
