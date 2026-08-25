"""Structured, evidence-grounded practice-guide generation."""

from __future__ import annotations

import hashlib
import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.core.llm.gateway import LLMGateway
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import GeneratedArtifact, PracticeGuidePackageV3, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


PRACTICE_GUIDE_PROMPT = """你是 PracticeGuideAgent。你的输出只能是一个可解析的 JSON 对象；不要输出 Markdown、代码围栏、HTML、脚本、说明文字或任何额外字段。

唯一允许的顶层格式如下。必须保留所有键名、层级和 phase_id 的字面值；不得增删、改名、合并、调换阶段，也不得输出 payload_hash（该字段由服务端计算）。
{
  "schema_version": "3.0",
  "title": "<实操指南标题>",
  "preparation": {
    "phase_id": "prepare",
    "goal": "<准备目标>",
    "items": ["<准备项>"],
    "evidence_ids": ["<冻结证据ID>"]
  },
  "practice": {
    "phase_id": "practice",
    "goal": "<实操目标>",
    "steps": [
      {
        "step_id": "step-1",
        "title": "<步骤标题>",
        "instruction_text": "<只含本步骤的文字说明>",
        "code_blocks": [
          {
            "language": "<代码语言>",
            "code": "<仅代码内容，不含 Markdown 围栏>",
            "purpose": "<代码用途>",
            "evidence_ids": ["<冻结证据ID>"]
          }
        ],
        "verification": "<本步骤完成验证>",
        "evidence_ids": ["<冻结证据ID>"]
      }
    ]
  },
  "verification": {
    "phase_id": "verify",
    "goal": "<验证目标>",
    "checklist": ["<最终检查项>"],
    "evidence_ids": ["<冻结证据ID>"]
  },
  "reflection": {
    "phase_id": "reflect",
    "goal": "<复盘目标>",
    "summary": "<复盘小结>",
    "evidence_ids": ["<冻结证据ID>"]
  }
}

严格字段规则：preparation 只能有 phase_id、goal、items、evidence_ids；practice 只能有 phase_id、goal、steps；verification 只能有 phase_id、goal、checklist、evidence_ids；reflection 只能有 phase_id、goal、summary、evidence_ids。每个实操步骤只能有 step_id、title、instruction_text、code_blocks、verification、evidence_ids，其中学习内容只有三项：instruction_text、code_blocks、verification。不得把代码合并到 instruction_text；没有代码时 code_blocks 必须为 []。

只使用输入的冻结 evidence。每个阶段、步骤、代码块和验证都必须填写 evidence_ids，且只能引用输入中存在的 ID。steps 必须为 1 至 8 步，并严格从 step-1 连续编号到 step-N。
禁止把分阶测试题、复习清单、案例分析或讲义的题目、答案、学习任务、下一步安排写入任何阶段；这些属于其他资源，不能作为实操内容。
不得展示、编造或硬编码密钥；尤其禁止 api_key="..."。若需要说明认证，只写“通过部署环境预先注入 OPENAI_API_KEY”，代码仅可使用 os.getenv("OPENAI_API_KEY") 读取，绝不提供带引号的环境变量赋值示例。"""


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def render_practice_guide_markdown(package: dict) -> str:
    """Render only server-validated JSON; this is the public text artifact."""
    preparation = package["preparation"]
    practice = package["practice"]
    verification = package["verification"]
    reflection = package["reflection"]
    lines = [f"# {package['title']}", "", "## 准备阶段", "", f"**阶段目标：** {preparation['goal']}", ""]
    lines.extend(f"- {item}" for item in preparation["items"])
    lines.extend(["", "## 实操阶段", "", f"**阶段目标：** {practice['goal']}", ""])
    for index, step in enumerate(practice["steps"], 1):
        lines += [f"### 步骤 {index}：{step['title']}", "", step["instruction_text"], ""]
        for code_block in step.get("code_blocks") or []:
            lines += ["", f"**代码用途：** {code_block['purpose']}", "", f"```{code_block['language']}", code_block["code"], "```", ""]
        lines += ["", f"**完成验证：** {step['verification']}", ""]
    lines += ["## 验证阶段", "", f"**阶段目标：** {verification['goal']}", ""]
    lines.extend(f"- [ ] {item}" for item in verification["checklist"])
    lines += ["", "## 复盘阶段", "", f"**阶段目标：** {reflection['goal']}", "", reflection["summary"]]
    return "\n".join(lines).rstrip()


class PracticeGuideAgent(BaseResourceGenerationAgent[PracticeGuidePackageV3]):
    resource_type = "实操指南"
    agent_name = "PracticeGuideAgent"
    prompt_version = "practice-guide-v3-fixed-phases"
    artifact_format = "json"
    default_max_output_tokens = 49152

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        settings = get_settings()
        result = self.invoke(
            spec=spec, context=context, llm_gateway=llm_gateway,
            messages=[
                SystemMessage(content=PRACTICE_GUIDE_PROMPT),
                HumanMessage(content=self.json_payload({
                    **self.common_prompt_payload(spec, context), "schema_version": "3.0", "max_steps": 8,
                    "step_id_rule": "从 step-1 开始连续编号，最后一个为 step-N（N 不大于 8）",
                })),
            ],
            output_schema=PracticeGuidePackageV3, representation="text",
            max_output_tokens=settings.practice_guide_max_output_tokens,
            request_timeout_seconds=settings.practice_guide_request_timeout_seconds,
        )
        package = result.output.model_dump(mode="json")
        package["payload_hash"] = _canonical_hash(package)
        artifact = GeneratedArtifact(
            metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)),
            difficulty=spec.difficulty, content_text=render_practice_guide_markdown(package),
            knowledge_points=list(spec.knowledge_points), artifact_data={"practice_guide_package": package},
            storage_type="text", mime_type="text/markdown",
            llm_metadata={**result.trace_metadata(), "request_timeout_seconds": settings.practice_guide_request_timeout_seconds},
        )
        return self.validate(artifact, spec=spec, context=context)

    def validate(self, artifact: GeneratedArtifact, *, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact:
        self._ensure_route(spec)
        self._scoped_evidence(spec, context)
        package = artifact.artifact_data.get("practice_guide_package")
        if not isinstance(package, dict):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        try:
            validated = PracticeGuidePackageV3.model_validate({key: value for key, value in package.items() if key != "payload_hash"})
        except ValueError as exc:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422) from exc
        allowed_evidence_ids = set(spec.evidence_ids)
        if (package.get("payload_hash") != _canonical_hash(validated.model_dump(mode="json"))
                or artifact.content_text != render_practice_guide_markdown(package)
                or not set(validated.preparation.evidence_ids + validated.verification.evidence_ids + validated.reflection.evidence_ids) <= allowed_evidence_ids
                or any(
                    not set(step.evidence_ids) <= allowed_evidence_ids
                    or any(not set(code_block.evidence_ids) <= allowed_evidence_ids for code_block in step.code_blocks)
                    for step in validated.practice.steps
                )):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
