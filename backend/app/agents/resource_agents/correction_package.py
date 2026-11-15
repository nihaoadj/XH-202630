"""Feedback-only, evidence-grounded remediation package generation."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.gateway import LLMGateway
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent
from .revision_prompts import attach_revision_fields

from app.models.learning_documents.correction_package import (
    CorrectionGenerationContractV1, CorrectionPackageContentV1,
    assemble_correction_package, CorrectionPackageContentV2, CorrectionGenerationContractV2,
    parse_correction_package, parse_correction_generation_contract, assemble_compact_correction_package,
)
from app.models.shared.persistence import canonical_hash
from app.core.learning_documents.correction_package import render_correction_markdown, correction_audit_source, CORRECTION_AUDIT_GUIDANCE

STRUCTURED_CONTRACT_KEY = "_correction_package_contract"
STRUCTURED_PROMPT = """你是单节点纠错训练内容生成器，版本 correction-json-generation-v1。
仅输出符合所给schema的JSON内容对象，不输出完整Markdown文档、额外字段或解释过程。
只使用输入冻结evidence支持的知识；不得猜测原测评题、学习者原始作答或个人诊断。
服务端负责标题、目标节点和学习状态，禁止生成这些字段，也不要在正文重复个人状态。
一份内容只对应一个目标节点，固定一个强化单元和引导、同构、迁移三道练习。
training_goals是本次目标，focus_overview只简要指出应防范的误区，不宣称用户实际犯过。
mistaken_view/incorrect_statement只放待纠正的错误命题，正确解释单独放explanation。
scenario只放明确假设的情境条件；一般技术规律应放解释字段，不伪装成已发生事件。
示例必须自包含，步骤包含action与explanation；参考答案、依据、提示和自查点与本题绑定。
分层反馈使用条件表达，不断言用户已经掌握。不得输出HTML、脚本或自行增加跨节点挑战。
总阅读正文不得超过14000中文字符，避免概览、错误模式与正误对照重复展开。
如有修订输入，只修正问题指定内容，保留其余正确内容；仍输出完整的content对象。
"""


COMPACT_PROMPT = """你是单节点纠错训练内容生成器，版本correction-json-generation-v2。
只输出符合schema的完整content JSON。仅使用冻结evidence，不猜测原题、原始作答或个人诊断。
固定单强化单元，只生成guided引导式和transfer迁移两题；不生成worked_example完整示例或similar同构练习。
服务端装配标题/节点/学习状态，不允许模型决定这些字段。每题情境、问题、提示、答案、解释与自查点相互对应。
training_goals只表达学习目标；focus_overview仅概括应关注的误区，不展开技术解释或断言个人状态；
mastery_criteria只表达可观察的达标行为，next_review_actions只表达复习动作。
这些展示字段不参加Claim抽取，不得把技术定义、规则、结论、具体算法步骤或知识讲解藏在其中；
技术讲解必须放在concept_repair、error_patterns.explanation、comparisons.correct_statement/explanation或题目答案解释中。
mistaken_view/incorrect_statement仅为待纠正命题；正确解释放独立字段。scenario明确为假设，不将假设包装成发生过的事件。
题干/提示/答案/解析中的技术结论必须符合冻结证据和题设条件；不能以假设之名免审技术事实。
分层反馈使用条件表达；总结简洁，避免重复整段概念。保留目标/概览/达标/复习动作展示，不删这些字段。
无HTML、脚本、跨节点挑战。总阅读正文不超过14000字符。
修订只修改指定问题与必须同步内容，保留其他正确内容，仍返回完整两题content，不跨版本改格式。
"""


def structured_generation_contract(version="correction-json-generation-v2"):
    if version not in {"correction-json-generation-v1", "correction-json-generation-v2"}:
        raise ValueError("unknown correction generation version")
    compact = version == "correction-json-generation-v2"
    schema = CorrectionPackageContentV2 if compact else CorrectionPackageContentV1
    contract = CorrectionGenerationContractV2 if compact else CorrectionGenerationContractV1
    return contract(
        schema_hash=canonical_hash(schema.model_json_schema()),
        prompt_hash=canonical_hash({"prompt": COMPACT_PROMPT if compact else STRUCTURED_PROMPT,
                                    "audit_guidance": CORRECTION_AUDIT_GUIDANCE}),
    ).model_dump(mode="json")


def validate_generation_contract(value):
    contract = parse_correction_generation_contract(value)
    if contract.model_dump(mode="json") != structured_generation_contract(contract.version):
        raise ValueError("correction generation identity drift")
    return contract


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
    prompt_version = "correction-training-package-v3-self-contained"
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
        if context.claim_review_revision is not None or context.resource_review_revision is not None:
            attach_revision_fields(payload, context)
        elif context.generation_attempt > 1:
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
        if STRUCTURED_CONTRACT_KEY in context.constraints:
            return self._generate_structured(spec, context, llm_gateway)
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

    def _generate_structured(self, spec, context, gateway):
        try:
            contract = validate_generation_contract(context.constraints[STRUCTURED_CONTRACT_KEY])
        except ValueError as exc:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409) from exc
        compact = contract.version == "correction-json-generation-v2"
        focus = self._focus(context)
        targets = focus["ordered_target_nodes"]
        if len(targets) != 1 or spec.knowledge_points != [targets[0]["skill_node_id"]]:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        target = targets[0]
        payload = self._prompt_payload(spec, context)
        payload.pop("correction_focus", None)
        payload["target_node_name"] = target.get("name") or target["skill_node_id"]
        # Revision contracts are private server inputs. Send only the editable
        # content and scoped issues, never the parent's learning state.
        parent_package = None
        if context.constraints.get("_correction_parent_package"):
            parent_package = parse_correction_package(context.constraints["_correction_parent_package"])
            payload["previous_content"] = parent_package.content.model_dump(mode="json")
        for key in ("claim_review_revision", "resource_review_revision"):
            revision = payload.get(key)
            if revision:
                parent_package = parse_correction_package(revision["previous_structured_payload"])
                revision["previous_text"] = correction_audit_source(parent_package).text
                revision["previous_structured_payload"] = parent_package.content.model_dump(mode="json")
                revision.pop("groups", None)
        payload.pop("previous_version_content", None)
        payload.pop("revision_edit_policy", None)
        if parent_package is not None and parent_package.provenance.renderer_version != contract.renderer_version:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409)
        result = self.invoke(
            spec=spec, context=context, llm_gateway=gateway,
            messages=[SystemMessage(content=COMPACT_PROMPT if compact else STRUCTURED_PROMPT), HumanMessage(content=self.json_payload(payload))],
            output_schema=CorrectionPackageContentV2 if compact else CorrectionPackageContentV1, representation="text",
            max_output_tokens=contract.max_output_tokens,
            strict_max_output_tokens=True,
            request_timeout_seconds=contract.timeout_seconds, max_attempts=contract.max_attempts,
        )
        status = target.get("mastery_status")
        assemble = assemble_compact_correction_package if compact else assemble_correction_package
        package = assemble(
            content=result.output, title=payload["display_title"],
            target={"node_id": target["skill_node_id"], "node_name": payload["target_node_name"],
                    "mastery_status": status if status in {"weak", "learning"} else "unknown",
                    "failed_dimensions": list(target.get("failed_dimensions") or [])},
            run_id=context.run_id, focus_snapshot_hash=canonical_hash(focus),
        )
        if parent_package is not None:
            if (parent_package.learning_status != package.learning_status
                    or parent_package.provenance.focus_snapshot_hash != package.provenance.focus_snapshot_hash):
                raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409)
            if parent_package.content == package.content:
                raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
            values = package.model_dump(mode="json", exclude={"payload_hash"})
            values["provenance"] = parent_package.provenance.model_dump(mode="json")
            values["title"] = parent_package.title
            package = parse_correction_package({**values, "payload_hash": canonical_hash(values)})
        artifact = GeneratedArtifact(
            metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)).model_copy(
                update={"prompt_version": contract.version, "artifact_format": "json"}),
            difficulty=spec.difficulty, content_text=render_correction_markdown(package),
            knowledge_points=list(spec.knowledge_points),
            artifact_data={"format": package.schema_version, "correction_package": package.model_dump(mode="json")},
            storage_type="text", mime_type="text/markdown", llm_metadata={},
        )
        return self.validate(artifact, spec=spec, context=context)

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
