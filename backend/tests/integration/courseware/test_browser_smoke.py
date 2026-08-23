"""Run a generated artifact in a real headless Edge instance when available."""

from pathlib import Path
import shutil
import subprocess

import pytest

from app.core.courseware.renderer import render_courseware
from app.core.courseware.runtime import SCRIPT


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


def _edge() -> str | None:
    return next((candidate for candidate in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
    ) if candidate and Path(candidate).exists()), None)


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
    profile = tmp_path / "edge-profile"
    result = subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--virtual-time-budget=1000",
         f"--user-data-dir={profile}", "--dump-dom", target.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr[-1000:]
    assert "第 1 /" in result.stdout
