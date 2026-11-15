from typing import Optional

from app.core.learning_tiers import difficulty_for_tier
from app.db.feedback.round_base import BaseRoundRepository
from app.db.learners.base import BaseLearnerRepository
from app.models.learning_documents.schemas import LearnerProfile


class ProfileService:
    """学习者画像查询与维护服务。

    首次创建画像由 OnboardingService 根据问卷完成；本服务只负责已存在画像的查询、维护和删除。
    """

    def __init__(self, repo: BaseLearnerRepository, round_repository: BaseRoundRepository | None = None):
        """初始化服务
        
        Args:
            repo: 学习者画像仓库（通过DI容器注入）
        """
        self.repo = repo
        self.round_repository = round_repository

    def _with_rating(self, profile: Optional[LearnerProfile]) -> Optional[LearnerProfile]:
        if profile is None:
            return None
        primary = (self.round_repository.latest_primary_node(profile.learner_id, profile.knowledge_base_id)
                   if self.round_repository is not None and profile.knowledge_base_id else None)
        valid = primary is not None and primary.get("tier") in {1, 2, 3}
        # Return a copy: memory repositories share stored profile objects.
        return profile.model_copy(update={
            "initial_skill_level": profile.skill_level,
            "current_skill_level": difficulty_for_tier(primary["tier"]) if valid else profile.skill_level,
            "current_skill_node_id": primary["skill_node_id"] if valid else None,
        })

    def save_existing_profile(self, profile: LearnerProfile) -> Optional[LearnerProfile]:
        """保存已存在画像的系统更新，不承担首次创建职责。"""
        if self.repo.get(profile.learner_id) is None:
            return None
        self.repo.save(profile)
        return self._with_rating(profile)

    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        """获取学习者画像"""
        return self._with_rating(self.repo.get(learner_id))

    def delete(self, learner_id: str) -> bool:
        """删除学习者画像"""
        return self.repo.delete(learner_id)

    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        illegal = sorted(self.SYSTEM_FIELDS.intersection(updates))
        if illegal:
            raise PermissionError(",".join(illegal))
        return self._with_rating(self.repo.update_partial(learner_id, updates))

    def list_with_pagination(
        self,
        page: int,
        page_size: int,
        skill_level: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        result = self.repo.list_with_pagination(page, page_size, skill_level, user_id)
        return {**result, "items": [self._with_rating(item) for item in result["items"]]}
    SYSTEM_FIELDS = frozenset({
        "knowledge_states",
        "theory_scores",
        "weak_points",
        "strong_points",
        "skill_level",
        "initial_skill_level",
        "current_skill_level",
        "current_skill_node_id",
        "last_feedback_summary",
        "profile_version",
        "knowledge_base_id",
    })
