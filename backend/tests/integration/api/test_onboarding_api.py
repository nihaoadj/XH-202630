"""Onboarding 初始画像创建与自适应诊断测试。"""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learners import diagnosis
from app.api.onboarding import onboarding
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.questionnaire.memory import MemoryQuestionnaireRepository
from app.db.users.memory import MemoryUserRepository
from app.models.users.users import UserProfile
from app.services.learners.diagnosis import DiagnosisService
from app.services.learners.mastery import MasteryService
from app.services.knowledge.knowledge import KnowledgeService
from app.services.onboarding.onboarding import OnboardingService
from tests.paths import KNOWLEDGE_BASE_ROOT


def _client():
    knowledge_service = KnowledgeService()
    learner_repo = MemoryLearnerRepository()
    questionnaire_repo = MemoryQuestionnaireRepository()
    user_repo = MemoryUserRepository()
    user_repo.save(
        UserProfile(
            user_id="user_001",
            display_name="测试用户",
            identity="在校学生",
            education="本科",
            major="软件工程",
        )
    )
    questionnaire_repo.upsert_questionnaire_template(
        json.loads((KNOWLEDGE_BASE_ROOT / "questionnaire_common.json").read_text(encoding="utf-8")),
        source_path="knowledge_base/questionnaire_common.json",
    )
    questionnaire_repo.upsert_questionnaire_template(
        json.loads((KNOWLEDGE_BASE_ROOT / "rag_engineering_training" / "questionnaire.json").read_text(encoding="utf-8")),
        source_path="knowledge_base/rag_engineering_training/questionnaire.json",
    )
    mastery_service = MasteryService(MemoryMasteryRepository(learner_repo), knowledge_service)
    onboarding_service = OnboardingService(
        learner_repo, knowledge_service, questionnaire_repo, user_repo, mastery_service
    )
    diagnosis_service = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
        mastery_service=mastery_service,
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        onboarding_service=lambda: onboarding_service,
        diagnosis_service=lambda: diagnosis_service,
    )
    app.include_router(onboarding.router, prefix="/api/onboarding")
    app.include_router(diagnosis.router, prefix="/api/diagnosis")
    return TestClient(app), learner_repo, knowledge_service


def _questionnaire_payload():
    return {
        "learner_id": "user_001__rag_engineering_training",
        "user_id": "user_001",
        "learning_direction_id": "rag_engineering_training",
        "learning_goals": ["了解基础概念", "完成一个入门项目"],
        "python_level": "能写脚本和调用 API",
        "llm_api_level": "调用过 OpenAI 或兼容 API",
        "prompt_level": "会写简单提问",
        "rag_level": "听说过，但说不清流程",
        "known_rag_nodes": ["Embedding", "Rerank"],
        "learning_modes": ["先讲概念，再做练习"],
        "weekly_time_budget": "2-4 小时",
    }


def test_onboarding_creates_stage_scoped_three_node_diagnostic_questions():
    client, repository, _ = _client()
    response = client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())

    assert response.status_code == 200
    body = response.json()
    learner_id = body["learner_id"]
    assert learner_id.startswith("user_001__rag_engineering_training__")
    assert body["diagnostic_node_ids"] == ["rag_basics", "document_parsing", "embedding"]
    assert body["screening_results"] == {}
    assert body["questionnaire_tier"] == 1
    assert body["initial_diagnostic_status"] == "pending"
    assert len(body["diagnostic_questions"]) == 9
    returned_node_ids = [question["skill_node_id"] for question in body["diagnostic_questions"]]
    assert returned_node_ids == ["rag_basics"] * 3 + ["document_parsing"] * 3 + ["embedding"] * 3
    assert all("answer" not in question and "explanation" not in question for question in body["diagnostic_questions"])
    assert "chunking" in body["not_started_node_ids"]

    profile = repository.get(learner_id)
    assert profile.knowledge_states["chunking"].status == "unassessed"
    assert "Chunk 切分" not in profile.weak_points
    assert profile.learning_preferences.metadata["onboarding"]["weekly_time_budget"] == "2-4 小时"
    assert profile.education == "本科"
    assert profile.major == "软件工程"
    assert profile.learner_type == "在校学生"
    assert profile.learning_preferences.metadata["user_id"] == "user_001"

    questionnaire = client.get(
        "/api/onboarding/questions",
        params={"learning_direction_id": "rag_engineering_training"},
    )
    assert questionnaire.status_code == 200
    question_ids = [item["question_id"] for item in questionnaire.json()["questions"]]
    assert "identity" not in question_ids
    assert "education" not in question_ids
    assert "major" not in question_ids
    assert "desired_resource_types" not in question_ids
    assert "learning_focus_rag_nodes" not in question_ids


def test_rag_questionnaire_exposes_all_ability_nodes_with_direct_diagnostic_mapping():
    client, _, knowledge_service = _client()

    response = client.get(
        "/api/onboarding/questions",
        params={"learning_direction_id": "rag_engineering_training"},
    )

    assert response.status_code == 200
    questions = {item["question_id"]: item for item in response.json()["questions"]}
    known_nodes = questions["known_rag_nodes"]
    expected_node_ids = [node.node_id for node in knowledge_service.list_skill_nodes("rag_engineering_training")]
    expected_node_names = [node.name for node in knowledge_service.list_skill_nodes("rag_engineering_training")]

    assert [option["label"] for option in known_nodes["options"][:-1]] == expected_node_names
    assert [option["diagnostic_scope_add"] for option in known_nodes["options"][:-1]] == [
        [node_id] for node_id in expected_node_ids
    ]
    assert known_nodes["options"][-1]["value"] == "都不了解"
    assert "learning_focus_rag_nodes" not in questions


def test_diagnosis_keeps_unassessed_nodes_out_of_confirmed_weaknesses():
    client, repository, knowledge_service = _client()
    onboarding_response = client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())
    learner_id = onboarding_response.json()["learner_id"]
    questions = onboarding_response.json()["diagnostic_questions"]
    raw_questions = {item.question_id: item for item in knowledge_service.load_diagnostic_questions("rag_engineering_training")}
    response = client.post(
        "/api/diagnosis/submit",
        json={
            "learner_id": learner_id,
            "learning_direction_id": "rag_engineering_training",
            "answers": [{"question_id": question["question_id"], "answer": raw_questions[question["question_id"]].answer} for question in questions],
        },
    )

    assert response.status_code == 200
    profile = repository.get(learner_id)
    assert profile.knowledge_states["chunking"].status == "unassessed"
    assert "Chunk 切分" not in profile.weak_points
    assert response.json()["initial_diagnostic_status"] == "final"
    assert response.json()["initial_recommended_node_id"] in {"rag_basics", "document_parsing", "embedding"}
    assert "Embedding" in profile.strong_points


def test_onboarding_all_unknown_still_uses_stage_scoped_diagnostic_questions():
    client, _, _ = _client()
    payload = _questionnaire_payload()
    payload["learner_id"] = "user_001__rag_engineering_training_unknown"
    payload["rag_level"] = "完全不了解"
    payload["known_rag_nodes"] = ["都不了解"]

    response = client.post("/api/onboarding/initial-profile", json=payload)
    assert response.status_code == 200
    assert response.json()["diagnostic_node_ids"] == ["rag_basics", "document_parsing", "embedding"]
    assert len(response.json()["diagnostic_questions"]) == 9


def test_intermediate_initial_diagnosis_retests_lower_tier_before_finalizing():
    client, repository, knowledge_service = _client()
    payload = _questionnaire_payload()
    payload.update({
        "python_level": "能写脚本和调用 API",
        "llm_api_level": "调用过 OpenAI 或兼容 API",
        "prompt_level": "知道角色设定、格式约束、上下文注入",
        "rag_level": "知道大致流程：文档、向量化、检索、生成",
    })
    onboarding_response = client.post("/api/onboarding/initial-profile", json=payload)
    body = onboarding_response.json()
    assert body["questionnaire_tier"] == 2
    assert len(body["diagnostic_questions"]) == 9

    retest = client.post("/api/diagnosis/submit", json={
        "learner_id": body["learner_id"],
        "learning_direction_id": "rag_engineering_training",
        "answers": [{"question_id": item["question_id"], "answer": "__wrong__"} for item in body["diagnostic_questions"]],
    })
    assert retest.status_code == 200
    retest_body = retest.json()
    assert retest_body["initial_diagnostic_status"] == "retest"
    assert retest_body["assessed_tier"] == 2
    assert len(retest_body["next_diagnostic_questions"]) == 9
    assert all(
        state.objective_evidence_count == 0
        for state in repository.get(body["learner_id"]).knowledge_states.values()
    )

    raw_questions = {item.question_id: item for item in knowledge_service.load_diagnostic_questions("rag_engineering_training")}
    final = client.post("/api/diagnosis/submit", json={
        "learner_id": body["learner_id"],
        "learning_direction_id": "rag_engineering_training",
        "answers": [
            {"question_id": item["question_id"], "answer": raw_questions[item["question_id"]].answer}
            for item in retest_body["next_diagnostic_questions"]
        ],
    })
    assert final.status_code == 200
    assert final.json()["initial_diagnostic_status"] == "final"
    assert final.json()["final_tier"] == 1


def test_same_direction_creates_distinct_profiles_and_histories():
    client, repository, _ = _client()

    first = client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())
    second = client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    first_learner_id = first.json()["learner_id"]
    second_learner_id = second.json()["learner_id"]
    assert first_learner_id != second_learner_id
    assert repository.get(first_learner_id) is not None
    assert repository.get(second_learner_id) is not None
