"""Specialized Agent for evidence-grounded lecture notes."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


TEXT_RESOURCE_PROMPT = """你是 TextResourceAgent，专门生成可直接学习的个性化 Markdown 讲义。优先保证证据可追溯、学习结构清晰和完整收束。

硬性边界：
1. 只使用输入中的冻结 evidence，不得借助记忆或外部知识补充事实。
2. 只生成当前 ResourceSpec 对应的一份讲义，不生成实操指南、测试题或 HTML。
3. 围绕 learning_objective 和 knowledge_points 组织内容，并匹配指定 difficulty。
4. Markdown 必须包含唯一一级标题，以及“学习目标、核心概念、逐点讲解、示例、常见误区、练习建议、总结”层级。
5. 技术事实、参数、结论与示例必须能由 evidence 支持；证据不足时明确指出边界，不得猜测。
6. knowledge_points 只能使用 ResourceSpec 中声明的知识点，并须完整覆盖。
7. 直接输出 Markdown 正文；不要输出 JSON、资源 ID、证据引用对象、Markdown 围栏或任何解释。

稳定输出规则：
1. 第一行必须是唯一的一级标题，且必须严格为输入 display_title，格式为“# <display_title>”；其余内容只包含讲义正文。
2. 按“学习目标、核心概念、逐点讲解、示例、常见误区、练习建议、总结”的顺序使用二级标题；每个知识点至少在“逐点讲解”中落到一个可学习的小节。
3. 正文目标为 5,000～8,500 个中文字符，硬性不得超过 12,000 个字符。输出预算仅用于保证完整性，不是扩写配额；证据不足时宁可明确边界，也不要编造或拉长内容。
4. “学习目标”写 3 条；“核心概念”写 3～6 项；“逐点讲解”按知识点写 3～6 个三级小节；“示例”写 2 个；“常见误区”写 3～5 项；“练习建议”写 3 项；“总结”写 4～6 条。每项只讲一个要点，避免复述 evidence。
5. 单个三级小节不超过 750 个字符，单个示例不超过 600 个字符，单个误区或练习建议不超过 200 个字符。完成最后一个必填字段后立即停止输出；不要为填满 token 预算重复说明、增加同义段落或扩展无关背景。
6. 一次性完整输出整篇 Markdown，在“总结”结束后立即停止；不得拆成多段，不得在正文外附加说明。若篇幅接近上限，优先压缩措辞而非省略必填章节或知识点。
"""


class TextResourceAgent(BaseResourceGenerationAgent):
    resource_type = "讲义"
    agent_name = "TextResourceAgent"
    prompt_version = "text-resource-v5-bounded-markdown"
    artifact_format = "markdown"
    default_max_output_tokens = 32768

    def build_messages(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ):
        payload = self.common_prompt_payload(spec, context)
        return [
            SystemMessage(content=TEXT_RESOURCE_PROMPT),
            HumanMessage(
                content="请根据以下受控输入生成讲义：\n" + self.json_payload(payload)
            ),
        ]

    def generate(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        *,
        llm_gateway: LLMGateway,
        **_: object,
    ) -> GeneratedArtifact:
        settings = get_settings()
        result = self.invoke_plain_text(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            messages=self.build_messages(spec, context),
            representation="text",
            # Keep the deployed 32k-token ceiling explicit for lectures while
            # allowing their slower long-form Markdown call a separate timeout.
            max_output_tokens=settings.text_resource_max_output_tokens,
            strict_max_output_tokens=True,
            request_timeout_seconds=settings.text_resource_request_timeout_seconds,
        )
        content = result.output.strip()
        title = content.splitlines()[0][2:].strip() if content.startswith("# ") else context.topic
        artifact = GeneratedArtifact(
            metadata=self.metadata(
                spec=spec,
                representation="text",
                source_evidence_ids=list(spec.evidence_ids),
            ),
            difficulty=spec.difficulty,
            content_text=content,
            # Knowledge-point ownership remains deterministic: the model may
            # explain only this frozen set, while the server records it.
            knowledge_points=list(spec.knowledge_points),
            artifact_data={"title": title},
            storage_type="text",
            mime_type="text/markdown",
            llm_metadata=result.trace_metadata(),
        )
        return self.validate(artifact, spec=spec, context=context)

    def validate(
        self,
        artifact: GeneratedArtifact,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ) -> GeneratedArtifact:
        self._ensure_route(spec)
        self._scoped_evidence(spec, context)
        if artifact.metadata.resource_spec_id != spec.resource_spec_id:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        if artifact.metadata.representation != "text":
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        content = artifact.content_text.strip()
        if not content.startswith("# ") or "\n## " not in content:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if set(artifact.knowledge_points) != set(spec.knowledge_points):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
