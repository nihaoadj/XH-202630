from typing import Annotated, Dict, List, Optional, TypedDict
import operator

from app.models.schemas import LearnerProfile, LearningResource


class AgentState(TypedDict):
    """多智能体共享状态"""
    learner: LearnerProfile
    topic: str
    resource_types: List[str]
    # 学情诊断输出
    diagnosis: Dict
    # 检索到的知识片段
    retrieved_chunks: List[Dict]
    # 学习路径规划输出
    learning_plan: Dict
    # 生成结果
    generated_resources: List[LearningResource]
    # 审核意见
    review_result: Dict
    # 最终决策
    final_decision: str
    # 执行轨迹
    trace: Annotated[List[Dict], operator.add]
    # 迭代次数
    iteration: int
