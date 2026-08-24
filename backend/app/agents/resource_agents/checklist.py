"""Specialized Agent for evidence-grounded review checklists."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


REVIEW_CHECKLIST_PROMPT = """你是 ReviewChecklistAgent，专门生成可直接执行的 Markdown 复习清单。

硬性边界：
1. 仅使用输入中的冻结 evidence，不得补充证据外的技术事实、参数或结论。
2. 只生成当前 ResourceSpec 对应的一份复习清单，不生成讲义、案例、测试题、HTML 或脚本。
3. 内容必须覆盖 ResourceSpec 的全部 knowledge_points，并匹配指定 difficulty。
4. 必须依次包含：唯一一级标题、复习目标、必会清单、易错点、自测清单、复习节奏。
5. 必会清单与自测清单均使用可勾选的行动项；每一项应具体、可判断，避免空泛口号。
6. 易错点必须说明错误表现、原因或纠正动作；复习节奏必须给出按天或按学习轮次执行的安排。
7. 直接输出 Markdown 正文，不输出 JSON、HTML、脚本、资源身份字段或额外解释。
"""


REQUIRED_SECTIONS = ("复习目标", "必会清单", "易错点", "自测清单", "复习节奏")


class ReviewChecklistAgent(BaseResourceGenerationAgent):
    resource_type = "复习清单"
    agent_name = "ReviewChecklistAgent"
    prompt_version = "review-checklist-v1-markdown"
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
                SystemMessage(content=REVIEW_CHECKLIST_PROMPT),
                HumanMessage(
                    content="请根据以下受控输入生成复习清单：\n"
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
            artifact_data={"format": "review-checklist-v1"},
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
