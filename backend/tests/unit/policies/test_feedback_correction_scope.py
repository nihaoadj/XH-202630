from types import SimpleNamespace

from app.db.learners.curriculum import MemoryCurriculumRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import MemoryTierProgressRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult
from app.models.learners.mastery import LearnerTierProgressV1
from app.models.learning_documents.schemas import LearnerProfile
from app.services.feedback.feedback import FeedbackService
from app.services.learners.mastery import MasteryService


def test_correction_option_uses_current_node_score_and_80_percent_gate():
    generation = SimpleNamespace(
        snapshot_hash="a" * 64,
        learning_candidates=[],
        reinforce_weakness=[],
        learn_new_knowledge=[],
    )
    result = SimpleNamespace(
        decision=SimpleNamespace(target_knowledge_point_ids=["lower-prerequisite"]),
        attempt=SimpleNamespace(knowledge_point_results=[
            KnowledgePointAttemptResult(
                knowledge_point_id="current-node", question_ids=["q1"],
                correct_count=3, total_count=4,
            ),
        ]),
    )

    option = FeedbackService._correction_package_option(
        generation, SimpleNamespace(skill_level="中级"), result,
    )

    assert option is not None
    assert option.recommended_target_ids == ["current-node"]
    assert option.selectable_targets[0]["reason_codes"] == ["CURRENT_FEEDBACK_TARGET"]

    result.attempt.knowledge_point_results[0] = KnowledgePointAttemptResult(
        knowledge_point_id="current-node", question_ids=["q1"],
        correct_count=4, total_count=4,
    )
    assert FeedbackService._correction_package_option(
        generation, SimpleNamespace(skill_level="中级"), result,
    ) is None


def test_downgrade_exposes_all_nodes_in_the_remedial_tier():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn", skill_level="中级",
    ))
    nodes = [
        SimpleNamespace(node_id="base", name="Base", description="", level="L1", tier=1,
                        prerequisites=[], children=["parser", "embedding"]),
        SimpleNamespace(node_id="parser", name="Parser", description="", level="L1", tier=1,
                        prerequisites=["base"], children=[]),
        SimpleNamespace(node_id="embedding", name="Embedding", description="", level="L1", tier=1,
                        prerequisites=["base"], children=["vector"]),
        SimpleNamespace(node_id="vector", name="Vector store", description="", level="L2", tier=2,
                        prerequisites=["embedding"], children=[]),
    ]
    service = MasteryService(
        MemoryMasteryRepository(learners),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        resource_repo=SimpleNamespace(list_by_learner=lambda _learner: []),
        curriculum_repo=MemoryCurriculumRepository(),
        tier_progress_repo=MemoryTierProgressRepository(),
    )
    profile = learners.get("learner")
    service.tier_progress_repo.save(LearnerTierProgressV1(
        learner_id="learner", knowledge_base_id="kb", placement_tier=2,
        active_tier=1, highest_unlocked_tier=2, remediation_return_tier=2,
        profile_version=profile.profile_version,
    ))

    options = service.next_generation_options(profile)
    by_id = {item.skill_node_id: item for item in options.learning_candidates}

    assert options.recommendation_type == "remedial"
    assert set(by_id) == {"base", "parser", "embedding"}
    assert all(not item.blocked_by_node_ids for item in by_id.values())
