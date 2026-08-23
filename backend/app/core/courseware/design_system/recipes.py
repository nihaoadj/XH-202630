"""Platform-owned visual recipes; models may select IDs only."""

from typing import Final

THEME_IDS: Final = ("editorial", "midnight", "paper")
SCENE_RECIPE_IDS: Final = ("cover", "learning_map", "chapter_transition", "concept", "practice", "quiz", "recap", "completion")
RECIPES = {theme: {scene: {"theme_id": theme, "recipe_id": scene, "token_ids": ("font_body", "space_card", "touch_min"), "layout_id": "cover" if scene == "cover" else ("practice" if scene == "practice" else "focus"), "motion_id": "subtle", "icon_id": f"{scene}-mark", "decoration_id": f"{theme}-{scene}"} for scene in SCENE_RECIPE_IDS} for theme in THEME_IDS}

def resolve_recipe(theme_id: str, recipe_id: str) -> dict[str, object]:
    try:
        return dict(RECIPES[theme_id][recipe_id])
    except KeyError as exc:
        raise ValueError("COURSEWARE_UNKNOWN_VISUAL_RECIPE") from exc
