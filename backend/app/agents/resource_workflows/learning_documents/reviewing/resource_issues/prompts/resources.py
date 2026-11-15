"""Per-resource professional fragments, explicitly selected by the registry."""

from __future__ import annotations

from app.agents.resource_workflows.learning_documents.reviewing.types import PromptFragment


LECTURE = PromptFragment(
    "resource_issue.lecture", "1.1",
    """本资源为讲义。事实必须有冻结证据依据，难度符合冻结目标，每个冻结知识点在正文中有可学习的讲解。按实际内容判断覆盖，章节名、示例形式和是否有自检不作为门槛。
讲解示例检查读者能否凭正文理解结论；对实际布置的自检，检查同版题目和材料能否让读者独立作答。要求定位原文或核对原话时才需要相关原文。
复审对照新版示例或题目及同版材料核对原验收条件。新版若已改成仅依赖正文内足够的摘要或要点，按原验收条件关闭该缺材料问题；仍不成立时指出新版具体缺少的信息。不硬编码题材答案。""",
)

PRACTICE = PromptFragment(
    "resource_issue.practice", "1.2",
    """本资源为实操指南。专业门：结构必须是固定四阶段 V3/V4/V5/V6（prepare/practice/verify/reflect）；
每个步骤可执行、前置条件明确、验证方法可判定；准备阶段用通俗语言说清目标与环境。旧 V5 的材料按原字段审核；V6 所需输入在首次使用的步骤中由代码提供，不能只写名称、摘要、路径或 URL。V6 每个独立步骤都要有可运行代码，保存文件、阅读和检查并入相邻步骤说明或验证；不得把整份脚本提前交付再拆成复制、运行步骤。首次出现的术语要解释，步骤说明运行命令与可观察结果。只有静态 JSON、配置片段或预填答案而没有可运行程序，不满足实操要求。代码块、验证点属于其所属步骤，证据引用只指向冻结 Evidence；
不得把测试题/清单/案例/讲义内容写入实操步骤。""",
)

ASSESSMENT = PromptFragment(
    "resource_issue.assessment", "1.0",
    """本资源为分阶测试题。专业门：每节点固定 2 单选 + 2 多选 + 2 简答（2+2+2）；目标阶级正确；分值总和 100；
答案/rubric 与冻结证据一致；逐题 scope/清晰度/答案/rubric 都要判定，且不被整卷汇总压掉。
每题 supported_evidence_ids 仅选该题白名单中的直接支持证据，in_scope 至少一条，必要时可多条，不得重复。
必须输出完整 findings（每题恰好一条），失败检查通过 finding_keys 与本轮开放阻断问题精确对应。""",
)

CASE_STUDY = PromptFragment(
    "resource_issue.case_study", "1.0",
    """本资源为案例分析。专业门：依次包含唯一一级标题、案例背景、任务目标、分析过程、参考方案、复盘要点；
只含安全文本；情境/分析/结论一致；事实与参数有冻结证据支持，证据不足须明确“无法据此判断”。""",
)

CHECKLIST = PromptFragment(
    "resource_issue.checklist", "1.0",
    """本资源为复习清单。专业门：题量符合阶级；每个节点有带证据的知识小结；缺省槽位可审计（原因只能是
INSUFFICIENT_DISTINCT_EVIDENCE 或 NO_EXPLICIT_CONCEPT_BOUNDARY）；答案位置与原始渲染约束一致；
闭卷回忆与概念辨析各至少保留一道。""",
)

CORRECTION_PACKAGE = PromptFragment(
    "resource_issue.correction_package", "1.0",
    """本资源为个性化纠错训练包。prose-first：不新增必需章节；只做脚本安全检查；
事实、示例与练习答案必须由冻结 Evidence 支持；不猜测原测评题、选项或学习者作答。""",
)

RESOURCES = {
    "讲义": LECTURE,
    "实操指南": PRACTICE,
    "分阶测试题": ASSESSMENT,
    "案例分析": CASE_STUDY,
    "复习清单": CHECKLIST,
    "个性化纠错训练包": CORRECTION_PACKAGE,
}


def resource_fragment(resource_type: str) -> PromptFragment:
    fragment = RESOURCES.get(resource_type)
    if fragment is None:
        raise ValueError(f"unknown resource review type: {resource_type}")
    return fragment
