from app.agents.resource_agents.lecture_contract import LECTURE_REVIEW_GUIDANCE

from ...types import PromptFragment

TEXT = PromptFragment(
    "resource.text", "2.1",
    "审核讲义的概念、事实和教学解释是否有本资源证据支持，覆盖冻结目标并符合目标难度。"
    + LECTURE_REVIEW_GUIDANCE,
)
