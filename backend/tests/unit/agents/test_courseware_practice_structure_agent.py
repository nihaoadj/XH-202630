import json
from types import SimpleNamespace

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewarePracticeStepExtraction
from app.agents.resource_workflows.interactive_courseware.practice_structure_agent import extract_practice_step_structure
from app.models.shared.llm import LLMCallOptions


class CapturingGateway:
    def __init__(self, output):
        self.output = output
        self.payload = None

    def invoke_structured(self, *, messages, **_kwargs):
        self.payload = json.loads(messages[-1].content)
        return SimpleNamespace(output=self.output, trace_metadata=lambda: {})


def test_practice_structure_uses_compact_model_context_but_validates_full_source_ranges():
    source = {
        "resource_id": "guide-1",
        "role": "practice",
        "blocks": [
            {"block_id": "intro", "kind": "paragraph", "text": "课程准备说明。"},
            {"block_id": "s1", "kind": "heading", "text": "### 步骤 1：配置环境"},
            {"block_id": "code", "kind": "code", "text": "```python\n" + "x = 1\n" * 1200 + "```"},
            {"block_id": "s2", "kind": "heading", "text": "### 步骤 2：运行校验"},
            {"block_id": "result", "kind": "paragraph", "text": "确认命令返回预期结果。"},
        ],
    }
    output = CoursewarePracticeStepExtraction.model_validate({
        "steps": [
            {"title": "配置环境", "source_block_ids": ["s1", "code"]},
            {"title": "运行校验", "source_block_ids": ["s2", "result"]},
        ],
        "context_block_ids": ["intro"],
    })
    gateway = CapturingGateway(output)

    extracted, warning = extract_practice_step_structure(
        gateway, "run-1", source, allowance=LLMCallOptions(max_output_tokens=2200, max_attempts=3),
    )

    assert warning is None
    assert extracted == [
        {"title": "配置环境", "source_block_ids": ["s1", "code"]},
        {"title": "运行校验", "source_block_ids": ["s2", "result"]},
    ]
    code_view = next(item for item in gateway.payload["source_blocks"] if item["block_id"] == "code")
    assert code_view["preview"].startswith("代码块（")
    assert "x = 1" not in code_view["preview"]
    assert gateway.payload["response_example"]["context_block_ids"] == ["intro-1"]
