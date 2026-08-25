from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult
from app.models.learners.history import DiagnosticRunRecord
from app.models.learners.mastery import (
    AbilityMasteryStateV2,
    AbilityNodeProjectionV1,
    AbilityNodeSummaryV1,
    AbilityNodesResponseV1,
)
from app.models.learning_documents.schemas import LearningResource
from app.services.reports import reports as reports_module
from app.services.reports.reports import ReportService


def _state(node_id, *, score, status, objective_count, confidence="medium"):
    return AbilityMasteryStateV2(
        learner_id="learner", knowledge_base_id="kb", skill_node_id=node_id,
        mastery_score=score, status=status, confidence=confidence,
        objective_evidence_count=objective_count,
    )


def _projection():
    foundation = AbilityNodeProjectionV1(
        skill_node_id="foundation", name="基础", prerequisites=[], children=["advanced"],
        mastery=_state("foundation", score=0.4, status="weak", objective_count=1),
    )
    advanced = AbilityNodeProjectionV1(
        skill_node_id="advanced", name="进阶", prerequisites=["foundation"], children=[],
        mastery=_state("advanced", score=None, status="unassessed", objective_count=0, confidence="none"),
    )
    return AbilityNodesResponseV1(
        learner_id="learner", knowledge_base_id="kb", as_of_profile_version=1,
        summary=AbilityNodeSummaryV1(
            total_count=2, mastered_count=0, learning_count=0, weak_count=1,
            self_reported_count=0, unassessed_count=1, medium_or_high_confidence_count=1,
        ),
        nodes=[foundation, advanced], edges=[{"from": "foundation", "to": "advanced"}],
    )


def _service():
    return ReportService(MemoryResourceRepository(), MemoryFeedbackRepository())


def test_blind_spot_map_only_projects_dimension_scores_with_exact_question_trace():
    attempt = SimpleNamespace(
        attempt_id="attempt", submitted_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        metadata={"question_trace": [{
            "question_id": "q1", "skill_node_id": "foundation", "diagnostic_dimension": "concept",
        }]},
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="foundation", question_ids=["q1"], correct_count=0, total_count=1,
        )],
    )
    result = _service()._build_blind_spot_map(_projection(), [attempt])
    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    scenario = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "scenario")
    unassessed = next(item for item in result["cells"] if item["skill_node_id"] == "advanced" and item["dimension"] == "concept")
    assert concept["score"] == 0.0
    assert concept["status"] == "verified_weak"
    assert scenario["score"] is None
    assert scenario["status"] == "needs_evidence"
    assert unassessed["score"] is None
    assert unassessed["status"] == "unassessed"


def test_blind_spot_map_surfaces_verified_node_score_when_legacy_questions_lack_dimension():
    attempt = SimpleNamespace(
        attempt_id="attempt", submitted_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        metadata={"question_trace": [{"question_id": "q1", "skill_node_id": "foundation"}]},
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="foundation", question_ids=["q1"], correct_count=0, total_count=1,
        )],
    )

    result = _service()._build_blind_spot_map(_projection(), [attempt])

    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    scenario = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "scenario")
    assert concept["score"] == 0.4
    assert concept["status"] == "verified_weak"
    assert concept["reason_codes"] == ["FORMAL_NODE_EVIDENCE_NO_DIMENSION"]
    assert scenario["score"] is None
    assert result["summary"]["measured_node_count"] == 1


def test_blind_spot_map_consumes_deidentified_initial_diagnosis_trace():
    run = DiagnosticRunRecord(
        diagnostic_result_id="diagnosis-1", learner_id="learner", knowledge_base_id="kb",
        ability_level="初级", raw_result={"blind_spot_trace": [{
            "question_id": "diagnostic-q1", "skill_node_id": "foundation",
            "diagnostic_dimension": "concept", "correct": False, "measurement_status": "measured",
        }]},
        created_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )

    result = _service()._build_blind_spot_map(_projection(), [], [run])

    concept = next(item for item in result["cells"] if item["skill_node_id"] == "foundation" and item["dimension"] == "concept")
    assert concept["score"] == 0.0
    assert concept["status"] == "verified_weak"


def test_report_node_order_respects_prerequisites_then_tier():
    base = SimpleNamespace(skill_node_id="base", name="基础", tier=1, prerequisites=[])
    independent = SimpleNamespace(skill_node_id="independent", name="同阶", tier=1, prerequisites=[])
    advanced = SimpleNamespace(skill_node_id="advanced", name="进阶", tier=2, prerequisites=["base"])

    ordered = ReportService._ordered_ability_nodes([advanced, independent, base])

    assert [item.skill_node_id for item in ordered] == ["base", "independent", "advanced"]


def test_report_revision_changes_when_the_client_projection_changes(monkeypatch):
    service = _service()
    parts = {"profile": "profile", "mastery": "mastery"}

    previous_revision = service._revision(parts, 30)
    monkeypatch.setattr(reports_module, "REPORT_PROJECTION_VERSION", "4.1-test-projection")

    assert service._revision(parts, 30) != previous_revision


def test_resource_curve_and_path_graph_do_not_invent_readiness_or_prerequisites():
    resources = [
        LearningResource(
            resource_id="foundation-guide", learner_id="learner", topic="基础", resource_type="讲义",
            difficulty="中级", content_text="", knowledge_points=["foundation"], source_refs=[],
            learning_path_node="foundation", publication_status="published",
        ),
        LearningResource(
            resource_id="advanced-guide", learner_id="learner", topic="进阶", resource_type="讲义",
            difficulty="未知", content_text="", knowledge_points=["advanced"], source_refs=[],
            learning_path_node="advanced", publication_status="published",
        ),
    ]
    service = _service()
    curve = service._build_resource_difficulty_curve(_projection(), resources)
    foundation = next(item for item in curve["points"] if item["resource_id"] == "foundation-guide")
    advanced = next(item for item in curve["points"] if item["resource_id"] == "advanced-guide")
    assert foundation["learner_readiness_score"] == 0.4
    assert foundation["match_status"] == "challenging"
    assert advanced["learner_readiness_score"] is None
    assert advanced["resource_difficulty_score"] is None
    assert advanced["match_status"] == "not_measured"

    graph = service._build_learning_path_graph(_projection(), None, None)
    base = next(item for item in graph["nodes"] if item["skill_node_id"] == "foundation")
    next_node = next(item for item in graph["nodes"] if item["skill_node_id"] == "advanced")
    assert base["role"] == "remedial"
    assert next_node["blocked"] is True
    assert next_node["blocked_by_node_ids"] == ["foundation"]
    assert graph["edges"] == [{"source_skill_node_id": "foundation", "target_skill_node_id": "advanced", "relation": "prerequisite"}]


def test_weakness_groups_keep_ready_and_maintained_nodes_out_of_evidence_risk_groups():
    priorities = [
        SimpleNamespace(skill_node_id="ready", priority_group="ready_uncovered", reason_codes=[], mastery_score=None, confidence=SimpleNamespace(value="none")),
        SimpleNamespace(skill_node_id="maintained", priority_group="maintain_mastery", reason_codes=[], mastery_score=.9, confidence=SimpleNamespace(value="high")),
        SimpleNamespace(skill_node_id="blocked", priority_group="blocked_uncovered", reason_codes=["PREREQUISITE_REQUIRED"], mastery_score=None, confidence=SimpleNamespace(value="none")),
    ]
    groups = ReportService._weakness_groups(priorities, {"blocked": "被阻塞节点"})
    assert groups["verified_weak"] == []
    assert groups["regressing_learning"] == []
    assert groups["needs_evidence"][0]["skill_node_id"] == "blocked"
