"""Candidate release construction and atomic publication coordination.

The coordinator freezes candidate hashes, builds artifacts through platform
callbacks, and delegates the final pointer switch to the repository's transaction
boundary. Model calls and the workflow's control/error boundary stay outside it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import zipfile

from app.core.courseware.runtime import RENDERER_VERSION, RUNTIME_VERSION
from app.models.courseware.learning_design import CoursewareLearningDesign
from app.agents.resource_workflows.interactive_courseware.composition import topic, source_summary


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidatePublication:
    """Frozen identities and payloads for the existing artifact publication stage."""

    run_id: str
    job: dict[str, Any]
    resource_id: str
    knowledge_base_id: str | None
    spec_id: str
    title: str
    snapshots: list[dict[str, Any]]
    learning_design: CoursewareLearningDesign | None
    provenance_graph: Any
    candidate: dict[str, Any]
    document: dict[str, Any]
    warnings: list[dict[str, Any]]


class CandidateReleaseCoordinator:
    """Build candidate records and commit them without mutating old releases."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def next_candidate_no(self, run_id: str) -> int:
        method = getattr(self.repository, "next_candidate_no", None)
        return int(method(run_id)) if method else 1

    def freeze(self, *, run_id: str, resource_id: str, release_policy: str,
               snapshots: list[dict[str, Any]], scenes: list[dict[str, Any]],
               provenance: dict[str, Any] | None = None,
               idempotency_key: str | None = None) -> dict[str, Any]:
        """Persist a candidate after freezing all inputs that define it."""
        scene_set = [{"scene_id": row.get("scene_id"),
                      "content_hash": row.get("content_hash"),
                      "revision_no": row.get("revision_no", row.get("attempt", 0))}
                     for row in sorted(scenes, key=lambda item: (item.get("scene_order", 0), item.get("scene_id", "")))]
        snapshot_set = [{"resource_id": row.get("resource_id"),
                         "version": row.get("version"),
                         "content_hash": row.get("content_hash")} for row in sorted(
                             snapshots, key=lambda item: item.get("resource_id", ""))]
        if idempotency_key:
            # The schema intentionally keeps the candidate key compact.  A
            # stable key-derived candidate number makes concurrent retries
            # converge on the same unique (run_id, candidate_no) row without
            # requiring a second mutable idempotency table.
            key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            candidate_no = int(key_hash[:12], 16)
            release_id = f"cwr_{run_id}_{key_hash[:16]}"
        else:
            candidate_no = self.next_candidate_no(run_id)
            release_id = f"cwr_{run_id}_{candidate_no}"
        row = {
            "release_id": release_id,
            "run_id": run_id,
            "resource_id": resource_id,
            "candidate_no": candidate_no,
            "status": "building",
            "release_policy": release_policy,
            "scene_set_hash": _hash(scene_set),
            "snapshot_set_hash": _hash(snapshot_set),
            "manifest_json": {"scene_set": scene_set, "snapshot_set": snapshot_set},
            "manifest_sha256": _hash({"scene_set": scene_set, "snapshot_set": snapshot_set}),
            "provenance_json": provenance or {},
        }
        if idempotency_key:
            row["manifest_json"]["idempotency_key_hash"] = _hash(idempotency_key)
        return self.repository.create_candidate_release_once(row)

    def commit(self, candidate: dict[str, Any], *, resource_id: str,
               resource_projection: dict[str, Any], job_status: str,
               warnings: list[dict[str, Any]], event_payload: dict[str, Any],
               manifest: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.repository.commit_release_once(
            candidate["release_id"], resource_id=resource_id,
            resource_projection=resource_projection, job_status=job_status,
            warnings=warnings, manifest=manifest, event_payload=event_payload,
        )

    def publish_artifacts(
        self,
        facts: CandidatePublication,
        *,
        checkpoint: Callable,
        emit_event: Callable,
        release_gate_error: type[Exception],
        page_quality_check: Callable,
        render: Callable,
        smoke_check: Callable,
        quality_report: Callable,
        save_html: Callable,
        save_artifact: Callable,
        package_artifact: Callable,
        resources_dir: Callable[[], Path],
    ) -> None:
        """Build required artifacts, then commit the original release manifest.

        Platform callables preserve the workflow module's existing test seams.
        The caller retains its control/error boundary and final checkpoint.
        """
        run_id = facts.run_id
        job = facts.job
        resource_id = facts.resource_id
        knowledge_base_id = facts.knowledge_base_id
        spec_id = facts.spec_id
        title = facts.title
        snapshots = facts.snapshots
        learning_design = facts.learning_design
        provenance_graph = facts.provenance_graph
        candidate = facts.candidate
        document = facts.document
        warnings = facts.warnings
        release_id = candidate["release_id"]
        document["event_context"] = {"resource_id": resource_id, "release_id": release_id}
        page_issues = page_quality_check(document)
        if page_issues:
            raise release_gate_error(
                "COURSEWARE_PAGE_QUALITY_GATE_FAILED", "重发布页面质量门失败",
                failed_dimensions=[str(item["code"]) for item in page_issues],
            )
        artifact = render(document)
        smoke_check(artifact)
        quality = quality_report(document, snapshots)
        measured_failures = [item for item in quality.get("failed_dimensions", [])
                             if not item.startswith("visual.")]
        if measured_failures:
            raise release_gate_error(
                "COURSEWARE_QUALITY_GATE_FAILED", "重发布质量门失败",
                failed_dimensions=measured_failures,
            )
        file_path, file_size, artifact_sha = save_html(
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
        self.repository.save_resource({
            "resource_id": resource_id, "resource_family_id": resource_id, "run_id": run_id,
            "batch_id": job.get("source_batch_id"),
            "learner_id": job["learner_id"], "knowledge_base_id": knowledge_base_id,
            "title": title, "topic": resource_topic,
            "status": "building", "version": 1,
            "file_path": file_path, "file_size": file_size, "artifact_sha256": artifact_sha,
            "renderer_version": RENDERER_VERSION, "runtime_version": RUNTIME_VERSION,
            "source_summary": [source_summary(item, usage_by_resource.get(item["resource_id"])) for item in snapshots], "warnings": warnings,
        }, links)
        self.repository.save_artifact({
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
        checkpoint(run_id, "candidate_artifact", state_json={
            "resource_id": resource_id, "artifact_sha256": artifact_sha,
        })
        required_package_failed = False
        for package_format, extension in (("zip", "zip"), ("scorm", "scorm.zip"), ("xapi", "xapi.zip")):
            try:
                package, manifest = package_artifact(
                    artifact, resource_id=resource_id, title=title, package_format=package_format,
                )
                package_path, package_size, package_sha = save_artifact(
                    job["learner_id"], resource_id, package, extension, release_id=release_id,
                )
                if package_format == "zip":
                    stored_path = Path(package_path)
                    if not stored_path.exists():
                        stored_path = (resources_dir() / "courseware" / job["learner_id"]
                                       / resource_id / "releases" / release_id / stored_path.name)
                    stored_package = stored_path.read_bytes()
                    with zipfile.ZipFile(__import__("io").BytesIO(stored_package)) as archive:
                        packaged_html = archive.read("index.html")
                    if packaged_html != artifact or hashlib.sha256(packaged_html).hexdigest() != artifact_sha:
                        raise release_gate_error(
                            "COURSEWARE_ZIP_HTML_MISMATCH", "required ZIP 的 index.html 与 HTML 产物不一致",
                        )
                self.repository.save_artifact({
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
                    raise release_gate_error(
                        "COURSEWARE_REQUIRED_ZIP_FAILED", "required ZIP 产物未通过写入/读取/hash 校验",
                    ) from exc
        if required_package_failed:
            raise release_gate_error("COURSEWARE_REQUIRED_ZIP_FAILED", "required ZIP 产物缺失")
        emit_event(run_id, "validating", "approved", {"artifact_sha256": artifact_sha,
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
                for item in self.repository.list_artifacts(resource_id)
                if item.get("release_id") == release_id
            ],
        }
        released = self.commit(
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


    def block(self, candidate: dict[str, Any], *, code: str, message: str) -> dict[str, Any] | None:
        method = getattr(self.repository, "block_release_once", None)
        if method:
            return method(candidate["release_id"], error_code=code, error_message=message)
        return None


__all__ = ["CandidateReleaseCoordinator"]
