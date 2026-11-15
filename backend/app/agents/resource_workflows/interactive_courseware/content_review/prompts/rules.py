from ..types import PromptFragment

RULES = (
    PromptFragment("factual_support", "1.0", "逐个事实与条件对照本项可读冻结原文/答案。矛盾为fail，缺依据为insufficient_evidence，不将ID视为正文支持。"),
    PromptFragment("scope_alignment", "1.0", "标题、总结、目标不得夸大来源知识范围、覆盖、能力或完成结果。"),
    PromptFragment("learning_guidance", "1.0", "仅引导真实页面支持的操作；不得发明按钮、评分、自动执行或宣称已经掌握。"),
    PromptFragment("procedural_consistency", "1.0", "核对准备、操作、验证、复盘的顺序与条件；不改变固定步骤或遗漏必要验证，GUI及非代码也适用。"),
    PromptFragment("code_constraints", "1.0", "仅对本项rule_ids明确包含code_constraints的说明核对冻结代码与环境限制；不发明版本、命令或执行能力，不实际执行代码。"),
)
