from app.db.feedback.base import BaseFeedbackRepository
from app.db.resource.base import BaseResourceRepository
from app.models.schemas import LearnerProfile


class ReportService:
    """学情报告业务服务
    
    通过构造函数注入依赖。
    """

    def __init__(
        self,
        resource_repo: BaseResourceRepository,
        feedback_repo: BaseFeedbackRepository,
    ):
        self.resource_repo = resource_repo
        self.feedback_repo = feedback_repo

    def build_report(self, profile: LearnerProfile) -> dict:
        """构建学情报告"""
        topics = list(profile.theory_scores.keys())
        scores = list(profile.theory_scores.values())
        resources = self.resource_repo.list_by_learner(profile.learner_id)
        feedback = self.feedback_repo.list_by_learner(profile.learner_id)
        weak_points = list(dict.fromkeys(profile.weak_points))
        strong_points = list(dict.fromkeys(profile.strong_points))
        avg_feedback = (
            sum(item.correct_rate for item in feedback) / len(feedback)
            if feedback
            else None
        )

        return {
            "learner_id": profile.learner_id,
            "radar": {
                "dimensions": topics,
                "values": scores,
            },
            "weak_points": weak_points,
            "strong_points": strong_points,
            "skill_level": profile.skill_level,
            "learning_goal": profile.learning_goal,
            "difficulty_curve": [
                {
                    "topic": t,
                    "score": s,
                    "recommended_difficulty": "初级" if s < 60 else "中级" if s < 80 else "高级",
                }
                for t, s in profile.theory_scores.items()
            ],
            "learning_path": [
                {
                    "order": index + 1,
                    "topic": point,
                    "reason": "当前画像中的薄弱项，建议优先补齐",
                }
                for index, point in enumerate(weak_points[:5])
            ],
            "blind_spot_heatmap": [
                {
                    "topic": point,
                    "score": profile.theory_scores.get(point, 0),
                    "status": profile.knowledge_states.get(point).status
                    if point in profile.knowledge_states
                    else "weak",
                }
                for point in weak_points
            ],
            "agent_flow": [],
            "resource_difficulty_match": [
                {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "difficulty": resource.difficulty,
                    "difficulty_match": resource.difficulty_match,
                    "review_status": resource.review_status,
                }
                for resource in resources[-10:]
            ],
            "review_summary": {
                "resource_count": len(resources),
                "passed_count": len([
                    resource
                    for resource in resources
                    if resource.review_status in {"passed", "approved"}
                ]),
                "average_hallucination_rate": self._average_hallucination_rate(resources),
            },
            "feedback_trend": [
                {
                    "resource_id": item.resource_id,
                    "correct_rate": item.correct_rate,
                    "decision": item.decision,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in feedback[:10]
            ],
            "metric_summary": {
                "resource_count": len(resources),
                "feedback_count": len(feedback),
                "average_correct_rate": avg_feedback,
                "weak_point_count": len(weak_points),
            },
            "next_suggestions": weak_points[:3] or profile.last_feedback_summary.get("recommended_topics", []),
            "recent_resources": resources[-5:],
            "recent_feedback": feedback[:5],
        }

    def _average_hallucination_rate(self, resources) -> float:
        values = [
            resource.hallucination_rate
            for resource in resources
            if resource.hallucination_rate is not None
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)
