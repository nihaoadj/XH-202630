from app.core.courseware.release_cycle import assess_release_cycle


def test_release_cycle_detects_hard_gate_bypass_and_duplicate_release():
    report = assess_release_cycle([
        {"event_sequence": 1, "run_id": "run-1", "stage": "quality_gate", "status": "rejected", "payload": {"code": "UNKNOWN_COMPONENT"}},
        {"event_sequence": 2, "run_id": "run-1", "stage": "publishing", "status": "released", "payload": {"release_id": "rel-1", "candidate_id": "candidate-1"}},
        {"event_sequence": 3, "run_id": "run-1", "stage": "publishing", "status": "released", "payload": {"release_id": "rel-1", "candidate_id": "candidate-1"}},
    ])

    assert report["status"] == "PARTIAL"
    assert {"HARD_GATE_BYPASS", "DUPLICATE_RELEASE"} <= set(report["violations"])
    assert report["observation_status"] == "EXTERNAL_PENDING"
    assert {"window", "build", "metrics", "artifacts", "learning_documents_regression"} <= set(report)


def test_release_cycle_redacts_and_summarizes_observation_metadata():
    report = assess_release_cycle([
        {"event_sequence": 1, "run_id": "run-1", "stage": "publishing", "status": "released",
         "payload": {"release_id": "rel-1", "artifact_hash": "a" * 64, "prompt": "must-not-leak"}},
    ], metadata={"started_at": "2026-08-23T00:00:00Z", "ended_at": "2026-08-23T01:00:00Z",
                 "build_version": "build-1", "config_version": "config-1", "evidence_paths": ["safe.json"],
                 "learning_documents_regression": {"text": "passed", "practice": "passed", "assessment": "passed", "case_study": "passed", "checklist": "passed"}})

    assert report["window"]["started_at"] == "2026-08-23T00:00:00Z"
    assert report["build"] == {"build_version": "build-1", "config_version": "config-1"}
    assert report["artifacts"]["release_hashes"] == ["a" * 64]
    assert "must-not-leak" not in str(report)


def test_release_cycle_rejects_empty_events_and_incomplete_observation_metadata():
    report = assess_release_cycle([])

    assert report["status"] == "PARTIAL"
    assert "OBSERVATION_EVIDENCE_MISSING" in report["violations"]


def test_release_cycle_only_treats_reject_then_release_in_the_same_run_as_bypass():
    metadata = {"started_at": "2026-08-23T00:00:00Z", "ended_at": "2026-08-24T00:00:00Z"}
    report = assess_release_cycle([
        {"event_sequence": 1, "run_id": "rejected-run", "stage": "quality_gate", "status": "rejected", "payload": {}},
        {"event_sequence": 1, "run_id": "published-run", "stage": "publishing", "status": "released", "payload": {"release_id": "release-1"}},
        {"event_sequence": 2, "run_id": "published-run", "stage": "publishing", "status": "released", "payload": {"release_id": "release-2"}},
    ], metadata=metadata)

    assert "HARD_GATE_BYPASS" not in report["violations"]
    assert "DUPLICATE_RELEASE" not in report["violations"]
