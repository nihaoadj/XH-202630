"""Deterministic correction Markdown; no model, database or service access."""

from dataclasses import dataclass
import html

from app.models.learning_documents.correction_package import (
    CorrectionPackageV1, parse_correction_package, MAX_RENDERED_CHARACTERS,
)

EXERCISE_LABELS = (("guided", "引导式练习"), ("similar", "同构练习"), ("transfer", "迁移练习"))
STATUS_LABELS = {"weak": "薄弱", "learning": "学习中", "unknown": "未记录"}
DIMENSION_LABELS = {"concept_application": "概念应用", "concept_understanding": "概念理解",
                    "concept": "概念理解", "scenario": "情境应用", "misconception": "误区辨析",
                    "practice": "实践操作", "boundary": "适用边界", "application": "应用"}


@dataclass(frozen=True)
class CorrectionSourceField:
    path: str
    role: str
    start: int
    end: int


@dataclass(frozen=True)
class CorrectionAuditSource:
    text: str
    fields: tuple[CorrectionSourceField, ...]


def correction_audit_source(package: CorrectionPackageV1) -> CorrectionAuditSource:
    """Copy every content leaf exactly, excluding the server's personal context."""
    package = parse_correction_package(package)
    parts, fields = [], []
    offset = 0

    def walk(value, path):
        nonlocal offset
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            key = path.rsplit(".", 1)[-1].split("[", 1)[0]
            role = {"mistaken_view": "exercise_proposition", "incorrect_statement": "exercise_proposition",
                    "scenario": "scenario", "question": "question_context", "hints": "hint",
                    "training_goals": "instruction", "mastery_criteria": "criterion",
                    "next_review_actions": "instruction", "self_check_points": "criterion"}.get(key, "explanation")
            header = f"## {path} [{role}]\n\n"
            start = offset + len(header)
            parts.extend((header, value, "\n\n"))
            fields.append(CorrectionSourceField(path, role, start, start + len(value)))
            offset = start + len(value) + 2

    walk(package.content.model_dump(mode="json"), "content")
    return CorrectionAuditSource("".join(parts), tuple(fields))


def _text(value: str) -> str:
    # Indent each continuation so field text cannot create top-level headings.
    return html.escape(value, quote=False).replace("\n", "\n    ")


def render_correction_markdown(package: CorrectionPackageV1) -> str:
    """Render the validated package, collecting exercise answers at the end."""
    package = parse_correction_package(package)
    c, target = package.content, package.learning_status.target
    lines = [f"# {_text(package.title)}", "", "## 本次强化目标", "",
             f"- 目标知识点：{_text(target.node_name)}。",
             f"- 当前状态：{STATUS_LABELS[target.mastery_status]}。"]
    dimensions = [DIMENSION_LABELS[d] for d in target.failed_dimensions if d in DIMENSION_LABELS]
    if dimensions:
        lines.append(f"- 失分维度：{'、'.join(dimensions)}。")

    def items(values):
        lines.extend(f"- {_text(v)}" for v in values)
        lines.append("")

    def section(title):
        lines.extend(("", title, ""))

    items(c.training_goals)
    section("## 薄弱模式概览")
    items(c.focus_overview)
    section(f"## 强化单元：{_text(target.node_name)}")
    section("### 错误模式")
    for row in c.unit.error_patterns:
        items((f"待纠正观点：{row.mistaken_view}", row.explanation))
    section("### 核心概念补救")
    for row in c.unit.concept_repair:
        items((f"{row.point}：{row.explanation}",))
    section("### 正误对照")
    for row in c.unit.comparisons:
        items((f"误：{row.incorrect_statement}", f"正：{row.correct_statement}", row.explanation))
    if package.schema_version == "correction-package-v1":
        example = c.unit.worked_example
        section("### 完整示例")
        items((f"假设情境：{example.scenario}", f"任务：{example.task}"))
        for number, row in enumerate(example.steps, 1):
            items((f"{number}. {row.action}", row.explanation))
        items((example.takeaway,))
    exercise_labels = EXERCISE_LABELS if package.schema_version == "correction-package-v1" else tuple(
        (key, label) for key, label in EXERCISE_LABELS if key != "similar")
    for key, label in exercise_labels:
        row = getattr(c.unit.exercises, key)
        section(f"### {label}")
        items((f"假设情境：{row.scenario}", row.question))
    section("## 参考答案与分层反馈")
    for key, label in exercise_labels:
        row = getattr(c.unit.exercises, key)
        section(f"### {label}参考答案")
        if row.hints:
            items([f"提示：{v}" for v in row.hints])
        items((row.reference_answer, row.explanation))
        items([f"自查：{v}" for v in row.self_check_points])
    for key, label in (("foundation", "基础层"), ("proficient", "进阶层"), ("advanced", "挑战层")):
        items((f"{label}：{getattr(c.layered_feedback, key)}",))
    section("## 达标标准")
    items(c.mastery_criteria)
    section("## 后续复习动作")
    items(c.next_review_actions)
    section("## 总结")
    lines.extend((_text(c.summary), ""))
    text = "\n".join(lines)
    if len(text) > MAX_RENDERED_CHARACTERS:
        raise ValueError("correction Markdown exceeds the character budget")
    return text


CORRECTION_AUDIT_GUIDANCE = """纠错包审核适配 correction-content-audit-v1：只审核 content 叶子和目标教学质量。
exercise_proposition 是明确的待纠正错误命题，不代表作者认可；其 explanation 必须正确。
scenario 是假设条件，不核验情境是否真实发生，但其中的独立技术事实仍需核验。
question_context/instruction/criterion 中的提问或教学指令不是事实，其中的技术断言仍审核。
explanation/answer/summary 中的技术结论、示例推理、参考答案必须审核，不能整段豁免。
服务端学习状态不在本输入中；不得猜测学习者诊断。字段路径与角色只用于定位和消歧，不是证据。"""

COMPACT_AUDIT_GUIDANCE = CORRECTION_AUDIT_GUIDANCE + """
双练习版本只要求guided和transfer，不要求完整示例或similar练习；保留目标、概览、达标标准和复习动作。
training_goals/focus_overview/mastery_criteria/next_review_actions只承载学习目标、关注点、行为标准和复习动作。
普通审核必须检查这些字段，若其中包含应由证据核验的技术讲解/规则/结论，要求移入对应解释字段，不能利用其Claim排除范围藏知识内容。
其他内容按现有自包含性、难度、目标覆盖和技术正确性审核；两题必须有充分上下文和对应答案。
"""


def validated_correction_package(resource, *, targets=None):
    """Verify canonical identity and exact public projection before any AI input."""
    package = parse_correction_package(resource.correction_package_payload)
    if resource.correction_package_payload_hash != package.payload_hash:
        raise ValueError("correction persisted hash mismatch")
    if (resource.content_text or "").strip() != render_correction_markdown(package).strip():
        raise ValueError("correction package/Markdown mismatch")
    expected = [package.learning_status.target.node_id]
    if list(resource.knowledge_points) != expected or (targets is not None and list(targets) != expected):
        raise ValueError("correction target mismatch")
    return package


def correction_model_projection(package):
    compact = package.schema_version == "correction-package-v2"
    return {"adapter_version": "correction-content-audit-v2" if compact else "correction-content-audit-v1",
            "role_guidance": COMPACT_AUDIT_GUIDANCE if compact else CORRECTION_AUDIT_GUIDANCE,
            "target_node_name": package.learning_status.target.node_name,
            "content": package.content.model_dump(mode="json")}
