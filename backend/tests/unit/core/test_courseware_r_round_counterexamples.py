from app.db.courseware.repository import MemoryCoursewareRepository


def test_component_projection_isolated_by_scene_and_component_instance():
    repo = MemoryCoursewareRepository()
    rows = [
        {"event_id": "e1", "event_type": "flashcard_flipped", "resource_id": "r", "release_id": "rel", "scene_id": "s1", "component_id": "flash-a", "component_version": "1.0", "state": {"component_state": {"flashcard": {"status": "back"}}}},
        {"event_id": "e2", "event_type": "flashcard_flipped", "resource_id": "r", "release_id": "rel", "scene_id": "s1", "component_id": "flash-b", "component_version": "1.0", "state": {"component_state": {"flashcard": {"status": "front"}}}},
    ]
    repo.ingest_learning_events(rows)
    progress = repo.learning_progress(resource_id="r", release_id="rel")
    assert progress["component_state_schema_version"] == "2.0"
    assert progress["component_state"] == {
        "s1": {
            "flash-a": {"component_version": "1.0", "value": {"flashcard": {"status": "back"}}},
            "flash-b": {"component_version": "1.0", "value": {"flashcard": {"status": "front"}}},
        }
    }
