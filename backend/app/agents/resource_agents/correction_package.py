"""Feedback-only, evidence-grounded remediation package generation."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.gateway import LLMGateway
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


CORRECTION_PACKAGE_PROMPT = """你是 CorrectionTrainingPackageAgent。一次性输出一份可直接发布的 Markdown 薄弱点强化包，不要输出写作说明、思考过程、JSON 或代码围栏。

绝对边界：
1. 只能使用输入的冻结 evidence 和受控 correction_focus；不得使用记忆、外部知识或学习者原始答案。
   correction_focus 中的 error_context 是服务端根据本次节点测评整理的错误摘要，node_context 是当前节点上下文；只能据此组织纠错内容。
2. 不得复述、猜测或构造原测评题、选项、正确答案、解析、题号、复测题或学习者自由文本；不得把错误摘要扩写成未被 evidence 支持的新事实。返工时可参考 previous_version_content，但新增或修改的事实仍必须由 evidence 支持。
3. correction_focus 中每个目标知识点必须有一个独立“## 强化单元：<知识点>”章节，且该章严格依次包含：
   “### 错误模式”“### 核心概念补救”“### 正误对照”“### 完整示例”“### 引导式练习”“### 同构练习”“### 迁移练习”。
4. 每个练习只使用证据支持的事实；题目后不要立刻给出答案。所有参考答案与分层反馈统一置于文末。
5. 文档必须依次包含：唯一一级标题、“本次强化目标”“薄弱模式概览”、全部强化单元；当目标超过一个时还必须包含“跨知识点综合挑战”；最后依次包含“参考答案与分层反馈”“达标标准”“后续复习动作”“总结”。
6. 不得生成 HTML、脚本、JSON、内部 ID、分数、题库标识或任何对学习者敏感的原始作答数据。
7. 采用短段落和项目符号，避免重复定义、重复题干或冗长铺垫。每个强化单元的三道练习各只出一道；答案、提示和分层反馈只放在文末。
8. 严格遵守输入 composition_budget。每个事实、示例与练习答案必须由 evidence 支持；证据不足时只做概念辨析或学习步骤，不补充新事实。
9. 直接输出 Markdown 正文，全文不得超过 14000 个中文字符。
10. 第一行必须是唯一一级标题，且严格使用输入 display_title。
11. 如果输入包含 previous_version_content，这是审核返工；仅修改反馈指出的问题，保留上一版本其余正确内容。
"""


REPAIR_PROMPT = """你是 Markdown 格式修复器。将草稿重写为一份完整、可直接发布的薄弱点强化包。

只使用受控输入中的 evidence 和 correction_focus；不得引入外部知识、原题、选项、答案、解析、题号、复测题、内部 ID、学习者原文、HTML、JSON 或代码围栏。严格保留所要求的标题顺序和每个强化单元的七个三级标题。答案与分层反馈只能出现在文末的“## 参考答案与分层反馈”中。直接输出完整 Markdown，不要解释修复过程。
"""


class CorrectionTrainingPackageAgent(BaseResourceGenerationAgent):
    resource_type = "个性化纠错训练包"
    agent_name = "CorrectionTrainingPackageAgent"
    prompt_version = "correction-training-package-v2-controlled-markdown"
    artifact_format = "markdown"
    # Keep enough headroom for a complete 1–2-node package.  The strict call
    # path below makes this an actual ceiling rather than silently inheriting
    # a different global resource-generator budget.
    default_max_output_tokens = 32768
    # Real-provider acceptance showed a valid one-node package can require
    # nearly five minutes.  The resource workflow has a separate 20-minute
    # deadline, so use the validated provider maximum instead of converting a
    # slow but complete generation into an avoidable failure.
    request_timeout_seconds = 300.0
    transport_max_attempts = 2

    def _focus(self, context: ResourceGenerationContext) -> dict:
        focus = context.constraints.get("correction_focus_snapshot")
        if not isinstance(focus, dict):
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        targets = focus.get("ordered_target_nodes")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 2:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        if any(not isinstance(item, dict) or not str(item.get("skill_node_id") or "").strip() for item in targets):
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        return focus

    def _prompt_payload(self, spec: ResourceSpec, context: ResourceGenerationContext) -> dict:
        focus = self._focus(context)
        evidence = self._scoped_evidence(spec, context)
        # This deliberate allow-list prevents the feedback request, raw answers,
        # free-text reflection and held-out assessment material reaching the model.
        payload = {
            "topic": context.topic,
            "resource_type": spec.resource_type,
            "display_title": f"{context.topic} · {spec.resource_type}",
            "knowledge_points": spec.knowledge_points,
            "difficulty": spec.difficulty,
            "correction_focus": {
                "difficulty": focus.get("difficulty"),
                "scaffolding_level": focus.get("scaffolding_level"),
                "ordered_target_nodes": focus.get("ordered_target_nodes"),
            },
            "composition_budget": self._composition_budget(focus),
            "evidence": [{"evidence_id": item.evidence_id, "source": item.locator.source_path,
                          "section": item.locator.section, "excerpt": item.excerpt} for item in evidence],
        }
        if context.generation_attempt > 1:
            payload["revision_feedback"] = context.constraints.get("revision_feedback", {})
            payload["previous_version_content"] = context.constraints.get("previous_version_content", "")
        return payload

    @staticmethod
    def _composition_budget(focus: dict) -> dict[str, str | int]:
        target_count = len(focus["ordered_target_nodes"])
        ranges = {
            1: (6200, 7600, "每个强化单元约 4000–4800 字符，文末部分约 1800–2400 字符"),
            2: (7000, 8600, "每个强化单元约 2200–2800 字符，综合与文末部分约 2200–3000 字符"),
        }
        minimum, maximum, allocation = ranges[target_count]
        return {
            "target_character_min": minimum,
            "target_character_max": maximum,
            "allocation": allocation,
            "hard_character_max": 14000,
        }

    def _generate_markdown(
        self,
        *,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
        llm_gateway: LLMGateway,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        result = self.invoke_plain_text(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            messages=[SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            representation="text",
            max_output_tokens=self.default_max_output_tokens,
            strict_max_output_tokens=True,
            request_timeout_seconds=self.request_timeout_seconds,
            max_attempts=self.transport_max_attempts,
        )
        return result.output.strip()

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        self._ensure_route(spec)
        prompt_payload = self._prompt_payload(spec, context)
        content = self._generate_markdown(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            system_prompt=CORRECTION_PACKAGE_PROMPT,
            user_prompt="请根据以下受控输入生成强化包：\n" + self.json_payload(prompt_payload),
        )
        artifact = GeneratedArtifact(
            metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)),
            difficulty=spec.difficulty, content_text=content, knowledge_points=list(spec.knowledge_points),
            artifact_data={"format": "correction-training-package-v1", "correction_focus_snapshot_hash": context.constraints.get("correction_focus_snapshot", {}).get("focus_snapshot_hash")},
            storage_type="text", mime_type="text/markdown", llm_metadata={},
        )
        try:
            return self.validate(artifact, spec=spec, context=context)
        except ApplicationError as error:
            if error.code != ErrorCode.LLM_OUTPUT_SCHEMA_INVALID:
                raise
        # A hard validation failure is retried as an explicit regeneration using
        # the same allow-listed snapshot, never as a generic-template fallback.
        repaired_content = self._generate_markdown(
            spec=spec,
            context=context,
            llm_gateway=llm_gateway,
            system_prompt=REPAIR_PROMPT,
            user_prompt=(
                "受控输入：\n" + self.json_payload(prompt_payload)
                + "\n\n待修复草稿（只能据此纠正结构，不能采纳不受证据支持的内容）：\n"
                + content
            ),
        )
        repaired = artifact.model_copy(update={
            "content_text": repaired_content,
            "artifact_data": {**artifact.artifact_data, "format_repair_attempted": True},
        })
        return self.validate(repaired, spec=spec, context=context)

    def validate(self, artifact: GeneratedArtifact, *, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact:
        """Check hard safety/scope invariants, while keeping Markdown layout advisory.

        This resource is learner-facing prose.  Headings, section order and
        optional unit headings are generation guidance, not a machine-readable
        contract, so formatting differences must not force a fallback artifact.
        """
        self._ensure_route(spec)
        self._focus(context)
        self._scoped_evidence(spec, context)
        content = artifact.content_text.strip()
        if not content or len(content) > 14000 or set(artifact.knowledge_points) != set(spec.knowledge_points):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        # Executable markup is a safety violation, not a presentation issue.
        if "<script" in content.lower():
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
