"""问卷仓储的内存实现。"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

from app.db.questionnaire.base import BaseQuestionnaireRepository


class MemoryQuestionnaireRepository(BaseQuestionnaireRepository):
    def __init__(self):
        self._templates: dict[str, dict[str, Any]] = {}
        self.submissions: list[dict[str, Any]] = []

    def upsert_questionnaire_template(self, template: Mapping[str, Any], source_path: str | None = None) -> None:
        payload = deepcopy(dict(template))
        if source_path:
            payload["source_path"] = source_path
        self._templates[payload["questionnaire_id"]] = payload

    def list_questionnaire_templates(self) -> list[dict[str, Any]]:
        return [deepcopy(template) for template in self._templates.values() if template.get("enabled", True)]

    def get_questionnaire_template(self, questionnaire_id: str) -> dict[str, Any] | None:
        template = self._templates.get(questionnaire_id)
        if template is None or not template.get("enabled", True):
            return None
        return deepcopy(template)

    def get_questionnaire_for_track(self, track_id: str, knowledge_base_id: str | None = None) -> dict[str, Any] | None:
        for template in self._templates.values():
            if not template.get("enabled", True) or template.get("scope") != "track":
                continue
            if template.get("track_id") == track_id or (
                knowledge_base_id is not None and template.get("knowledge_base_id") == knowledge_base_id
            ):
                return deepcopy(template)
        return None

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
        submission_id = _stable_id("questionnaire_submission", questionnaire_id, learner_id, len(self.submissions) + 1)
        self.submissions.append(
            {
                "submission_id": submission_id,
                "questionnaire_id": questionnaire_id,
                "learner_id": learner_id,
                "track_id": track_id,
                "knowledge_base_id": knowledge_base_id,
                "answers": deepcopy(dict(answers)),
                "profile_updates": deepcopy(dict(profile_updates or {})),
                "metadata": deepcopy(dict(metadata or {})),
            }
        )
        return submission_id

    def list_submissions_by_learner(self, learner_id: str) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self.submissions if item["learner_id"] == learner_id]


def _stable_id(prefix: str, *parts: object) -> str:
    text = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]}"
