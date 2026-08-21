"""Specialized Agent for evidence-grounded case-study learning resources."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGateway
from app.models.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


CASE_STUDY_PROMPT = """你是 CaseStudyAgent，专门生成用于训练分析与决策能力的 Markdown 案例分析。

硬性边界：
1. 仅使用输入中的冻结 evidence。案例中的事实、条件、参数、分析依据和参考方案均不得超出证据。
2. 只生成当前 ResourceSpec 对应的一份案例分析，不生成讲义、实操指南、测试题、HTML 或脚本。
3. 内容必须覆盖 ResourceSpec 的全部 knowledge_points，并匹配指定 difficulty。
4. 必须依次包含：唯一一级标题、案例背景、任务目标、分析过程、参考方案、复盘要点。
5. 案例背景应给出足以推理的受控情境；任务目标应提出 2 至 4 个明确问题或决策点。
6. 分析过程必须区分事实、判断与行动；参考方案应说明依据和可验证结果，不得把猜测写成事实。
7. 复盘要点应列出可迁移的判断原则、常见误判或边界条件。
8. 直接输出 Markdown 正文，不输出 JSON、HTML、脚本、资源身份字段或额外解释。
"""


REQUIRED_SECTIONS = ("案例背景", "任务目标", "分析过程", "参考方案", "复盘要点")


class CaseStudyAgent(BaseResourceGenerationAgent):
    resource_type = "案例分析"
    agent_name = "CaseStudyAgent"
    prompt_version = "case-study-v1-markdown"
    artifact_format = "markdown"

    def generate(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        *,
        llm_gateway: LLMGateway,
        **_: object,
    ) -> GeneratedArtifact:
        result = self.invoke_plain_text(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            messages=[
                SystemMessage(content=CASE_STUDY_PROMPT),
                HumanMessage(
                    content="请根据以下受控输入生成案例分析：\n"
                    + self.json_payload(self.common_prompt_payload(spec, context))
                ),
            ],
            representation="text",
        )
        artifact = GeneratedArtifact(
            metadata=self.metadata(
                spec=spec,
                representation="text",
                source_evidence_ids=list(spec.evidence_ids),
            ),
            difficulty=spec.difficulty,
            content_text=result.output.strip(),
            knowledge_points=list(spec.knowledge_points),
            artifact_data={"format": "case-study-v1"},
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
        content = artifact.content_text.strip()
        if (
            artifact.metadata.representation != "text"
            or not content.startswith("# ")
            or any(f"## {section}" not in content for section in REQUIRED_SECTIONS)
            or "<script" in content.lower()
            or set(artifact.knowledge_points) != set(spec.knowledge_points)
        ):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
