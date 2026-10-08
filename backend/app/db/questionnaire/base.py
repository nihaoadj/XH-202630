"""问卷仓储接口定义。"""
from abc import ABC, abstractmethod
from typing import Any, Mapping


class BaseQuestionnaireRepository(ABC):
    @abstractmethod
    def upsert_questionnaire_template(self, template: Mapping[str, Any], source_path: str | None = None) -> None:
        """保存问卷模板及其题目配置。"""

    @abstractmethod
    def list_questionnaire_templates(self) -> list[dict[str, Any]]:
        """列出当前启用的问卷模板。"""

    @abstractmethod
    def get_questionnaire_template(self, questionnaire_id: str) -> dict[str, Any] | None:
        """按问卷 ID 获取模板。"""

    @abstractmethod
    def get_questionnaire_for_track(self, track_id: str, knowledge_base_id: str | None = None) -> dict[str, Any] | None:
        """按学习方向或知识库 ID 获取方向问卷。"""

    @abstractmethod
    def save_submission(
        self,
        *,
        questionnaire_id: str,
        learner_id: str,
        answers: Mapping[str, Any],
        track_id: str | None = None,
        knowledge_base_id: str | None = None,
        profile_updates: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """保存一次问卷提交。"""

    @abstractmethod
    def list_submissions_by_learner(self, learner_id: str) -> list[dict[str, Any]]:
        """列出指定学习者的问卷提交记录。"""
