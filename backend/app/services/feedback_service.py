import uuid

from app.agents.feedback import apply_feedback_decision, decide_feedback
from app.db.feedback.base import BaseFeedbackRepository
from app.models.schemas import FeedbackRecord, FeedbackRequest, FeedbackResponse, LearnerProfile


class FeedbackService:
    """学习反馈与动态迭代业务服务
    
    通过构造函数注入依赖。
    """

    def __init__(self, feedback_repo: BaseFeedbackRepository):
        self.feedback_repo = feedback_repo

    def process_feedback(self, profile: LearnerProfile, req: FeedbackRequest) -> FeedbackResponse:
        """处理学习反馈"""
        history = self.feedback_repo.list_by_learner(req.learner_id)
        decision_result = decide_feedback(profile, req, history)
        apply_feedback_decision(profile, req, decision_result)

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            learner_id=req.learner_id,
            resource_id=req.resource_id,
            correct_rate=req.correct_rate,
            decision=decision_result.decision,
            answers=req.answers,
            feedback_type=req.feedback_type,
            time_spent_seconds=req.time_spent_seconds,
            completed=req.completed,
            self_rating=req.self_rating,
            practice_result=req.practice_result,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )
        self.feedback_repo.save(record)

        return FeedbackResponse(
            learner_id=req.learner_id,
            decision=decision_result.decision,
            message=f"根据正确率 {req.correct_rate:.0%}，系统决定：{decision_result.decision}",
            updated_profile=profile,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )

    def list_history(self, learner_id: str) -> list[FeedbackRecord]:
        """查询学习者反馈历史"""
        return self.feedback_repo.list_by_learner(learner_id)
