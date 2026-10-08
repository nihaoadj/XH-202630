"""Acceptance tests for immutable candidate publication."""

from pathlib import Path

from app.core.storage import file_storage
from app.core.courseware.storage import save_courseware_html
from app.db.courseware.repository import MemoryCoursewareRepository
from app.services.courseware.release import CandidateReleaseCoordinator


def _repo() -> MemoryCoursewareRepository:
    repo = MemoryCoursewareRepository()
    repo.create_job({"run_id": "run-a7", "learner_id": "learner-a7", "request_hash": "hash-a7",
                     "status": "queued", "release_policy": "resilient", "next_event_sequence": 1})
    repo.save_resource({"resource_id": "resource-a7", "resource_family_id": "resource-a7", "run_id": "run-a7",
                        "learner_id": "learner-a7", "title": "A7", "topic": "测试", "status": "building",
                        "version": 1, "file_path": "candidate", "file_size": 1, "artifact_sha256": "old",
                        "renderer_version": "r1", "runtime_version": "rt1", "source_summary": [], "warnings": []}, [])
    return repo


def _candidate(coordinator: CandidateReleaseCoordinator, repo: MemoryCoursewareRepository):
    return coordinator.freeze(run_id="run-a7", resource_id="resource-a7", release_policy="resilient",
                              snapshots=[{"resource_id": "source", "version": 1, "content_hash": "source-hash"}],
                              scenes=[{"scene_id": "scene", "scene_order": 0, "content_hash": "scene-hash", "revision_no": 1}],
                              provenance={"root_hash": "root"})


def test_commit_is_idempotent_and_switches_projection_once():
    repo = _repo()
    coordinator = CandidateReleaseCoordinator(repo)
    candidate = _candidate(coordinator, repo)
    event = {"event_id": "release-event-a7", "run_id": "run-a7", "stage": "publishing",
             "status": "published", "payload": {"release_id": candidate["release_id"]}}
    first = coordinator.commit(candidate, resource_id="resource-a7",
                               resource_projection={"file_path": "new", "file_size": 3, "artifact_sha256": "new"},
                               job_status="published", warnings=[], event_payload=event)
    second = coordinator.commit(candidate, resource_id="resource-a7",
                                resource_projection={"file_path": "other", "file_size": 4, "artifact_sha256": "other"},
                                job_status="published", warnings=[], event_payload=event)
    assert first and second and first["release_id"] == second["release_id"]
    assert repo.get_resource("resource-a7")["file_path"] == "new"
    assert repo.get_resource("resource-a7")["released_release_id"] == candidate["release_id"]
    assert len(repo.list_events("run-a7")) == 1


def test_blocked_candidate_keeps_previous_release_pointer_and_files_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "_get_resources_dir", lambda: tmp_path)
    repo = _repo()
    coordinator = CandidateReleaseCoordinator(repo)
    first = _candidate(coordinator, repo)
    old_path, _, _ = save_courseware_html("learner-a7", "resource-a7", b"old", release_id=first["release_id"])
    coordinator.commit(first, resource_id="resource-a7", resource_projection={"file_path": old_path, "file_size": 3,
                                                                                  "artifact_sha256": "old"},
                       job_status="published", warnings=[], event_payload={"event_id": "event-old", "payload": {}})
    second = coordinator.freeze(run_id="run-a7", resource_id="resource-a7", release_policy="resilient",
                                snapshots=[{"resource_id": "source", "version": 2, "content_hash": "source-new"}],
                                scenes=[{"scene_id": "scene", "scene_order": 0, "content_hash": "scene-new", "revision_no": 2}],
                                provenance={"root_hash": "root-new"})
    new_path, _, _ = save_courseware_html("learner-a7", "resource-a7", b"new", release_id=second["release_id"])
    coordinator.block(second, code="REQUIRED_ARTIFACT_FAILED", message="zip failed")
    assert old_path != new_path
    assert Path(tmp_path / "courseware" / "learner-a7" / "resource-a7" / "releases" / first["release_id"] / "index.html").read_bytes() == b"old"
    assert repo.get_resource("resource-a7")["released_release_id"] == first["release_id"]
    assert repo.get_job("run-a7")["status"] == "release_blocked"


def test_idempotency_key_converges_to_one_candidate():
    repo = _repo()
    coordinator = CandidateReleaseCoordinator(repo)
    kwargs = dict(run_id="run-a7", resource_id="resource-a7", release_policy="resilient",
                  snapshots=[], scenes=[], provenance={}, idempotency_key="same-key")
    one = coordinator.freeze(**kwargs)
    two = coordinator.freeze(**kwargs)
    assert one["release_id"] == two["release_id"]
    assert len(repo.releases) == 1
