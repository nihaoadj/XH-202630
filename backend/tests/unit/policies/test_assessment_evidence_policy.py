from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.mastery import MasteryService


def _service():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    ))
    nodes = [SimpleNamespace(
        node_id="skill-a", name="A", description=None, level="L1",
        prerequisites=[], children=[],
    )]
    repository = MemoryMasteryRepository(learners)
    return MasteryService(repository, SimpleNamespace(list_skill_nodes=lambda _kb: nodes)), learners


def _metadata(session_id, question_ids, dimensions, audit="single_pass"):
    return {
        "assessment_session_id": session_id,
        "assessment_form_id": f"form-{session_id}",
        "question_ids": question_ids,
        "covered_dimensions": dimensions,
        "scoring_audit_status": audit,
    }


def test_single_high_diagnosis_is_baseline_and_two_independent_sessions_confirm_mastery():
    service, learners = _service()
    now = datetime.now(timezone.utc)
    service.apply_diagnosis(
        learners.get("learner"), {"skill-a": 0.9}, source_id="diagnosis-1", source_hash="a" * 64,
        occurred_at=now,
        assessment_metadata={"skill-a": _metadata(
            "session-1", ["q1", "q2", "q3"], ["concept", "scenario", "misconception"],
        )},
    )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.status.value == "learning"
    assert state.objective_evidence_count == 1

    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-1", point_scores={"skill-a": 0.9},
        occurred_at=now + timedelta(minutes=1),
        assessment_metadata={
            "assessment_kind": "learning_check",
            "assessment_session_id": "session-2",
            "assessment_form_id": "form-session-2",
            "question_trace": [
                {"question_id": "q4", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q5", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
                {"question_id": "q6", "skill_node_id": "skill-a", "diagnostic_dimension": "misconception"},
            ],
        },
    )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.status.value == "mastered"
    assert state.distinct_objective_source_count == 2


def test_mastery_threshold_is_inclusive_at_eighty_percent():
    service, learners = _service()
    now = datetime.now(timezone.utc)
    dimensions = ["concept", "scenario", "misconception"]
    service.apply_diagnosis(
        learners.get("learner"), {"skill-a": 0.8}, source_id="diagnosis-80", source_hash="e" * 64,
        occurred_at=now,
        assessment_metadata={"skill-a": _metadata("session-80-1", ["q1", "q2", "q3"], dimensions)},
    )
    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-80", point_scores={"skill-a": 0.8},
        occurred_at=now + timedelta(minutes=1),
        assessment_metadata={
            "assessment_session_id": "session-80-2",
            "question_trace": [
                {"question_id": "q4", "skill_node_id": "skill-a", "diagnostic_dimension": dimension}
                for dimension, question_id in zip(dimensions, ["q4", "q5", "q6"])
            ],
        },
    )
    assert service.repository.list_states("learner", "kb")[0].status.value == "mastered"


def test_repeated_question_set_and_failed_llm_audit_do_not_add_objective_evidence():
    service, learners = _service()
    now = datetime.now(timezone.utc)
    service.apply_diagnosis(
        learners.get("learner"), {"skill-a": 0.9}, source_id="diagnosis-1", source_hash="b" * 64,
        occurred_at=now,
        assessment_metadata={"skill-a": _metadata(
            "session-1", ["q1", "q2", "q3"], ["concept", "scenario", "misconception"],
        )},
    )
    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-repeat", point_scores={"skill-a": 0.9},
        occurred_at=now + timedelta(minutes=1),
        assessment_metadata={
            "assessment_session_id": "session-2",
            "assessment_form_id": "form-session-2",
            "question_trace": [
                {"question_id": "q1", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q2", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
                {"question_id": "q3", "skill_node_id": "skill-a", "diagnostic_dimension": "misconception"},
            ],
        },
    )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.objective_evidence_count == 1
    assert state.status.value == "learning"
    assert service.repository.list_events("learner", "kb")[-1].evidence_eligible is False

    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-llm-disagree", point_scores={"skill-a": 0.9},
        occurred_at=now + timedelta(minutes=2),
        assessment_metadata={
            "assessment_session_id": "session-3",
            "assessment_form_id": "form-session-3",
            "scoring_audit": {"skill-a": "double_disagreement"},
            "question_trace": [
                {"question_id": "q7", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q8", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
                {"question_id": "q9", "skill_node_id": "skill-a", "diagnostic_dimension": "misconception"},
            ],
        },
    )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.objective_evidence_count == 1
    assert service.repository.list_events("learner", "kb")[-1].scoring_audit_status == "double_disagreement"


def test_later_assessment_can_promote_after_initial_calibration_without_repeating_dimensions():
    service, learners = _service()
    now = datetime.now(timezone.utc)
    service.apply_diagnosis(
        learners.get("learner"), {"skill-a": 0.9}, source_id="diagnosis-1", source_hash="c" * 64,
        occurred_at=now,
        assessment_metadata={"skill-a": _metadata(
            "session-1", ["q1", "q2", "q3"], ["concept", "scenario", "misconception"],
        )},
    )
    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-incomplete", point_scores={"skill-a": 0.95},
        occurred_at=now + timedelta(minutes=1),
        assessment_metadata={
            "assessment_session_id": "session-2",
            "question_trace": [
                {"question_id": "q4", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q5", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
            ],
        },
    )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.objective_evidence_count == 2
    assert state.status.value == "mastered"

    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-2", point_scores={"skill-a": 0.95},
        occurred_at=now + timedelta(minutes=2),
        assessment_metadata={
            "assessment_session_id": "session-3",
            "question_trace": [
                {"question_id": "q6", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q7", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
                {"question_id": "q8", "skill_node_id": "skill-a", "diagnostic_dimension": "misconception"},
            ],
        },
    )
    assert service.repository.list_states("learner", "kb")[0].status.value == "mastered"

    service.apply_learning_attempt(
        learners.get("learner"), attempt_id="attempt-low", point_scores={"skill-a": 0.5},
        occurred_at=now + timedelta(minutes=3),
        assessment_metadata={
            "assessment_session_id": "session-4",
            "question_trace": [
                {"question_id": "q9", "skill_node_id": "skill-a", "diagnostic_dimension": "concept"},
                {"question_id": "q10", "skill_node_id": "skill-a", "diagnostic_dimension": "scenario"},
                {"question_id": "q11", "skill_node_id": "skill-a", "diagnostic_dimension": "misconception"},
            ],
        },
    )
    assert service.repository.list_states("learner", "kb")[0].status.value == "weak"


def test_later_assessment_dimensions_are_accumulated_across_sessions():
    service, learners = _service()
    now = datetime.now(timezone.utc)
    service.apply_diagnosis(
        learners.get("learner"), {"skill-a": 0.9}, source_id="diagnosis-partial", source_hash="d" * 64,
        occurred_at=now,
        assessment_metadata={"skill-a": _metadata("session-1", ["q1"], ["concept"])},
    )
    for index, dimension in enumerate(("scenario", "misconception"), start=2):
        service.apply_learning_attempt(
            learners.get("learner"), attempt_id=f"attempt-{index}", point_scores={"skill-a": 0.95},
            occurred_at=now + timedelta(minutes=index),
            assessment_metadata={
                "assessment_session_id": f"session-{index}",
                "question_trace": [{
                    "question_id": f"q{index}", "skill_node_id": "skill-a",
                    "diagnostic_dimension": dimension,
                }],
            },
        )
    state = service.repository.list_states("learner", "kb")[0]
    assert state.status.value == "mastered"
