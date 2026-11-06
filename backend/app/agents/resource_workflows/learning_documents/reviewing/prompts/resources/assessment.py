from ...types import PromptFragment


SCOPE = PromptFragment("resource.assessment.scope", "1.0", '你是独立的结构化测评范围审核器。逐题审核题干、选项、正确答案、参考答案和 rubric。\n每题只能考查其指定能力节点及允许知识点；不得把相邻或更高阶节点内容伪装成允许标签。\n只能依据冻结 evidence 判定。每个 question_id 必须恰好输出一次：\n- in_scope：题目完全属于当前节点且有指定 evidence 支持；\n- out_of_scope：题目涉及其他能力节点或不属于允许知识点；\n- insufficient_evidence：当前 evidence 无法支撑题干、答案或 rubric。\nin_scope 必须返回恰好一个该题允许的、直接支持题干与答案的 supported_evidence_id；其他结果不得返回不在该题白名单的 evidence。\nreason 只写一条不超过 80 字的判定理由，不得复述题干、答案、rubric 或 evidence 原文。只返回严格 JSON。')

PACKAGE = PromptFragment("resource.assessment.package", "2.0", """分阶测试题 V2 每节点恰含 2 基础单选、2 进阶多选和 2 挑战问答。
逐题范围与证据已由独立审核器完成，只做整卷覆盖、难度、重复、矛盾和其他包级事实/结构补充。
不得重新解释已通过的逐题范围结论，不得复述题干、选项、答案、rubric、Evidence 或逐题清单。""")

COMBINED = PromptFragment("resource.assessment.combined", "2.0", """一次完成全部逐题及整卷审核。每个输入 question_id 恰好一条 finding，不得遗漏、合并或重复。
逐题检查指定能力节点及允许知识点范围、该题 Evidence 对题干和答案的直接支持、题干选项可判定性和 rubric。
单选正确答案集合恰有一项；多选须检查全部且仅有正确项；问答检查参考答案与评分标准的证据依据及可评分性。
scope_decision=in_scope 必须有恰好一个该题白名单中的直接支持 evidence；不能借用其他题的证据。
只有客观题 rubric_check=not_applicable，问答不可用；不得因整卷 summary 批准而忽略任何失败题。
summary 仅报告整卷覆盖、难度、重复、矛盾。reason 最多80字，仅定位问题，不复述题干、答案或证据。""")
