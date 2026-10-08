"""Registered page-level visual variants for deterministic courseware pages.

The layout recipe remains unchanged. These IDs only select platform-owned
color and typography treatments for structured practice pages and review
checklist pages. Selection is seed-stable so a published artifact can be
rendered again without changing its appearance.
"""

from __future__ import annotations

import hashlib
from typing import Final


PRACTICE_STYLE_OPTIONS: Final[dict[str, tuple[str, ...]]] = {
    "prepare": ("practice-prepare-classic", "practice-prepare-calm"),
    "step": (
        "practice-step-classic",
        "practice-step-terminal",
        "practice-step-signal",
        "practice-step-ocean",
        "practice-step-forest",
        "practice-step-coral",
        "practice-step-lilac",
        "practice-step-sand",
    ),
    "verify": ("practice-verify-classic", "practice-verify-blueprint"),
    "reflect": ("practice-reflect-classic", "practice-reflect-dawn"),
    "review": (
        "review-archive",
        "review-mint",
        "review-lilac",
        "review-coral",
        "review-sand",
        "review-ink",
    ),
}

VISUAL_STYLE_METADATA: Final[dict[str, dict[str, str]]] = {
    "practice-prepare-classic": {"page": "prepare", "label": "准备 · 经典"},
    "practice-prepare-calm": {"page": "prepare", "label": "准备 · 清透"},
    "practice-step-classic": {"page": "step", "label": "步骤 · 经典"},
    "practice-step-terminal": {"page": "step", "label": "步骤 · 终端"},
    "practice-step-signal": {"page": "step", "label": "步骤 · 信号"},
    "practice-step-ocean": {"page": "step", "label": "步骤 · 海洋"},
    "practice-step-forest": {"page": "step", "label": "步骤 · 森林"},
    "practice-step-coral": {"page": "step", "label": "步骤 · 珊瑚"},
    "practice-step-lilac": {"page": "step", "label": "步骤 · 丁香"},
    "practice-step-sand": {"page": "step", "label": "步骤 · 沙岩"},
    "practice-verify-classic": {"page": "verify", "label": "验证 · 经典"},
    "practice-verify-blueprint": {"page": "verify", "label": "验证 · 蓝图"},
    "practice-reflect-classic": {"page": "reflect", "label": "复盘 · 经典"},
    "practice-reflect-dawn": {"page": "reflect", "label": "复盘 · 晨光"},
    "review-archive": {"page": "review", "label": "复习 · 档案"},
    "review-mint": {"page": "review", "label": "复习 · 薄荷"},
    "review-lilac": {"page": "review", "label": "复习 · 丁香"},
    "review-coral": {"page": "review", "label": "复习 · 珊瑚"},
    "review-sand": {"page": "review", "label": "复习 · 沙岩"},
    "review-ink": {"page": "review", "label": "复习 · 墨色"},
}

STEP_STYLE_SELECTION_COUNT: Final[int] = 5
REVIEW_QUESTION_STYLE_MINIMUM: Final[int] = 4
REVIEW_QUESTION_PAGE_ROLES: Final[frozenset[str]] = frozenset({
    "review_recall",
    "review_distinction",
    "review_example",
})


def practice_style_family(scene: dict) -> str | None:
    review_page_roles = {
        "review_overview",
        "review_recall",
        "review_distinction",
        "review_example",
        "review_node_summary",
        "summary_action",
    }
    review_recipe_ids = {
        "review_overview",
        "review_recall_grid",
        "review_distinction_grid",
        "review_example_focus",
        "review_node_summary",
        "recap_dashboard",
    }
    if str(scene.get("page_role") or "") in review_page_roles or str(
        scene.get("layout_recipe_id") or scene.get("recipe_id") or ""
    ) in review_recipe_ids:
        return "review"
    if scene.get("practice_json_schema_version") != "3.0":
        return None
    variant = str(scene.get("practice_variant") or "")
    if variant in {"prepare", "verify", "reflect"}:
        return variant
    if str(scene.get("practice_json_subject") or "").startswith("practice.steps."):
        return "step"
    return None


def select_practice_step_styles(*, seed: str, count: int = STEP_STYLE_SELECTION_COUNT) -> tuple[str, ...]:
    options = PRACTICE_STYLE_OPTIONS["step"]
    if count < 1 or count > len(options):
        raise ValueError(f"COURSEWARE_INVALID_STEP_STYLE_COUNT: {count}")
    ranked = sorted(
        options,
        key=lambda style_id: hashlib.sha256(
            f"courseware-step-style-set-v1|{seed}|{style_id}".encode("utf-8")
        ).digest(),
    )
    return tuple(ranked[:count])


def select_review_question_styles(*, seed: str) -> tuple[str, ...]:
    """Return the seed-stable style order used by review question pages."""
    options = PRACTICE_STYLE_OPTIONS["review"]
    if len(options) < REVIEW_QUESTION_STYLE_MINIMUM:
        raise ValueError("COURSEWARE_REVIEW_STYLE_POOL_TOO_SMALL")
    return tuple(sorted(
        options,
        key=lambda style_id: hashlib.sha256(
            f"courseware-review-question-style-v1|{seed}|{style_id}".encode("utf-8")
        ).digest(),
    ))


def select_practice_visual_style(*, family: str, seed: str, sequence_index: int = 0) -> str:
    options = PRACTICE_STYLE_OPTIONS.get(family)
    if not options:
        raise ValueError(f"COURSEWARE_UNKNOWN_PRACTICE_STYLE_FAMILY: {family}")
    if family == "step":
        selected = select_practice_step_styles(seed=seed)
        return selected[sequence_index % len(selected)]
    digest = hashlib.sha256(f"courseware-style-v1|{family}|{seed}".encode("utf-8")).digest()
    return options[int.from_bytes(digest[:8], "big") % len(options)]


def visual_style_for_scene(scene: dict, *, seed: str, sequence_index: int = 0) -> str | None:
    family = practice_style_family(scene)
    if not family:
        return None
    # Review pages share one fixed layout system, but each page gets an
    # independent seed suffix so a checklist reads like a designed sequence
    # instead of one repeated skin. The artifact-level seed still makes the
    # result reproducible on re-render.
    if family == "review":
        if str(scene.get("page_role") or "") in REVIEW_QUESTION_PAGE_ROLES:
            selected = select_review_question_styles(seed=seed)
            return selected[sequence_index % len(selected)]
        scene_key = str(scene.get("scene_id") or scene.get("page_role") or "review-scene")
        seed = f"{seed}|{scene_key}"
    return select_practice_visual_style(family=family, seed=seed, sequence_index=sequence_index)


__all__ = [
    "PRACTICE_STYLE_OPTIONS",
    "REVIEW_QUESTION_PAGE_ROLES",
    "REVIEW_QUESTION_STYLE_MINIMUM",
    "STEP_STYLE_SELECTION_COUNT",
    "VISUAL_STYLE_METADATA",
    "practice_style_family",
    "select_practice_step_styles",
    "select_review_question_styles",
    "select_practice_visual_style",
    "visual_style_for_scene",
]
