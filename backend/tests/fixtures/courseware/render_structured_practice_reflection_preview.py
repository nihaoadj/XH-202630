"""Generate the standalone reflection-page preview from the production renderer."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import PracticeGuidePackageV3
from app.services.courseware.composition import compose_scenes
from app.services.courseware.source import _snapshot


def main() -> None:
    fixture = Path(__file__).with_name("structured_practice_preview.json")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    payload = dict(data)
    canonical = PracticeGuidePackageV3.model_validate(payload).model_dump(mode="json")
    payload["payload_hash"] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    resource = LearningResource(
        resource_id="reflection-preview", resource_type="实操指南", difficulty="初级", content_text="# 结构化预览",
        knowledge_points=["复盘"], source_refs=[], practice_guide_payload=payload,
        practice_guide_payload_hash=payload["payload_hash"],
    )
    snapshot = _snapshot(resource)
    scenes, _ = compose_scenes([snapshot], learning_design=build_learning_design([snapshot]))
    reflection_scene = next(scene for scene in scenes if scene.get("practice_variant") == "reflect")
    preparation_scene = next(scene for scene in scenes if scene.get("practice_variant") == "prepare")
    step_scene = next(scene for scene in scenes if str(scene.get("practice_json_subject") or "").startswith("practice.steps."))
    # Use a versioned filename: the in-app file viewer may retain a same-URL
    # document in memory even after its bytes have changed.
    output = fixture.with_name("structured_practice_reflection_preview_v3.html")
    output.write_bytes(render_courseware({"title": data["title"], "scenes": [reflection_scene]}))
    preparation_output = fixture.with_name("structured_practice_preparation_preview_v11.html")
    preparation_output.write_bytes(render_courseware({"title": "准备阶段", "scenes": [preparation_scene]}))
    step_output = fixture.with_name("structured_practice_step_preview_v2.html")
    step_output.write_bytes(render_courseware({"title": "实操步骤", "scenes": [step_scene]}))
    print(output)
    print(preparation_output)
    print(step_output)


if __name__ == "__main__":
    main()
