from datetime import datetime, timezone

from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.questionnaire.memory import MemoryQuestionnaireRepository
from app.models.learning_documents.schemas import FeedbackAnswer, FeedbackRecord, LearnerProfile
from app.services.learners.history import LearningHistoryService
from app.services.learners.profiles import ProfileService


def test_learning_history_merges_initial_profile_submissions_into_one_event():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="history_initial_001",
            learner_type="测试学习者",
            education="本科",
            major="软件工程",
            knowledge_base_id="rag_engineering_training",
            learning_goal="完成画像创建",
        )
    )
    questionnaire_repo = MemoryQuestionnaireRepository()
    questionnaire_repo.submissions = [
        {
            "submission_id": "submission_common",
            "questionnaire_id": "common_initial_profile_v1",
            "learner_id": "history_initial_001",
            "track_id": "rag_engineering_training",
            "knowledge_base_id": "rag_engineering_training",
            "answers": {"learning_goal": "了解基础概念"},
            "profile_updates": {},
            "metadata": {"purpose": "initial_profile"},
            "created_at": datetime(2026, 8, 16, 2, 45, 29, tzinfo=timezone.utc),
        },
        {
            "submission_id": "submission_track",
            "questionnaire_id": "rag_track_profile_v1",
            "learner_id": "history_initial_001",
            "track_id": "rag_engineering_training",
            "knowledge_base_id": "rag_engineering_training",
            "answers": {"known_rag_nodes": ["Embedding"]},
            "profile_updates": {},
            "metadata": {"purpose": "initial_profile"},
            "created_at": datetime(2026, 8, 16, 2, 45, 29, tzinfo=timezone.utc),
        },
    ]

    service = LearningHistoryService(
        profile_service=ProfileService(learner_repo),
        questionnaire_repo=questionnaire_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
        generation_job_repo=MemoryGenerationJobRepository(),
        feedback_repo=MemoryFeedbackRepository(),
    )

    timeline = service.timeline("history_initial_001")

    assert timeline is not None
    initial_events = [event for event in timeline.events if event.event_type == "initial_profile_created"]
    assert len(initial_events) == 1
    assert initial_events[0].title == "创建学习方向画像"
    assert initial_events[0].payload["submission_count"] == 2
    assert initial_events[0].payload["questionnaire_ids"] == [
        "common_initial_profile_v1",
        "rag_track_profile_v1",
    ]
    assert initial_events[0].payload["answers"]["learning_goal"] == "了解基础概念"
    assert initial_events[0].payload["answers"]["known_rag_nodes"] == ["Embedding"]


def test_learning_history_includes_feedback_before_feedback_based_regeneration():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="history_001",
            learner_type="测试学习者",
            education="本科",
            major="软件工程",
            knowledge_base_id="rag_engineering_training",
            learning_goal="验证完整学习闭环",
        )
    )
    questionnaire_repo = MemoryQuestionnaireRepository()
    diagnosis_repo = MemoryDiagnosisRepository()
    job_repo = MemoryGenerationJobRepository()
    feedback_repo = MemoryFeedbackRepository()

    job_repo.create(
        run_id="run_first",
        learner_id="history_001",
        topic="第一次资源生成",
        knowledge_base_id="rag_engineering_training",
        request_payload={
            "learner_id": "history_001",
            "topic": "第一次资源生成",
            "constraints": {},
        },
    )
    job_repo.mark_completed("run_first", ["resource_first"])

    feedback_repo.save(
        FeedbackRecord(
            feedback_id="feedback_001",
            learner_id="history_001",
            resource_id="resource_first",
            correct_rate=0.5,
            decision="降维解释",
            feedback_type="run_evaluation_feedback",
            answers=[
                FeedbackAnswer(
                    question_id="q1",
                    correct=False,
                    knowledge_point="Chunk 切分",
                    answer="错误答案",
                    expected_answer="正确答案",
                )
            ],
            decision_reason="正确率低于 60%，需要降低难度并补齐前置知识。",
            next_action="regenerate",
            recommended_topics=["Chunk 切分"],
            regenerate_suggestion={"topic": "Chunk 切分 补救训练"},
            practice_result={
                "run_id": "run_first",
                "evaluation_total": 10,
                "evaluation_correct": 5,
                "evaluated_resource_ids": ["resource_first"],
            },
            created_at=datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        )
    )

    job_repo.create(
        run_id="run_regenerated",
        learner_id="history_001",
        topic="Chunk 切分 补救训练",
        knowledge_base_id="rag_engineering_training",
        request_payload={
            "learner_id": "history_001",
            "topic": "Chunk 切分 补救训练",
            "constraints": {
                "based_on_feedback_id": "feedback_001",
                "based_on_feedback_run_id": "run_first",
                "based_on_feedback_resource_ids": ["resource_first"],
            },
        },
    )
    job_repo.mark_completed("run_regenerated", ["resource_regenerated"])

    service = LearningHistoryService(
        profile_service=ProfileService(learner_repo),
        questionnaire_repo=questionnaire_repo,
        diagnosis_repo=diagnosis_repo,
        generation_job_repo=job_repo,
        feedback_repo=feedback_repo,
    )

    timeline = service.timeline("history_001")

    assert timeline is not None
    feedback_event = next(
        event for event in timeline.events if event.event_id == "feedback_001"
    )
    regenerated_event = next(
        event for event in timeline.events if event.event_id == "run_regenerated"
    )
    assert feedback_event.event_type == "post_learning_diagnosis_completed"
    assert feedback_event.title == "完成学习后测评/反馈诊断"
    assert feedback_event.payload["run_id"] == "run_first"
    assert feedback_event.payload["wrong_knowledge_points"] == ["Chunk 切分"]
    assert regenerated_event.title == "基于反馈重新生成"
    assert regenerated_event.payload["based_on_feedback_id"] == "feedback_001"
    assert regenerated_event.description.startswith("基于学习后测评 50%")
