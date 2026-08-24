"""Fault-tolerant orchestration workflow for interactive HTML courseware."""

from __future__ import annotations

import json
import hashlib
import uuid
import zipfile
from pathlib import Path
from time import monotonic
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.courseware.packaging import package_courseware
from app.core.courseware.provenance import build_provenance_graph, validate_provenance_graph
from app.core.courseware.renderer import render_courseware
from app.core.courseware.components import is_registered_component
from app.core.courseware.runtime import RENDERER_VERSION, RUNTIME_VERSION
from app.core.courseware.security import browser_smoke_check
from app.core.courseware.evaluation import quality_gate_report
from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.quality_summary import build_quality_summary
from app.core.courseware.storage import save_courseware_artifact, save_courseware_html
from app.core.storage.file_storage import load_resource_file
from app.core.storage import file_storage
from app.config import get_settings
from app.db.audit.base import BaseAuditRepository
from app.models.courseware import (
    CoursewareJobCreateRequest,
    CoursewareJobDetail,
    CoursewareJobResponse,
    CoursewareSceneStatus,
    CoursewareResourceDetail,
    CoursewareDesign,
)
from app.models.courseware.snapshots import LearnerContextSnapshot, ResourceBundleSnapshot
from app.models.shared.resource_library import ResourceLibraryItem
from app.services.learning_documents.resources import ResourceService
from app.agents.resource_workflows.interactive_courseware.planner_agent import build_courseware_spec
from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import review_courseware_quality_decision, resolve_review_targets
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
from app.agents.resource_workflows.interactive_courseware.validators import validate_scene_shape, validate_storyboard_bindings
from app.agents.resource_workflows.interactive_courseware.budget import CoursewareBudgetCoordinator
from app.services.courseware.composition import compose_scenes, default_title, source_summary, topic
from app.services.courseware.lineage import reconcile_stale_resources
from app.services.courseware.review import quality_review, source_trace_review
from app.services.courseware.source import CoursewareAdmissionError, admit_and_snapshot, content_hash, frozen_source_batch_id
from app.services.courseware.release import CandidateReleaseCoordinator


class CoursewareControlStop(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CoursewareReleaseGateError(RuntimeError):
    """A required release artifact failed validation; no pointer may switch."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class InteractiveCoursewareWorkflow:
    """Own the courseware production state machine and its persistence writes."""

    def __init__(self, repo, resource_service: ResourceService, audit_repo: BaseAuditRepository,
                 llm_gateway: Any | None = None, learner_context_provider: Any | None = None):
        self.repo = repo
        self.resource_service = resource_service
        self.audit_repo = audit_repo
        self.llm_gateway = llm_gateway
        self.learner_context_provider = learner_context_provider
        self.file_loader = load_resource_file
        self.scene_composer = compose_courseware_scene
        self.budget = CoursewareBudgetCoordinator(self.repo, get_settings)
        self.release_coordinator = CandidateReleaseCoordinator(self.repo)
        self._lease_lost_event = None

    def set_lease_lost_event(self, event) -> None:
        """Attach the executor's ownership signal for node-boundary guards."""
        self._lease_lost_event = event

    def _control_guard(self, run_id: str) -> None:
        """Stop before a model or persistence side effect when control is lost."""
        if self._lease_lost_event is not None and self._lease_lost_event.is_set():
            raise CoursewareControlStop("COURSEWARE_LEASE_LOST")
        job = self.repo.get_job(run_id) or {}
        if job.get("status") == "cancelled":
            raise CoursewareControlStop("COURSEWARE_CANCELLED")
        deadline = job.get("deadline_at")
        if deadline is not None:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline <= datetime.now(timezone.utc):
                raise CoursewareControlStop("COURSEWARE_RUN_TIMEOUT")

    def _checkpoint_completed(self, run_id: str, stage: str, *, state_json: dict[str, Any] | None = None) -> None:
        """Persist a checkpoint only after the stage's side effects completed."""
        row = self.repo.get_job(run_id)
        if row is None:
            return
        state = {
            "run_id": run_id,
            "stage": stage,
            "status": row.get("status"),
            "attempt": int(row.get("attempt") or 0),
            "source_snapshot_ids": [item.get("resource_id") for item in (row.get("source_snapshots") or [])],
        }
        if state_json:
            state.update(state_json)
        output_hash = content_hash(json.dumps(state, ensure_ascii=False, sort_keys=True, default=str))
        previous = self.repo.latest_checkpoint(run_id) or {}
        input_projection = {
            "upstream_output_hash": previous.get("output_hash"),
            "source_snapshot_hashes": [item.get("content_hash") for item in (row.get("source_snapshots") or [])],
            "workflow_version": "courseware-v1",
            "renderer_version": RENDERER_VERSION,
            "runtime_version": RUNTIME_VERSION,
            "stage": stage,
        }
        input_hash = content_hash(json.dumps(input_projection, ensure_ascii=False, sort_keys=True, default=str))
        self.repo.save_checkpoint_once({
            "checkpoint_id": f"cwc_{run_id}_{stage}_{int(row.get('attempt') or 0)}",
            "run_id": run_id, "stage": stage, "attempt": int(row.get("attempt") or 0),
            "state_json": state, "input_hash": input_hash, "output_hash": output_hash,
            "workflow_version": "courseware-v1",
        })

    def _checkpoint_valid(self, run_id: str, checkpoint: dict[str, Any] | None) -> bool:
        """Reject tampered/legacy checkpoints before selecting a resume stage."""
        if not checkpoint or checkpoint.get("workflow_version") != "courseware-v1":
            return False
        state = checkpoint.get("state_json") or {}
        expected_output = content_hash(json.dumps(state, ensure_ascii=False, sort_keys=True, default=str))
        return bool(checkpoint.get("output_hash")) and checkpoint.get("output_hash") == expected_output \
            and checkpoint.get("input_hash") != checkpoint.get("output_hash")

    def create_job(self, request: CoursewareJobCreateRequest) -> CoursewareJobResponse:
        # The old wire value is tolerated so a queued legacy request can still
        # be read, but newly created resources never wait for human release.
        request = request.model_copy(update={"publish_mode": "automatic"})
        source_fingerprints = []
        for resource_id in sorted(request.source_resource_ids):
            source = self.resource_service.get(resource_id)
            source_fingerprints.append({
                "resource_id": resource_id,
                "version": source.version if source else None,
                "content_hash": content_hash(source.content_text or "") if source else None,
            })
        request_hash = content_hash(json.dumps({
            "learner_id": request.learner_id,
            "sources": source_fingerprints,
            "title": request.title or "",
            "request_options": request.model_dump(include={"learning_goal", "expected_duration_minutes", "interaction_intensity", "visual_style_id"}),
            "publish_mode": request.publish_mode,
            "workflow_version": "courseware-v1",
        }, ensure_ascii=False, separators=(",", ":")))
        job_row = {
            "run_id": f"cw_{uuid.uuid4().hex}", "learner_id": request.learner_id,
            "knowledge_base_id": None, "title": request.title,
            "publish_mode": request.publish_mode,
            "source_resource_ids": request.source_resource_ids, "source_snapshots": [],
            "source_batch_id": frozen_source_batch_id(self.resource_service, request.source_resource_ids),
            "request_options": request.model_dump(include={"learning_goal", "expected_duration_minutes", "interaction_intensity", "visual_style_id"}, exclude_none=True),
            "request_hash": request_hash, "idempotency_key": request.idempotency_key,
            "status": "queued", "warnings": [], "attempt": 0,
            "release_policy": get_settings().courseware_release_policy,
            "deadline_at": datetime.now(timezone.utc) + timedelta(
                seconds=get_settings().courseware_total_run_timeout_seconds
            ),
        }
        run_id = job_row["run_id"]
        task_row = {
            "outbox_id": f"cwo_{run_id}", "run_id": run_id, "event_type": "courseware.run",
            "task_kind": "courseware.run", "status": "queued", "payload": {"run_id": run_id},
            "idempotency_key": f"courseware.run:{run_id}",
        }
        if hasattr(self.repo, "create_job_with_task_once"):
            row = self.repo.create_job_with_task_once(job_row, task_row)
        else:
            row = self.repo.create_job(job_row)
            self.repo.enqueue_task_once(task_row)
            self.repo.append_event_once(run_id, f"{run_id}:queued", "job", "queued")
        return self._job_response(row)

    def get_job(self, run_id: str) -> CoursewareJobResponse | None:
        row = self.repo.get_job(run_id)
        return self._job_response(row) if row else None

    def get_job_detail(self, run_id: str) -> CoursewareJobDetail | None:
        row = self.repo.get_job(run_id)
        if row is None:
            return None
        base = self._job_response(row)
        spec = self.repo.get_spec_by_run(run_id)
        scenes = self.repo.list_scenes(spec["spec_id"]) if spec else []
        resource = self.repo.get_resource_by_run(run_id)
        return CoursewareJobDetail(
            **base.model_dump(),
            scenes=[CoursewareSceneStatus(
                scene_id=item["scene_id"], scene_order=item["scene_order"], kind=item["kind"],
                title=(item.get("scene_json") or {}).get("title"), status=item["status"],
                attempt=item.get("attempt") or 0, error_code=item.get("error_code"),
                error_message=item.get("error_message"),
                input_snapshot_hash=item.get("input_snapshot_hash"), agent_version=item.get("agent_version"),
                prompt_version=item.get("prompt_version"), review_instruction=item.get("review_instruction"),
            ) for item in scenes],
            reviews=self.repo.list_reviews(run_id),
            artifacts=self.repo.list_artifacts(resource["resource_id"]) if resource else [],
            scene_revisions={item["scene_id"]: self.repo.list_scene_revisions(item["scene_id"]) for item in scenes},
        )

    def events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self.repo.list_events(run_id, after_sequence)

    def run(self, run_id: str) -> CoursewareJobResponse | None:
        """Execute or resume the durable courseware state machine."""
        try:
            return self._run_workflow(run_id)
        except CoursewareControlStop as exc:
            return self._control_result(run_id, exc.code)

    def _control_result(self, run_id: str, code: str) -> CoursewareJobResponse | None:
        status = {
            "COURSEWARE_CANCELLED": "cancelled",
            "COURSEWARE_RUN_TIMEOUT": "timed_out",
            "COURSEWARE_LEASE_LOST": "release_blocked",
        }.get(code, "release_blocked")
        row = self.repo.update_job(
            run_id, status=status, error_code=code,
            error_message="课件任务在控制边界停止，未继续发布",
        )
        self._event(run_id, "job", status, {"error_code": code})
        return self._job_response(row)

    def _run_workflow(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None:
            return None
        if job["status"] in {"approved_pending_publish", "published", "published_with_warnings"}:
            return self._job_response(job)
        self._control_guard(run_id)
        warnings: list[dict[str, str]] = list(job.get("warnings") or [])
        checkpoint = self.repo.latest_checkpoint(run_id)
        completed_stage = (checkpoint or {}).get("stage") if self._checkpoint_valid(run_id, checkpoint) else None
        stage_order = {"snapshot": 1, "design": 2, "scenes": 3, "rule_review": 4,
                       "quality_review": 5, "candidate_artifact": 6, "release": 7}
        completed_rank = stage_order.get(completed_stage, 0)
        self._stage(run_id, "admitting", attempt=int(job.get("attempt") or 0) + 1,
                    error_code=None, error_message=None)
        if job.get("source_snapshots") and job.get("knowledge_base_id"):
            snapshots = job["source_snapshots"]
            knowledge_base_id = job["knowledge_base_id"]
            self._event(run_id, "snapshotting", "reused", {"snapshot_count": len(snapshots)})
            self._checkpoint_completed(run_id, "snapshot", state_json={"knowledge_base_id": knowledge_base_id})
        else:
            try:
                self._stage(run_id, "snapshotting")
                snapshots, knowledge_base_id = admit_and_snapshot(self.resource_service, self.audit_repo, job)
                frozen_batch_id = job.get("source_batch_id") or next(
                    (str(item.get("batch_id")).strip() for item in snapshots if item.get("batch_id")), None
                )
                if not frozen_batch_id or any(item.get("batch_id") != frozen_batch_id for item in snapshots):
                    raise CoursewareAdmissionError("互动课件源资源必须来自同一反馈批次")
                self.repo.update_job(run_id, source_snapshots=snapshots, knowledge_base_id=knowledge_base_id,
                                     source_batch_id=frozen_batch_id)
                self._checkpoint_completed(run_id, "snapshot", state_json={"knowledge_base_id": knowledge_base_id})
            except CoursewareAdmissionError as exc:
                row = self.repo.update_job(run_id, status="rejected_admission", error_code=exc.code,
                                           error_message=str(exc), warnings=warnings)
                self._event(run_id, "admission", "rejected", {"error_code": exc.code})
                return self._job_response(row)
            except Exception as exc:
                row = self.repo.update_job(run_id, status="failed", error_code="COURSEWARE_SNAPSHOT_FAILED",
                                           error_message="源资源快照失败，可重试", warnings=warnings)
                self._event(run_id, "snapshotting", "failed", {"error_type": type(exc).__name__})
                return self._job_response(row)

        self._stage(run_id, "design_reviewing", source_snapshots=snapshots,
                    knowledge_base_id=knowledge_base_id)
        self._control_guard(run_id)
        learner_context = self._learner_context(job.get("learner_id"))
        learning_design = build_learning_design(snapshots, learner_context, job.get("request_options") or {})
        for usage in learning_design.resource_usage_plan:
            if usage.get("adopted") is False:
                warnings.append({
                    "code": "ASSESSMENT_SCENE_OPTIONAL" if usage.get("unused_reason") == "missing_verifiable_exercise" else "COURSEWARE_RESOURCE_UNUSED",
                    "message": f"资源 {usage['resource_id']} 未进入课程主线：{usage.get('unused_reason') or '未采用'}",
                })
        resource_bundle = [
            ResourceBundleSnapshot.from_snapshot(item).model_dump(mode="json") for item in snapshots
        ]
        recovered_spec = self.repo.get_spec_by_run(run_id) if completed_rank >= 2 else None
        if recovered_spec:
            plan, plan_warning = None, None
            spec_id = recovered_spec["spec_id"]
            spec_json = recovered_spec.get("spec_json") or {}
            if not spec_json.get("learning_design"):
                spec_json["learning_design"] = learning_design.model_dump(mode="json")
            spec_json.setdefault("resource_bundle_snapshot", resource_bundle)
            spec_json.setdefault("learner_context_snapshot", learner_context.model_dump(mode="json"))
            spec_json.setdefault("design", CoursewareDesign().model_dump(mode="json"))
            spec_json.setdefault("storyboard", learning_design.storyboard.model_dump(mode="json"))
            title = job.get("title") or spec_json.get("title") or default_title(snapshots)
            self._event(run_id, "design_reviewing", "reused", {"spec_id": spec_id})
        else:
            planner_budget = self.budget.before_call(run_id, "planner")
            if planner_budget.allowed:
                planner_options = self.llm_gateway.options_for("generator", temperature=0.0).model_copy(update={
                    "max_output_tokens": planner_budget.max_output_tokens,
                    "request_timeout_seconds": planner_budget.timeout_seconds,
                }) if self.llm_gateway else None
                plan, plan_warning = build_courseware_spec(
                    self.llm_gateway, run_id, snapshots, allowance=planner_options,
                    learning_design=learning_design,
                    request_options=job.get("request_options") or {},
                )
                self.budget.reconcile(run_id, planner_budget.call_id,
                                      actual_input=None, actual_output=None,
                                      status="completed" if plan is not None else "failed")
                if plan is not None:
                    expected_slots = [
                        (scene.kind, scene.source_resource_ids[0] if scene.source_resource_ids else None)
                        for scene in learning_design.storyboard.scenes
                        if scene.kind != "recap"
                    ]
                    actual_slots = [(scene.kind, scene.source_resource_id) for scene in plan.scenes]
                    if actual_slots != expected_slots:
                        plan = None
                        plan_warning = {
                            "code": "AI_PLAN_SLOT_MISMATCH",
                            "message": "AI 课程规格未严格填充冻结 Storyboard 槽位，已降级为确定性编排",
                        }
            else:
                plan, plan_warning = None, planner_budget.warning
            plan_warning = self._record_agent_trace(run_id, plan_warning, "courseware_spec_builder")
            title = job.get("title") or (plan.title if plan else default_title(snapshots))
            selected_design = plan.design if plan and plan.design else CoursewareDesign()
            spec_json = {
                "schema_version": "1.0", "title": title,
                "learning_design": learning_design.model_dump(mode="json"),
                "storyboard": learning_design.storyboard.model_dump(mode="json"),
                "resource_bundle_snapshot": resource_bundle,
                "learner_context_snapshot": learner_context.model_dump(mode="json"),
                "design": selected_design.model_dump(mode="json"),
                "scenes": ([item.model_dump(mode="json") for item in plan.scenes] if plan else [
                    {
                        "source_resource_id": scene.source_resource_ids[0], "kind": scene.kind,
                        "title": scene.scene_id, "learning_objective": scene.interaction_purpose,
                        "source_block_ids": list(scene.source_block_ids), "required": scene.required,
                    }
                    for scene in learning_design.storyboard.scenes
                    if scene.kind != "recap" and scene.source_resource_ids
                ]),
            }
            spec_id = f"cws_{run_id}"
            self.repo.save_spec({
                "spec_id": spec_id, "run_id": run_id, "schema_version": "1.0",
                "prompt_version": "ai-v1" if plan else "deterministic-v1", "runtime_version": RUNTIME_VERSION,
                "spec_json": spec_json, "content_hash": content_hash(json.dumps(spec_json, ensure_ascii=False, sort_keys=True)),
                "status": "approved",
            })
            self._event(run_id, "design_reviewing", "approved", {"spec_id": spec_id})
            self._checkpoint_completed(run_id, "design", state_json={"spec_id": spec_id})
        self._stage(run_id, "composing")
        recovered_scenes = self.repo.list_scenes(spec_id) if completed_rank >= 3 else []
        if recovered_scenes:
            scenes, scene_warnings = [row["scene_json"] for row in recovered_scenes], []
            self._event(run_id, "composing", "reused", {"scene_count": len(scenes)})
        else:
            scenes, scene_warnings = compose_scenes(snapshots, plan, learning_design=learning_design)
            design_payload = learning_design.model_dump(mode="json")
            for candidate in scenes:
                binding_errors = validate_storyboard_bindings(candidate, design_payload)
                if binding_errors:
                    error_code = "COURSEWARE_STORYBOARD_SLOT_MISMATCH"
                    row = self.repo.update_job(
                        run_id, status="quarantined", error_code=error_code,
                        error_message="场景未严格填充冻结 Storyboard 槽位: " + ",".join(binding_errors),
                        warnings=warnings,
                    )
                    self._event(run_id, "composing", "quarantined", {
                        "error_code": error_code,
                        "binding_errors": binding_errors,
                    })
                    return self._job_response(row)
        if plan_warning:
            warnings.append(plan_warning)
        warnings.extend(scene_warnings)
        # AI writes one closed SceneSpec at a time.  A bad response is isolated:
        # the deterministic scene remains publishable and the warning is surfaced
        # in the job rather than discarding the entire course.
        sources_by_id = {item["resource_id"]: item for item in snapshots}
        def compose_one(index: int, scene: dict[str, Any]):
            scene_id = f"{spec_id}_scene_{index + 1}"
            contract_errors = validate_scene_shape(scene)
            if contract_errors:
                return index, None, {
                    "code": "COURSEWARE_SCENE_CONTRACT_INVALID",
                    "message": f"场景 {scene_id} 未通过确定性结构校验：{','.join(contract_errors)}",
                }
            source_id = next(iter(scene.get("source_refs") or []), None)
            source = sources_by_id.get(source_id) if source_id else None
            if source is None or scene.get("kind") == "recap":
                return index, scene, None
            self._control_guard(run_id)
            scene_budget = self.budget.before_call(run_id, "scene")
            if not scene_budget.allowed:
                return index, scene, scene_budget.warning
            try:
                scene_options = self.llm_gateway.options_for("generator", temperature=0.0).model_copy(update={
                    "max_output_tokens": scene_budget.max_output_tokens,
                    "request_timeout_seconds": scene_budget.timeout_seconds,
                }) if self.llm_gateway else None
                if self.llm_gateway:
                    enhanced, scene_warning = self.scene_composer(
                        self.llm_gateway, run_id, scene_id, scene, source, allowance=scene_options,
                    )
                else:
                    enhanced, scene_warning = self.scene_composer(
                        self.llm_gateway, run_id, scene_id, scene, source,
                    )
                self.budget.reconcile(run_id, scene_budget.call_id,
                                      status="completed" if enhanced is not None else "failed")
                self._control_guard(run_id)
                return index, enhanced or scene, scene_warning
            except CoursewareControlStop:
                raise
            except Exception:
                # This is intentionally broad at the task boundary: one broken
                # provider adapter must never discard unrelated approved scenes.
                return index, scene, {"code": "AI_SCENE_FALLBACK", "message": f"场景 {scene_id} 调用异常，已保留确定性版本"}

        enhanced_scenes: list[dict[str, Any] | None] = [None] * len(scenes)
        scene_hard_gate_code: str | None = None
        ai_enabled = courseware_ai_available(self.llm_gateway)
        if recovered_scenes:
            results = [(index, scene, None) for index, scene in enumerate(scenes)]
            ai_enabled = any((row.get("agent_version") or "").startswith("ai") for row in recovered_scenes)
        elif ai_enabled and len(scenes) > 1:
            with ThreadPoolExecutor(max_workers=min(2, len(scenes)), thread_name_prefix="courseware-scene") as executor:
                results = list(executor.map(lambda item: compose_one(*item), enumerate(scenes)))
        else:
            results = [compose_one(index, scene) for index, scene in enumerate(scenes)]
        for index, resolved_scene, scene_warning in results:
            scene_warning = self._record_agent_trace(run_id, scene_warning, "courseware_scene_composer",
                                                      f"{spec_id}_scene_{index + 1}")
            if scene_warning:
                warnings.append(scene_warning)
                if scene_warning.get("code") in {"AI_SCENE_UNKNOWN_COMPONENT", "AI_SCENE_UNKNOWN_SOURCE_BLOCK"}:
                    scene_hard_gate_code = scene_warning["code"]
            base_scene = scenes[index]
            slot = list(learning_design.storyboard.scenes)[index] if index < len(learning_design.storyboard.scenes) else None
            if resolved_scene is not None:
                # Model prose may enrich a slot, but cannot mutate frozen
                # objective/source/component bindings.
                resolved_scene = {
                    **resolved_scene,
                    "scene_id": base_scene.get("scene_id") or (slot.scene_id if slot else None),
                    "objective_ids": list(base_scene.get("objective_ids") or (slot.objective_ids if slot else [])),
                    "allowed_component_ids": list(base_scene.get("allowed_component_ids") or (slot.allowed_component_ids if slot else [])),
                    "source_refs": list(base_scene.get("source_refs") or []),
                    "source_block_ids": list(base_scene.get("source_block_ids") or []),
                }
            enhanced_scenes[index] = resolved_scene
        scenes = [scene for scene in enhanced_scenes if scene is not None]
        if scene_hard_gate_code:
            row = self.repo.update_job(
                run_id, status="quarantined", error_code=scene_hard_gate_code,
                error_message="AI 场景契约引用了未注册组件或未冻结来源块，未发布", warnings=warnings,
            )
            self._event(run_id, "composing", "quarantined", {"error_code": scene_hard_gate_code})
            return self._job_response(row)
        for index, scene in enumerate(scenes):
            scene_id = f"{spec_id}_scene_{index + 1}"
            scene_hash = content_hash(json.dumps(scene, ensure_ascii=False, sort_keys=True))
            existing_scene = self.repo.get_scene(scene_id)
            if existing_scene and existing_scene["status"] == "approved" and existing_scene["content_hash"] == scene_hash:
                self._event(run_id, "composing", "scene_reused", {"scene_order": index}, scene_id)
                continue
            self.repo.upsert_scene({
                "scene_id": scene_id, "spec_id": spec_id, "scene_order": index,
                "kind": scene["kind"], "scene_json": scene,
                "content_hash": scene_hash,
                "status": "approved", "attempt": int((existing_scene or {}).get("attempt") or 0) + 1,
                "input_snapshot_hash": content_hash(json.dumps({
                    "spec": spec_id, "source_refs": scene.get("source_refs") or [],
                    "source_block_ids": scene.get("source_block_ids") or [],
                    "snapshots": [item.get("content_hash") for item in snapshots
                                  if item["resource_id"] in (scene.get("source_refs") or [])],
                }, ensure_ascii=False, sort_keys=True)),
                "agent_version": "ai-v1" if ai_enabled else "deterministic-v1",
                "prompt_version": "ai-v1" if ai_enabled else "deterministic-v1",
                "approved_at": datetime.now(timezone.utc),
                "error_code": None, "error_message": None,
            })
            self._event(run_id, "composing", "scene_approved", {"scene_order": index}, scene_id)
        self._checkpoint_completed(run_id, "scenes", state_json={
            "spec_id": spec_id,
            "scene_ids": [f"{spec_id}_scene_{index + 1}" for index in range(len(scenes))],
        })
        if not scenes:
            row = self.repo.update_job(run_id, status="failed", error_code="COURSEWARE_NO_RENDERABLE_SCENES",
                                       error_message="没有可渲染的课件场景，可在修复源资源后重试", warnings=warnings)
            self._event(run_id, "composing", "failed", {"error_code": "COURSEWARE_NO_RENDERABLE_SCENES"})
            return self._job_response(row)
        candidate = None
        try:
            spec_record = self.repo.get_spec_by_run(run_id) or {}
            document = {
                "schema_version": "1.0", "title": title, "scenes": scenes,
                "design": (spec_record.get("spec_json") or {}).get("design") or CoursewareDesign().model_dump(mode="json"),
            }
            self._stage(run_id, "trace_reviewing", warnings=warnings)
            trace_issues = source_trace_review(document, snapshots)
            self._save_review(run_id, "source_trace", "approved" if not trace_issues else "rejected", trace_issues)
            self._checkpoint_completed(run_id, "rule_review", state_json={"review": "source_trace"})
            if trace_issues:
                row = self.repo.update_job(
                    run_id, status="quarantined", error_code=str(trace_issues[0].get("code") or "COURSEWARE_SOURCE_TRACE_FAILED"),
                    error_message="课件来源追踪审核未通过，candidate 未创建", warnings=warnings,
                )
                self._event(run_id, "source_trace", "quarantined", {"error_code": row.get("error_code")})
                return self._job_response(row)
            self._stage(run_id, "quality_reviewing")
            quality_issues = quality_review(document)
            self._save_review(run_id, "teaching_quality", "approved" if not quality_issues else "rejected", quality_issues)
            self._checkpoint_completed(run_id, "quality_review", state_json={"review": "teaching_quality"})
            if quality_issues:
                row = self.repo.update_job(
                    run_id, status="quarantined", error_code=str(quality_issues[0].get("code") or "COURSEWARE_QUALITY_GATE_FAILED"),
                    error_message="课件教学质量审核未通过，candidate 未创建", warnings=warnings,
                )
                self._event(run_id, "quality_review", "quarantined", {"error_code": row.get("error_code")})
                return self._job_response(row)
            deterministic_document = self._deterministic_document(title, snapshots, learning_design)
            self._control_guard(run_id)
            document, auto_review_warning = self._auto_review_and_revise(
                run_id, job, self.repo.get_spec_by_run(run_id) or {"spec_id": spec_id}, document, snapshots,
                deterministic_document=deterministic_document,
            )
            if auto_review_warning:
                warnings.append(auto_review_warning)
            if document is None:
                unavailable_code = next(
                    (warning["code"] for warning in warnings
                     if warning.get("code", "").startswith("AI_QUALITY_REVIEW_")),
                    "COURSEWARE_AUTO_REVIEW_UNRESOLVED",
                )
                row = self.repo.update_job(
                    run_id, status="quarantined", error_code=unavailable_code,
                    error_message="AI 自动审核未能在允许的修订次数内通过；课件未发布", warnings=warnings,
                )
                self._event(run_id, "auto_revising", "quarantined")
                return self._job_response(row)
            # The deterministic fallback is the candidate that will be
            # rendered. Re-run both hard gates against it so an unavailable AI
            # review cannot accidentally preserve an invalid AI candidate.
            if auto_review_warning and auto_review_warning.get("discarded_candidate"):
                fallback_issues = source_trace_review(document, snapshots) + quality_review(document)
                self._event(run_id, "deterministic_fallback",
                            "approved" if not fallback_issues else "rejected",
                            {"issue_count": len(fallback_issues), "fallback_version": "deterministic-v1"})
                if fallback_issues:
                    row = self.repo.update_job(
                        run_id, status="quarantined", error_code="COURSEWARE_DETERMINISTIC_FALLBACK_REJECTED",
                        error_message="确定性降级产物未通过来源或教学硬门", warnings=warnings,
                    )
                    self._event(run_id, "quality_review", "rejected", {
                        "error_code": "COURSEWARE_DETERMINISTIC_FALLBACK_REJECTED",
                    })
                    return self._job_response(row)
            provenance_graph = build_provenance_graph(document, snapshots)
            provenance_issues = validate_provenance_graph(provenance_graph)
            unknown_components = [str(block.get("component")) for scene in document.get("scenes", [])
                                  for block in (scene.get("component_blocks") or [])
                                  if isinstance(block, dict) and not is_registered_component(
                                      block.get("component"), str(block.get("schema_version") or "1.0"))]
            if unknown_components:
                provenance_issues.append({"code": "PROVENANCE_UNKNOWN_COMPONENT",
                                          "message": "课件包含未注册互动组件"})
            if provenance_issues:
                row = self.repo.update_job(
                    run_id, status="quarantined", error_code=provenance_issues[0]["code"],
                    error_message="课件字段级来源图未达到 100% 覆盖，未发布", warnings=warnings,
                )
                self._event(run_id, "provenance", "rejected", {
                    "errors": provenance_issues, "root_hash": provenance_graph.root_hash,
                })
                return self._job_response(row)
            self._control_guard(run_id)
            self._stage(run_id, "rendering")
            artifact = render_courseware(document)
            self._stage(run_id, "validating")
            browser_smoke_check(artifact)
            quality = quality_gate_report(document, snapshots)
            measured_failures = [item for item in quality.get("failed_dimensions", [])
                                 if not item.startswith("visual.")]
            if measured_failures:
                raise CoursewareReleaseGateError("COURSEWARE_QUALITY_GATE_FAILED", ";".join(measured_failures))
            self._control_guard(run_id)
            existing_resource = self.repo.get_resource_by_run(run_id)
            resource_id = existing_resource["resource_id"] if existing_resource else f"cwr_{uuid.uuid4().hex}"
            candidate = self.release_coordinator.freeze(
                run_id=run_id, resource_id=resource_id, release_policy=job.get("release_policy") or "resilient",
                snapshots=snapshots, scenes=self.repo.list_scenes(spec_id),
                provenance=provenance_graph.as_manifest(),
                idempotency_key=(f"{job.get('idempotency_key')}:attempt:{int(job.get('attempt') or 0)}"
                                 if job.get("idempotency_key") else None),
            )
            release_id = candidate["release_id"]
            # The release-scoped runtime context is only known after the
            # immutable candidate is frozen; render once more so offline
            # events cannot be attributed to another release.
            document["event_context"] = {"resource_id": resource_id, "release_id": release_id}
            artifact = render_courseware(document)
            browser_smoke_check(artifact)
            quality = quality_gate_report(document, snapshots)
            if any(not item.startswith("visual.") for item in quality.get("failed_dimensions", [])):
                raise CoursewareReleaseGateError("COURSEWARE_QUALITY_GATE_FAILED", "重发布质量门失败")
            file_path, file_size, artifact_sha = save_courseware_html(
                job["learner_id"], resource_id, artifact, release_id=release_id
            )
            resource_topic = topic(snapshots)
            links = [
                {
                    "link_id": f"csl_{resource_id}_{index}", "courseware_resource_id": resource_id,
                    "source_resource_id": source["resource_id"], "source_run_id": source.get("run_id"),
                    "source_version": source["version"], "source_content_hash": source["content_hash"],
                    "source_role": source["role"],
                    "source_snapshot": json.dumps(source, ensure_ascii=False, sort_keys=True),
                }
                for index, source in enumerate(snapshots)
            ]
            usage_by_resource = {
                item["resource_id"]: item for item in (learning_design.resource_usage_plan if learning_design else ())
            }
            self.repo.save_resource({
                "resource_id": resource_id, "resource_family_id": resource_id, "run_id": run_id,
                "batch_id": job.get("source_batch_id"),
                "learner_id": job["learner_id"], "knowledge_base_id": knowledge_base_id,
                "title": title, "topic": resource_topic,
                "status": "building", "version": 1,
                "file_path": file_path, "file_size": file_size, "artifact_sha256": artifact_sha,
                "renderer_version": RENDERER_VERSION, "runtime_version": RUNTIME_VERSION,
                "source_summary": [source_summary(item, usage_by_resource.get(item["resource_id"])) for item in snapshots], "warnings": warnings,
            }, links)
            self.repo.save_artifact({
                "artifact_id": f"cwa_{release_id}_html", "release_id": release_id,
                "courseware_resource_id": resource_id,
                "artifact_format": "html", "file_path": file_path, "mime_type": "text/html",
                "file_size": file_size, "sha256": artifact_sha,
                "required": 1, "artifact_status": "ready",
                "manifest": {
                    "entrypoint": "index.html", "security_check": "passed",
                    "source_batch_id": job.get("source_batch_id"),
                    "provenance": provenance_graph.as_manifest(),
                },
            })
            self._checkpoint_completed(run_id, "candidate_artifact", state_json={
                "resource_id": resource_id, "artifact_sha256": artifact_sha,
            })
            required_package_failed = False
            for package_format, extension in (("zip", "zip"), ("scorm", "scorm.zip"), ("xapi", "xapi.zip")):
                try:
                    package, manifest = package_courseware(
                        artifact, resource_id=resource_id, title=title, package_format=package_format,
                    )
                    package_path, package_size, package_sha = save_courseware_artifact(
                        job["learner_id"], resource_id, package, extension, release_id=release_id,
                    )
                    if package_format == "zip":
                        stored_path = Path(package_path)
                        if not stored_path.exists():
                            stored_path = (file_storage._get_resources_dir() / "courseware" / job["learner_id"]
                                           / resource_id / "releases" / release_id / stored_path.name)
                        stored_package = stored_path.read_bytes()
                        with zipfile.ZipFile(__import__("io").BytesIO(stored_package)) as archive:
                            packaged_html = archive.read("index.html")
                        if packaged_html != artifact or hashlib.sha256(packaged_html).hexdigest() != artifact_sha:
                            raise CoursewareReleaseGateError(
                                "COURSEWARE_ZIP_HTML_MISMATCH", "required ZIP 的 index.html 与 HTML 产物不一致",
                            )
                    self.repo.save_artifact({
                        "artifact_id": f"cwa_{release_id}_{package_format}", "release_id": release_id,
                        "courseware_resource_id": resource_id, "artifact_format": package_format,
                        "file_path": package_path, "mime_type": "application/zip",
                        "file_size": package_size, "sha256": package_sha, "manifest": manifest,
                        "required": 1 if package_format == "zip" else 0, "artifact_status": "ready",
                    })
                except Exception as exc:
                    if package_format == "zip":
                        required_package_failed = True
                    warnings.append({"code": f"{package_format.upper()}_PACKAGE_SKIPPED",
                                     "message": f"{package_format} 导出失败（{type(exc).__name__}）",
                                     "artifact_status": "failed_required" if package_format == "zip" else "failed_optional"})
                    if package_format == "zip":
                        raise CoursewareReleaseGateError(
                            "COURSEWARE_REQUIRED_ZIP_FAILED", "required ZIP 产物未通过写入/读取/hash 校验",
                        ) from exc
            if required_package_failed:
                raise CoursewareReleaseGateError("COURSEWARE_REQUIRED_ZIP_FAILED", "required ZIP 产物缺失")
            self._event(run_id, "validating", "approved", {"artifact_sha256": artifact_sha,
                                                              "release_id": release_id})
            state = "published_with_warnings" if warnings else "published"
            release_manifest = {
                "schema_version": "1.0", "renderer_version": RENDERER_VERSION,
                "runtime_version": RUNTIME_VERSION, "scene_set_hash": candidate["scene_set_hash"],
                "snapshot_set_hash": candidate["snapshot_set_hash"],
                "source_batch_id": job.get("source_batch_id"),
                "provenance": provenance_graph.as_manifest(),
                "artifacts": [
                    {"format": item.get("artifact_format"), "path": item.get("file_path"),
                     "mime": item.get("mime_type"), "size": item.get("file_size"),
                     "sha256": item.get("sha256"), "release_id": item.get("release_id")}
                    for item in self.repo.list_artifacts(resource_id)
                    if item.get("release_id") == release_id
                ],
            }
            released = self.release_coordinator.commit(
                candidate, resource_id=resource_id,
                resource_projection={"file_path": file_path, "file_size": file_size,
                                     "artifact_sha256": artifact_sha, "warnings": warnings},
                job_status=state, warnings=warnings,
                event_payload={"event_id": f"cwe_{release_id}", "run_id": run_id,
                               "stage": "publishing", "status": state,
                               "payload": {"resource_id": resource_id, "release_id": release_id}},
                manifest=release_manifest,
            )
            if released is None:
                raise ValueError("candidate release commit failed")
        except CoursewareControlStop as exc:
            return self._control_result(run_id, exc.code)
        except Exception as exc:
            if candidate is not None:
                self.release_coordinator.block(candidate, code=getattr(exc, "code", "COURSEWARE_RELEASE_GATE_FAILED"),
                                               message="candidate 未通过发布门，旧 release 保持不变")
            release_blocked = isinstance(exc, CoursewareReleaseGateError)
            row = self.repo.update_job(run_id, status="release_blocked" if release_blocked else "failed",
                                       error_code=getattr(exc, "code", "COURSEWARE_RENDER_FAILED"),
                                       error_message="课件渲染或发布失败，源快照已保留，可重试", warnings=warnings)
            self._event(run_id, "release_gate", "failed", {"error_type": type(exc).__name__})
            return self._job_response(row)
        state = "published_with_warnings" if warnings else "published"
        row = self.repo.get_job(run_id)
        self._checkpoint_completed(run_id, "release", state_json={"resource_id": resource_id, "status": state})
        return self._job_response(row)

    def _learner_context(self, learner_id: str | None) -> LearnerContextSnapshot:
        """Freeze only allowlisted, design-relevant profile fields at the boundary."""
        if self.learner_context_provider is None:
            return LearnerContextSnapshot()
        try:
            raw = self.learner_context_provider(learner_id)
            return raw if isinstance(raw, LearnerContextSnapshot) else LearnerContextSnapshot(**(raw or {}))
        except Exception:
            # A profile outage must produce neutral deterministic design, not a
            # model/renderer dependency on a live profile store.
            return LearnerContextSnapshot()

    def retry(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None or job["status"] in {"published", "published_with_warnings"}:
            return self._job_response(job) if job else None
        self.repo.update_job(run_id, status="queued", error_code=None, error_message=None)
        self.repo.enqueue_task_once({
            "outbox_id": f"cwo_{run_id}_retry_{uuid.uuid4().hex}", "run_id": run_id,
            "event_type": "courseware.run", "task_kind": "courseware.run", "status": "queued",
            "payload": {"run_id": run_id, "retry": True},
            "idempotency_key": f"courseware.run.retry:{run_id}:{int(job.get('attempt') or 0) + 1}",
        })
        self._event(run_id, "job", "retry_queued")
        return self._job_response(self.repo.get_job(run_id))

    def cancel(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None:
            return None
        if job["status"] in {"published", "published_with_warnings", "cancelled"}:
            return self._job_response(job)
        row = self.repo.update_job(
            run_id, status="cancelled", cancel_requested_at=datetime.now(timezone.utc),
            error_code="COURSEWARE_CANCELLED", error_message="课件任务已取消",
        )
        self._event(run_id, "job", "cancelled", {"error_code": "COURSEWARE_CANCELLED"})
        return self._job_response(row)

    def retry_scene(
        self, run_id: str, scene_id: str, *, review_instruction: str | None = None,
        automatic: bool = False, enqueue_outbox: bool = True, enqueue_only: bool = False,
    ) -> CoursewareJobResponse | None:
        self._control_guard(run_id)
        job = self.repo.get_job(run_id)
        scene = self.repo.get_scene(scene_id)
        spec = self.repo.get_spec_by_run(run_id)
        if job is None or scene is None or spec is None or scene["spec_id"] != spec["spec_id"]:
            return None
        if enqueue_only:
            next_attempt = int(scene.get("attempt") or 0) + 1
            input_snapshot_hash = content_hash(json.dumps({
                "spec": spec["content_hash"], "source": scene.get("input_snapshot_hash"),
                "source_blocks": scene.get("scene_json", {}).get("source_block_ids") or [],
            }, ensure_ascii=False, sort_keys=True))
            self.repo.enqueue_task_once({
                "outbox_id": f"cwo_{run_id}_{scene_id}_{next_attempt}", "run_id": run_id,
                "scene_id": scene_id, "event_type": "scene_retry", "task_kind": "courseware.scene.revise",
                "payload": {"attempt": next_attempt, "review_instruction": review_instruction},
                "idempotency_key": f"{scene_id}:{input_snapshot_hash}:{next_attempt}",
            })
            self._event(run_id, "composing", "scene_retry_queued", {"attempt": next_attempt}, scene_id)
            return self._job_response(job)
        owner = f"scene-retry-{uuid.uuid4().hex}"
        claimed = self.repo.claim_scene(scene_id, owner, get_settings().courseware_scene_lease_seconds)
        if claimed is None:
            self._event(run_id, "composing", "scene_retry_already_running", {}, scene_id)
            return self._job_response(job)
        scene = claimed
        snapshots = job.get("source_snapshots") or []
        source_id = next(iter(scene.get("scene_json", {}).get("source_refs") or []), None)
        source = next((item for item in snapshots if item["resource_id"] == source_id), None)
        if source is None or scene.get("kind") == "recap":
            # A recap aggregates multiple sources and is deterministic today.
            # Keeping it immutable avoids accidentally regenerating unrelated pages.
            return self._job_response(job)
        before_hash = scene["content_hash"]
        next_attempt = int(scene.get("attempt") or 0) + 1
        input_snapshot_hash = content_hash(json.dumps({
            "spec": spec["content_hash"], "source": source.get("content_hash"),
            "source_blocks": scene.get("scene_json", {}).get("source_block_ids") or [],
        }, ensure_ascii=False, sort_keys=True))
        self.repo.upsert_scene({
            **{key: scene[key] for key in ("scene_id", "spec_id", "scene_order", "kind", "scene_json", "content_hash")},
            "status": "composing", "attempt": next_attempt,
            "input_snapshot_hash": input_snapshot_hash, "agent_version": "ai-v1",
            "prompt_version": "ai-v1", "review_instruction": review_instruction or scene.get("review_instruction"),
            "lease_owner": owner, "lease_expires_at": scene.get("lease_expires_at"),
            "error_code": None, "error_message": None,
        })
        if enqueue_outbox:
            self.repo.enqueue_outbox({
                "outbox_id": f"cwo_{uuid.uuid4().hex}", "run_id": run_id, "scene_id": scene_id,
                "event_type": "scene_auto_revision" if automatic else "scene_retry", "payload": {"attempt": next_attempt},
                "idempotency_key": f"{scene_id}:{input_snapshot_hash}:{next_attempt}",
            })
        self._event(run_id, "composing", "scene_retry_started", {"attempt": next_attempt, "input_snapshot_hash": input_snapshot_hash}, scene_id)
        try:
            revision_budget = self.budget.before_call(run_id, "revision")
            if not revision_budget.allowed:
                raise RuntimeError(revision_budget.warning.get("code") if revision_budget.warning else "COURSEWARE_REVISION_BUDGET_EXHAUSTED")
            composer_input = {**scene["scene_json"], "_review_instruction": review_instruction} if review_instruction else scene["scene_json"]
            revision_options = self.llm_gateway.options_for("generator", temperature=0.0).model_copy(update={
                "max_output_tokens": revision_budget.max_output_tokens,
                "request_timeout_seconds": revision_budget.timeout_seconds,
            }) if self.llm_gateway else None
            if self.llm_gateway:
                enhanced, warning = self.scene_composer(
                    self.llm_gateway, run_id, scene_id, composer_input, source,
                    allowance=revision_options,
                )
            else:
                enhanced, warning = self.scene_composer(
                    self.llm_gateway, run_id, scene_id, composer_input, source,
                )
            self.budget.reconcile(run_id, revision_budget.call_id,
                                  status="completed" if enhanced is not None else "failed")
            warning = self._record_agent_trace(run_id, warning, "courseware_scene_composer", scene_id, "revision")
            resolved = enhanced or scene["scene_json"]
            document = {"title": (job.get("title") or spec.get("spec_json", {}).get("title") or "互动课件"),
                        "scenes": [item["scene_json"] if item["scene_id"] != scene_id else resolved
                                   for item in self.repo.list_scenes(spec["spec_id"])]}
            issues = source_trace_review(document, snapshots) + quality_review(document)
            if issues:
                raise ValueError("局部场景未通过来源或教学质量审核")
            next_hash = content_hash(json.dumps(resolved, ensure_ascii=False, sort_keys=True))
            self.repo.upsert_scene({
                **{key: scene[key] for key in ("scene_id", "spec_id", "scene_order", "kind")},
                "scene_json": resolved, "content_hash": next_hash, "status": "approved", "attempt": next_attempt,
                "input_snapshot_hash": input_snapshot_hash, "agent_version": "ai-v1" if enhanced else "deterministic-v1",
                "prompt_version": "ai-v1" if enhanced else "deterministic-v1", "approved_at": datetime.now(timezone.utc),
                "review_instruction": review_instruction or scene.get("review_instruction"),
                "lease_owner": None, "lease_expires_at": None,
                "error_code": None, "error_message": None,
            })
            revisions = self.repo.list_scene_revisions(scene_id)
            self.repo.save_scene_revision({
                "revision_id": f"cwsr_{uuid.uuid4().hex}", "scene_id": scene_id,
                "revision_no": len(revisions) + 1, "trigger": "auto_review" if automatic else "model_retry", "actor_id": None,
                "reason": review_instruction or "单场景重试", "before_content_hash": before_hash,
                "after_content_hash": next_hash, "input_snapshot_hash": input_snapshot_hash,
            })
            if warning:
                warnings = list(job.get("warnings") or []) + [warning]
                self.repo.update_job(run_id, warnings=warnings)
            self._event(run_id, "composing", "scene_approved", {"attempt": next_attempt, "input_snapshot_hash": input_snapshot_hash}, scene_id)
            if job.get("status") in {"published", "published_with_warnings"}:
                self._refresh_published_artifact(run_id)
        except Exception as exc:
            self.repo.upsert_scene({
                **{key: scene[key] for key in ("scene_id", "spec_id", "scene_order", "kind", "scene_json", "content_hash")},
                "status": "revision_required", "attempt": next_attempt,
                "input_snapshot_hash": input_snapshot_hash, "agent_version": "ai-v1", "prompt_version": "ai-v1",
                "review_instruction": review_instruction or scene.get("review_instruction"),
                "lease_owner": None, "lease_expires_at": None,
                "error_code": "COURSEWARE_SCENE_RETRY_FAILED", "error_message": "场景局部重试未通过审核",
            })
            self._event(run_id, "composing", "scene_revision_required", {"attempt": next_attempt, "error_type": type(exc).__name__}, scene_id)
        return self._job_response(self.repo.get_job(run_id))

    def process_scene_outbox(self, run_id: str | None = None, limit: int = 10) -> dict[str, int]:
        """Consume retry intents after a process restart, idempotently."""
        processed = skipped = failed = 0
        for item in self.repo.list_outbox(run_id, pending_only=True)[:max(1, limit)]:
            scene_id = item.get("scene_id")
            scene = self.repo.get_scene(scene_id) if scene_id else None
            expected_attempt = int((item.get("payload") or {}).get("attempt") or 0)
            if scene is None or (scene.get("status") == "approved" and int(scene.get("attempt") or 0) >= expected_attempt):
                self.repo.mark_outbox_delivered(item["outbox_id"])
                skipped += 1
                continue
            try:
                result = self.retry_scene(
                    item["run_id"], scene_id, review_instruction=scene.get("review_instruction"),
                    automatic=True, enqueue_outbox=False,
                )
                current = self.repo.get_scene(scene_id)
                if result is not None and current and current.get("status") == "approved":
                    self.repo.mark_outbox_delivered(item["outbox_id"])
                    processed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"processed": processed, "skipped": skipped, "failed": failed}

    def _refresh_published_artifact(self, run_id: str) -> bool:
        """Rebuild the published artifact from the complete current scene set."""
        job = self.repo.get_job(run_id)
        resource = self.repo.get_resource_by_run(run_id)
        spec = self.repo.get_spec_by_run(run_id)
        if not job or not resource or not spec:
            return False
        snapshots = job.get("source_snapshots") or []
        document = {
            "schema_version": "1.0",
            "title": job.get("title") or spec.get("spec_json", {}).get("title") or "互动课件",
            "scenes": [row["scene_json"] for row in self.repo.list_scenes(spec["spec_id"])],
        }
        issues = source_trace_review(document, snapshots) + quality_review(document)
        if issues:
            self._event(run_id, "republishing", "blocked", {"issue_count": len(issues)})
            return False
        candidate = None
        try:
            artifact = render_courseware(document)
            browser_smoke_check(artifact)
            provenance_graph = build_provenance_graph(document, snapshots)
            candidate = self.release_coordinator.freeze(
                run_id=run_id, resource_id=resource["resource_id"],
                release_policy=job.get("release_policy") or "resilient", snapshots=snapshots,
                scenes=self.repo.list_scenes(spec["spec_id"]), provenance=provenance_graph.as_manifest(),
                idempotency_key=f"scene-retry:{run_id}:{content_hash(json.dumps(document, ensure_ascii=False, sort_keys=True))}",
            )
            release_id = candidate["release_id"]
            file_path, file_size, artifact_sha = save_courseware_html(
                job["learner_id"], resource["resource_id"], artifact, release_id=release_id
            )
            self.repo.save_artifact({
                "artifact_id": f"cwa_{release_id}_html", "release_id": release_id,
                "courseware_resource_id": resource["resource_id"], "artifact_format": "html",
                "file_path": file_path, "mime_type": "text/html", "file_size": file_size,
                "sha256": artifact_sha,
                "required": 1, "artifact_status": "ready",
                "manifest": {"entrypoint": "index.html", "security_check": "passed",
                              "provenance": provenance_graph.as_manifest()},
            })
            for package_format, extension in (("zip", "zip"), ("scorm", "scorm.zip"), ("xapi", "xapi.zip")):
                package, manifest = package_courseware(
                    artifact, resource_id=resource["resource_id"], title=document["title"], package_format=package_format,
                )
                package_path, package_size, package_sha = save_courseware_artifact(
                    job["learner_id"], resource["resource_id"], package, extension, release_id=release_id,
                )
                self.repo.save_artifact({
                    "artifact_id": f"cwa_{release_id}_{package_format}", "release_id": release_id,
                    "courseware_resource_id": resource["resource_id"], "artifact_format": package_format,
                    "file_path": package_path, "mime_type": "application/zip", "file_size": package_size,
                    "sha256": package_sha, "manifest": manifest,
                    "required": 1 if package_format == "zip" else 0, "artifact_status": "ready",
                })
            self.release_coordinator.commit(
                candidate, resource_id=resource["resource_id"],
                resource_projection={"file_path": file_path, "file_size": file_size,
                                     "artifact_sha256": artifact_sha},
                job_status=job.get("status") or "published", warnings=job.get("warnings") or [],
                event_payload={"event_id": f"cwe_{release_id}", "run_id": run_id,
                               "stage": "republishing", "status": "published",
                               "payload": {"release_id": release_id, "artifact_sha256": artifact_sha}},
                manifest={"schema_version": "1.0", "renderer_version": RENDERER_VERSION,
                          "runtime_version": RUNTIME_VERSION, "provenance": provenance_graph.as_manifest(),
                          "artifacts": [item for item in self.repo.list_artifacts(resource["resource_id"])
                                        if item.get("release_id") == release_id]},
            )
            return True
        except Exception as exc:
            if candidate is not None:
                self.release_coordinator.block(candidate, code="COURSEWARE_RELEASE_GATE_FAILED",
                                               message="scene retry candidate 未通过发布门")
            self._event(run_id, "republishing", "failed", {"error_type": type(exc).__name__, "error": str(exc)[:200]})
            return False

    def publish(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None:
            return None
        if job["status"] in {"published", "published_with_warnings"}:
            return self._job_response(job)
        if job["status"] != "approved_pending_publish" or not job.get("resource_id"):
            return self._job_response(job)
        resource = self.repo.update_resource_status(job["resource_id"], "published")
        if resource is None:
            return self._job_response(self.repo.update_job(run_id, status="failed", error_code="COURSEWARE_ARTIFACT_MISSING", error_message="待发布课件不存在"))
        state = "published_with_warnings" if job.get("warnings") else "published"
        row = self.repo.update_job(run_id, status=state)
        self._event(run_id, "publishing", state, {"resource_id": job["resource_id"]})
        return self._job_response(row)

    def get_resource(self, resource_id: str) -> CoursewareResourceDetail | None:
        row = self.repo.get_resource(resource_id)
        if row is None:
            return None
        return CoursewareResourceDetail(
            resource_id=row["resource_id"], learner_id=row["learner_id"], run_id=row["run_id"],
            batch_id=row.get("batch_id"),
            title=row["title"], topic=row["topic"], status=row["status"], version=row["version"],
            released_release_id=row.get("released_release_id"),
            artifact_sha256=row["artifact_sha256"], artifact_size=row["file_size"],
            source_summary=row["source_summary"], warnings=row["warnings"],
            created_at=row.get("created_at"), published_at=row.get("published_at"),
        )

    def artifact(self, resource_id: str) -> tuple[dict[str, Any], bytes] | None:
        row = self.repo.get_resource(resource_id)
        if row is None or row["status"] not in {"published", "stale"} or not row.get("released_release_id"):
            return None
        released = next((item for item in self.repo.list_artifacts(resource_id)
                         if item.get("artifact_format") == "html"
                         and item.get("release_id") == row.get("released_release_id")
                         and item.get("artifact_status") == "ready"), None)
        if released is None:
            return None
        try:
            return row, self.file_loader(released["file_path"])
        except (OSError, ValueError):
            try:
                path = file_storage._get_resources_dir() / "courseware" / row["learner_id"] / resource_id / "releases" / row["released_release_id"] / "index.html"
                return row, path.read_bytes()
            except (OSError, TypeError):
                return None

    def packaged_artifact(self, resource_id: str, package_format: str) -> tuple[dict[str, Any], bytes] | None:
        row = self.repo.get_resource(resource_id)
        if row is None or row["status"] not in {"published", "stale"}:
            return None
        artifact = next((item for item in self.repo.list_artifacts(resource_id)
                         if item["artifact_format"] == package_format
                         and item.get("release_id") == row.get("released_release_id")
                         and item.get("artifact_status") == "ready"), None)
        if artifact is None:
            return None
        try:
            return artifact, self.file_loader(artifact["file_path"])
        except (OSError, ValueError):
            try:
                release_id = row.get("released_release_id")
                filename = Path(artifact["file_path"]).name
                path = file_storage._get_resources_dir() / "courseware" / row["learner_id"] / resource_id / "releases" / release_id / filename
                return artifact, path.read_bytes()
            except (OSError, TypeError):
                return None

    def list_library_items(self, learner_id: str) -> list[ResourceLibraryItem]:
        reconcile_stale_resources(self.repo, self.resource_service, learner_id, self._event)
        return [
            ResourceLibraryItem(
                id=row["resource_id"], resource_kind="interactive_courseware", title=row["title"],
                topic=row["topic"], learner_id=row["learner_id"], created_at=row.get("created_at"),
                published_at=row.get("published_at"), version=row["version"], status=row["status"],
                preview_capability=True, download_capability=True, source_summary=row["source_summary"],
                run_id=row["run_id"], batch_id=row.get("batch_id"), resource_type="互动HTML课件", difficulty="互动学习",
            )
            for row in self.repo.list_resources(learner_id)
            if row["status"] in {"published", "stale"}
        ]

    def _deterministic_document(self, title: str, snapshots: list[dict[str, Any]], learning_design=None) -> dict[str, Any]:
        deterministic_scenes, _ = compose_scenes(snapshots, None, learning_design=learning_design)
        return {"schema_version": "1.0", "title": title, "scenes": deterministic_scenes,
                "design": CoursewareDesign().model_dump(mode="json")}

    def _persist_deterministic_scenes(self, run_id: str, document: dict[str, Any]) -> None:
        spec = self.repo.get_spec_by_run(run_id)
        if spec is None:
            return
        for index, scene in enumerate(document.get("scenes") or []):
            scene_id = f"{spec['spec_id']}_scene_{index + 1}"
            scene_hash = content_hash(json.dumps(scene, ensure_ascii=False, sort_keys=True))
            current = self.repo.get_scene(scene_id) or {}
            self.repo.upsert_scene({
                "scene_id": scene_id, "spec_id": spec["spec_id"], "scene_order": index,
                "kind": scene["kind"], "scene_json": scene, "content_hash": scene_hash,
                "status": "approved", "attempt": int(current.get("attempt") or 0),
                "input_snapshot_hash": current.get("input_snapshot_hash") or "",
                "agent_version": "deterministic-v1", "prompt_version": "deterministic-v1",
                "approved_at": datetime.now(timezone.utc), "lease_owner": None,
                "lease_expires_at": None, "error_code": None, "error_message": None,
            })

    def _fallback_warning(self, warning: dict[str, Any] | None) -> dict[str, Any]:
        return {
            **(warning or {"code": "AI_QUALITY_REVIEW_UNAVAILABLE", "message": "AI 教学质量审核不可用"}),
            "fallback_version": "deterministic-v1", "discarded_candidate": True,
        }

    def _auto_review_and_revise(
        self, run_id: str, job: dict[str, Any], spec: dict[str, Any], document: dict[str, Any],
        snapshots: list[dict[str, Any]], deterministic_document: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        """Run bounded, machine-only quality repair before an artifact exists."""
        budget_warning = self._review_budget_warning(run_id, job)
        quality_budget = self.budget.before_call(run_id, "quality_review")
        if not quality_budget.allowed:
            budget_warning = quality_budget.warning
        if budget_warning:
            self._save_review(run_id, "ai_teaching_quality", "unavailable", [])
            if get_settings().courseware_release_policy == "strict":
                return None, self._fallback_warning(budget_warning)
            fallback = deterministic_document or document
            self._persist_deterministic_scenes(run_id, fallback)
            return fallback, self._fallback_warning(budget_warning)
        review_options = self.llm_gateway.options_for("generator", temperature=0.0).model_copy(update={
            "max_output_tokens": quality_budget.max_output_tokens,
            "request_timeout_seconds": quality_budget.timeout_seconds,
        }) if self.llm_gateway else None
        if self.llm_gateway:
            decision, warning = review_courseware_quality_decision(
                self.llm_gateway, run_id, document, allowance=review_options,
            )
        else:
            decision, warning = review_courseware_quality_decision(self.llm_gateway, run_id, document)
        self.budget.reconcile(run_id, quality_budget.call_id,
                              status="completed" if decision.decision != "unavailable" else "failed")
        self._control_guard(run_id)
        issues = [issue.model_dump(mode="json") for issue in decision.issues]
        self._record_llm_trace(
            run_id, "courseware_quality_reviewer", decision.trace_metadata,
            budget_stage="quality_review",
        )
        self._save_review(run_id, "ai_teaching_quality", decision.decision, issues)
        if decision.decision == "unavailable":
            # Strict releases require live AI-review evidence. Resilient
            # releases use only the deterministic document already accepted by
            # source, quality, renderer and browser gates, with a durable
            # warning that states why the AI gate was unavailable.
            if get_settings().courseware_release_policy == "strict":
                return None, self._fallback_warning(warning)
            fallback = deterministic_document or document
            self._persist_deterministic_scenes(run_id, fallback)
            return fallback, self._fallback_warning(warning)
        if decision.decision == "approved" and not issues:
            return document, warning
        if decision.decision == "rejected":
            return None, warning

        settings = get_settings()
        started_at = monotonic()
        for revision_no in range(1, settings.courseware_auto_revision_max_attempts + 1):
            budget_warning = self._review_budget_warning(run_id, job)
            if budget_warning:
                self._save_review(run_id, "ai_teaching_quality", "unavailable", [])
                if settings.courseware_release_policy == "strict":
                    return None, self._fallback_warning(budget_warning)
                fallback = deterministic_document or document
                self._persist_deterministic_scenes(run_id, fallback)
                return fallback, self._fallback_warning(budget_warning)
            if monotonic() - started_at > settings.courseware_auto_review_max_seconds:
                self._event(run_id, "auto_revising", "budget_exhausted", {"budget": "elapsed_seconds"})
                return None, warning
            targets = self._review_targets(spec["spec_id"], issues)
            if not targets:
                return None, warning
            self._stage(run_id, "auto_revising")
            self._event(run_id, "auto_revising", "started", {"revision": revision_no, "scene_count": len(targets)})
            for scene_id, instruction in targets:
                self.retry_scene(run_id, scene_id, review_instruction=instruction, automatic=True)
            scene_rows = self.repo.list_scenes(spec["spec_id"])
            if any(row.get("status") != "approved" for row in scene_rows):
                return None, warning
            revised = {
                "schema_version": "1.0", "title": document["title"],
                "scenes": [row["scene_json"] for row in scene_rows],
            }
            deterministic_issues = source_trace_review(revised, snapshots) + quality_review(revised)
            if deterministic_issues:
                self._save_review(run_id, "post_revision_rules", "rejected", deterministic_issues)
                return None, warning
            review_budget = self.budget.before_call(run_id, "revision")
            if not review_budget.allowed:
                self._save_review(run_id, "ai_teaching_quality", "unavailable", [])
                fallback = deterministic_document or document
                self._persist_deterministic_scenes(run_id, fallback)
                return fallback, self._fallback_warning(review_budget.warning)
            review_options = self.llm_gateway.options_for("generator", temperature=0.0).model_copy(update={
                "max_output_tokens": review_budget.max_output_tokens,
                "request_timeout_seconds": review_budget.timeout_seconds,
            }) if self.llm_gateway else None
            if self.llm_gateway:
                decision, next_warning = review_courseware_quality_decision(
                    self.llm_gateway, run_id, revised, allowance=review_options,
                )
            else:
                decision, next_warning = review_courseware_quality_decision(self.llm_gateway, run_id, revised)
            self.budget.reconcile(run_id, review_budget.call_id,
                                  status="completed" if decision.decision != "unavailable" else "failed")
            self._control_guard(run_id)
            warning = warning or next_warning
            issues = [issue.model_dump(mode="json") for issue in decision.issues]
            self._record_llm_trace(
                run_id, "courseware_quality_reviewer", decision.trace_metadata,
                budget_stage="revision",
            )
            self._save_review(run_id, "ai_teaching_quality", decision.decision, issues)
            if decision.decision == "approved" and not issues:
                self._event(run_id, "auto_revising", "approved", {"revision": revision_no})
                return revised, warning
            if decision.decision == "rejected":
                return None, warning
            document = revised
        return None, warning

    def _review_budget_warning(self, run_id: str, job: dict[str, Any]) -> dict[str, str] | None:
        """Avoid a further model call once the persisted run budget is spent."""
        settings = get_settings()
        created_at = job.get("created_at")
        if isinstance(created_at, datetime):
            created_at_utc = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            now = datetime.now(created_at_utc.tzinfo)
            if (now - created_at_utc).total_seconds() >= settings.courseware_total_run_timeout_seconds:
                return {
                    "code": "COURSEWARE_RUN_TIMEOUT",
                    "message": "课件任务总时限已耗尽，未继续调用 AI 审核",
                    "fallback_version": "deterministic-v1",
                }
        total_tokens = 0
        for event in self.repo.list_events(run_id):
            trace = (event.get("payload") or {}).get("trace") or {}
            total_tokens += int(trace.get("input_tokens") or 0) + int(trace.get("output_tokens") or 0)
        if total_tokens >= settings.courseware_total_llm_token_budget:
            return {
                "code": "COURSEWARE_LLM_TOKEN_BUDGET_EXHAUSTED",
                "message": "课件模型 token 总预算已耗尽，未继续调用 AI 审核",
                "fallback_version": "deterministic-v1",
            }
        return None

    def _review_targets(self, spec_id: str, issues: list[dict[str, Any]]) -> list[tuple[str, str]]:
        """Map field-level review issues to the smallest possible scene set."""
        scenes = self.repo.list_scenes(spec_id)
        return resolve_review_targets(
            [
                {
                    **(row.get("scene_json") or {}),
                    "scene_id": row.get("scene_id"),
                    "scene_json": row.get("scene_json") or {},
                }
                for row in scenes
            ],
            issues,
        )

    def _stage(self, run_id: str, status: str, **changes: Any) -> dict[str, Any] | None:
        row = self.repo.update_job(run_id, status=status, **changes)
        self._event(run_id, status, "started")
        return row

    def _event(
        self, run_id: str, stage: str, status: str,
        payload: dict[str, Any] | None = None, scene_id: str | None = None,
    ) -> dict[str, Any]:
        return self.repo.append_event({
            "event_id": f"cwe_{uuid.uuid4().hex}", "run_id": run_id, "stage": stage,
            "scene_id": scene_id, "status": status, "payload": payload or {},
        })

    def _record_agent_trace(
        self, run_id: str, warning: dict[str, Any] | None, node_name: str,
        scene_id: str | None = None, budget_stage: str | None = None,
    ) -> dict[str, Any] | None:
        if warning and warning.get("code") == "LLM_TRACE":
            self._record_llm_trace(run_id, node_name, warning.get("trace") or {}, scene_id, budget_stage)
            return None
        return warning

    def _record_llm_trace(
        self, run_id: str, node_name: str, trace: dict[str, Any], scene_id: str | None = None,
        budget_stage: str | None = None,
    ) -> None:
        if not trace:
            return
        settings = get_settings()
        input_tokens = trace.get("input_tokens") or 0
        output_tokens = trace.get("output_tokens") or 0
        trace = {
            **trace,
            "budget_stage": budget_stage or ({
                "courseware_spec_builder": "planner",
                "courseware_quality_reviewer": "quality_review",
                "courseware_scene_composer": "scene",
            }.get(node_name, "revision")),
            "estimated_cost_usd": round(
                (input_tokens / 1000) * settings.courseware_input_cost_per_1k_tokens
                + (output_tokens / 1000) * settings.courseware_output_cost_per_1k_tokens,
                8,
            ),
        }
        self._event(run_id, "llm_observation", "completed", {
            "node_name": node_name,
            "trace": trace,
        }, scene_id)

    def _save_review(
        self, run_id: str, kind: str, decision: str, issues: list[dict[str, Any]],
        scene_id: str | None = None,
    ) -> None:
        self.repo.save_review({
            "review_id": f"cwv_{uuid.uuid4().hex}", "run_id": run_id, "scene_id": scene_id,
            "kind": kind, "decision": decision, "issues": issues, "reviewer_version": "rules-v1",
        })
        self._event(run_id, kind, decision, {"issue_count": len(issues)}, scene_id)

    def _job_response(self, row: dict[str, Any] | None) -> CoursewareJobResponse | None:
        if row is None:
            return None
        spec = self.repo.get_spec_by_run(row["run_id"])
        artifacts = self.repo.list_artifacts(row.get("resource_id")) if row.get("resource_id") else []
        quality_summary = build_quality_summary(
            self.repo.list_events(row["run_id"]), status=row["status"], warnings=row.get("warnings") or [],
            artifact_success=bool(artifacts and row.get("status") in {"published", "published_with_warnings"}),
            spec_prompt_version=spec.get("prompt_version") if spec else None,
            required_scene_ids=[item["scene_id"] for item in self.repo.list_scenes(spec["spec_id"])
                                if item.get("kind") != "recap"] if spec else None,
            learning_design=(spec or {}).get("spec_json", {}).get("learning_design") if spec else None,
            scenes=[item.get("scene_json") or {} for item in self.repo.list_scenes(spec["spec_id"])] if spec else None,
        )
        return CoursewareJobResponse(
            run_id=row["run_id"], learner_id=row["learner_id"], status=row["status"], title=row.get("title"),
            publish_mode=row.get("publish_mode") or "automatic",
            resource_id=row.get("resource_id"), source_batch_id=row.get("source_batch_id"), warnings=row.get("warnings") or [], error_code=row.get("error_code"),
            request_options=row.get("request_options") or {},
            quality_summary=quality_summary,
            error_message=row.get("error_message"), created_at=row.get("created_at"), updated_at=row.get("updated_at"),
        )
