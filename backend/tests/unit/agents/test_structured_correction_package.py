"""Contract and projection boundaries for the new correction package."""
import copy

import pytest
from pydantic import ValidationError

from app.models.learning_documents.correction_package import (
    CorrectionPackageContentV1, CorrectionPackageV1, assemble_correction_package,
)
from app.core.learning_documents.correction_package import (
    correction_audit_source, render_correction_markdown,
)


def content():
    question = dict(scenario="某团队使用一个索引。", question="请说明判断依据。",
                    hints=["先检查条件。"], reference_answer="应检查编码契约。",
                    explanation="相同维度不证明语义空间兼容。", self_check_points=["是否解释条件。"])
    return dict(training_goals=["解释编码契约。"], focus_overview=["防范只看维度的误区。"],
                unit=dict(error_patterns=[dict(mistaken_view="维度相同即可混用。", explanation="需要检查编码契约。")],
                          concept_repair=[dict(point="编码契约", explanation="包含模型及编码方式。")],
                          comparisons=[dict(incorrect_statement="直接混用。", correct_statement="先核对契约。", explanation="需要确认适用条件。")],
                          worked_example=dict(scenario="某知识库更换模型。", task="说明处理步骤。",
                                              steps=[dict(action="检查契约。", explanation="识别变化。"), dict(action="验证结果。", explanation="确认条件。")],
                                              takeaway="保留判断依据。"),
                          exercises={key: copy.deepcopy(question) for key in ("guided", "similar", "transfer")}),
                layered_feedback=dict(foundation="如果需要提示，先回看示例。", proficient="如果能够独立完成，尝试迁移。", advanced="如果能够解释边界，继续巩固。"),
                mastery_criteria=["能够说明依据。"], next_review_actions=["换一个情境练习。"], summary="先检查契约，再作判断。")


def package(body=None):
    return assemble_correction_package(content=body or content(), title="纠错包",
        target=dict(node_id="embedding", node_name="Embedding", mastery_status="weak", failed_dimensions=["concept_application"]),
        run_id="run-test", focus_snapshot_hash="a" * 64)


@pytest.mark.parametrize("field,value", [("learning_status", {}), ("units", []), ("cross_unit_challenge", None), ("target", {})])
def test_model_cannot_write_server_context_or_multiple_units(field, value):
    body = content(); body[field] = value
    with pytest.raises(ValidationError):
        CorrectionPackageContentV1.model_validate(body)


def test_package_tampering_is_rejected():
    value = package().model_dump(mode="json")
    value["learning_status"]["target"]["mastery_status"] = "learning"
    with pytest.raises(ValidationError, match="hash mismatch"):
        CorrectionPackageV1.model_validate(value)


def test_learning_state_never_enters_audit_and_every_content_leaf_is_exact():
    value = package(); audit = correction_audit_source(value)
    assert "learning_status" not in audit.text
    assert "concept_application" not in audit.text
    assert "薄弱" not in audit.text
    leaves = {}
    def walk(v, p):
        if isinstance(v, dict):
            for k, child in v.items(): walk(child, f"{p}.{k}")
        elif isinstance(v, list):
            for i, child in enumerate(v): walk(child, f"{p}[{i}]")
        else: leaves[p] = v
    walk(value.content.model_dump(), "content")
    assert {f.path for f in audit.fields} == set(leaves)
    for field in audit.fields:
        assert audit.text[field.start:field.end] == leaves[field.path]
    roles = {f.path: f.role for f in audit.fields}
    assert roles["content.unit.worked_example.scenario"] == "scenario"
    assert roles["content.unit.exercises.guided.explanation"] == "explanation"


def test_answers_are_rendered_at_the_end_and_questions_stay_bound():
    body = content()
    for key in ("guided", "similar", "transfer"):
        body["unit"]["exercises"][key]["reference_answer"] = f"专属答案{key}。"
    value = package(body); text = render_correction_markdown(value)
    before, after = text.split("## 参考答案与分层反馈")
    assert "当前状态：薄弱" in before
    assert "跨知识点" not in text
    for key in ("guided", "similar", "transfer"):
        assert f"专属答案{key}" not in before
        assert after.count(f"专属答案{key}") == 1
    assert text == render_correction_markdown(value)


def test_structural_limits_and_total_render_budget_are_enforced():
    body = content(); body["unit"]["worked_example"]["steps"] = []
    with pytest.raises(ValidationError): package(body)
    body = content()
    body["unit"]["concept_repair"] = [dict(point="定义", explanation="字" * 4000) for _ in range(4)]
    with pytest.raises(ValueError, match="character budget"):
        render_correction_markdown(package(body))


def test_html_and_newline_headings_are_not_emitted_as_executable_markup():
    body = content(); body["summary"] = "<script>alert(1)</script>\n## injected"
    text = render_correction_markdown(package(body))
    assert "<script>" not in text
    assert "\n## injected" not in text


def structured_inputs():
    from tests.unit.agents.test_resource_type_agents import _inputs
    from app.agents.resource_agents.correction_package import STRUCTURED_CONTRACT_KEY, structured_generation_contract
    spec, context, _ = _inputs("讲义")
    spec = spec.model_copy(update={"resource_type": "个性化纠错训练包"})
    context = context.model_copy(update={"constraints": {
        STRUCTURED_CONTRACT_KEY: structured_generation_contract("correction-json-generation-v1"),
        "correction_focus_snapshot": {"ordered_target_nodes": [{
            "skill_node_id": "skill-search", "name": "受控检索", "mastery_status": "weak",
            "failed_dimensions": ["concept_application"],
        }]},
    }})
    return spec, context


def test_structured_generation_assembles_state_without_model_control():
    import json
    from app.agents.resource_agents.correction_package import CorrectionTrainingPackageAgent
    from tests.fakes.llm import ScriptedLLMGateway
    spec, context = structured_inputs()
    gateway = ScriptedLLMGateway([json.dumps(content(), ensure_ascii=False)])
    artifact = CorrectionTrainingPackageAgent().generate(spec, context, llm_gateway=gateway)
    value = CorrectionPackageV1.model_validate(artifact.artifact_data["correction_package"])
    assert value.learning_status.target.mastery_status == "weak"
    assert value.learning_status.target.node_id == "skill-search"
    assert artifact.metadata.artifact_format == "json"
    assert artifact.metadata.prompt_version == "correction-json-generation-v1"
    assert "当前状态：薄弱" in artifact.content_text
    assert gateway.calls[0]["options"].max_output_tokens == 32768
    assert gateway.calls[0]["options"].max_attempts == 2
    payload = json.loads(gateway.calls[0]["messages"][1].content)
    assert "correction_focus" not in payload
    assert gateway.calls[0]["output_schema"] is CorrectionPackageContentV1


@pytest.mark.parametrize("damage", ["contract", "targets"])
def test_structured_generation_rejects_drift_and_multiple_nodes_before_call(damage):
    from app.agents.resource_agents.correction_package import CorrectionTrainingPackageAgent, STRUCTURED_CONTRACT_KEY
    from app.core.security.errors import ApplicationError
    from tests.fakes.llm import ScriptedLLMGateway
    spec, context = structured_inputs()
    constraints = copy.deepcopy(context.constraints)
    if damage == "contract":
        constraints[STRUCTURED_CONTRACT_KEY]["prompt_hash"] = "b" * 64
    else:
        constraints["correction_focus_snapshot"]["ordered_target_nodes"].append({"skill_node_id": "other"})
    context = context.model_copy(update={"constraints": constraints})
    gateway = ScriptedLLMGateway([])
    with pytest.raises(ApplicationError):
        CorrectionTrainingPackageAgent().generate(spec, context, llm_gateway=gateway)
    assert gateway.calls == []
