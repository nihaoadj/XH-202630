"""Prepare a confirmed follow-up without creating jobs or committing learner facts."""

from dataclasses import dataclass
from typing import Any

from app.models.feedback.feedback_loop import FeedbackFollowupSelection, FeedbackResourceOption
from app.models.learners.mastery import NextGenerationOptionsV1
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile


@dataclass(frozen=True)
class FollowupRequestPlan:
    request: GenerateRequest
    resource_types: list[str]
    source_batch_id: str | None

    def requests(self, *, include_claim_check: bool) -> list[GenerateRequest]:
        # Called within the Service's original job-creation exception boundary.
        if include_claim_check and len(self.resource_types) > 1:
            return [self.request.model_copy(update={
                "resource_types": [resource_type], "include_claim_check": True,
            }) for resource_type in self.resource_types]
        return [self.request]


def build_followup_plan(
    profile: LearnerProfile,
    selection: FeedbackFollowupSelection,
    option: FeedbackResourceOption,
    *,
    attempt_id: str,
    decision_id: str,
    difficulty: str,
    selection_type: str | None,
    correction_snapshot: dict[str, Any] | None,
    historical_assessment_questions: list[dict[str, object]],
    intent_options: NextGenerationOptionsV1 | None,
    source_batch_id: object = None,
) -> FollowupRequestPlan:
    """Consume validated choices; Mastery confirmation and stable IDs stay in Service."""
    is_correction_package = selection.option_id == "personalized-correction-package-v1"
    resource_types = (["个性化纠错训练包", "分阶测试题"] if is_correction_package
                      else (selection.resource_types or option.resource_types))
    constraints = {
        "feedback_attempt_id": attempt_id,
        "source_attempt_id": attempt_id,
        "feedback_option_id": option.option_id,
        "feedback_decision_id": decision_id,
        "feedback_resource_types": resource_types,
        "feedback_difficulty": difficulty,
        **({"selection_type": "correction_package"} if correction_snapshot else {}),
        **({"selection_type": selection_type} if selection_type is not None else {}),
        **({"correction_focus_snapshot": correction_snapshot} if correction_snapshot else {}),
        **({"historical_assessment_questions": historical_assessment_questions,
            "historical_assessment_questions_status": "available" if historical_assessment_questions else "unavailable"}
           if is_correction_package else {}),
        **({"learning_intent": selection.learning_intent.value,
            "next_generation_options": intent_options.model_dump(mode="json"),
            "next_generation_snapshot_hash": selection.next_generation_snapshot_hash}
           if intent_options is not None else {}),
    }
    request = GenerateRequest(
        learner_id=profile.learner_id,
        topic=f"{option.target_knowledge_point_ids[0]} {option.title}",
        knowledge_base_id=profile.knowledge_base_id,
        target_skill_nodes=option.target_knowledge_point_ids,
        resource_types=resource_types,
        difficulty_preference=difficulty,
        profile_focus_mode="off", generation_mode="standard", include_review=True,
        # Multi-resource Claim requests are split before creating jobs.
        include_claim_check=selection.include_claim_check and len(resource_types) == 1,
        max_iterations=2,
        constraints=constraints,
    )
    # A correction package supplements its source batch; other choices start a new one.
    batch_id = str(source_batch_id or "").strip() if is_correction_package else None
    return FollowupRequestPlan(request=request, resource_types=resource_types, source_batch_id=batch_id)
