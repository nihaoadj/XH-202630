"""Read server-recorded initial diagnostic passes without marking courses complete."""

from app.models.learning_documents.schemas import LearnerProfile


def initial_passed_node_ids(profile: LearnerProfile) -> set[str]:
    preferences = profile.learning_preferences
    metadata = preferences.metadata if preferences else {}
    flow = metadata.get("initial_diagnostic_flow", {}) if isinstance(metadata, dict) else {}
    if not isinstance(flow, dict) or flow.get("status") != "final" or flow.get("pass_policy_version") != "initial-pass/v1":
        return set()
    passes = flow.get("node_passes", {})
    if not isinstance(passes, dict):
        return set()
    return {
        node_id for node_id, evidence in passes.items()
        if isinstance(evidence, dict)
        and evidence.get("diagnostic_result_id")
        and evidence.get("valid_question_count", 0) >= 3
        and evidence.get("correct_question_count") == evidence.get("valid_question_count")
        and set(evidence.get("covered_dimensions", [])) >= {"concept", "scenario", "misconception"}
    }
