from app.models.learning_documents.schemas import GenerateRequest
from app.services.feedback.followup_plan import FollowupRequestPlan
from app.services.feedback.round_plans import plan_member
from app.models.learning_documents.schemas import SkillNode


def test_claim_split_preserves_one_target_and_single_resource_per_job():
    request = GenerateRequest(
        learner_id="learner", topic="topic", target_skill_nodes=["node"],
        resource_types=["复习清单", "分阶测试题"],
    )
    plan = FollowupRequestPlan(request=request, resource_types=request.resource_types, source_batch_id=None)
    requests = plan.requests(include_claim_check=True)
    assert [item.target_skill_nodes for item in requests] == [["node"], ["node"]]
    assert [item.resource_types for item in requests] == [["复习清单"], ["分阶测试题"]]
    assert all(item.include_claim_check for item in requests)


def test_review_plan_is_two_fixed_resources_and_uses_its_own_tier():
    node = SkillNode(node_id="b", knowledge_base_id="kb", name="B", tier=1)
    result = plan_member(round_id="r", stage_id="s", learner_id="l", knowledge_base_id="kb", node=node,
                         role="review", primary_resource_types=["讲义", "案例分析"], include_claim_check=True)
    assert result.resource_types == ("复习清单", "分阶测试题")
    assert len(result.requests) == 2
    assert all(req.target_skill_nodes == ["b"] and req.difficulty_preference == "初级" for req in result.requests)


def test_two_correction_plans_are_four_separate_node_scoped_resources():
    results = [plan_member(round_id="r", stage_id="correction", learner_id="l", knowledge_base_id="kb",
                           node=SkillNode(node_id=key, knowledge_base_id="kb", name=key, tier=tier), role=role,
                           primary_resource_types=[], include_claim_check=True,
                           correction_focus={"node": key})
               for key, tier, role in [("a", 2, "primary"), ("b", 1, "review")]]
    assert results[0].batch_id != results[1].batch_id
    assert results[0].difficulty != results[1].difficulty
    assert sum(len(result.requests) for result in results) == 4
    for result in results:
        assert result.resource_types == ("个性化纠错训练包", "分阶测试题")
        assert all(req.target_skill_nodes == [result.node_id] for req in result.requests)
