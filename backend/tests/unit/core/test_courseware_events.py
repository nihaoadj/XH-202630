from app.services.courseware.events import CoursewareEventProjector


def test_learning_events_are_idempotent_release_scoped_and_redact_raw_input():
    projector = CoursewareEventProjector()
    event = projector.record_runtime(
        "answer_submitted", resource_id="resource-1", release_id="release-a", scene_id="scene-1",
        state={"attempt": 1, "answer_text": "敏感原始答案"},
    )
    assert event.state == {"attempt": 1}
    assert projector.record(event).event_id == event.event_id
    assert len(projector.events()) == 1
    assert projector.progress(resource_id="resource-1", release_id="release-old")["answer_count"] == 0
    assert projector.progress(resource_id="resource-1", release_id="release-a")["answer_count"] == 1


def test_replay_deduplicates_and_projects_completion_without_mutating_profile():
    projector = CoursewareEventProjector()
    events = [
        projector.record_runtime("scene_viewed", resource_id="r", release_id="a", scene_id="s1", state={"scene_index": 0}),
        projector.record_runtime("scene_completed", resource_id="r", release_id="a", scene_id="s1", state={"completed": True}),
        projector.record_runtime("courseware_completed", resource_id="r", release_id="a", state={"completed": True}),
    ]
    assert projector.replay(events) == 0
    assert projector.progress(resource_id="r", release_id="a") == {
        "resource_id": "r", "release_id": "a", "viewed_scene_ids": ["s1"],
        "completed_scene_ids": ["s1"], "courseware_completed": True, "answer_count": 0,
    }
