from app.core.courseware.design_system.recipes import RECIPES, SCENE_RECIPE_IDS, THEME_IDS, resolve_recipe
from app.core.courseware.renderer import render_courseware

def test_all_theme_scene_recipes_are_registered_and_platform_owned():
    assert set(RECIPES) == set(THEME_IDS)
    for theme in THEME_IDS:
        assert set(RECIPES[theme]) == set(SCENE_RECIPE_IDS)
        for scene in SCENE_RECIPE_IDS:
            recipe = resolve_recipe(theme, scene)
            assert recipe["theme_id"] == theme and recipe["recipe_id"] == scene
            assert recipe["layout_id"] and recipe["motion_id"] and recipe["decoration_id"]


def test_renderer_binds_registered_scene_recipes_to_the_artifact():
    artifact = render_courseware({
        "title": "配方绑定",
        "scenes": [
            {"kind": "intro", "title": "封面", "blocks": ["内容"], "source_refs": ["source"]},
            {"kind": "quiz", "title": "自测", "blocks": ["问题"], "options": ["A"], "answer": ["A"], "source_refs": ["source"]},
        ],
    }).decode("utf-8")
    assert 'data-recipe-id="cover"' in artifact
    assert 'data-recipe-id="quiz"' in artifact
