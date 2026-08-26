from backend.tests.integration.courseware.test_ai_first_generation import _WorkflowFakeGateway
from backend.tests.integration.courseware.test_api import _client, _run_worker


def test_new_job_freezes_source_batch_before_worker_and_resource_inherits_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake
    response = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner",
        "source_resource_ids": ["lecture", "guide", "assessment"],
        "publish_mode": "automatic",
    })
    assert response.status_code == 200
    assert response.json()["source_batch_id"] == "batch-courseware"
    _run_worker(client)
    detail = client.get(f"/api/resources/courseware/jobs/{response.json()['run_id']}/detail").json()
    resource = client.get(f"/api/resources/courseware/items/{detail['resource_id']}").json()
    assert resource["batch_id"] == "batch-courseware"


def test_mixed_release_event_batch_is_rejected_without_partial_write(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    service = client.app.container.courseware_service()
    fake = _WorkflowFakeGateway()
    service.llm_gateway = fake
    service.workflow.llm_gateway = fake
    created = client.post("/api/resources/courseware/jobs", json={
        "learner_id": "courseware-learner", "source_resource_ids": ["lecture", "guide", "assessment"],
    })
    _run_worker(client)
    resource_id = client.get(f"/api/resources/courseware/jobs/{created.json()['run_id']}/detail").json()["resource_id"]
    resource = client.get(f"/api/resources/courseware/items/{resource_id}").json()
    current = resource["released_release_id"]
    events = [
        {"event_id": "r-current", "event_type": "scene_viewed", "resource_id": resource_id, "release_id": current, "scene_id": "s1", "state": {}},
        {"event_id": "r-old", "event_type": "scene_viewed", "resource_id": resource_id, "release_id": "old-release", "scene_id": "s2", "state": {}},
    ]
    response = client.post(f"/api/resources/courseware/items/{resource_id}/learning-events", json={"events": events})
    assert response.status_code == 409
    assert client.get(f"/api/resources/courseware/items/{resource_id}/learning-progress?release_id={current}").json()["viewed_scene_ids"] == []
