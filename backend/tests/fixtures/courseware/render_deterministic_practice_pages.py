"""Render the JSON-owned pages of a V3 practice guide for local inspection.

This driver deliberately uses the production snapshot, storyboard composition,
and renderer. It does not call a model and it does not project the legacy
Markdown field into learner-facing pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.agents.resource_workflows.interactive_courseware.validators import validate_scene_shape
from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.core.courseware.design_system.visual_styles import (
    PRACTICE_STYLE_OPTIONS,
    practice_style_family,
    select_practice_step_styles,
    select_practice_visual_style,
    visual_style_for_scene,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import PracticeGuidePackageV3
from app.services.courseware.composition import compose_scenes
from app.services.courseware.source import _snapshot


DIRECT_VARIANTS = {"prepare", "code", "guided", "verify", "reflect"}


def _payload_hash(payload: dict) -> str:
    canonical = PracticeGuidePackageV3.model_validate(payload).model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_scenes(fixture: Path) -> tuple[dict, list[dict], list[dict], list[dict]]:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    payload = dict(data)
    payload["payload_hash"] = _payload_hash(payload)
    source = LearningResource(
        resource_id="deterministic-practice-preview",
        resource_type="实操指南",
        difficulty="初级",
        content_text="# 结构化实操指南（JSON 预览）",
        knowledge_points=["结构化课件渲染"],
        source_refs=[],
        practice_guide_payload=payload,
        practice_guide_payload_hash=payload["payload_hash"],
    )
    snapshot = _snapshot(source)
    design = build_learning_design([snapshot])
    scenes, warnings = compose_scenes([snapshot], learning_design=design)
    direct_scenes = [
        scene
        for scene in scenes
        if scene.get("practice_json_schema_version") == "3.0"
        and str(scene.get("practice_variant") or "") in DIRECT_VARIANTS
    ]
    if not direct_scenes:
        raise RuntimeError("fixture 没有生成 JSON-owned 实操页面")
    for scene in direct_scenes:
        errors = validate_scene_shape(scene)
        if errors:
            raise ValueError(f"页面 {scene.get('scene_id')} 未通过结构校验: {errors}")
    return data, scenes, direct_scenes, warnings


def _write_catalog(output_dir: Path, title: str, rows: list[dict]) -> None:
    links = "".join(
        f'<li><a href="{row["file"]}">{row["index"]:02d} · {row["title"]}</a>'
        f' <code>{row["variant"]}</code></li>'
        for row in rows
    )
    catalog = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>JSON 确定性页面预览</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 24px;line-height:1.7}"
        "a{color:#1456d9}code{color:#667085;margin-left:8px}</style></head><body>"
        f"<h1>{title}</h1><p>以下页面均由测试 JSON 的 V3 字段直接投影，经生产 renderer 输出。</p>"
        f"<p><a href=\"courseware-complete.html\">打开完整课件（含封面）</a> · "
        "<a href=\"courseware-complete-long-text.html\">长文本首页测试</a> · "
        f"<a href=\"courseware.html\">实操页面（{len(rows)} 页）</a> · "
        "<a href=\"style_variants/index.html\">查看全部视觉风格</a> · "
        "<a href=\"source.json\">查看输入 JSON</a> · <a href=\"manifest.json\">查看映射清单</a></p>"
        f"<ol>{links}</ol></body></html>"
    )
    (output_dir / "index.html").write_text(catalog, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).with_name("structured_practice_preview.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("deterministic_practice_pages"),
    )
    parser.add_argument(
        "--long-text-test",
        action="store_true",
        help="在完整课件封面注入长标题、长说明和长结论，验证动态文本布局",
    )
    args = parser.parse_args()
    data, all_scenes, scenes, warnings = _load_scenes(args.fixture)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    style_seed = "deterministic-practice-preview-v1"
    selected_step_styles = select_practice_step_styles(seed=style_seed)
    render_title = f"实操指南｜{data['title']}"
    complete_filename = "courseware-complete.html"
    if args.long_text_test:
        render_title = (
            "实操指南｜知识检索实操完整课件：从环境准备、文档切分、索引构建到检索验证与页面发布的全流程复现与验收"
        )
        cover = next(scene for scene in all_scenes if scene.get("page_role") == "cover")
        cover["key_question"] = (
            "这份完整实操课件将如何帮助学习者从准备运行环境开始，逐步完成文档处理、索引构建、检索验证、页面生成，"
            "并在最后通过来源、交互和可复现性检查确认整个流程确实能够独立完成？"
        )
        cover["lead"] = (
            "本页是完整流程的动态首页说明：学习者可以先了解本课件覆盖的范围、每个阶段之间的衔接关系、"
            "每一步需要观察的输入与输出，以及最终如何通过验证与复盘确认自己不仅完成了操作，而且理解了操作为什么有效。"
        )
        cover["conclusion"] = (
            "首页结论：当你能够沿着准备、执行、验证、复盘和总结的顺序完成全部页面，并能根据来源解释每一个关键判断时，"
            "本次实操才算真正完成；如果任一环节的输入、结果或证据不清晰，应返回对应步骤重新检查，而不是直接跳到结论。"
        )
        long_cover_blocks = [
            "学习概述：覆盖环境准备、依赖安装、文档切分、索引构建、检索验证和互动课件生成六个连续阶段。",
            "学习方法：先阅读每一页的目标与说明，再执行代码或操作，随后对照验证项检查结果，最后把异常与证据记录下来。",
            "完成信号：能够独立复述完整流程，说明每个步骤的输入、输出、来源依据和失败后的回退路径。",
        ]
        for block, text in zip(cover.get("component_blocks") or [], long_cover_blocks):
            block["text"] = text
        complete_filename = "courseware-complete-long-text.html"

    page_rows: list[dict] = []
    step_sequence_index = 0
    for index, scene in enumerate(scenes, 1):
        filename = f"{index:02d}-{scene['practice_variant']}.html"
        scene_style_sequence_index = step_sequence_index
        (args.output_dir / filename).write_bytes(
            render_courseware(
                {
                    "title": render_title,
                    "resource_name_en": "KNOWLEDGE RETRIEVAL PRACTICE GUIDE",
                    "visual_style_seed": style_seed,
                    "visual_style_sequence_index": scene_style_sequence_index,
                    "scenes": [scene],
                }
            )
        )
        page_rows.append(
            {
                "index": index,
                "file": filename,
                "scene_id": scene["scene_id"],
                "title": scene["title"],
                "variant": scene["practice_variant"],
                "visual_style_id": visual_style_for_scene(
                    scene, seed=style_seed, sequence_index=scene_style_sequence_index
                ),
                "json_subject": scene.get("practice_json_subject"),
                "component_source_paths": [
                    block.get("source_json_path")
                    for block in scene.get("component_blocks") or []
                    if block.get("source_json_path")
                ],
            }
        )
        if practice_style_family(scene) == "step":
            step_sequence_index += 1

    (args.output_dir / "courseware.html").write_bytes(
        render_courseware(
            {
                "title": render_title,
                "resource_name_en": "KNOWLEDGE RETRIEVAL PRACTICE GUIDE",
                "visual_style_seed": style_seed,
                "scenes": scenes,
            }
        )
    )
    (args.output_dir / complete_filename).write_bytes(
        render_courseware(
            {
                "title": render_title,
                "resource_name_en": "KNOWLEDGE RETRIEVAL PRACTICE GUIDE",
                "visual_style_seed": style_seed,
                "scenes": all_scenes,
            }
        )
    )
    complete_rows: list[dict] = []
    complete_step_sequence_index = 0
    for index, scene in enumerate(all_scenes, 1):
        scene_style_sequence_index = complete_step_sequence_index
        complete_rows.append(
            {
                "index": index,
                "scene_id": scene["scene_id"],
                "kind": scene.get("kind"),
                "page_role": scene.get("page_role"),
                "practice_variant": scene.get("practice_variant"),
                "title": scene.get("title"),
                "visual_style_id": visual_style_for_scene(
                    scene, seed=style_seed, sequence_index=scene_style_sequence_index
                ),
            }
        )
        if practice_style_family(scene) == "step":
            complete_step_sequence_index += 1
    (args.output_dir / "source.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "renderer": "app.core.courseware.renderer.render_courseware",
                "source_fixture": str(args.fixture.resolve().relative_to(ROOT.parent)).replace("\\", "/"),
                "schema_version": data.get("schema_version"),
                "visual_style_seed": style_seed,
                "selected_step_style_ids": list(selected_step_styles),
                "page_count": len(page_rows),
                "complete_courseware_file": complete_filename,
                "complete_page_count": len(complete_rows),
                "text_test_mode": "long_cover_text" if args.long_text_test else "default",
                "warnings": warnings,
                "pages": page_rows,
                "complete_pages": complete_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_catalog(args.output_dir, f"实操指南｜{data['title']}", page_rows)

    style_variant_dir = args.output_dir / "style_variants"
    style_variant_dir.mkdir(parents=True, exist_ok=True)
    style_variant_rows: list[dict] = []
    for index, scene in enumerate(scenes, 1):
        family = practice_style_family(scene)
        if not family:
            continue
        for style_id in PRACTICE_STYLE_OPTIONS[family]:
            variant_seed = next(
                f"style-preview-{family}-{candidate}"
                for candidate in range(10_000)
                if select_practice_visual_style(
                    family=family, seed=f"style-preview-{family}-{candidate}"
                )
                == style_id
            )
            filename = f"{index:02d}-{style_id}.html"
            (style_variant_dir / filename).write_bytes(
                render_courseware(
                    {
                        "title": render_title,
                        "resource_name_en": "KNOWLEDGE RETRIEVAL PRACTICE GUIDE",
                        "visual_style_seed": variant_seed,
                        "scenes": [scene],
                    }
                )
            )
            style_variant_rows.append(
                {
                    "index": index,
                    "file": filename,
                    "scene_id": scene["scene_id"],
                    "title": scene["title"],
                    "variant": scene["practice_variant"],
                    "visual_style_id": style_id,
                    "json_subject": scene.get("practice_json_subject"),
                    "component_source_paths": [],
                }
            )
    variant_links = "".join(
        f'<li><a href="{row["file"]}">{row["variant"]} · {row["visual_style_id"]}</a>'
        f' <code>{row["title"]}</code></li>'
        for row in style_variant_rows
    )
    (style_variant_dir / "index.html").write_text(
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>全部视觉风格预览</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:48px auto;padding:0 24px;line-height:1.7}"
        "a{color:#1456d9}code{color:#667085;margin-left:8px}</style></head><body>"
        f"<h1>全部视觉风格预览</h1><p>共 {len(style_variant_rows)} 个注册风格；布局配方保持为 practice_workspace。</p>"
        "<p><a href=\"../index.html\">返回页面目录</a> · <a href=\"../manifest.json\">查看映射清单</a></p>"
        f"<ol>{variant_links}</ol></body></html>",
        encoding="utf-8",
    )
    manifest_path = args.output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["style_variant_count"] = len(style_variant_rows)
    manifest["style_variants"] = style_variant_rows
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output_dir.resolve())
    for row in page_rows:
        print(f"{row['index']:02d}: {row['file']} <- {row['json_subject']}")


if __name__ == "__main__":
    main()
