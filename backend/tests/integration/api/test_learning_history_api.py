from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learners import history as history_api
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.questionnaire.memory import MemoryQuestionnaireRepository
from app.models.learning_documents.schemas import FeedbackAnswer, FeedbackRecord, LearnerProfile
from app.services.learners.history import LearningHistoryService
from app.services.learners.profiles import ProfileService


def test_path_change_summary_exposes_real_node_changes_and_names():
    service = LearningHistoryService(
        None, None, None, None, None,
        knowledge_service=SimpleNamespace(
            list_skill_nodes=lambda knowledge_base_id: [
                SimpleNamespace(node_id="kp-retrieval", name="检索流程", children=["kp-embedding"]),
                SimpleNamespace(node_id="kp-embedding", name="向量嵌入", children=[]),
            ],
        ),
    )
    result = SimpleNamespace(
        path_mutation=SimpleNamespace(
            mutation_type=SimpleNamespace(value="insert_remedial"),
            completed_node_ids=[], unlocked_node_ids=[], inserted_node_ids=["node-remedial"],
            path_version_before=1, path_version_after=2,
        ),
        learning_path=SimpleNamespace(nodes=[
            SimpleNamespace(
                node_id="node-remedial", knowledge_point_id="kp-retrieval",
                node_type=SimpleNamespace(value="remedial"), status=SimpleNamespace(value="available"),
            ),
        ]),
        knowledge_state_updates=[],
    )

    summary = service._path_change_summary(result, "rag_engineering_training")

    assert summary["mutation_type"] == "insert_remedial"
    assert summary["inserted_nodes"] == [{
        "node_id": "node-remedial",
        "knowledge_point_id": "kp-retrieval",
        "name": "检索流程",
        "node_type": "remedial",
        "status": "available",
    }]
    assert summary["assessed_nodes"] == []
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

    journey = service.journey("history_001")
    first_round = next(item for item in journey.rounds if item.run_id == "run_first")
    assert first_round.assessment["score"] == 0.5
    assert first_round.feedback["targets"] == ["Chunk 切分"]


def test_learning_journey_groups_generation_round_and_keeps_current_state():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="journey_001", learner_type="测试学习者", education="本科", major="软件工程",
        knowledge_base_id="rag_engineering_training", learning_goal="理解检索流程",
    ))
    job_repo = MemoryGenerationJobRepository()
    job_repo.create("run_journey", "journey_001", "检索流程入门", "rag_engineering_training", {
        "learner_id": "journey_001", "topic": "检索流程入门",
    })
    job_repo.mark_completed("run_journey", ["resource_journey"])
    resource_repo = MemoryResourceRepository()
    from app.models.learning_documents.schemas import LearningResource
    resource_repo.save(LearningResource(
        resource_id="resource_journey", learner_id="journey_001", topic="检索流程入门",
        resource_type="讲义", difficulty="初级", knowledge_points=["检索流程"], source_refs=[],
        publication_status="published", run_id="run_journey",
    ), "journey_001", "检索流程入门", run_id="run_journey")

    service = LearningHistoryService(
        profile_service=ProfileService(learner_repo), questionnaire_repo=MemoryQuestionnaireRepository(),
        diagnosis_repo=MemoryDiagnosisRepository(), generation_job_repo=job_repo,
        feedback_repo=MemoryFeedbackRepository(), resource_repo=resource_repo,
    )

    journey = service.journey("journey_001")

    assert journey is not None
    assert journey.total_rounds == 1
    assert journey.rounds[0].run_id == "run_journey"
    assert journey.rounds[0].resources[0]["publication_status"] == "published"
    assert journey.rounds[0].run_summary["availability"] == "legacy_or_unavailable"


def test_learning_journey_uses_one_feedback_chain_for_all_runs_in_a_batch():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="journey_batch_001", learner_type="测试学习者", education="本科", major="软件工程",
        knowledge_base_id="rag_engineering_training", learning_goal="验证批次聚合",
    ))
    job_repo = MemoryGenerationJobRepository()
    for run_id, resource_type in (("run_batch_lecture", "讲义"), ("run_batch_assessment", "分阶测试题")):
        job_repo.create(
            run_id,
            "journey_batch_001",
            "批次聚合测试",
            "rag_engineering_training",
            {"topic": "批次聚合测试", "resource_types": [resource_type]},
            batch_id="batch_shared",
        )
        job_repo.mark_completed(run_id, [f"resource_{run_id}"])

    from app.models.learning_documents.schemas import LearningResource
    resource_repo = MemoryResourceRepository()
    for run_id, resource_type in (("run_batch_lecture", "讲义"), ("run_batch_assessment", "分阶测试题")):
        resource_repo.save(LearningResource(
            resource_id=f"resource_{run_id}", learner_id="journey_batch_001", topic="批次聚合测试",
            resource_type=resource_type, difficulty="初级", knowledge_points=["检索流程"], source_refs=[],
            publication_status="published", run_id=run_id, batch_id="batch_shared",
        ), "journey_batch_001", "批次聚合测试", run_id=run_id, batch_id="batch_shared")

    submitted_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    result = SimpleNamespace(
        attempt=SimpleNamespace(
            attempt_id="attempt_batch", source_run_id="run_batch_assessment",
            metadata={"source_batch_id": "batch_shared"}, submitted_at=submitted_at,
            overall_score=0.75, duration_ms=1000, hint_count=0,
            knowledge_point_results=[SimpleNamespace(
                knowledge_point_id="检索流程", score=0.75, correct_count=3, total_count=4,
            )],
        ),
        decision=SimpleNamespace(
            action=SimpleNamespace(value="practice"), decision_reason="继续巩固", target_knowledge_point_ids=["检索流程"],
        ),
        analysis=SimpleNamespace(learner_suggestions=["完成巩固练习"]),
        followup_run_ids=[],
        followup_relations=[],
        path_mutation=SimpleNamespace(
            mutation_type=SimpleNamespace(value="insert_practice"), completed_node_ids=[],
            unlocked_node_ids=[], inserted_node_ids=["node_practice"], path_version_before=1,
            path_version_after=2,
        ),
        knowledge_state_updates=[],
    )
    feedback_loop_repo = SimpleNamespace(
        list_results=lambda learner_id, limit=500: [result],
        get_current_path=lambda learner_id: None,
    )

    service = LearningHistoryService(
        profile_service=ProfileService(learner_repo), questionnaire_repo=MemoryQuestionnaireRepository(),
        diagnosis_repo=MemoryDiagnosisRepository(), generation_job_repo=job_repo,
        feedback_repo=MemoryFeedbackRepository(), feedback_loop_repo=feedback_loop_repo,
        resource_repo=resource_repo,
    )

    journey = service.journey("journey_batch_001")

    assert journey is not None
    assert journey.total_rounds == 1
    assert journey.rounds[0].batch_id == "batch_shared"
    assert journey.rounds[0].run_ids == ["run_batch_lecture", "run_batch_assessment"]
    assert {item["resource_type"] for item in journey.rounds[0].resources} == {"讲义", "分阶测试题"}
    assert journey.rounds[0].assessment["score"] == 0.75
    assert journey.rounds[0].feedback["action"] == "practice"
    assert journey.rounds[0].path_change["path_version_after"] == 2


def test_learning_journey_keeps_correction_package_assessment_in_a_separate_round():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="journey_correction_001", learner_type="测试学习者", education="本科", major="软件工程",
        knowledge_base_id="rag_engineering_training", learning_goal="验证纠错包独立测评",
    ))
    job_repo = MemoryGenerationJobRepository()
    job_repo.create(
        "run_source",
        "journey_correction_001",
        "原始学习批次",
        "rag_engineering_training",
        {"topic": "原始学习批次", "resource_types": ["讲义"]},
        batch_id="batch_shared",
    )
    job_repo.mark_completed("run_source", ["resource_source"])
    job_repo.create(
        "run_correction",
        "journey_correction_001",
        "纠错训练批次",
        "rag_engineering_training",
        {
            "topic": "纠错训练批次",
            "resource_types": ["个性化纠错训练包", "分阶测试题"],
            "constraints": {
                "selection_type": "correction_package",
                "feedback_attempt_id": "attempt_source",
                "correction_focus_snapshot": {"source_run_id": "run_source"},
            },
        },
        batch_id="batch_shared",
    )
    job_repo.mark_completed("run_correction", ["resource_correction"])

    from app.models.learning_documents.schemas import LearningResource
    resource_repo = MemoryResourceRepository()
    for resource_id, run_id, resource_type in (
        ("resource_source", "run_source", "讲义"),
        ("resource_correction", "run_correction", "分阶测试题"),
    ):
        resource_repo.save(LearningResource(
            resource_id=resource_id, learner_id="journey_correction_001", topic="学习批次",
            resource_type=resource_type, difficulty="初级", knowledge_points=["检索流程"], source_refs=[],
            publication_status="published", run_id=run_id, batch_id="batch_shared",
        ), "journey_correction_001", "学习批次", run_id=run_id, batch_id="batch_shared")

    def result(attempt_id, source_run_id, score):
        return SimpleNamespace(
            attempt=SimpleNamespace(
                attempt_id=attempt_id, source_run_id=source_run_id,
                metadata={"source_batch_id": "batch_shared"},
                submitted_at=datetime(2026, 8, 27, 12 if source_run_id == "run_source" else 13, tzinfo=timezone.utc),
                overall_score=score, duration_ms=1000, hint_count=0,
                knowledge_point_results=[SimpleNamespace(
                    knowledge_point_id="检索流程", score=score, correct_count=3, total_count=4,
                )],
            ),
            decision=SimpleNamespace(
                action=SimpleNamespace(value="practice"), decision_reason="继续巩固",
                target_knowledge_point_ids=["检索流程"],
            ),
            analysis=SimpleNamespace(learner_suggestions=["完成巩固练习"]),
            followup_run_ids=[], followup_relations=[],
            path_mutation=SimpleNamespace(
                mutation_type=SimpleNamespace(value="insert_practice"), completed_node_ids=[],
                unlocked_node_ids=[], inserted_node_ids=[], path_version_before=1, path_version_after=2,
            ),
            knowledge_state_updates=[],
        )

    source_result = result("attempt_source", "run_source", 0.5)
    correction_result = result("attempt_correction", "run_correction", 0.75)
    source_result.followup_relations = [{
        "parent_run_id": "run_source",
        "child_run_id": "run_correction",
        "relation_type": "selection",
    }]
    feedback_loop_repo = SimpleNamespace(
        list_results=lambda learner_id, limit=500: [correction_result, source_result],
        get_current_path=lambda learner_id: None,
    )
    service = LearningHistoryService(
        profile_service=ProfileService(learner_repo), questionnaire_repo=MemoryQuestionnaireRepository(),
        diagnosis_repo=MemoryDiagnosisRepository(), generation_job_repo=job_repo,
        feedback_repo=MemoryFeedbackRepository(), feedback_loop_repo=feedback_loop_repo,
        resource_repo=resource_repo,
    )

    journey = service.journey("journey_correction_001")

    assert journey is not None
    assert journey.total_rounds == 2
    rounds_by_run = {item.run_id: item for item in journey.rounds}
    assert rounds_by_run["run_source"].batch_id == rounds_by_run["run_correction"].batch_id == "batch_shared"
    assert [item["resource_type"] for item in rounds_by_run["run_source"].resources] == ["讲义"]
    assert [item["resource_type"] for item in rounds_by_run["run_correction"].resources] == ["分阶测试题"]
    assert rounds_by_run["run_source"].assessment["score"] == 0.5
    assert rounds_by_run["run_correction"].assessment["score"] == 0.75
    assert rounds_by_run["run_correction"].path_change["assessed_nodes"] == [{
        "node_id": "检索流程",
        "knowledge_point_id": "检索流程",
        "name": "检索流程",
    }]
    next_step = rounds_by_run["run_source"].path_change["next_steps"][0]
    assert next_step["run_id"] == "run_correction"
    assert next_step["round_id"] == "correction:batch_shared:attempt_source"
    assert next_step["relation_type"] == "selection"
    assert "个性化纠错训练包" in next_step["topic"]
    assert "分阶测试题" in next_step["topic"]


def test_learning_journey_endpoint_keeps_timeline_contract_available():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="journey_api", learner_type="测试学习者", education="本科", major="软件工程",
        knowledge_base_id="rag_engineering_training", learning_goal="接口验证",
    ))
    service = LearningHistoryService(
        profile_service=ProfileService(learners), questionnaire_repo=MemoryQuestionnaireRepository(),
        diagnosis_repo=MemoryDiagnosisRepository(), generation_job_repo=MemoryGenerationJobRepository(),
        feedback_repo=MemoryFeedbackRepository(),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners),
        learning_history_service=lambda: service,
    )
    app.include_router(history_api.router, prefix="/api/learning-history")
    client = TestClient(app)

    journey = client.get("/api/learning-history/journey_api/journey")
    timeline = client.get("/api/learning-history/journey_api/timeline")

    assert journey.status_code == 200
    assert journey.json()["total_rounds"] == 0
    assert journey.json()["current_state"]["current_nodes"] == []
    assert timeline.status_code == 200
    assert "events" in timeline.json()
