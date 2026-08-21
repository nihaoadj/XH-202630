"""Specialized Agent for structured, tiered assessments."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGateway
from app.models.agent_contracts import (
    AssessmentLLMOutput,
    AssessmentQuestion,
    GeneratedArtifact,
    ResourceGenerationContext,
    ResourceSpec,
)

from .base import BaseResourceGenerationAgent


ASSESSMENT_PROMPT = """你是 AssessmentAgent，专门生成可机器校验、面向学习反馈的分阶测试题。优先保证每题可判定、证据受控和 JSON 完整，而不是堆砌题量。

硬性边界：
1. 只使用输入中的冻结 evidence；题干、正确答案和解析不得引入证据外的事实。
2. 只生成当前 ResourceSpec 的测试题，不生成讲义、实操指南或 HTML。
3. 必须同时覆盖“基础、进阶、挑战”三个层级，每层至少一道题；题目 ID 使用 q-01 起的稳定顺序。
4. 选择题的 answer 只能引用已声明 option_id；简答题 answer 给出可判定的参考答案要点。
5. 每题必须包含 explanation、ability_node、knowledge_points 和 evidence_ids。
6. 每题 evidence_ids 只能取自 ResourceSpec.evidence_ids；knowledge_points 只能取自 ResourceSpec.knowledge_points。
7. 避免只考记忆：基础层检验理解，进阶层检验应用，挑战层检验分析与排错。
8. 输出仅包含 AssessmentLLMOutput Schema 字段，不输出资源身份字段或额外解释。

稳定输出规则：
1. 默认生成恰好 3 题：q-01=基础、q-02=进阶、q-03=挑战。证据充分且确有不同能力点时才扩展到每层最多 2 题；ID 必须连续、层级顺序不变，最多不得超过 6 题。
2. 选择题给出 2～4 个唯一的大写 option_id；单选题 answer 只能有一个 option_id。简答题不带 options，answer 写成 1～3 条短小、可核对的要点。
3. 每题题干不超过 360 个字符，解析不超过 360 个字符，选项文本不超过 160 个字符；每题仅引用 1～3 个 evidence_id 与 1～3 个知识点。
4. 每题只考一个主要能力节点，题干不得使用“以上、同上、资料中”等无法独立作答的指代。instructions 不超过 300 个字符。
5. 在同一个 JSON 对象中一次性返回所有必填字段；不要把 JSON 拆成多段，也不要在字段外附加说明，并在最后一个字段后立即停止。
"""


def _render_question(question: AssessmentQuestion) -> str:
    lines = [
        f"### {question.question_id} · {question.level}",
        question.stem,
    ]
    if question.options:
        lines.extend(f"- {option.option_id}. {option.text}" for option in question.options)
    lines.extend(
        [
            f"**参考答案：** {'；'.join(question.answer)}",
            f"**解析：** {question.explanation}",
            f"**能力节点：** {question.ability_node}",
        ]
    )
    return "\n\n".join(lines)


def render_assessment_markdown(output: AssessmentLLMOutput) -> str:
    questions = "\n\n".join(_render_question(item) for item in output.questions)
    return f"# {output.title}\n\n{output.instructions}\n\n{questions}"


class AssessmentAgent(BaseResourceGenerationAgent[AssessmentLLMOutput]):
    resource_type = "分阶测试题"
    agent_name = "AssessmentAgent"
    prompt_version = "assessment-resource-v4-compact-json"
    artifact_format = "json"
    default_max_output_tokens = 8192

    def build_messages(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ):
        payload = self.common_prompt_payload(spec, context)
        return [
            SystemMessage(content=ASSESSMENT_PROMPT),
            HumanMessage(
                content="请根据以下受控输入生成分阶测试题：\n"
                + self.json_payload(payload)
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
        result = self.invoke(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            messages=self.build_messages(spec, context),
            output_schema=AssessmentLLMOutput,
            representation="text",
        )
        output = result.output
        artifact = GeneratedArtifact(
            metadata=self.metadata(
                spec=spec,
                representation="text",
                source_evidence_ids=list(spec.evidence_ids),
            ),
            difficulty=spec.difficulty,
            content_text=render_assessment_markdown(output),
            knowledge_points=output.knowledge_points,
            artifact_data=output.model_dump(mode="json"),
            storage_type="text",
            mime_type="application/json",
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
        try:
            output = AssessmentLLMOutput.model_validate(artifact.artifact_data)
        except ValueError:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422) from None
        allowed_evidence = set(spec.evidence_ids)
        allowed_points = set(spec.knowledge_points)
        if set(output.knowledge_points) != allowed_points:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if any(
            not set(question.evidence_ids) <= allowed_evidence
            or not set(question.knowledge_points) <= allowed_points
            for question in output.questions
        ):
            raise ApplicationError(ErrorCode.EVIDENCE_SCOPE_VIOLATION, status_code=422)
        return artifact
