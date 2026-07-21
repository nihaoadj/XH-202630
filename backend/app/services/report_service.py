from app.models.schemas import LearnerProfile


class ReportService:
    """学情报告业务服务
    
    无外部依赖，通过DI容器管理生命周期。
    """

    def build_report(self, profile: LearnerProfile) -> dict:
        """构建学情报告"""
        topics = list(profile.theory_scores.keys())
        scores = list(profile.theory_scores.values())

        return {
            "learner_id": profile.learner_id,
            "radar": {
                "dimensions": topics,
                "values": scores,
            },
            "weak_points": profile.weak_points,
            "strong_points": profile.strong_points,
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
        }
