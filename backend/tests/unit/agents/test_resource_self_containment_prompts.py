from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_agents.base import with_self_contained_rule


def test_shared_generation_rule_keeps_resource_system_prompt_and_input_separate():
    original = [SystemMessage(content="只输出严格 JSON。"), HumanMessage(content='{"evidence":[]}')]

    messages = with_self_contained_rule(original)

    assert messages[0].content.startswith("只输出严格 JSON。")
    assert "不得让学习者另找" in messages[0].content
    assert messages[1] is original[1]
    assert original[0].content == "只输出严格 JSON。"


def test_generic_review_prompt_rejects_hidden_material_for_every_resource():
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.prompts import resource_profile_fragments

    for resource_type in ("讲义", "实操指南", "分阶测试题", "案例分析", "复习清单", "个性化纠错训练包"):
        fragments = resource_profile_fragments(resource_type)
        assert "未在本资源呈现的资料" in fragments[0].text
    assert "静态 JSON" in resource_profile_fragments("实操指南")[1].text


def test_standard_review_prompt_also_checks_practice_inputs_and_executable_code():
    from app.agents.resource_workflows.learning_documents.reviewing import build_review_prompt, resolve_review_profile

    prompt = build_review_prompt(
        profile=resolve_review_profile(resource_type="实操指南", phase="practice_semantic_v2")
    ).system_text
    assert "未展示的资料" in prompt
    assert "静态 JSON 示例不能冒充可运行程序" in prompt
