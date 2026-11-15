from types import SimpleNamespace

import pytest

from app.agents.resource_agents.practice import PRACTICE_GUIDE_PROMPT, PracticeGuideAgent, render_practice_guide_markdown
from app.core.security.errors import ApplicationError
from app.models.shared.agent_contracts import ResourceGenerationContext, ResourceRepresentationSpec, ResourceSpec, validate_practice_guide_package
from tests.fakes.evidence import make_evidence


class Gateway:
    def __init__(self, output):
        self.output = output
        self.calls = []
        self.messages = []

    def options_for(self, *_args, **kwargs):
        return SimpleNamespace(max_output_tokens=8192, request_timeout_seconds=120, max_attempts=2, model_copy=lambda update: SimpleNamespace(**{**{"max_output_tokens": 8192, "request_timeout_seconds": 120, "max_attempts": 2}, **update}))

    def invoke_structured(self, *, output_schema, options, messages, **_kwargs):
        self.calls.append(options)
        self.messages.append(messages)
        return SimpleNamespace(output=output_schema.model_validate(self.output), trace_metadata=lambda: {})


def _inputs():
    evidence = make_evidence(evidence_id="ev-practice")
    spec = ResourceSpec(resource_spec_id="11111111-1111-1111-1111-111111111111", resource_family_id="22222222-2222-2222-2222-222222222222", resource_type="实操指南", learning_objective="完成受控操作", knowledge_points=["node-practice"], evidence_ids=[evidence.evidence_id], difficulty="初级", representations=[ResourceRepresentationSpec(representation="text", max_output_tokens=8192)], display_order=1)
    context = ResourceGenerationContext(run_id="run-practice", batch_id="batch-practice", topic="受控操作", evidence=[evidence])
    return spec, context


def _package(steps=2, *, version="3.0"):
    package = {
        "schema_version": version, "title": "受控操作实操指南",
        "preparation": {"phase_id": "prepare", "goal": "确认前置条件。", "items": ["确认冻结证据可用。"], "evidence_ids": ["ev-practice"]},
        "practice": {"phase_id": "practice", "goal": "完成受控操作。", "steps": [{"step_id": f"step-{index}", "title": f"执行操作 {index}", "instruction_text": "在 Python 环境中运行代码并观察输出。", "code_blocks": [{"language": "python", "code": "print('ready')", "purpose": "输出可观察状态", "evidence_ids": ["ev-practice"]}] if version == "6.0" or index == 1 and version in {"4.0", "5.0"} else [], "verification": "运行后终端应显示 ready。" if index == 1 else "观察上一步结果并记录。", "evidence_ids": ["ev-practice"]} for index in range(1, steps + 1)]},
        "verification": {"phase_id": "verify", "goal": "验证操作结果。", "checklist": ["确认结果。"], "evidence_ids": ["ev-practice"]},
        "reflection": {"phase_id": "reflect", "goal": "复盘操作。", "summary": "复盘每一步的证据依据和验证结果。", "evidence_ids": ["ev-practice"]},
    }
    if version == "5.0":
        package["preparation"]["materials"] = []
    return package


def test_practice_guide_prompt_explicitly_reinforces_v6_steps():
    for fragment in (
        "practice 阶段本身没有 evidence_ids",
        "所有对象都不得包含未列出的字段",
        "steps 必须为 1 至 8 步",
        "只返回 JSON 对象",
        "previous_version_content",
        "每个步骤的 code_blocks 必须包含至少一段可运行代码",
        "不得输出 materials",
        "不得要求学习者从准备阶段复制一整份脚本",
    ):
        assert fragment in PRACTICE_GUIDE_PROMPT


def test_practice_guide_generates_json_then_deterministic_markdown(monkeypatch):
    spec, context = _inputs()
    gateway = Gateway(_package(version="6.0"))
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))

    artifact = PracticeGuideAgent().generate(spec, context, llm_gateway=gateway)

    package = artifact.artifact_data["practice_guide_package"]
    assert artifact.metadata.artifact_format == "json"
    assert artifact.content_text == render_practice_guide_markdown(package)
    assert "## 准备阶段" in artifact.content_text
    assert "## 验证阶段" in artifact.content_text
    assert "### 步骤 2：执行操作 2" in artifact.content_text
    assert package["payload_hash"]
    assert package["schema_version"] == "6.0"
    assert "```python" in artifact.content_text
    assert gateway.calls[0].max_output_tokens == 49152
    assert gateway.calls[0].request_timeout_seconds == 300
    assert "不能只给外部材料名" in gateway.messages[0][0].content
    assert "静态 JSON、配置或预填答案不能单独充当本步可运行代码" in gateway.messages[0][0].content


def test_v5_preparation_material_is_visible_and_old_versions_keep_their_rendering():
    package = _package(version="5.0")
    package["preparation"]["materials"] = [{"name": "练习短文", "content": "第一句。\n第二句。"}]
    package["practice"]["steps"][0]["instruction_text"] = "读取练习短文，再运行代码。"

    validated = validate_practice_guide_package(package)
    rendered = render_practice_guide_markdown(validated.model_dump(mode="json"))
    assert "### 材料：练习短文\n\n> 第一句。\n> 第二句。" in rendered
    assert rendered.index("### 材料：练习短文") < rendered.index("## 实操阶段")
    assert validate_practice_guide_package(_package(version="5.0")).preparation.materials == []
    for version in ("3.0", "4.0"):
        legacy = _package(version=version)
        assert "### 材料：" not in render_practice_guide_markdown(legacy)
        assert validate_practice_guide_package(legacy).schema_version == version


@pytest.mark.parametrize("materials", [
    [{"name": "练习短文", "content": "  "}],
    [{"name": "  ", "content": "有内容"}],
    [{"name": "练习短文", "content": "内容"}, {"name": " 练习短文 ", "content": "另一个内容"}],
    [{"name": str(i), "content": "内容"} for i in range(5)],
    [{"name": "练习短文", "content": "字" * 3001}],
])
def test_v5_preparation_material_rejects_invalid_values(materials):
    package = _package(version="5.0")
    package["preparation"]["materials"] = materials
    with pytest.raises(ValueError):
        validate_practice_guide_package(package)


def test_practice_issue_location_accepts_materials_only_in_v5():
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.practice import PracticeAdapter

    adapter = PracticeAdapter()
    for version in ("3.0", "4.0", "5.0"):
        resource = SimpleNamespace(practice_guide_payload=_package(version=version))
        index = adapter.build_location_index(resource=resource, evidence=[], targets=[])
        assert ("materials" in index.unit_fields["prepare"]) == (version == "5.0")


def test_practice_guide_contract_rejects_more_than_eight_steps(monkeypatch):
    spec, context = _inputs()
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))

    with pytest.raises(Exception):
        PracticeGuideAgent().generate(spec, context, llm_gateway=Gateway(_package(9, version="5.0")))


def test_new_practice_guide_rejects_paper_only_output(monkeypatch):
    spec, context = _inputs()
    package = _package(version="5.0")
    package["practice"]["steps"][0]["code_blocks"] = []
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))
    with pytest.raises(Exception):
        PracticeGuideAgent().generate(spec, context, llm_gateway=Gateway(package))


def test_review_gate_requires_code_only_for_new_practice_contract():
    from app.agents.resource_workflows.learning_documents.reviewing.checks import check_practice_structure
    from app.agents.resource_workflows.learning_documents.reviewing.profiles import select_specialties

    legacy = _package(version="3.0")
    modern = _package(version="4.0")
    modern["practice"]["steps"][0]["code_blocks"] = []
    resource = SimpleNamespace(resource_type="实操指南", practice_guide_payload=legacy,
                               content_text=render_practice_guide_markdown(legacy))
    assert check_practice_structure(resource) is None
    resource.practice_guide_payload = modern
    resource.content_text = render_practice_guide_markdown(modern)
    assert check_practice_structure(resource)["decision"] == "revise"
    resource.practice_guide_payload = _package(version="4.0")
    assert select_specialties(profile=SimpleNamespace(resource_type="实操指南"), resource=resource)
    resource.practice_guide_payload = _package(version="5.0")
    resource.practice_guide_payload["preparation"]["materials"] = [
        {"name": "练习短文", "content": "这一段可直接供学习者复制。"}
    ]
    resource.content_text = render_practice_guide_markdown(resource.practice_guide_payload)
    assert check_practice_structure(resource) is None


def test_executable_guide_preserves_all_frozen_source_refs(monkeypatch):
    from app.agents.resource_workflows.learning_documents.generator_agent import _materialize

    spec, context = _inputs()
    evidence = [*context.evidence, *(make_evidence(evidence_id=f"ev-practice-{i}") for i in range(2, 7))]
    spec = spec.model_copy(update={"evidence_ids": [item.evidence_id for item in evidence]})
    supplement = make_evidence(evidence_id="ev-supplement")
    context = context.model_copy(update={"evidence": [*evidence, supplement],
                                 "supplement_evidence_ids": [supplement.evidence_id]})
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))
    artifact = PracticeGuideAgent().generate(spec, context, llm_gateway=Gateway(_package(version="6.0")))
    node_input = SimpleNamespace(learner=SimpleNamespace(learner_id="learner"), topic="受控操作",
                                 run_id="run-practice", batch_id="batch-practice", include_review=True,
                                 retrieved_evidence=evidence, retrieval_strategy_version="legacy")
    resource = _materialize(artifact, node_input, None, spec, context)
    assert [ref.evidence_id for ref in resource.source_refs] == spec.evidence_ids


def test_v6_requires_code_in_every_step_and_omits_materials():
    package = _package(version="6.0")
    assert validate_practice_guide_package(package).schema_version == "6.0"
    package["practice"]["steps"][1]["code_blocks"] = []
    with pytest.raises(ValueError):
        validate_practice_guide_package(package)
    package = _package(version="6.0")
    package["practice"]["steps"][0]["code_blocks"][0]["language"] = "json"
    with pytest.raises(ValueError):
        validate_practice_guide_package(package)
    package = _package(version="6.0")
    package["preparation"]["materials"] = []
    with pytest.raises(ValueError):
        validate_practice_guide_package(package)
