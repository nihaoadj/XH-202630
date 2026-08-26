from datetime import datetime, timedelta, timezone

from .test_api import _client, _run_worker


def test_api_creation_only_enqueues_and_worker_persists_checkpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    })
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["status"] == "queued"
    assert client.get(f"/api/resources/courseware/jobs/{run_id}").json()["status"] == "queued"

    result = _run_worker(client)
    assert result["processed"] == 1
    completed = client.get(f"/api/resources/courseware/jobs/{run_id}").json()
    assert completed["status"] in {"published", "published_with_warnings"}
    checkpoints = client.app.container.courseware_service().repo.checkpoints
    assert any(key[0] == run_id for key in checkpoints)


def test_cancelled_queued_job_is_terminal_without_running_workflow(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    }).json()
    run_id = created["run_id"]
    cancelled = client.post(f"/api/resources/courseware/jobs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    result = _run_worker(client)
    assert result["processed"] == 1
    assert client.get(f"/api/resources/courseware/jobs/{run_id}").json()["status"] == "cancelled"


def test_worker_failure_after_checkpoint_retries_without_rebuilding_completed_scenes(tmp_path, monkeypatch):
    """A process failure after a durable checkpoint resumes from that checkpoint."""
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    }).json()
    run_id = created["run_id"]
    workflow = service.workflow
    original_checkpoint = workflow._checkpoint_completed
    tripped = {"value": False}

    def fail_after_scene_checkpoint(checkpoint_run_id, stage, **kwargs):
        original_checkpoint(checkpoint_run_id, stage, **kwargs)
        if stage == "scenes" and not tripped["value"]:
            tripped["value"] = True
            raise RuntimeError("simulated worker kill after checkpoint")

    monkeypatch.setattr(workflow, "_checkpoint_completed", fail_after_scene_checkpoint)
    first = _run_worker(client)
    assert first["failed"] == 1
    assert service.repo.latest_checkpoint(run_id)["stage"] == "scenes"
    spec_before = service.repo.get_spec_by_run(run_id)
    scenes_before = [(row["scene_id"], row["content_hash"], row["attempt"])
                     for row in service.repo.list_scenes(spec_before["spec_id"])]

    # The executor's bounded retry delay is part of the durable outbox state;
    # advancing the test clock makes the second worker deterministic.
    task = next(item for item in service.repo.outbox.values() if item["run_id"] == run_id)
    task["next_attempt_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(workflow, "_checkpoint_completed", original_checkpoint)
    second = _run_worker(client)
    assert second["processed"] == 1
    assert client.get(f"/api/resources/courseware/jobs/{run_id}").json()["status"] in {"published", "published_with_warnings"}
    scenes_after = [(row["scene_id"], row["content_hash"], row["attempt"])
                    for row in service.repo.list_scenes(spec_before["spec_id"])]
    assert scenes_after == scenes_before


def test_duplicate_run_delivery_is_idempotent_and_only_one_release_is_visible(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide"],
    }).json()
    run_id = created["run_id"]
    _run_worker(client)
    job = service.repo.get_job(run_id)
    assert job["released_release_id"]
    # A duplicate delivery after completion is ignored by the durable outbox
    # claim, so it cannot create a second release or event.
    duplicate = service.repo.enqueue_task_once({
        "outbox_id": f"duplicate-{run_id}", "run_id": run_id,
        "event_type": "courseware.run", "task_kind": "courseware.run",
        "payload": {"run_id": run_id}, "idempotency_key": f"duplicate:{run_id}",
    })
    assert duplicate["status"] == "queued"
    _run_worker(client)
    assert service.repo.get_job(run_id)["released_release_id"] == job["released_release_id"]
    assert len(service.repo.releases) == 1
    assert len([event for event in service.repo.list_events(run_id) if event["stage"] == "publishing"]) == 1
