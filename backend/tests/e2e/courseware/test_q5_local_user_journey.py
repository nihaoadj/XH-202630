"""One state-driven local journey through the public courseware API."""

from backend.tests.integration.courseware.test_ai_first_generation import _WorkflowFakeGateway
from backend.tests.integration.courseware.test_api import _client, _run_worker


def test_local_user_journey_preferences_progress_refresh_and_release_isolation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake

    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide", "assessment"],
        "learning_goal": "完成一次可追溯检索", "expected_duration_minutes": 30,
        "interaction_intensity": "high", "visual_style_id": "midnight", "publish_mode": "automatic",
    })
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["request_options"]["interaction_intensity"] == "high"

    _run_worker(client)
    # Read the public event stream after the independent Worker finishes. A
    # terminal stream drains its durable events and closes, which makes this
    # assertion deterministic for the in-process HTTP client while still
    # exercising the public SSE contract.
    stream = client.get(f"/api/resources/courseware/jobs/{run_id}/events?after_sequence=0")
    assert stream.status_code == 200 and "courseware_progress" in stream.text
    completed = client.get(f"/api/resources/courseware/jobs/{run_id}/detail").json()
    assert completed["status"] == "published"
    assert completed["quality_summary"]["ai_full_course_success"] is True, (
        completed["quality_summary"], service.repo.list_events(run_id)
    )

    resource_id = completed["resource_id"]
    resource = client.get(f"/api/resources/courseware/items/{resource_id}").json()
    release_id = resource["released_release_id"]
    event = {
        "event_id": "journey-scene-1", "occurrence_id": "journey-scene-1", "event_schema_version": "1.0",
        "event_type": "scene_viewed", "resource_id": resource_id, "resource_version": resource["version"],
        "release_id": release_id, "release_version": 1, "scene_id": "cws_scene_1", "scene_version": "1.0",
        "state": {"scene_index": 1, "scene_count": 3, "component_state": {"ordering": {"order": ["a", "b"], "free_text": "drop"}}},
    }
    first = client.post(f"/api/resources/courseware/items/{resource_id}/learning-events", json={"events": [event]})
    second = client.post(f"/api/resources/courseware/items/{resource_id}/learning-events", json={"events": [event]})
    assert first.status_code == second.status_code == 200
    progress = client.get(f"/api/resources/courseware/items/{resource_id}/learning-progress?release_id={release_id}").json()
    assert progress["current_scene_id"] == "cws_scene_1"
    assert progress["current_scene_index"] == 1
    assert progress["component_state"] == {"ordering": {"order": ["a", "b"]}}
    assert client.get(f"/api/resources/courseware/items/{resource_id}/learning-progress?release_id=old-release").json()["answer_count"] == 0


def test_local_journey_keeps_cross_feedback_batch_request_rejected(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, mixed_feedback_batches=True)
    response = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide", "assessment"],
        "publish_mode": "automatic",
    })
    assert response.status_code == 200
    _run_worker(client)
    rejected = client.get(f"/api/resources/courseware/jobs/{response.json()['run_id']}").json()
    assert rejected["status"] == "rejected_admission"
    assert "同一反馈批次" in rejected["error_message"]
