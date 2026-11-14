"""Specialized Agent for evidence-grounded lecture notes."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent
from .lecture_contract import lecture_payload


TEXT_RESOURCE_PROMPT = """你是 TextResourceAgent，专门生成可直接学习的个性化 Markdown 讲义。优先保证证据可追溯、学习结构清晰和完整收束。

硬性边界：
1. 只使用输入中的冻结 evidence，不得借助记忆或外部知识补充事实。
2. 只生成当前 ResourceSpec 对应的一份讲义，不生成实操指南、测试题或 HTML。
3. 围绕 learning_objective 和 knowledge_points 组织内容，并匹配指定 difficulty 与 teaching_contract。knowledge_points 是内部范围标识，正文按 knowledge_point_display_names 表达其语义，不要抄内部ID。
4. Markdown 必须有唯一一级标题，并用二级标题组织概念讲解。
5. 技术事实、参数、结论与示例必须能由 evidence 支持；证据不足时明确指出边界，不得猜测。
6. knowledge_points 只能使用 ResourceSpec 中声明的知识点，并须完整覆盖。
7. 直接输出 Markdown 正文；不要输出 JSON、资源 ID、证据引用对象、Markdown 围栏或任何解释。

稳定输出规则：
1. 第一行必须是唯一的一级标题，且必须严格为输入 display_title，格式为“# <display_title>”；其余内容只包含讲义正文。
2. 简短交代本篇要理解的问题，按概念之间的关系组织正文。每个目标知识点都要有可独立阅读的讲解，可在相关小节说明其含义、用途及适用边界。标题随内容设置，teaching_contract.explanation_subsections 仅供组织篇幅参考。
3. 正文目标由 teaching_contract.target_chars 按当前难度确定，初级不要套用长篇工程手册；最大仍不得超过12,000字符。目标不是最低字数，也不是扩写配额；证据不足时宁可明确边界，不编造或拉长内容。
4. 示例就近放在所解释的概念下。按需加入误区或简短总结，避免重复讲解。正文讲完即可结束；确有帮助时可在末尾附一至两项自检，材料与判断依据随题给出。
5. 单个三级小节不超过 750 个字符，单个示例不超过 600 个字符，单个误区或自检不超过 200 个字符。不要为填满 token 预算重复说明、增加同义段落或扩展无关背景。
6. 一次性完整输出整篇 Markdown，正文外不附加说明。若篇幅接近上限，压缩措辞，保证目标知识点完整覆盖。

教学加工规则：
1. 严格落实teaching_contract.rules：示例自包含、受众匹配、展示名、通用与项目边界、递进和去重复。证据是事实材料，不是要照抄的课程脚本。
2. 用简短、证据支持的示例直接解释概念；只有同一情境有助于串联多个目标概念且材料齐全时才用贯穿案例。正文应讲清例子说明了什么。保留材料标识时，提供读者理解示例所需的内容；要求读者定位原文或核对原话时，须提供相关原文。
3. 初级先解释概念和链路直觉，除非目标直接要求，不展开hash、模型revision、数据库迁移、冻结快照或生产治理细节；术语首次集中解释，不在每节附重复术语表、自检和相同警告。高级目标仍按显式难度处理。
4. 本项目工程约定、实验设置必须明确限定，不能冒充通用规范；不伪造日期、API、参数或性能指标。内部节点/资源/运行/证据ID、存储路径不作教学内容，但保留真正需要学习的API术语。
5. 输出前在内部完成teaching_contract.self_check；只输出讲义正文，不输出自检报告、证据清单或你掌握的来源数量。
"""


class TextResourceAgent(BaseResourceGenerationAgent):
    resource_type = "讲义"
    agent_name = "TextResourceAgent"
    prompt_version = "text-resource-v8-concept-explanation"
    artifact_format = "markdown"
    default_max_output_tokens = 32768

    def build_messages(
        self,
        spec: ResourceSpec,
        context: ResourceGenerationContext,
    ):
        payload = lecture_payload(self.common_prompt_payload(spec, context), spec, context)
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
