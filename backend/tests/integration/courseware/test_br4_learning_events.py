from app.db.courseware.repository import MemoryCoursewareRepository


def test_learning_events_persist_redacted_occurrences_and_isolate_release():
    repo = MemoryCoursewareRepository()
    first = {"event_id": "occ-1", "occurrence_id": "occ-1", "event_schema_version": "1.0", "event_type": "answer_submitted", "resource_id": "r", "resource_version": 1, "release_id": "rel-1", "release_version": 1, "scene_id": "s", "scene_version": "1.0", "component_id": "q", "component_version": "1.0", "state": {"attempt": 1, "answer_text": "敏感原文", "component_state": {"ordering": {"order": ["a", "b"], "free_text": "不要保存"}}}}
    second = {**first, "event_id": "occ-2", "occurrence_id": "occ-2", "state": {"attempt": 2}}
    assert len(repo.ingest_learning_events([first, first, second])) == 3
    rows = repo.list_learning_events(resource_id="r", release_id="rel-1")
    assert len(rows) == 2 and "answer_text" not in rows[0]["state"]
    progress = repo.learning_progress(resource_id="r", release_id="rel-1")
    assert progress["current_scene_id"] == "s"
    assert progress["component_state_schema_version"] == "2.0"
    assert progress["component_state"] == {"s": {"q": {"component_version": "1.0", "value": {"ordering": {"order": ["a", "b"]}}}}}
    assert repo.learning_progress(resource_id="r", release_id="rel-2")["answer_count"] == 0
