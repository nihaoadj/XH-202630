"""Run a generated artifact in a real headless Edge instance when available."""

from pathlib import Path
import shutil

import pytest

from app.core.courseware.renderer import render_courseware
from app.core.courseware.runtime import SCRIPT
from tests import browser_cdp
from tests.browser_cdp import read_edge_page


def test_runtime_binds_messages_to_the_initializing_parent_origin():
    assert "e.source!==parent" in SCRIPT
    assert "parentOrigin=e.origin" in SCRIPT
    assert "postMessage({type,nonce,...context,...extra},parentOrigin)" in SCRIPT
    assert "e.data?.nonce===nonce" in SCRIPT
    assert "event_type:'answer_submitted'" in SCRIPT
    assert "send('progress'" in SCRIPT
    assert "applyRestore(e.data.restore)" in SCRIPT
    assert "component_state" in SCRIPT
    assert "matched_pair_ids" in SCRIPT
    assert "current_scene_id" in SCRIPT
    assert "data-component-id" in render_courseware({
        "title": "实例",
        "scenes": [{"scene_id": "scene-1", "kind": "intro", "source_refs": ["source"], "component_blocks": [{
            "component": "flashcard", "block_id": "flash-1", "text": "卡片", "front": "正面", "back": "背面",
            "source_refs": [{"source_resource_id": "source", "source_block_ids": ["block-1"]}],
        }]}],
    }).decode("utf-8")


def test_fenced_source_code_is_rendered_as_a_readable_inert_code_region():
    artifact = render_courseware({
        "title": "代码实操", "scenes": [{
            "scene_id": "practice-code", "kind": "practice", "page_role": "practice_workspace",
            "layout_recipe_id": "practice_workspace", "title": "步骤 1", "source_refs": ["source"],
            "source_block_ids": ["block-1"], "source_map": {"blocks": [["block-1"]]},
            "component_blocks": [{
                "component": "key_point", "block_id": "code-zone",
                "text": "操作说明：\n```python\nif score < limit:\n    return count > 0\n```",
                "source_refs": [{"source_resource_id": "source", "source_block_ids": ["block-1"]}],
            }],
        }],
    }).decode("utf-8")
    assert '<pre class="source-code" tabindex="0"><code>if score &lt; limit:' in artifact
    assert "overflow:visible" in artifact
    assert "white-space:pre-wrap" in artifact


def test_only_practice_steps_keep_an_internal_scroll_region():
    artifact = render_courseware({
        "title": "实操指南｜代码演练", "scenes": [{
            "scene_id": "practice-step", "kind": "practice", "page_role": "practice_workspace",
            "layout_recipe_id": "practice_workspace", "title": "步骤 1", "source_refs": ["source"],
            "source_block_ids": ["block-1"], "source_map": {"blocks": [["block-1"]]},
            "component_blocks": [{
                "component": "steps", "block_id": "completion", "steps": ["完成当前操作"],
                "text": "完成当前操作", "source_refs": [{"source_resource_id": "source", "source_block_ids": ["block-1"]}],
            }, {"component": "key_point", "block_id": "detail", "text": "完整说明。", "source_refs": [{"source_resource_id": "source", "source_block_ids": ["block-1"]}]}],
        }],
    }).decode("utf-8")
    assert ".component-steps{grid-column:span 3;grid-row:1/4;align-self:start;max-height:100%;overflow:auto" in artifact
    assert ".component-content{min-height:0;overflow:visible" in artifact


def _edge() -> str | None:
    return next((candidate for candidate in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
    ) if candidate and Path(candidate).exists()), None)


@pytest.mark.parametrize("style", ["equals", "separate"])
def test_cleanup_profile_matching_is_exact_even_with_spaces(tmp_path, style):
    profile = tmp_path / "edge profile with spaces"

    def arguments(path):
        return ([f"--user-data-dir={path}"] if style == "equals"
                else ["--user-data-dir", str(path)])

    assert browser_cdp._uses_profile(arguments(profile), profile)
    assert not browser_cdp._uses_profile(arguments(str(profile) + "-other"), profile)
    assert not browser_cdp._uses_profile(arguments(profile / "child"), profile)
    assert not browser_cdp._uses_profile(["--user-data-dir"], profile)
    assert not browser_cdp._uses_profile([], profile)


def test_generated_courseware_boots_in_real_headless_browser(tmp_path):
    edge = _edge()
    if edge is None:
        pytest.skip("Edge is not installed on this runner")
    artifact = render_courseware({
        "title": "浏览器冒烟课件",
        "scenes": [
            {"kind": "intro", "title": "开始", "blocks": ["先检索。"], "source_refs": ["source"], "source_block_ids": ["b1"], "source_map": {"blocks": [["b1"]]}},
            {"kind": "quiz", "title": "自测", "blocks": ["第一步是什么？"], "options": ["检索", "猜测"], "answer": ["检索"], "feedback": "答案来自来源块。", "source_refs": ["source"], "source_block_ids": ["b1"], "source_map": {"blocks": [["b1"]], "options": [["b1"], ["b1"]], "answer": [["b1"]]}},
            {"kind": "recap", "title": "复盘", "blocks": ["完成。"], "source_refs": ["source"], "source_block_ids": ["b1"], "source_map": {"blocks": [["b1"]]}},
        ],
    })
    target = tmp_path / "index.html"
    target.write_bytes(artifact)
    page = read_edge_page(edge, target, tmp_path / "edge-profile")
    assert page["progress"] == "第 1 / 3 页"
    assert page["sceneCount"] == 3
    assert page["activeSceneCount"] == 1
    assert page["errors"] == []


def test_browser_probe_captures_javascript_failures(tmp_path):
    edge = _edge()
    if edge is None:
        pytest.skip("Edge is not installed on this runner")
    target = tmp_path / "broken.html"
    target.write_text(
        '<!doctype html><meta charset="utf-8"><script>throw new Error("browser-probe-error")</script>',
        encoding="utf-8",
    )
    page = read_edge_page(edge, target, tmp_path / "edge-profile")
    assert any("browser-probe-error" in error for error in page["errors"])


def test_browser_startup_timeout_closes_detached_profile(tmp_path, monkeypatch):
    edge = _edge()
    if edge is None:
        pytest.skip("Edge is not installed on this runner")
    profile = tmp_path / "edge profile with spaces"
    target = tmp_path / "index.html"
    target.write_text("<!doctype html><title>startup cleanup</title>", encoding="utf-8")
    original_endpoint = browser_cdp._debug_endpoint

    def hidden_endpoint(_profile):
        raise FileNotFoundError("Simulated unavailable DevToolsActivePort")

    monkeypatch.setattr(browser_cdp, "_debug_endpoint", hidden_endpoint)
    monkeypatch.setattr(browser_cdp, "_STARTUP_TIMEOUT_SECONDS", 1)
    with pytest.raises(TimeoutError, match="Edge CDP startup timed out"):
        read_edge_page(edge, target, profile)
    if (profile / "DevToolsActivePort").exists():
        port, _ = original_endpoint(profile)
        assert not browser_cdp._port_open(port)
