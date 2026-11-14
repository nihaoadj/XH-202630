"""Structured, evidence-grounded practice-guide generation."""

from __future__ import annotations

import hashlib
import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.core.llm.gateway import LLMGateway
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import GeneratedArtifact, PracticeGuidePackageV6, ResourceGenerationContext, ResourceSpec, validate_practice_guide_package

from .base import BaseResourceGenerationAgent


PRACTICE_GUIDE_PROMPT = """你是 PracticeGuideAgent。你的输出只能是一个可解析的 JSON 对象；不要输出 Markdown、代码围栏、HTML、脚本、说明文字或任何额外字段。

唯一允许的顶层格式如下。必须保留所有键名、层级和 phase_id 的字面值；不得增删、改名、合并、调换阶段，也不得输出 payload_hash（该字段由服务端计算）。示例中的尖括号仅是占位符，必须替换为真实内容，不能原样输出。
{
  "schema_version": "6.0",
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

严格字段规则：preparation 只能有 phase_id、goal、items、evidence_ids，不得输出 materials；practice 只能有 phase_id、goal、steps（practice 阶段本身没有 evidence_ids）；verification 只能有 phase_id、goal、checklist、evidence_ids；reflection 只能有 phase_id、goal、summary、evidence_ids。每个实操步骤只能有 step_id、title、instruction_text、code_blocks、verification、evidence_ids，其中学习内容只有三项：instruction_text、code_blocks、verification。每个步骤的 code_blocks 必须包含至少一段可运行代码；不得把代码合并到 instruction_text。所有对象都不得包含未列出的字段，不得使用 null、空字符串或空数组替代必填值。

围绕当前学习目标设计一个能亲手完成的最小任务，而非纸笔推演或概念复述。准备阶段说明运行环境、依赖、示例输入与安全配置；实操步骤按实际执行顺序提供至少一段可运行代码，说明如何运行及输入从何而来。代码应能在所述环境中使用，不得留下省略号、未定义变量或缺失的必要文件。每段代码所属步骤的 verification 必须写明可观察的输出、文件、状态或错误及其判定方法；最终 checklist 至少复核实际产物和一个关键失败条件。不得声称代码已经由系统执行。来源不支持某个 API 或参数时，应选择有依据的更小任务，不得编造接口、运行结果或证据。

写给第一次做这个任务的学习者。准备阶段用通俗语言说清目标、运行环境和工具，不在此阶段集中罗列、展示或要求复制整份材料及完整脚本。实操按执行顺序拆成少量步骤：每一步都让学习者运行本步代码，完成一个可观察的小目标；所需示例输入在首次使用的步骤内以代码块创建或定义，后一步可使用前一步生成的文件。教学用的自拟输入须标明“示例”或“假设”，不得冒充冻结证据中的真实事实。不能只给外部材料名、路径、URL 或 evidence ID 让读者自行查找；输入过长时缩小任务。
实操阶段先解释首次出现的专业词或字段名，用日常语言说明作用；每步按“要做什么→运行哪段代码→运行后看什么”写清。保存文件、阅读材料、检查结果等无代码动作并入相关步骤的 instruction_text 或 verification，不得单列独立步骤。每步 code_blocks 至少一段可运行的命令或程序；静态 JSON、配置或预填答案不能单独充当本步可运行代码。允许逐步写入、扩展同一个脚本，但每一步都要给出该步可直接运行的完整代码或明确可执行的增量命令，不得要求学习者从准备阶段复制一整份脚本。说明运行命令和产生的文件或输出；验证检查本步实际结果，不只核对预填答案。

只使用输入的冻结 evidence。preparation、verification、reflection 三个阶段、每个 step、每个 code_block 都必须填写 evidence_ids，且只能引用输入中存在的 ID；practice 阶段通过其 steps 间接绑定 Evidence。所有 evidence_ids 必须非空、去重。steps 必须为 1 至 8 步，并严格从 step-1 连续编号到 step-N；不要为了凑数拆分步骤，优先用最少但足够完成目标的步骤。
长度与数量也必须满足：title 1–160 字符；各阶段 goal 1–400 字符；items、checklist 各 1–6/8 项；每个 step 的 title 1–120、instruction_text 1–1200、verification 1–500 字符，至少 1 个、最多 3 个 code_blocks；每个 code_block 的 language 1–40、code 1–8000、purpose 1–400 字符。所有列表元素必须是非空且不重复的字符串。
禁止把分阶测试题、复习清单、案例分析或讲义的题目、答案、学习任务、下一步安排写入任何阶段；这些属于其他资源，不能作为实操内容。
不得展示、编造或硬编码密钥；尤其禁止 api_key="..."。若需要说明认证，只写“通过部署环境预先注入 OPENAI_API_KEY”，代码仅可使用 os.getenv("OPENAI_API_KEY") 读取，绝不提供带引号的环境变量赋值示例。
输出示例前逐步推演代码对实际输入的结果，核对说明、verification 与真实代码行为一致；不要凭意图填写预期输出。文本匹配示例须核对分词粒度、标点、大小写和输入语言：str.split() 只按空白切分，不会把连续中文切成词。使用与算法相容的教学输入，或明确实现简单分词并解释局限；不得声称出现实际不存在的命中词或得分。无需在输出中复述内部检查过程。
如果输入包含 revision_feedback 和 previous_version_content，这是审核返工：只修改反馈明确指出的问题，保留上一版本其他正确字段和内容；不要把 previous_version_content 当作新的 Evidence，也不要输出内部 ID、审核字段或 payload_hash。

输出前只在内部逐项检查：顶层 6 个键完全匹配；四个 phase_id 正确；准备阶段没有 materials；step_id 连续；每一步都有可运行代码、运行方式和可观察验证；所有必填字符串和数组非空；所有 Evidence ID 来自输入；没有额外键、Markdown 围栏、解释文字、密钥或其他资源类型。检查完成后只返回 JSON 对象，不要返回检查清单。"""


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
    for material in preparation.get("materials") or []:
        lines.extend(["", f"### 材料：{material['name']}", ""])
        lines.extend(f"> {line}" if line else ">" for line in material["content"].splitlines())
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


class PracticeGuideAgent(BaseResourceGenerationAgent[PracticeGuidePackageV6]):
    resource_type = "实操指南"
    agent_name = "PracticeGuideAgent"
    prompt_version = "practice-guide-v6-steps-verified"
    artifact_format = "json"
    default_max_output_tokens = 49152

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        settings = get_settings()
        result = self.invoke(
            spec=spec, context=context, llm_gateway=llm_gateway,
            messages=[
                SystemMessage(content=PRACTICE_GUIDE_PROMPT),
                HumanMessage(content=self.json_payload({
                    **self.common_prompt_payload(spec, context), "schema_version": "6.0", "max_steps": 8,
                    "step_id_rule": "从 step-1 开始连续编号，最后一个为 step-N（N 不大于 8）",
                })),
            ],
            output_schema=PracticeGuidePackageV6, representation="text",
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
            validated = validate_practice_guide_package({key: value for key, value in package.items() if key != "payload_hash"})
            if validated.schema_version != "6.0":
                raise ValueError("new practice guide must use V6")
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
