from datetime import datetime, timezone

from app.models.reports.contracts import LearningPathGraphNodeV1, ReportResponse, ReportRevisionPartsV1


def test_report_3_contract_keeps_additive_defaults():
    report = ReportResponse.model_validate({
        "generated_at": datetime.now(timezone.utc), "learner_id": "learner",
        "radar": {"dimensions": [], "values": []}, "weak_points": [], "strong_points": [],
        "skill_level": "beginner", "learning_goal": "learn", "difficulty_curve": [],
    })
    assert report.report_schema_version == "4.1"
    assert report.learning_activity == {}
    assert report.recent_resource_credibility == []


def test_revision_parts_are_a_versioned_allow_list_contract():
    parts = ReportRevisionPartsV1(profile="a", mastery="b", activity="c", text_resources="d")
    assert parts.model_dump() == {
        "profile": "a", "mastery": "b", "activity": "c", "text_resources": "d",
        "resource_match": "", "path": "",
    }


def test_learning_path_contract_preserves_placement_verification_status():
    node = LearningPathGraphNodeV1.model_validate({
        "skill_node_id": "foundation",
        "name": "基础",
        "progress_status": "unplanned",
        "mastery_status": "unassessed",
        "confidence": "none",
        "role": "verification",
        "blocked": False,
        "stable_order": 1,
        "placement_verification_status": "verification_required",
    })

    assert node.placement_verification_status == "verification_required"
