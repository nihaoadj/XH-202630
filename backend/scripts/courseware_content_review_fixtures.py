"""Generate synthetic frozen candidates and real offline workflow HTML artifacts."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.courseware.content_review import json_hash

GROUPS = ("review", "practice_code", "practice_noncode")
DEFECTS = ("factual_conflict", "scope_exaggeration", "misleading_guidance", "mixed_facts")


def frozen_manifest():
    from tests.fakes.courseware_content_review import resource, candidate
    from app.agents.resource_workflows.interactive_courseware.source import _snapshot
    cases = []
    for group in GROUPS:
        source = _snapshot(resource(group), content_review=True)
        for index in range(12):
            values = candidate(group); defect = DEFECTS[(index-4)//2] if index >= 4 else None
            key = "learning_scope" if group == "review" else "cover_lead"
            if defect:
                target = values if group == "review" else values["practice_cover"]
                target[key] = {"factual_conflict": "错误候选：所有结果均无需依据即可确认。", "scope_exaggeration": "错误候选：覆盖全部领域并保证完全掌握。", "misleading_guidance": "错误候选：点击不存在的自动执行与自动评分按钮。", "mixed_facts": "先核对来源。错误候选：系统随后自动验证所有事实并给出正式成绩。"}[defect]
            identifier = f"{group}.{'clean' if not defect else defect}.{index+1 if not defect else (index-4)%2+1:02}"
            cases.append({"id": identifier, "group": group, "frozen_source": source, "candidate": values,
                "source_hash": json_hash(source), "candidate_hash": json_hash(values), "primary_defect": defect,
                "item_id": f"ai:{'course' if group == 'review' else 'cover'}:{key}" if defect else None,
                "critical_for_gate": bool(defect), "necessary_evidence_ids": ["course:rules"], "annotation_reviewed": False})
    body = {"schema_version": "1.0", "repeats": 3, "cases": cases}
    return {**body, "manifest_hash": json_hash(body)}


def artifact_path(directory, resource_row):
    relative = Path(resource_row["file_path"]).relative_to(Path("data/generated_resources"))
    return Path(directory) / relative


def generate_browser_fixtures(output):
    from tests.fakes.courseware_content_review import fixture_environment, make_workflow, candidate, ContentReviewGateway
    from app.models.courseware.contracts import CoursewareJobCreateRequest
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for group in GROUPS:
        with tempfile.TemporaryDirectory(prefix="content-review-fixture-") as temp:
            with fixture_environment(temp):
                values = candidate(group)
                rejected = "错误候选：系统保证完全掌握并自动执行所有操作。"
                if group == "review": values["learning_scope"] = rejected
                else: values["practice_cover"]["cover_lead"] = rejected
                workflow, source = make_workflow(temp, group, gateway=ContentReviewGateway(group, candidate_values=values))
                request = CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id])
                job = workflow.create_job(request); result = workflow.run(job.run_id)
                if result.status != "published":
                    raise ValueError(f"workflow fixture failed: {group}/{result.status}/{result.error_code}")
                resource_row = workflow.repo.get_resource_by_run(job.run_id)
                data = artifact_path(temp, resource_row).read_bytes()
                target = output / f"{group}.html"; target.write_bytes(data)
                spec = workflow.repo.get_spec_by_run(job.run_id)
                record = workflow.content_review.state(job.run_id).record
                scenes = [r["scene_json"] for r in workflow.repo.list_scenes(spec["spec_id"])]
                artifacts.append({"group": group, "path": target.name, "artifact_sha256": hashlib.sha256(data).hexdigest(),
                    "resource_id": resource_row["resource_id"], "release_id": resource_row["released_release_id"],
                    "source_hash": record.source_hash, "candidate_hash": json_hash(values), "approved_values_hash": record.value_hash, "identity": record.identity, "rejected_value": rejected,
                    "record_status": record.status, "workflow_status": result.status, "calls": len(workflow.llm_gateway.calls),
                    "scene_ids": [s["scene_id"] for s in scenes], "approved_display_values": [i.value for i in __import__("app.core.courseware.content_review.registry", fromlist=["resolve_adapter"]).resolve_adapter(workflow.repo.get_job(job.run_id)["source_snapshots"][0]).prepare(job.run_id, workflow.repo.get_job(job.run_id)["source_snapshots"][0], workflow.content_review.context(job.run_id)[4], record.approved_values).items if i.origin == "ai" and i.owner_id in {"course", "cover", "node-1"}],
                    "first_question": source.review_practice_payload["node_blocks"][0]["recall_questions"][0] if group == "review" else None})
    paths = ["backend/app/core/courseware/renderer.py", "backend/app/core/courseware/assets/runtime.js", "backend/app/models/courseware/content_review.py", "backend/app/db/courseware/repository.py", "backend/app/config.py"]
    paths += [p.relative_to(ROOT).as_posix() for directory in (ROOT/"backend/app/agents/resource_workflows/interactive_courseware", ROOT/"backend/app/core/courseware/content_review") for p in sorted(directory.rglob("*.py"))]
    manifest = {"schema_version": "1.0", "execution": "real_workflow_scripted_gateway", "quality_gate": "NOT_RUN_OFFLINE", "production_enabled": False,
        "source_files": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}, "artifacts": artifacts}
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"frontend/tests/fixtures/courseware/content_review")
    parser.add_argument("--manifest-output", type=Path, default=ROOT/"backend/tests/fixtures/courseware/content_review/manifest.json")
    args = parser.parse_args(argv)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(frozen_manifest(), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    result = generate_browser_fixtures(args.output)
    print(f"Generated {len(result['artifacts'])} real workflow fixtures; live quality NOT_RUN_OFFLINE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
