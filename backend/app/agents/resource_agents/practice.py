"""Plain-Markdown, evidence-grounded practice-guide generation."""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGateway
from app.models.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


PRACTICE_GUIDE_PROMPT = """你是 PracticeGuideAgent，只生成可直接阅读的 Markdown 实操指南。
仅使用给定 evidence；不生成 HTML、脚本、组件标记或任何派生格式。内容依次包含：唯一一级标题、准备、实践步骤、检查清单、常见问题、复盘建议。每个步骤可执行且与知识点相关。直接输出 Markdown 正文。
Markdown 标记必须直接书写，绝不能在行首为 #、>、|、---、列表编号或列表符号添加反斜杠转义。
安全规则：不得展示、编造或硬编码任何密钥；尤其禁止 `OPENAI_API_KEY="示例值"`、`api_key="..."`、`openai.api_key = ...` 等写法。若需要说明认证，只写“通过部署环境预先注入 OPENAI_API_KEY”，代码仅可使用 `os.getenv("OPENAI_API_KEY")` 读取，且不得提供任何带引号的环境变量赋值示例。"""


def _normalize_escaped_markdown_blocks(text: str) -> str:
    """Recover safe, block-level Markdown escapes produced by some models."""
    normalized = text.replace("\r\n", "\n")
    normalized = re.sub(r"^(\s*)\\(?=[>|])", r"\1", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"^(\s*)\\(?=---+\s*$)", r"\1", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"^(\s*\d+)\\\.(?=\s)", r"\1.", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"^(\s*)\\([-*])(?=\s)", r"\1\2", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"(?<=\|)\\(?=\n|$)", "", normalized)
    return normalized


class PracticeGuideAgent(BaseResourceGenerationAgent):
    resource_type = "实操指南"
    agent_name = "PracticeGuideAgent"
    prompt_version = "practice-guide-v1-plain-markdown"
    artifact_format = "markdown"
    default_max_output_tokens = 8192

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        result = self.invoke_plain_text(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            messages=[
                SystemMessage(content=PRACTICE_GUIDE_PROMPT),
                HumanMessage(content="请根据以下受控输入生成实操指南：\n" + self.json_payload(self.common_prompt_payload(spec, context))),
            ],
            representation="text",
        )
        artifact = GeneratedArtifact(
            metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)),
            difficulty=spec.difficulty,
            content_text=_normalize_escaped_markdown_blocks(result.output).strip(),
            knowledge_points=list(spec.knowledge_points),
            artifact_data={}, storage_type="text", mime_type="text/markdown",
            llm_metadata=result.trace_metadata(),
        )
        return self.validate(artifact, spec=spec, context=context)

    def validate(self, artifact: GeneratedArtifact, *, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact:
        self._ensure_route(spec)
        self._scoped_evidence(spec, context)
        if artifact.metadata.representation != "text" or not artifact.content_text.strip().startswith("# "):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if set(artifact.knowledge_points) != set(spec.knowledge_points):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
