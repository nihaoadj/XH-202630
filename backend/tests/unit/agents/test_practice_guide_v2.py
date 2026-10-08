from types import SimpleNamespace

import pytest

from app.agents.resource_agents.practice import PRACTICE_GUIDE_PROMPT, PracticeGuideAgent, render_practice_guide_markdown
from app.core.security.errors import ApplicationError
from app.models.shared.agent_contracts import ResourceGenerationContext, ResourceRepresentationSpec, ResourceSpec
from tests.fakes.evidence import make_evidence


class Gateway:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def options_for(self, *_args, **kwargs):
        return SimpleNamespace(max_output_tokens=8192, request_timeout_seconds=120, max_attempts=2, model_copy=lambda update: SimpleNamespace(**{**{"max_output_tokens": 8192, "request_timeout_seconds": 120, "max_attempts": 2}, **update}))

    def invoke_structured(self, *, output_schema, options, **_kwargs):
        self.calls.append(options)
        return SimpleNamespace(output=output_schema.model_validate(self.output), trace_metadata=lambda: {})


def _inputs():
    evidence = make_evidence(evidence_id="ev-practice")
    spec = ResourceSpec(resource_spec_id="11111111-1111-1111-1111-111111111111", resource_family_id="22222222-2222-2222-2222-222222222222", resource_type="实操指南", learning_objective="完成受控操作", knowledge_points=["node-practice"], evidence_ids=[evidence.evidence_id], difficulty="初级", representations=[ResourceRepresentationSpec(representation="text", max_output_tokens=8192)], display_order=1)
    context = ResourceGenerationContext(run_id="run-practice", batch_id="batch-practice", topic="受控操作", evidence=[evidence])
    return spec, context


def _package(steps=2):
    return {
        "schema_version": "3.0", "title": "受控操作实操指南",
        "preparation": {"phase_id": "prepare", "goal": "确认前置条件。", "items": ["确认冻结证据可用。"], "evidence_ids": ["ev-practice"]},
        "practice": {"phase_id": "practice", "goal": "完成受控操作。", "steps": [{"step_id": f"step-{index}", "title": f"执行操作 {index}", "instruction_text": "根据冻结证据完成当前操作。", "code_blocks": [], "verification": "检查结果。", "evidence_ids": ["ev-practice"]} for index in range(1, steps + 1)]},
        "verification": {"phase_id": "verify", "goal": "验证操作结果。", "checklist": ["确认结果。"], "evidence_ids": ["ev-practice"]},
        "reflection": {"phase_id": "reflect", "goal": "复盘操作。", "summary": "复盘每一步的证据依据和验证结果。", "evidence_ids": ["ev-practice"]},
    }


def test_practice_guide_prompt_explicitly_reinforces_v3_shape():
    for fragment in (
        "practice 阶段本身没有 evidence_ids",
        "所有对象都不得包含未列出的字段",
        "steps 必须为 1 至 8 步",
        "只返回 JSON 对象",
        "previous_version_content",
    ):
        assert fragment in PRACTICE_GUIDE_PROMPT


def test_practice_guide_generates_json_then_deterministic_markdown(monkeypatch):
    spec, context = _inputs()
    gateway = Gateway(_package())
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))

    artifact = PracticeGuideAgent().generate(spec, context, llm_gateway=gateway)

    package = artifact.artifact_data["practice_guide_package"]
    assert artifact.metadata.artifact_format == "json"
    assert artifact.content_text == render_practice_guide_markdown(package)
    assert "## 准备阶段" in artifact.content_text
    assert "## 验证阶段" in artifact.content_text
    assert "### 步骤 2：执行操作 2" in artifact.content_text
    assert package["payload_hash"]
    assert gateway.calls[0].max_output_tokens == 49152
    assert gateway.calls[0].request_timeout_seconds == 300


def test_practice_guide_contract_rejects_more_than_eight_steps(monkeypatch):
    spec, context = _inputs()
    monkeypatch.setattr("app.agents.resource_agents.practice.get_settings", lambda: SimpleNamespace(practice_guide_max_output_tokens=49152, practice_guide_request_timeout_seconds=300))

    with pytest.raises(Exception):
        PracticeGuideAgent().generate(spec, context, llm_gateway=Gateway(_package(9)))
