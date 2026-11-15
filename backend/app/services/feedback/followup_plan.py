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

    def requests(
        self, *, include_claim_check: bool,
        include_claim_evidence_retrieval: bool = False,
    ) -> list[GenerateRequest]:
        # Called within the Service's original job-creation exception boundary.
        supplement = include_claim_evidence_retrieval and include_claim_check
        focus = self.request.constraints.get("correction_focus_snapshot")
        if focus and "个性化纠错训练包" in self.resource_types:
            from copy import deepcopy
            from app.core.learning_tiers import difficulty_for_tier
            from app.models.shared.persistence import canonical_hash
            result = []
            for node in focus["ordered_target_nodes"]:
                node_id = node["skill_node_id"]
                tier = (node.get("node_context") or {}).get("tier") or node.get("tier")
                difficulty = difficulty_for_tier(tier) if tier in {1, 2, 3} else self.request.difficulty_preference
                single = deepcopy(focus)
                single["ordered_target_nodes"] = [deepcopy(node)]
                single["difficulty"] = difficulty
                single["scaffolding_level"] = "high" if node.get("mastery_status") == "weak" else "medium"
                single["parent_focus_snapshot_hash"] = focus.get("focus_snapshot_hash")
                single["focus_snapshot_hash"] = canonical_hash({k:v for k,v in single.items() if k != "focus_snapshot_hash"})
                constraints = {**self.request.constraints, "correction_focus_snapshot": single,
                               "feedback_difficulty": difficulty}
                history = [q for q in constraints.get("historical_assessment_questions", [])
                           if q.get("skill_node_id") == node_id]
                constraints["historical_assessment_questions"] = history
                constraints["historical_assessment_questions_status"] = "available" if history else "unavailable"
                groups = [[kind] for kind in self.resource_types] if include_claim_check else [self.resource_types]
                for group in groups:
                    result.append(self.request.model_copy(update={
                        "target_skill_nodes": [node_id], "resource_types": list(group),
                        "topic": f"{node.get('name') or node_id} · 薄弱点强化",
                        "difficulty_preference": difficulty, "constraints": deepcopy(constraints),
                        "include_claim_check": include_claim_check,
                        "include_claim_evidence_retrieval": supplement}))
            return result
        if include_claim_check and len(self.resource_types) > 1:
            return [self.request.model_copy(update={
                "resource_types": [resource_type], "include_claim_check": True,
                "include_claim_evidence_retrieval": supplement,
            }) for resource_type in self.resource_types]
        if self.request.include_claim_evidence_retrieval != supplement:
            return [self.request.model_copy(update={
                "include_claim_evidence_retrieval": supplement,
            })]
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
        include_claim_evidence_retrieval=(
            selection.include_claim_evidence_retrieval
            and selection.include_claim_check
            and len(resource_types) == 1
        ),
        claim_post_retrieval_max_iterations=selection.claim_post_retrieval_max_iterations,
        constraints=constraints,
    )
    # A correction package supplements its source batch; other choices start a new one.
    batch_id = str(source_batch_id or "").strip() if is_correction_package else None
    return FollowupRequestPlan(request=request, resource_types=resource_types, source_batch_id=batch_id)
