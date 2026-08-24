"""Platform-owned visual recipes; models may select IDs only."""

from typing import Final

THEME_IDS: Final = ("editorial", "midnight", "paper")
SCENE_RECIPE_IDS: Final = (
    "editorial_cover", "learning_map_grid", "concept_split", "process_lane",
    "comparison_matrix", "case_diagnostic", "practice_workspace",
    "quiz_focus", "recap_dashboard",
)
LEGACY_RECIPE_ALIASES: Final = {
    "cover": "editorial_cover", "learning_map": "learning_map_grid",
    "chapter_transition": "concept_split", "concept": "concept_split",
    "practice": "practice_workspace", "quiz": "quiz_focus",
    "recap": "recap_dashboard", "completion": "recap_dashboard",
}
_LAYOUT_BY_RECIPE = {
    "editorial_cover": "cover", "learning_map_grid": "progress",
    "concept_split": "focus", "process_lane": "steps",
    "comparison_matrix": "compare", "case_diagnostic": "focus",
    "practice_workspace": "practice", "quiz_focus": "focus",
    "recap_dashboard": "recap",
}
RECIPES = {
    theme: {
        recipe_id: {
            "theme_id": theme, "recipe_id": recipe_id,
            "token_ids": ("grid_columns", "safe_area", "space_card", "touch_min", "density_comfortable"),
            "layout_id": _LAYOUT_BY_RECIPE[recipe_id], "motion_id": "subtle",
            "icon_id": f"{recipe_id}-mark", "decoration_id": f"{theme}-{recipe_id}",
        }
        for recipe_id in SCENE_RECIPE_IDS
    }
    for theme in THEME_IDS
}

def resolve_recipe(theme_id: str, recipe_id: str) -> dict[str, object]:
    recipe_id = LEGACY_RECIPE_ALIASES.get(recipe_id, recipe_id)
    try:
        return dict(RECIPES[theme_id][recipe_id])
    except KeyError as exc:
        raise ValueError("COURSEWARE_UNKNOWN_VISUAL_RECIPE") from exc
