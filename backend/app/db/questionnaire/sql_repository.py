"""问卷仓储的 SQLAlchemy 实现。"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from app.db.shared.models import (
    QuestionnaireAnswerORM,
    QuestionnaireQuestionORM,
    QuestionnaireSubmissionORM,
    QuestionnaireTemplateORM,
)
from app.db.questionnaire.base import BaseQuestionnaireRepository


def _stable_id(prefix: str, *parts: object) -> str:
    text = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]}"


class SQLQuestionnaireRepository(BaseQuestionnaireRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def upsert_questionnaire_template(self, template: Mapping[str, Any], source_path: str | None = None) -> None:
        questionnaire_id = str(template["questionnaire_id"])
        questions = list(template.get("questions", []))
        with self.session_factory() as db:
            values = {
                "scope": template["scope"],
                "domain_id": template.get("domain_id"),
                "track_id": template.get("track_id"),
                "knowledge_base_id": template.get("knowledge_base_id"),
                "name": template["name"],
                "description": template.get("description"),
                "version": template.get("version", "1.0.0"),
                "enabled": template.get("enabled", True),
                "source_path": source_path,
                "extra_metadata": template.get("metadata", {}),
            }
            row = db.get(QuestionnaireTemplateORM, questionnaire_id)
            if row is None:
                db.add(QuestionnaireTemplateORM(questionnaire_id=questionnaire_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

            question_ids = {str(question["question_id"]) for question in questions}
            stale = db.query(QuestionnaireQuestionORM).filter_by(questionnaire_id=questionnaire_id)
            if question_ids:
                stale = stale.filter(~QuestionnaireQuestionORM.question_id.in_(question_ids))
            stale.delete(synchronize_session=False)

            for question in questions:
                question_id = str(question["question_id"])
                question_uid = _stable_id("questionnaire_question", questionnaire_id, question_id)
                question_values = {
                    "questionnaire_id": questionnaire_id,
                    "question_id": question_id,
                    "field_key": question.get("field_key") or question_id,
                    "title": question["title"],
                    "question_type": question["type"],
                    "required": question.get("required", False),
                    "sort_order": question.get("sort_order", 100),
                    "hint": question.get("hint"),
                    "options": question.get("options", []),
                    "validation": question.get("validation", {}),
                    "show_when": question.get("show_when", {}),
                    "profile_mapping": question.get("profile_mapping", {}),
                    "extra_metadata": question.get("metadata", {}),
                }
                question_row = db.get(QuestionnaireQuestionORM, question_uid)
                if question_row is None:
                    db.add(QuestionnaireQuestionORM(question_uid=question_uid, **question_values))
                else:
                    for key, value in question_values.items():
                        setattr(question_row, key, value)
            db.commit()

    def list_questionnaire_templates(self) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = (
                db.query(QuestionnaireTemplateORM)
                .filter_by(enabled=True)
                .order_by(QuestionnaireTemplateORM.scope, QuestionnaireTemplateORM.name)
                .all()
            )
        return [self._template_payload(row, include_questions=False) for row in rows]

    def get_questionnaire_template(self, questionnaire_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(QuestionnaireTemplateORM, questionnaire_id)
            if row is None or not row.enabled:
                return None
            questions = (
                db.query(QuestionnaireQuestionORM)
                .filter_by(questionnaire_id=questionnaire_id)
                .order_by(QuestionnaireQuestionORM.sort_order, QuestionnaireQuestionORM.question_id)
                .all()
            )
            payload = self._template_payload(row, include_questions=False)
            payload["questions"] = [self._question_payload(question) for question in questions]
            return payload

    def get_questionnaire_for_track(self, track_id: str, knowledge_base_id: str | None = None) -> dict[str, Any] | None:
        with self.session_factory() as db:
            query = db.query(QuestionnaireTemplateORM).filter(
                QuestionnaireTemplateORM.enabled.is_(True),
                QuestionnaireTemplateORM.scope == "track",
            )
            if knowledge_base_id:
                query = query.filter(
                    (QuestionnaireTemplateORM.track_id == track_id)
                    | (QuestionnaireTemplateORM.knowledge_base_id == knowledge_base_id)
                )
            else:
                query = query.filter(QuestionnaireTemplateORM.track_id == track_id)
            row = query.order_by(QuestionnaireTemplateORM.version.desc()).first()
            if row is None:
                return None
            questionnaire_id = row.questionnaire_id
            questions = (
                db.query(QuestionnaireQuestionORM)
                .filter_by(questionnaire_id=questionnaire_id)
                .order_by(QuestionnaireQuestionORM.sort_order, QuestionnaireQuestionORM.question_id)
                .all()
            )
            payload = self._template_payload(row, include_questions=False)
            payload["questions"] = [self._question_payload(question) for question in questions]
            return payload

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
        with self.session_factory() as db:
            count = db.query(QuestionnaireSubmissionORM).filter_by(
                questionnaire_id=questionnaire_id,
                learner_id=learner_id,
            ).count()
            submission_id = _stable_id("questionnaire_submission", questionnaire_id, learner_id, count + 1)
            db.add(
                QuestionnaireSubmissionORM(
                    submission_id=submission_id,
                    questionnaire_id=questionnaire_id,
                    learner_id=learner_id,
                    track_id=track_id,
                    knowledge_base_id=knowledge_base_id,
                    answers_snapshot=dict(answers),
                    profile_updates=dict(profile_updates or {}),
                    extra_metadata=dict(metadata or {}),
                )
            )
            # The models intentionally avoid relationship() mappings, so flush
            # the parent row before adding answer rows that reference it.
            db.flush()
            questions = db.query(QuestionnaireQuestionORM).filter_by(questionnaire_id=questionnaire_id).all()
            by_field = {question.field_key: question for question in questions}
            by_id = {question.question_id: question for question in questions}
            for key, answer in answers.items():
                question = by_field.get(key) or by_id.get(key)
                if question is None:
                    continue
                db.add(
                    QuestionnaireAnswerORM(
                        answer_id=_stable_id("questionnaire_answer", submission_id, question.question_id),
                        submission_id=submission_id,
                        questionnaire_id=questionnaire_id,
                        question_id=question.question_id,
                        field_key=question.field_key,
                        answer=answer,
                        profile_mapping=question.profile_mapping or {},
                    )
                )
            db.commit()
            return submission_id

    def list_submissions_by_learner(self, learner_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = (
                db.query(QuestionnaireSubmissionORM)
                .filter_by(learner_id=learner_id)
                .order_by(QuestionnaireSubmissionORM.created_at.desc())
                .all()
            )
        return [
            {
                "submission_id": row.submission_id,
                "questionnaire_id": row.questionnaire_id,
                "learner_id": row.learner_id,
                "track_id": row.track_id,
                "knowledge_base_id": row.knowledge_base_id,
                "purpose": row.purpose,
                "answers": row.answers_snapshot or {},
                "profile_updates": row.profile_updates or {},
                "metadata": row.extra_metadata or {},
                "created_at": row.created_at,
            }
            for row in rows
        ]

    @staticmethod
    def _template_payload(row: QuestionnaireTemplateORM, include_questions: bool = True) -> dict[str, Any]:
        payload = {
            "questionnaire_id": row.questionnaire_id,
            "scope": row.scope,
            "domain_id": row.domain_id,
            "track_id": row.track_id,
            "knowledge_base_id": row.knowledge_base_id,
            "name": row.name,
            "description": row.description,
            "version": row.version,
            "enabled": row.enabled,
            "source_path": row.source_path,
            "metadata": row.extra_metadata or {},
        }
        if include_questions:
            payload["questions"] = []
        return payload

    @staticmethod
    def _question_payload(row: QuestionnaireQuestionORM) -> dict[str, Any]:
        return {
            "question_id": row.question_id,
            "field_key": row.field_key,
            "title": row.title,
            "type": row.question_type,
            "required": row.required,
            "sort_order": row.sort_order,
            "hint": row.hint,
            "options": row.options or [],
            "validation": row.validation or {},
            "show_when": row.show_when or {},
            "profile_mapping": row.profile_mapping or {},
            "metadata": row.extra_metadata or {},
        }
