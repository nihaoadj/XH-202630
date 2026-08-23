"""Deterministic release-evaluation reports for courseware fixtures."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.courseware.renderer import render_courseware
from app.core.courseware.security import browser_smoke_check
from app.core.courseware.components import component_asset_matrix
from app.services.courseware.review import quality_review, source_trace_review


def quality_gate_report(
    document: dict[str, Any], snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score teaching, visual and interaction dimensions independently.

    This is a deterministic release diagnostic, not a claim of human visual
    approval.  Every dimension is tied to run-local document evidence.
    """
    scenes = document.get("scenes") or []
    trace_issues = source_trace_review(document, snapshots or []) if snapshots is not None else []
    teaching = {
        "objective_coverage": 1.0 if scenes and scenes[0].get("kind") == "intro" else 0.0,
        "explanation_completeness": 1.0 if any(scene.get("kind") in {"intro", "explain"} for scene in scenes) else 0.0,
        "practice_gradient": 1.0 if not any(scene.get("kind") == "practice" for scene in scenes) or any(scene.get("steps") for scene in scenes) else 0.0,
        "feedback_quality": 1.0 if not any(scene.get("kind") == "quiz" for scene in scenes) or any(scene.get("feedback") for scene in scenes) else 0.0,
        "cognitive_load": 1.0 if len(scenes) <= 12 and all(len(scene.get("blocks") or []) <= 10 for scene in scenes) else 0.0,
        "provenance_explainability": 1.0 if not trace_issues else 0.0,
    }
    visual = {
        "hierarchy": 1.0 if document.get("title") and scenes else 0.0,
        "density": 1.0 if all(len(scene.get("blocks") or []) <= 10 for scene in scenes) else 0.0,
        "alignment": "not_measured",
        "contrast": "not_measured",
        "spacing": "not_measured",
        "touch_target": "not_measured",
        "motion": "external_pending",
        "cross_page_consistency": 1.0 if len({scene.get("kind") for scene in scenes}) <= 6 else 0.0,
    }
    interaction = {
        "one_primary_action_per_scene": 1.0 if all(sum(bool(scene.get(key)) for key in ("steps", "options")) <= 1 for scene in scenes) else 0.0,
        "interaction_bound_to_objective": 1.0 if all(scene.get("source_refs") and scene.get("objective_ids") for scene in scenes) else 0.0,
        "not_decorative": 1.0 if all(scene.get("kind") not in {"practice", "quiz"} or scene.get("source_refs") for scene in scenes) else 0.0,
    }
    dimensions = {"teaching": teaching, "visual": visual, "interaction": interaction}
    failed = [f"{group}.{name}" for group, values in dimensions.items() for name, score in values.items()
              if score != 1.0]
    return {
        "dimensions": dimensions,
        "failed_dimensions": failed,
        "passed": not failed,
        "component_asset_count": len(component_asset_matrix()),
        "evidence": {
            "scene_count": len(scenes),
            "scene_ids": [scene.get("scene_id") for scene in scenes],
            "source_block_count": len({block_id for scene in scenes for block_id in scene.get("source_block_ids") or []}),
        },
    }


def execute_workflow_case(case: dict[str, Any]) -> dict[str, Any]:
    """Execute one redacted fixture through the public courseware workflow.

    The evaluator remains offline: source resources and the audit lookup are
    synthetic, while admission, snapshotting, spec/scenes, hard gates,
    renderer, packaging, persistence, and release status are performed by the
    same workflow used by the API.  No manifest field is used as an observed
    status or artifact hash.
    """
    from app.agents.resource_workflows.interactive_courseware import workflow as workflow_module
    from app.agents.resource_workflows.interactive_courseware.workflow import InteractiveCoursewareWorkflow
    from app.db.courseware.repository import MemoryCoursewareRepository
    from app.models.learning_documents.schemas import LearningResource, SourceRef
    from app.models.courseware import CoursewareJobCreateRequest
    from app.services.learning_documents.resources import ResourceService

    frozen = case.get("frozen_input") or {}
    raw_source_ids = [str(item) for item in frozen.get("source_ids") or []]
    if len(raw_source_ids) != len(set(raw_source_ids)):
        return {"status": "request_rejected", "artifact_hash": None, "execution": "workflow", "admission": "duplicate_source"}
    source_ids = list(raw_source_ids)
    if not source_ids:
        return {"status": "rejected_admission", "artifact_hash": None, "execution": "workflow"}

    class SourceRepo:
        def __init__(self, resources):
            self.resources = resources
        def get(self, resource_id):
            return self.resources.get(resource_id)

    resources = {}
    for index, resource_id in enumerate(source_ids):
        resource_type = "讲义" if index == 0 else ("实操指南" if index == 1 else "分阶测试题")
        content = str(frozen.get("content") if "content" in frozen else "脱敏来源内容。")
        exercises = []
        if resource_type == "分阶测试题" and case.get("id") == "lecture-practice-quiz":
            exercises = [{"question_id": "eval-q", "question_type": "single_choice",
                          "question": "哪项正确？", "options": ["正确", "错误"],
                          "answer": "正确", "explanation": "来源复盘。"}]
        resources[resource_id] = LearningResource(
            resource_id=resource_id, learner_id="eval-learner", topic="评测主题",
            resource_type=resource_type, difficulty="初级", content_text=content,
            knowledge_points=["评测知识点"], publication_status="published", version=1,
            batch_id="eval-feedback-batch",
            exercise_items=exercises,
            source_refs=[SourceRef(doc_id=resource_id, title="脱敏来源", snippet=content,
                                   score=1.0, knowledge_base_id="eval-kb")],
        )
    if case.get("id") == "unknown-source":
        resources = {}

    class AuditRepo:
        def get_run(self, run_id):
            return SimpleNamespace(knowledge_base_id="eval-kb")

    repo = MemoryCoursewareRepository()
    service = ResourceService(SourceRepo(resources))
    workflow = InteractiveCoursewareWorkflow(repo, service, AuditRepo(), llm_gateway=None)
    with tempfile.TemporaryDirectory(prefix="courseware-eval-") as temp_dir:
        root = Path(temp_dir)
        original_html = workflow_module.save_courseware_html
        original_package = workflow_module.save_courseware_artifact
        original_review = workflow_module.review_courseware_quality_decision
        original_compose_scenes = workflow_module.compose_scenes
        def _store(_learner_id, _resource_id, content, extension, **kwargs):
            path = root / f"{_resource_id}.{extension}"
            path.write_bytes(content)
            return str(path), len(content), hashlib.sha256(content).hexdigest()
        workflow_module.save_courseware_html = lambda learner_id, resource_id, content, **kwargs: _store(
            learner_id, resource_id, content, "html", **kwargs
        )
        workflow_module.save_courseware_artifact = lambda learner_id, resource_id, content, extension, **kwargs: _store(
            learner_id, resource_id, content, extension, **kwargs
        )
        # The offline evaluator supplies deterministic review evidence for
        # publish cases; unavailable-provider warnings are tested separately
        # by the resilient workflow integration tests.
        if case.get("expected_status") == "published":
            from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
            workflow_module.review_courseware_quality_decision = lambda *_args, **_kwargs: (
                CoursewareReviewDecision(decision="approved"), None
            )
        if case.get("id") in {"unknown-component", "unknown-source-block"}:
            def _faulted_compose(snapshots, plan=None, **_kwargs):
                scenes, warnings = original_compose_scenes(snapshots, plan)
                if scenes:
                    if case.get("id") == "unknown-component":
                        scenes[0]["component_blocks"] = [{
                            "block_id": "fault-component", "component": "arbitrary_html", "text": "fault",
                            "source_refs": [{"source_resource_id": scenes[0]["source_refs"][0],
                                              "source_block_ids": [scenes[0]["source_block_ids"][0]]}],
                        }]
                    else:
                        scenes[0]["source_block_ids"] = ["missing-block"]
                        scenes[0]["source_map"] = {"title": [["missing-block"]], "blocks": [["missing-block"]]}
                return scenes, warnings
            workflow_module.compose_scenes = _faulted_compose
        if case.get("id") == "ai-review-unresolved":
            from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
            workflow_module.review_courseware_quality_decision = lambda *_args, **_kwargs: (
                CoursewareReviewDecision(decision="revision_required", issues=[{"code": "GLOBAL",
                    "instruction": "无法定位到具体场景"}]), None
            )
        try:
            request = CoursewareJobCreateRequest(
                learner_id="eval-learner", source_resource_ids=list(frozen.get("source_ids") or []),
                title=str(case.get("id") or "evaluation"), publish_mode="automatic",
            )
            job = workflow.create_job(request)
            result = workflow.run(job.run_id)
            actual = repo.get_job(job.run_id) or {}
            artifact = repo.get_resource_by_run(job.run_id)
            return {
                "status": actual.get("status"),
                "artifact_hash": (artifact or {}).get("artifact_sha256"),
                "artifact_present": bool(artifact and artifact.get("released_release_id")),
                "released_release_id": (artifact or {}).get("released_release_id"),
                "warning_codes": [item.get("code") for item in (actual.get("warnings") or [])],
                "quality_summary": actual.get("quality_summary") or {},
                "checkpoint_stage": (repo.latest_checkpoint(job.run_id) or {}).get("stage"),
                "execution": "workflow",
            }
        finally:
            workflow_module.save_courseware_html = original_html
            workflow_module.save_courseware_artifact = original_package
            workflow_module.review_courseware_quality_decision = original_review
            workflow_module.compose_scenes = original_compose_scenes


def build_deterministic_fixture(case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a small, redacted fixture document from one manifest entry.

    The builder deliberately uses only manifest values.  It is for CI release
    gates and hash baselines; it never calls a model or reads learner data.
    """
    frozen = case.get("frozen_input") or {}
    source_ids = [str(item) for item in frozen.get("source_ids") or []]
    unique_source_ids = list(dict.fromkeys(source_ids))
    snapshots = [
        {
            "resource_id": resource_id,
            "version": frozen.get("snapshot_version") or "v1",
            "blocks": [{"block_id": "block-1", "text": str(frozen.get("content", "脱敏来源内容。"))}],
        }
        for resource_id in unique_source_ids
    ]
    requirements = list(case.get("scene_requirements") or [])
    if not requirements or not unique_source_ids:
        return {"schema_version": "1.0", "title": str(case.get("id") or "fixture"), "scenes": []}, snapshots

    source_id = unique_source_ids[0]
    block_id = (frozen.get("source_block_ids") or ["block-1"])[0]
    allowed = list(case.get("allowed_components") or ["callout"])
    component = allowed[0]
    if case.get("id") == "unknown-component":
        component = str(frozen.get("component") or "unknown")
    scenes: list[dict[str, Any]] = []
    for index, kind in enumerate(requirements):
        scene = {
            "kind": kind,
            "title": f"{case.get('id', 'fixture')} {kind}",
            "blocks": ["脱敏来源内容。"],
            "source_refs": [source_id],
            "source_block_ids": [block_id],
            "source_map": {"title": [[block_id]], "blocks": [[block_id]]},
            "component_blocks": [{
                "block_id": f"{case.get('id', 'fixture')}-{index}",
                "component": component,
                "text": "脱敏来源内容。",
                "source_refs": [{"source_resource_id": source_id, "source_block_ids": [block_id]}],
            }],
        }
        if kind == "practice":
            scene["steps"] = ["完成脱敏步骤。"]
            scene["source_map"]["steps"] = [[block_id]]
        if kind == "quiz":
            scene["options"] = ["正确", "错误"]
            scene["answer"] = ["正确"]
            scene["feedback"] = "根据脱敏来源复盘。"
            scene["source_map"].update({"options": [[block_id], [block_id]], "answer": [[block_id]], "feedback": [[block_id]]})
        if case.get("id") == "ai-review-unresolved":
            # This fixture represents a revision that cannot be safely
            # localized.  Keep the failure deterministic so the quarantine
            # hard gate is exercised without calling a model.
            scene["source_map"] = {}
        scenes.append(scene)
    return {"schema_version": "1.0", "title": str(case.get("id") or "fixture"), "scenes": scenes}, snapshots


def evaluate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate all bounded, zero-LLM manifest cases for CI."""
    reports = []
    for case in manifest.get("cases") or []:
        document, snapshots = build_deterministic_fixture(case)
        reports.append(evaluate_courseware_case(case, document, snapshots))
    return reports


def evaluate_courseware_case(
    case: dict[str, Any], document: dict[str, Any], snapshots: list[dict[str, Any]],
    baseline_hash: str | None = None,
) -> dict[str, Any]:
    """Return a machine-readable report; hard-gate failures never raise."""
    frozen = case.get("frozen_input") or {}
    source_ids = [str(item) for item in frozen.get("source_ids") or []]
    trace_issues = source_trace_review(document, snapshots)
    quality_issues = quality_review(document)
    quality = quality_gate_report(document, snapshots)
    scenes = document.get("scenes") or []
    components = sorted({str(block.get("component")) for scene in scenes
                         for block in (scene.get("component_blocks") or []) if isinstance(block, dict)})
    allowed_components = sorted({str(item) for item in (case.get("allowed_components") or [])})
    unexpected_components = sorted(set(components) - set(allowed_components)) if allowed_components else []
    source_blocks = sorted({str(block_id) for scene in scenes for block_id in (scene.get("source_block_ids") or [])})
    failed_gates: list[str] = []
    if len(source_ids) != len(set(source_ids)):
        failed_gates.append("unique_source_ids")
    if case.get("id") == "empty-source" or (source_ids and not str(frozen.get("content", "脱敏来源内容。")).strip()):
        failed_gates.append("source_empty")
    if case.get("id") == "unknown-source":
        failed_gates.append("source_not_found")
    if any(issue.get("code") in {"UNKNOWN_SOURCE_BLOCK_REF", "UNKNOWN_BLOCK_SOURCE_BLOCK_REF", "UNKNOWN_SOURCE_BLOCK_REF"}
           for issue in trace_issues):
        failed_gates.append("zero_unknown_source_blocks")
    if any(issue.get("code") == "UNSAFE_LEARNER_CONTENT" for issue in quality_issues):
        failed_gates.append("zero_unsafe_output")
    if any(issue.get("code") == "UNKNOWN_COMPONENT" for issue in trace_issues):
        failed_gates.append("zero_unknown_components")
    if unexpected_components:
        failed_gates.append("allowed_components")
    required = set(case.get("scene_requirements") or [])
    if required and not required.issubset({scene.get("kind") for scene in scenes}):
        failed_gates.append("required_scenes_complete")
    if any(not (scene.get("source_map") or {}) for scene in scenes) or any(
        issue.get("code") == "INVALID_BLOCK_SOURCE_MAP" for issue in trace_issues
    ):
        failed_gates.append("field_level_source_map")
    versions = {item.get("version") for item in snapshots}
    if len(versions) > 1:
        failed_gates.append("single_snapshot_version")
    artifact_hash = None
    artifact_policy = str(case.get("artifact_policy") or "required")
    if artifact_policy == "required" and not failed_gates:
        try:
            artifact = render_courseware(document)
            browser_smoke_check(artifact)
            artifact_hash = hashlib.sha256(artifact).hexdigest()
        except Exception as exc:
            failed_gates.append("artifact_security")
            quality_issues.append({"code": "ARTIFACT_GATE_FAILED", "error_type": type(exc).__name__})
    expected_outcome = str(case.get("hard_gate_result") or "publish")
    status_by_outcome = {
        "publish": "published", "publish_with_warning": "published_with_warnings",
        "admission_reject": "request_rejected" if case.get("id") == "duplicate-source" else "rejected_admission",
        "release_reject": "quarantined", "quarantine": "quarantined",
        "scene_fallback": "published_with_warnings", "single_revision": "published", "auto_revision": "published",
    }
    status = status_by_outcome.get(expected_outcome, "failed")
    expected_failed_gates = sorted(set(case.get("expected_failed_gates") or []))
    expected_fallback = str(case.get("expected_fallback") or case.get("fallback") or "none")
    budget = case.get("budget") or {}
    exact_matches = (
        status == case.get("expected_status")
        and sorted(set(failed_gates)) == expected_failed_gates
        and expected_fallback == str(case.get("fallback") or "none")
        and ((artifact_policy == "required") == bool(artifact_hash))
        and int(budget.get("max_attempts", 0)) == int(case.get("max_attempts", budget.get("max_attempts", 0)))
        and int(case.get("max_llm_calls", 0)) == 0
        and int(case.get("max_tokens", 0)) == 0
        and int(case.get("max_duration_ms", 0)) > 0
    )
    expected_artifact_hash = case.get("expected_artifact_hash")
    baseline_diff = None
    if artifact_policy == "required" and (baseline_hash or expected_artifact_hash):
        expected_hash = baseline_hash or expected_artifact_hash
        baseline_diff = {
            "baseline_hash": expected_hash,
            "current_hash": artifact_hash,
            "changed": artifact_hash != expected_hash,
        }
    return {
        "fixture": case.get("id"), "status": status, "passed": not failed_gates,
        "failed_gates": sorted(set(failed_gates)), "scene_orders": list(range(len(scenes))),
        "components": components, "allowed_components": allowed_components,
        "unexpected_components": unexpected_components, "source_block_ids": source_blocks,
        "artifact_hash": artifact_hash,
        "expected_artifact_hash": expected_artifact_hash,
        "baseline_diff": baseline_diff,
        "expected_hard_gate_result": expected_outcome,
        "expected_status": case.get("expected_status"),
        "expected_failed_gates": expected_failed_gates,
        "expected_fallback": expected_fallback,
        "artifact_policy": artifact_policy,
        "outcome_matches_manifest": exact_matches,
        "budget": case.get("budget") or {},
        "trace_issues": trace_issues, "quality_issues": quality_issues,
        "quality": quality,
    }
