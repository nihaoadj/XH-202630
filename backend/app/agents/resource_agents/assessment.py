"""Specialized Agent for a learner-facing, plain-text assessment paper."""

from __future__ import annotations

import re

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


ASSESSMENT_PROMPT = """你是 AssessmentAgent，专门生成给学习者直接阅读和作答的分阶测试卷。
这份资源是展示型学习材料，不会被反馈系统解析或自动评分；请直接输出 Markdown/纯文本试卷，不要输出 JSON、代码块包裹的 JSON 或任何字段对象。

硬性边界：
1. 只使用输入中的冻结 evidence；题干、正确答案和解析不得引入证据外的事实。
2. 只生成当前 ResourceSpec 的测试题，不生成讲义、实操指南或 HTML。
3. 必须同时覆盖“基础、进阶、挑战”三个层级，每层至少一道题；题目 ID 使用 q-01 起的稳定顺序。
4. 选择题的 answer 只能引用已声明 option_id；简答题 answer 给出可判定的参考答案要点。
5. 每题必须包含 explanation、ability_node、knowledge_points 和 evidence_ids。
6. 每题 evidence_ids 只能取自 ResourceSpec.evidence_ids；knowledge_points 只能取自 ResourceSpec.knowledge_points。
7. 避免只考记忆：基础层检验理解，进阶层检验应用，挑战层检验分析与排错。
8. 只输出一张完整试卷，不输出资源身份字段、JSON、内部校验说明或额外解释。

稳定输出规则：
1. 目标生成 12 题：基础 4 题、进阶 4 题、挑战 4 题；题号连续使用 q-01 至 q-12，最低不得少于 10 题。
2. 题型必须混合：至少 4 道单选题、至少 2 道多选题、至少 2 道判断题、至少 2 道简答/分析题；不要整套只生成单选题。
3. 难度递进：基础考理解与辨析，进阶考流程应用与故障判断，挑战考权衡、设计或排错；题目必须围绕输入知识点，不凭空增加事实。
4. 严格按以下文本结构输出：标题；作答说明；“## 一、题目”及 q-01 至 q-08；“## 二、参考答案与解析”且该章节必须位于所有题目之后。答案章节按题号给出答案、解析、能力点和证据 ID。
5. 每道选择题列出 A/B/C/D 选项；多选题明确“可多选”；判断题给出“正确/错误”选项；简答题写清回答要求。不要在题目章节提前泄露答案。
6. 每题题干不超过 360 个字符，解析不超过 360 个字符；每题引用 1～3 个 evidence_id 与 1～3 个知识点。
7. 每题只考一个主要能力节点，题干不得使用“以上、同上、资料中”等无法独立作答的指代。
8. 全部 ResourceSpec.knowledge_points 都必须在题目或答案解析中实际覆盖；证据 ID 必须来自输入 evidence。
9. 使用 Markdown 标题、编号列表和普通文本即可；不要使用 JSON、表格嵌套对象或 ``` 代码围栏。
"""


def _render_question(question: AssessmentQuestion) -> str:
    lines = [
        f"### {question.question_id} · {question.level}",
        question.stem,
    ]
    if question.options:
        lines.extend(f"- {option.option_id}. {option.text}" for option in question.options)
    return "\n\n".join(lines)


def render_assessment_markdown(output: AssessmentLLMOutput) -> str:
    questions = "\n\n".join(_render_question(item) for item in output.questions)
    answers = "\n\n".join(
        f"### {item.question_id}\n**参考答案：** {'；'.join(item.answer)}\n\n"
        f"**解析：** {item.explanation}\n\n**能力节点：** {item.ability_node}"
        for item in output.questions
    )
    return f"# {output.title}\n\n{output.instructions}\n\n## 一、题目\n\n{questions}\n\n## 二、参考答案与解析\n\n{answers}"


class AssessmentAgent(BaseResourceGenerationAgent[AssessmentLLMOutput]):
    resource_type = "分阶测试题"
    agent_name = "AssessmentAgent"
    prompt_version = "assessment-resource-v5-plain-paper"
    artifact_format = "markdown"
    default_max_output_tokens = 12000
    # Validation failures are local contract errors. Retry the Agent call
    # before returning a failure to the workflow-level policy.
    validation_retry_attempts = 2

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
        last_error: ApplicationError | None = None
        for _ in range(self.validation_retry_attempts):
            result = self.invoke_plain_text(
                spec=spec,
                context=context,
                llm_gateway=llm_gateway,
                messages=self.build_messages(spec, context),
                representation="text",
                max_output_tokens=self.default_max_output_tokens,
            )
            artifact = GeneratedArtifact(
                metadata=self.metadata(
                    spec=spec,
                    representation="text",
                    source_evidence_ids=list(spec.evidence_ids),
                ),
                difficulty=spec.difficulty,
                content_text=str(result.output).strip(),
                knowledge_points=list(spec.knowledge_points),
                artifact_data={},
                storage_type="text",
                mime_type="text/markdown",
                llm_metadata=result.trace_metadata(),
            )
            try:
                return self.validate(artifact, spec=spec, context=context)
            except ApplicationError as exc:
                if exc.code not in {
                    ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
                }:
                    raise
                last_error = exc
        assert last_error is not None
        raise last_error

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
        answer_section = content.find("参考答案")
        question_text = content[:answer_section] if answer_section >= 0 else content
        question_ids = re.findall(r"(?mi)^#{1,4}\s*(q-\d{2,3})\b", question_text)
        if len(set(question_ids)) < 10 or answer_section < 0:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if content.lower().startswith("{") or "```json" in content.lower():
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
