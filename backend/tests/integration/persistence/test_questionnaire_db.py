"""问卷 SQL 同步测试。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.shared.models import (
    Base,
    LearnerProfileORM,
    QuestionnaireAnswerORM,
    QuestionnaireQuestionORM,
    QuestionnaireSubmissionORM,
    QuestionnaireTemplateORM,
)
from app.db.questionnaire.sql_repository import SQLQuestionnaireRepository
from tests.paths import KNOWLEDGE_BASE_ROOT


def test_questionnaire_source_sync_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'questionnaire.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    catalog = KnowledgeCatalogRepository(factory)
    repository = SQLQuestionnaireRepository(factory)
    manifest = load_knowledge_base_manifest()
    catalog.upsert_knowledge_base(manifest)
    catalog.upsert_learning_catalog(
        {
            "domain_id": "ai_application",
            "name": "AI 应用开发",
            "description": "测试领域",
            "sort_order": 10,
            "enabled": True,
        },
        {
            "track_id": "rag_engineering_training",
            "domain_id": "ai_application",
            "knowledge_base_id": "rag_engineering_training",
            "name": "RAG 工程链路培训",
            "description": "测试方向",
            "sort_order": 10,
            "enabled": True,
        },
    )

    common_path = KNOWLEDGE_BASE_ROOT / "questionnaire_common.json"
    track_path = KNOWLEDGE_BASE_ROOT / "rag_engineering_training" / "questionnaire.json"
    common_template = json.loads(common_path.read_text(encoding="utf-8"))
    track_template = json.loads(track_path.read_text(encoding="utf-8"))

    repository.upsert_questionnaire_template(common_template, source_path="knowledge_base/questionnaire_common.json")
    repository.upsert_questionnaire_template(track_template, source_path="knowledge_base/rag_engineering_training/questionnaire.json")
    repository.upsert_questionnaire_template(track_template, source_path="knowledge_base/rag_engineering_training/questionnaire.json")

    with factory() as db:
        assert db.query(QuestionnaireTemplateORM).count() == 2
        assert db.query(QuestionnaireQuestionORM).count() == len(common_template["questions"]) + len(track_template["questions"])

    loaded = repository.get_questionnaire_template("rag_engineering_initial_profile_v1")
    assert loaded is not None
    assert loaded["track_id"] == "rag_engineering_training"
    assert [question["question_id"] for question in loaded["questions"]][-1] == "learning_focus_rag_nodes"
    assert loaded["questions"][-1]["profile_mapping"]["target_path"] == "learning_preferences.focus_nodes"

    common_loaded = repository.get_questionnaire_template("common_initial_profile_v1")
    common_question_ids = [question["question_id"] for question in common_loaded["questions"]]
    assert "identity" not in common_question_ids
    assert "education" not in common_question_ids
    assert "major" not in common_question_ids
    assert "desired_resource_types" not in common_question_ids

    with factory() as db:
        db.add(
            LearnerProfileORM(
                learner_id="questionnaire_learner",
                learner_type="测试",
                education="本科",
                major="软件工程",
                learning_goal="验证问卷提交",
            )
        )
        db.commit()

    submission_id = repository.save_submission(
        questionnaire_id="rag_engineering_initial_profile_v1",
        learner_id="questionnaire_learner",
        track_id="rag_engineering_training",
        knowledge_base_id="rag_engineering_training",
        answers={
            "rag_level": "听说过，但说不清流程",
            "known_rag_nodes": ["Embedding"],
            "learning_focus_rag_nodes": ["Embedding"],
        },
        profile_updates={"learning_preferences": {"focus_nodes": ["Embedding"]}},
    )

    with factory() as db:
        assert db.query(QuestionnaireSubmissionORM).filter_by(submission_id=submission_id).count() == 1
        assert db.query(QuestionnaireAnswerORM).filter_by(submission_id=submission_id).count() == 3
