"""Fault-tolerant orchestration service for interactive HTML courseware."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.courseware.packaging import package_courseware
from app.core.courseware.renderer import render_courseware
from app.core.courseware.runtime import RENDERER_VERSION, RUNTIME_VERSION
from app.core.courseware.security import browser_smoke_check
from app.core.courseware.storage import save_courseware_artifact, save_courseware_html
from app.core.file_storage import load_resource_file
from app.db.audit.base import BaseAuditRepository
from app.models.courseware import (
    CoursewareJobCreateRequest,
    CoursewareJobDetail,
    CoursewareJobResponse,
    CoursewareSceneStatus,
    CoursewareResourceDetail,
)
from app.models.resource_library import ResourceLibraryItem
from app.services.resource_service import ResourceService
from app.agents.resource_workflows.interactive_courseware.planner_agent import build_courseware_spec
from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import review_courseware_quality
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import compose_courseware_scene
from app.services.courseware.composition import compose_scenes, default_title, source_summary, topic
from app.services.courseware.lineage import reconcile_stale_resources
from app.services.courseware.review import quality_review, source_trace_review
from app.services.courseware.source import CoursewareAdmissionError, admit_and_snapshot, content_hash


class CoursewareService:
    def __init__(self, repo, resource_service: ResourceService, audit_repo: BaseAuditRepository, llm_gateway: Any | None = None):
        self.repo = repo
        self.resource_service = resource_service
        self.audit_repo = audit_repo
        self.llm_gateway = llm_gateway

    def create_job(self, request: CoursewareJobCreateRequest) -> CoursewareJobResponse:
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
            "publish_mode": request.publish_mode,
            "workflow_version": "courseware-v1",
        }, ensure_ascii=False, separators=(",", ":")))
        row = self.repo.create_job({
            "run_id": f"cw_{uuid.uuid4().hex}", "learner_id": request.learner_id,
            "knowledge_base_id": None, "title": request.title,
            "publish_mode": request.publish_mode,
            "source_resource_ids": request.source_resource_ids, "source_snapshots": [],
            "request_hash": request_hash, "idempotency_key": request.idempotency_key,
            "status": "queued", "warnings": [], "attempt": 0,
        })
        if not self.repo.list_events(row["run_id"]):
            self._event(row["run_id"], "job", "queued")
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
            ) for item in scenes],
            reviews=self.repo.list_reviews(run_id),
            artifacts=self.repo.list_artifacts(resource["resource_id"]) if resource else [],
        )

    def events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self.repo.list_events(run_id, after_sequence)

    def run_job(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None:
            return None
        if job["status"] in {"approved_pending_publish", "published", "published_with_warnings"}:
            return self._job_response(job)
        warnings: list[dict[str, str]] = list(job.get("warnings") or [])
        self._stage(run_id, "admitting", attempt=int(job.get("attempt") or 0) + 1,
                    error_code=None, error_message=None)
        if job.get("source_snapshots") and job.get("knowledge_base_id"):
            snapshots = job["source_snapshots"]
            knowledge_base_id = job["knowledge_base_id"]
            self._event(run_id, "snapshotting", "reused", {"snapshot_count": len(snapshots)})
        else:
            try:
                self._stage(run_id, "snapshotting")
                snapshots, knowledge_base_id = admit_and_snapshot(self.resource_service, self.audit_repo, job)
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
        plan, plan_warning = build_courseware_spec(self.llm_gateway, run_id, snapshots)
        title = job.get("title") or (plan.title if plan else default_title(snapshots))
        spec_json = {
            "schema_version": "1.0", "title": title,
            "scenes": ([item.model_dump(mode="json") for item in plan.scenes] if plan else [
                {"source_resource_id": item["resource_id"], "kind": item["role"], "title": item["resource_type"]}
                for item in snapshots
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
        self._stage(run_id, "composing")
        scenes, scene_warnings = compose_scenes(snapshots, plan)
        if plan_warning:
            warnings.append(plan_warning)
        warnings.extend(scene_warnings)
        # AI writes one closed SceneSpec at a time.  A bad response is isolated:
        # the deterministic scene remains publishable and the warning is surfaced
        # in the job rather than discarding the entire course.
        sources_by_id = {item["resource_id"]: item for item in snapshots}
        def compose_one(index: int, scene: dict[str, Any]):
            scene_id = f"{spec_id}_scene_{index + 1}"
            source_id = next(iter(scene.get("source_refs") or []), None)
            source = sources_by_id.get(source_id) if source_id else None
            if source is None or scene.get("kind") == "recap":
                return index, scene, None
            try:
                enhanced, scene_warning = compose_courseware_scene(self.llm_gateway, run_id, scene_id, scene, source)
                return index, enhanced or scene, scene_warning
            except Exception:
                # This is intentionally broad at the task boundary: one broken
                # provider adapter must never discard unrelated approved scenes.
                return index, scene, {"code": "AI_SCENE_FALLBACK", "message": f"场景 {scene_id} 调用异常，已保留确定性版本"}

        enhanced_scenes: list[dict[str, Any] | None] = [None] * len(scenes)
        ai_enabled = courseware_ai_available(self.llm_gateway)
        if ai_enabled and len(scenes) > 1:
            with ThreadPoolExecutor(max_workers=min(2, len(scenes)), thread_name_prefix="courseware-scene") as executor:
                results = list(executor.map(lambda item: compose_one(*item), enumerate(scenes)))
        else:
            results = [compose_one(index, scene) for index, scene in enumerate(scenes)]
        for index, resolved_scene, scene_warning in results:
            if scene_warning:
                warnings.append(scene_warning)
            enhanced_scenes[index] = resolved_scene
        scenes = [scene for scene in enhanced_scenes if scene is not None]
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
                "error_code": None, "error_message": None,
            })
            self._event(run_id, "composing", "scene_approved", {"scene_order": index}, scene_id)
        if not scenes:
            row = self.repo.update_job(run_id, status="failed", error_code="COURSEWARE_NO_RENDERABLE_SCENES",
                                       error_message="没有可渲染的课件场景，可在修复源资源后重试", warnings=warnings)
            self._event(run_id, "composing", "failed", {"error_code": "COURSEWARE_NO_RENDERABLE_SCENES"})
            return self._job_response(row)
        try:
            document = {"schema_version": "1.0", "title": title, "scenes": scenes}
            self._stage(run_id, "trace_reviewing", warnings=warnings)
            trace_issues = source_trace_review(document, snapshots)
            self._save_review(run_id, "source_trace", "approved" if not trace_issues else "rejected", trace_issues)
            if trace_issues:
                raise ValueError("课件来源追踪审核未通过")
            self._stage(run_id, "quality_reviewing")
            quality_issues = quality_review(document)
            self._save_review(run_id, "teaching_quality", "approved" if not quality_issues else "rejected", quality_issues)
            if quality_issues:
                raise ValueError("课件教学质量审核未通过")
            if courseware_ai_available(self.llm_gateway):
                ai_quality_issues, ai_quality_warning = review_courseware_quality(self.llm_gateway, run_id, document)
                self._save_review(
                    run_id, "ai_teaching_quality", "revision_required" if ai_quality_issues else "approved", ai_quality_issues,
                )
                if ai_quality_warning:
                    warnings.append(ai_quality_warning)
                for issue in ai_quality_issues:
                    warnings.append({
                        "code": f"AI_REVIEW_{issue.get('code', 'ISSUE')}",
                        "message": str(issue.get("instruction") or "AI 审核发现一项教学质量建议"),
                    })
            self._stage(run_id, "rendering")
            artifact = render_courseware(document)
            self._stage(run_id, "validating")
            browser_smoke_check(artifact)
            existing_resource = self.repo.get_resource_by_run(run_id)
            resource_id = existing_resource["resource_id"] if existing_resource else f"cwr_{uuid.uuid4().hex}"
            file_path, file_size, artifact_sha = save_courseware_html(job["learner_id"], resource_id, artifact)
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
            pending_publication = job.get("publish_mode", "manual") == "manual"
            self.repo.save_resource({
                "resource_id": resource_id, "resource_family_id": resource_id, "run_id": run_id,
                "learner_id": job["learner_id"], "knowledge_base_id": knowledge_base_id,
                "title": title, "topic": resource_topic,
                "status": "building", "version": 1,
                "file_path": file_path, "file_size": file_size, "artifact_sha256": artifact_sha,
                "renderer_version": RENDERER_VERSION, "runtime_version": RUNTIME_VERSION,
                "source_summary": [source_summary(item) for item in snapshots], "warnings": warnings,
            }, links)
            self.repo.save_artifact({
                "artifact_id": f"cwa_{resource_id}_html", "courseware_resource_id": resource_id,
                "artifact_format": "html", "file_path": file_path, "mime_type": "text/html",
                "file_size": file_size, "sha256": artifact_sha,
                "manifest": {"entrypoint": "index.html", "security_check": "passed"},
            })
            for package_format, extension in (("zip", "zip"), ("scorm", "scorm.zip"), ("xapi", "xapi.zip")):
                try:
                    package, manifest = package_courseware(
                        artifact, resource_id=resource_id, title=title, package_format=package_format,
                    )
                    package_path, package_size, package_sha = save_courseware_artifact(
                        job["learner_id"], resource_id, package, extension,
                    )
                    self.repo.save_artifact({
                        "artifact_id": f"cwa_{resource_id}_{package_format}",
                        "courseware_resource_id": resource_id, "artifact_format": package_format,
                        "file_path": package_path, "mime_type": "application/zip",
                        "file_size": package_size, "sha256": package_sha, "manifest": manifest,
                    })
                except Exception as exc:
                    warnings.append({"code": f"{package_format.upper()}_PACKAGE_SKIPPED",
                                     "message": f"{package_format} 导出失败，HTML 主课件仍可使用（{type(exc).__name__}）"})
            self.repo.update_resource_status(
                resource_id, "approved_pending_publish" if pending_publication else "published"
            )
            self._event(run_id, "validating", "approved", {"artifact_sha256": artifact_sha})
        except Exception as exc:
            row = self.repo.update_job(run_id, status="failed", error_code="COURSEWARE_RENDER_FAILED",
                                       error_message="课件渲染或发布失败，源快照已保留，可重试", warnings=warnings)
            self._event(run_id, "release_gate", "failed", {"error_type": type(exc).__name__})
            return self._job_response(row)
        if job.get("publish_mode", "manual") == "manual":
            row = self.repo.update_job(run_id, status="approved_pending_publish", resource_id=resource_id, warnings=warnings)
            self._event(run_id, "publishing", "awaiting_manual_approval", {"resource_id": resource_id})
        else:
            state = "published_with_warnings" if warnings else "published"
            row = self.repo.update_job(run_id, status=state, resource_id=resource_id, warnings=warnings)
            self._event(run_id, "publishing", state, {"resource_id": resource_id})
        return self._job_response(row)

    def retry(self, run_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        if job is None or job["status"] in {"published", "published_with_warnings"}:
            return self._job_response(job) if job else None
        self.repo.update_job(run_id, status="queued", error_code=None, error_message=None)
        self._event(run_id, "job", "retry_queued")
        return self.run_job(run_id)

    def retry_scene(self, run_id: str, scene_id: str) -> CoursewareJobResponse | None:
        job = self.repo.get_job(run_id)
        scene = self.repo.get_scene(scene_id)
        spec = self.repo.get_spec_by_run(run_id)
        if job is None or scene is None or spec is None or scene["spec_id"] != spec["spec_id"]:
            return None
        if job["status"] in {"approved_pending_publish", "published", "published_with_warnings"}:
            return self._job_response(job)
        self.repo.upsert_scene({
            **{key: scene[key] for key in ("scene_id", "spec_id", "scene_order", "kind", "scene_json", "content_hash")},
            "status": "retry_queued", "attempt": int(scene.get("attempt") or 0) + 1,
            "error_code": None, "error_message": None,
        })
        self._event(run_id, "composing", "scene_retry_queued", {}, scene_id)
        return self.retry(run_id)

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
            title=row["title"], topic=row["topic"], status=row["status"], version=row["version"],
            artifact_sha256=row["artifact_sha256"], artifact_size=row["file_size"],
            source_summary=row["source_summary"], warnings=row["warnings"],
            created_at=row.get("created_at"), published_at=row.get("published_at"),
        )

    def artifact(self, resource_id: str) -> tuple[dict[str, Any], bytes] | None:
        row = self.repo.get_resource(resource_id)
        if row is None or row["status"] not in {"approved_pending_publish", "published", "stale"}:
            return None
        try:
            return row, load_resource_file(row["file_path"])
        except (OSError, ValueError):
            return None

    def packaged_artifact(self, resource_id: str, package_format: str) -> tuple[dict[str, Any], bytes] | None:
        row = self.repo.get_resource(resource_id)
        if row is None or row["status"] not in {"published", "stale"}:
            return None
        artifact = next((item for item in self.repo.list_artifacts(resource_id)
                         if item["artifact_format"] == package_format), None)
        if artifact is None:
            return None
        try:
            return artifact, load_resource_file(artifact["file_path"])
        except (OSError, ValueError):
            return None

    def list_library_items(self, learner_id: str) -> list[ResourceLibraryItem]:
        reconcile_stale_resources(self.repo, self.resource_service, learner_id, self._event)
        return [
            ResourceLibraryItem(
                id=row["resource_id"], resource_kind="interactive_courseware", title=row["title"],
                topic=row["topic"], learner_id=row["learner_id"], created_at=row.get("created_at"),
                published_at=row.get("published_at"), version=row["version"], status=row["status"],
                preview_capability=True, download_capability=True, source_summary=row["source_summary"],
                run_id=row["run_id"], resource_type="互动HTML课件", difficulty="互动学习",
            )
            for row in self.repo.list_resources(learner_id)
            if row["status"] in {"published", "stale"}
        ]

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

    def _save_review(
        self, run_id: str, kind: str, decision: str, issues: list[dict[str, Any]],
        scene_id: str | None = None,
    ) -> None:
        self.repo.save_review({
            "review_id": f"cwv_{uuid.uuid4().hex}", "run_id": run_id, "scene_id": scene_id,
            "kind": kind, "decision": decision, "issues": issues, "reviewer_version": "rules-v1",
        })
        self._event(run_id, kind, decision, {"issue_count": len(issues)}, scene_id)

    @staticmethod
    def _job_response(row: dict[str, Any] | None) -> CoursewareJobResponse | None:
        if row is None:
            return None
        return CoursewareJobResponse(
            run_id=row["run_id"], learner_id=row["learner_id"], status=row["status"], title=row.get("title"),
            publish_mode=row.get("publish_mode") or "manual",
            resource_id=row.get("resource_id"), warnings=row.get("warnings") or [], error_code=row.get("error_code"),
            error_message=row.get("error_message"), created_at=row.get("created_at"), updated_at=row.get("updated_at"),
        )
