from app.models.schemas import FeedbackRequest, FeedbackResponse, LearnerProfile


class FeedbackService:
    """学习反馈与动态迭代业务服务
    
    无外部依赖，通过DI容器管理生命周期。
    """

    def process_feedback(self, profile: LearnerProfile, req: FeedbackRequest) -> FeedbackResponse:
        """处理学习反馈"""
        decision = self._decide_next_step(profile, req.correct_rate, req.resource_id)

        return FeedbackResponse(
            learner_id=req.learner_id,
            decision=decision,
            message=f"根据正确率 {req.correct_rate:.0%}，系统决定：{decision}",
            updated_profile=profile,
        )

    def _decide_next_step(self, profile: LearnerProfile, correct_rate: float, resource_id: str) -> str:
        """根据答题正确率决定下一步学习策略"""
        if correct_rate < 0.6:
            profile.weak_points.append(f"{resource_id}（基础薄弱）")
            profile.skill_level = "初级"
            return "降维解释"
        elif correct_rate > 0.85:
            profile.skill_level = "高级"
            return "进阶挑战任务"
        return "保持当前难度"
